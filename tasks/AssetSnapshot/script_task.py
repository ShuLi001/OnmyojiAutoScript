from __future__ import annotations

import json
import time
from collections import Counter
from copy import copy
from datetime import datetime
from uuid import uuid4
from decimal import Decimal
from pathlib import Path
from typing import Callable, Mapping

import numpy as np

from module.atom.click import RuleClick
from module.config.utils import configured_device_id
from module.exception import ScriptError, TaskEnd
from module.image.rpc import get_image_client
from module.logger import logger
from tasks.AssetSnapshot.quantity_ocr import InventoryQuantityOcr as RuleOcr
from tasks.GameUi.game_ui import GameUi

from tasks.AssetSnapshot.asset_snapshot import (
    DEFAULT_MATERIAL_MATCH_THRESHOLD,
    build_empty_snapshot,
    build_snapshot_payload,
    build_swipe_points,
    classify_match_score,
    inventory_card_selected,
    inventory_detail_quantity,
    merge_snapshot_values,
    normalize_inventory_title,
    MATERIAL_SWIPE_END,
    MATERIAL_SWIPE_START,
    UNSUPPORTED_MATERIAL_VARIABLES,
    parse_inventory_quantity,
    parse_stamina_detail_quantity,
    parse_top_resource_quantity,
    quantity_roi_from_card_match,
    scroll_boundary_state,
)
from tasks.AssetSnapshot.assets import MATERIAL_MAPPING, AssetSnapshotAssets
from tasks.AssetSnapshot.auspicious_demons import (
    DEMON_NAMES,
    DEMON_VARIABLES,
    demon_detail_variable,
    find_demon_candidates,
)
from tasks.AssetSnapshot.config import AssetSnapshotConfig
from tasks.AssetSnapshot.history import SnapshotStore
from tasks.AssetSnapshot.repository import parse_time, utc_now
from tasks.AssetSnapshot.skin_tickets import (
    SKIN_TICKET_VARIABLES,
    TICKET_BODY_OFFSET,
    SkinTicketCandidate,
    classify_skin_ticket,
    skin_ticket_name,
    skin_ticket_selected,
)
from tasks.AssetSnapshot.page import page_inventory
from tasks.GameUi.page import page_main
from tasks.Component.Login.service import LoginService


MATERIAL_DETAIL_NAMES = {normalize_inventory_title(name): variable for name, variable in MATERIAL_MAPPING.items()}
MATERIAL_DETAIL_NAMES["ssr全集赏体验卡"] = "ssr_collection_trial"


class ScriptTask(GameUi, AssetSnapshotAssets):
    """登录、进入纳物库，首次全量读取，后续增量更新，再返回庭院。"""

    max_reset_swipes = 3
    max_scan_swipes = 10
    settle_seconds = 0.15
    settle_timeout_seconds = 2.0
    settle_stable_frames = 2
    swipe_duration = (0.45, 0.65)
    swipe_random_x_offset = 18
    swipe_random_y_offset = 10
    material_match_threshold = DEFAULT_MATERIAL_MATCH_THRESHOLD

    def _settings(self) -> AssetSnapshotConfig:
        task_config = getattr(self.config, "asset_snapshot", None)
        return task_config.asset_snapshot_config if task_config else AssetSnapshotConfig()

    def _snapshot_store(self) -> SnapshotStore:
        return SnapshotStore(
            Path("config/asset_snapshot"), self.config.config_name,
            configured_device_id(self.config),
            str(self.config.restart.login_character_config.character),
            self.VARIABLE_MAPPING,
            generation=getattr(self._settings(), "history_generation", 0),
        )

    def _prepare_game(self) -> None:
        if not self.device.app_is_running():
            self.device.app_start()
            self.device.wait_app_start_ready()
            LoginService(config=self.config, device=self.device).app_handle_login()
        # Global navigation also handles the login form and configured courtyard skin.
        self.goto_page(page_main, skip_first_screenshot=False)

    def execute_workflow(self) -> dict[str, object]:
        store = self._snapshot_store()
        history = store.load()
        settings = self._settings()
        interval = getattr(settings, "full_scan_interval_hours", 0)
        expired = bool(history and interval and
                       (parse_time(utc_now()) - parse_time(history["fullScanCompletedAt"])).total_seconds()
                       >= interval * 3600)
        category = "composite" if (history is None or settings.force_full_scan or expired
                                   or history.get("origin") == "legacy") else "recent"
        self.previous_assets = history["snapshot"].get("assets", {}) if history else {}
        self.workflow_run_id = getattr(self, "capture_run_id", None) or str(uuid4())
        self._prepare_game()
        payload = None
        try:
            self.goto_page(page_inventory, skip_first_screenshot=False)
            payload = self.scan(
                category=category,
                previous_values=history["snapshot"]["values"] if history else None,
            )
        finally:
            # Do not establish a baseline until both scanning and courtyard return succeed.
            self.goto_page(page_main, skip_first_screenshot=False)
        payload["runId"] = self.workflow_run_id
        saved = store.save(payload, category, history)
        if isinstance(saved, dict):
            payload["snapshotId"] = saved["snapshotId"]
        logger.info(f"AssetSnapshot saved {category} snapshot")
        logger.debug(f"AssetSnapshot snapshot path: {store.path}")
        return payload

    def scan(self, *, category: str = "composite",
             previous_values: Mapping[str, int] | None = None) -> dict[str, object]:
        if category not in {"composite", "recent"}:
            raise ValueError(f"Unknown inventory category: {category}")
        if category == "recent" and previous_values is None:
            raise ValueError("Recent scan requires historical values")
        settings = self._settings()
        self.max_reset_swipes = settings.max_reset_swipes
        self.max_scan_swipes = settings.max_scan_swipes
        self.material_match_threshold = settings.match_threshold
        self.match_score_records = []
        self.quantity_observations = {}
        self.observation_metadata = {}
        self.quantity_read_metadata = {}
        self.read_failures = set()
        self.scan_category = category
        self.screenshot()
        if not self.appear(self.I_CHECK_INVENTORY):
            raise ScriptError("当前页面不是纳物库，停止资产识别")

        self._select_category(category)
        self._reset_material_grid_to_top()

        values = (merge_snapshot_values(self.VARIABLE_MAPPING, previous_values)
                  if category == "recent" else build_empty_snapshot(self.VARIABLE_MAPPING))
        top_values = self._scan_top_resources()
        values.update(top_values)
        historical_materials = {
            name for name, count in (previous_values or {}).items()
            if category == "composite" and count > 0 and name not in top_values
            and name not in UNSUPPORTED_MATERIAL_VARIABLES
        }
        try:
            if not self._scan_material_pages(values, historical_materials=historical_materials):
                raise ScriptError("纳物库扫描达到滑动上限，保留旧历史，下次重试")
        finally:
            self._write_match_score_diagnostics()
        for name in UNSUPPORTED_MATERIAL_VARIABLES:
            values[name] = 0
        previous_assets = getattr(self, "previous_assets", {})
        unresolved_demons = (self.read_failures & DEMON_VARIABLES) - self.quantity_observations.keys()
        missing_demon_history = [
            name for name in sorted(unresolved_demons)
            if (previous_assets[name].get("quantity") if name in previous_assets
                else (previous_values or {}).get(name)) is None
        ]
        if missing_demon_history:
            names = "、".join(DEMON_NAMES[name] for name in missing_demon_history)
            raise ScriptError(f"{names}本轮未确认且没有历史数量，暂不保存资产快照")
        payload = build_snapshot_payload(
            values,
            updated_at=utc_now(),
        )
        observed = {**top_values, **self.quantity_observations}
        assets = {}
        for name, quantity in values.items():
            previous = previous_assets.get(name, {})
            last_quantity = previous.get('quantity')
            if last_quantity is None:
                last_quantity = (previous_values or {}).get(name)
            if name in UNSUPPORTED_MATERIAL_VARIABLES:
                item = {"source": "unsupported", "precision": "unknown", "readStatus": "unsupported"}
            elif name in observed:
                item = {"source": "observed", "precision": "exact", "readStatus": "ok",
                        "observedAt": payload["updatedAt"], **self.observation_metadata.get(name, {})}
            else:
                carried = category == "recent" or (name in self.read_failures and last_quantity is not None)
                source = "carried" if carried else "assumed_zero"
                item = {**previous, "source": source,
                        "readStatus": "ocr_failed" if name in self.read_failures else "not_seen", "quantity": last_quantity,
                        "observedAt": previous.get("observedAt"), "precision": previous.get("precision", "unknown")}
            item.setdefault("quantity", quantity)
            if name not in observed and name not in UNSUPPORTED_MATERIAL_VARIABLES and last_quantity is not None:
                values[name] = last_quantity
            assets[name] = item
        payload['values'] = dict(values)
        payload["assets"] = assets
        logger.info(f"AssetSnapshot scan completed: {len(observed)} items confirmed")
        logger.debug(f"AssetSnapshot payload: {json.dumps(payload, ensure_ascii=False, sort_keys=True)}")
        return payload

    def run(self):
        self.execute_workflow()
        self.set_next_run(task="AssetSnapshot", success=True, finish=True)
        raise TaskEnd("AssetSnapshot")

    def _select_category(self, category: str) -> None:
        selected, click = ((self.I_TAB_COMPOSITE, self.C_TAB_COMPOSITE) if category == "composite"
                           else (self.I_TAB_RECENT, self.C_TAB_RECENT))
        for _ in range(3):
            if self.appear(selected, threshold=0.98):
                logger.info(f"AssetSnapshot selected category: {category}")
                return
            self.click(click)
            time.sleep(0.5)
            self.screenshot()
        if not self.appear(selected, threshold=0.98):
            raise ScriptError(f"无法确认纳物库分组已选中: {category}")

    def _scan_top_resources(self) -> dict[str, int]:
        values = {}
        for variable_name, rule in self.TOP_RESOURCE_OCR.items():
            if variable_name == "jade":
                values[variable_name] = self._read_jade_detail()
                continue
            x, y, width, height = rule.roi
            # Change vertical padding without dropping any leading/trailing digits.
            retry_rois = ((x - 4, y - 4, width + 4, height + 8),
                          (x - 4, y + 4, width + 4, height - 8))
            if variable_name == "soul_jade":
                retry_rois = ((1185, 12, 30, 40), (1185, 10, 30, 44))
            for attempt, roi in enumerate((rule.roi, *retry_rois)):
                if attempt:
                    time.sleep(self.settle_seconds)
                    self._refresh_inventory_frame(f"top resource {variable_name} retry {attempt}")
                    if not self.appear(self.I_CHECK_INVENTORY):
                        raise ScriptError("重试顶部资源 OCR 期间离开纳物库，保留旧历史")
                    current_rule = RuleOcr(
                        roi=roi, area=roi, mode="Single", method="Default",
                        keyword="", name=f"asset_snapshot_{variable_name}_retry_{attempt}",
                    )
                    current_rule.filter_white = False
                else:
                    current_rule = rule
                raw = current_rule.ocr(self.device.image)
                quantity = parse_top_resource_quantity(raw)
                # The narrow soul-jade fallback can only verify a single zero.
                if attempt and variable_name == "soul_jade" and quantity != 0:
                    quantity = None
                if quantity is not None:
                    if variable_name == "stamina":
                        quantity = self._read_stamina_detail()
                    values[variable_name] = quantity
                    text = str(raw).strip()
                    unit = {"万": 10000, "亿": 100000000, "千": 1000}.get(text[-1:] or "")
                    decimals = len(text[:-1].split(".")[-1]) if unit and "." in text else 0
                    if hasattr(self, "observation_metadata"):
                        self.observation_metadata[variable_name] = {
                            "observedAt": utc_now(), "precision": "display_quantized" if unit and variable_name != "stamina" else "exact",
                            "displayUnitStep": max(1, int(Decimal(unit) / (10 ** decimals))) if unit and variable_name != "stamina" else None,
                            "rawText": text,
                        }
                    logger.info(f"AssetSnapshot top {variable_name}: {quantity}")
                    logger.debug(
                        f"AssetSnapshot top resource={variable_name} raw={raw!r} "
                        f"quantity={quantity} roi={roi} attempt={attempt}"
                    )
                    break
                logger.warning(f"AssetSnapshot top {variable_name} unreadable (attempt {attempt + 1})")
                logger.debug(
                    f"AssetSnapshot rejected top resource={variable_name} "
                    f"raw={raw!r} roi={roi} attempt={attempt}"
                )
            else:
                raise ScriptError(f"顶部资源 OCR 未能读取: {variable_name}")
        return values

    def _read_stamina_detail(self) -> int:
        return self._read_resource_detail("stamina", "体力")

    def _read_jade_detail(self) -> int:
        return self._read_resource_detail("jade", "勾玉")

    def _read_resource_detail(self, variable_name: str, display_name: str) -> int:
        prefix = variable_name.upper()
        marker = getattr(self, f"I_{prefix}_DETAIL")
        name_rule = getattr(self, f"O_{prefix}_DETAIL_NAME")
        owned_rule = getattr(self, f"O_{prefix}_DETAIL_OWNED")
        if not self.appear(marker):
            self.device.click_record_clear()
            self.click(getattr(self, f"C_{prefix}_DETAIL"))
        try:
            previous = None
            for _ in range(4):
                time.sleep(0.3)
                self._refresh_inventory_frame(f"{variable_name} detail")
                if not self.appear(self.I_CHECK_INVENTORY):
                    raise ScriptError(f"读取{display_name}详情期间离开纳物库，保留旧历史")
                if not self.appear(marker):
                    previous = None
                    continue
                name = str(name_rule.ocr(self.device.image)).strip()
                if name != display_name:
                    previous = None
                    continue
                raw = owned_rule.ocr(self.device.image)
                quantity = parse_stamina_detail_quantity(raw)
                logger.info(f"AssetSnapshot {variable_name} detail: {quantity}")
                if quantity is not None and quantity == previous:
                    if hasattr(self, "observation_metadata"):
                        self.observation_metadata[variable_name] = {
                            "observedAt": utc_now(), "precision": "exact",
                            "displayUnitStep": None, "rawText": str(raw).strip(),
                        }
                    return quantity
                previous = quantity
            raise ScriptError(f"{display_name}详情未能确认精确数量，保留旧历史")
        finally:
            self._close_resource_detail(variable_name, display_name)

    def _close_stamina_detail(self) -> None:
        self._close_resource_detail("stamina", "体力")

    def _close_resource_detail(self, variable_name: str, display_name: str) -> None:
        marker = getattr(self, f"I_{variable_name.upper()}_DETAIL")
        close = getattr(self, f"C_{variable_name.upper()}_DETAIL_CLOSE")
        for _ in range(3):
            if not self.appear(self.I_CHECK_INVENTORY):
                raise ScriptError(f"关闭{display_name}详情期间离开纳物库，保留旧历史")
            if not self.appear(marker):
                return
            self.device.click_record_clear()
            self.click(close)
            time.sleep(0.3)
            self._refresh_inventory_frame(f"close {variable_name} detail")
        if not self.appear(self.I_CHECK_INVENTORY) or self.appear(marker):
            raise ScriptError(f"无法确认{display_name}详情已关闭，停止扫描并保留旧历史")

    def _scan_material_pages(self, values: dict[str, int], *, historical_materials: set[str] | None = None) -> bool:
        previous_signature = None
        pending = set()
        page_details = {}
        for page_index in range(self.max_scan_swipes + 1):
            # Material OCR can take longer than the image server frame TTL.  Always
            # register a fresh frame before using it for the next page.
            self._refresh_inventory_frame(f"scan page {page_index + 1}")
            if not self.appear(self.I_CHECK_INVENTORY):
                raise ScriptError("扫描期间离开纳物库，保留旧历史")
            signature = self._material_grid_signature()
            if signature == previous_signature:
                boundary = self._scroll_boundary_state()
                if boundary == "bottom" or (boundary == "top" and page_index == 1):
                    logger.info("AssetSnapshot grid stopped at end of list")
                    break
                logger.warning("AssetSnapshot swipe made no progress inside list")
                return False
            previous_signature = signature

            page_details = self._scan_matched_materials(values, page_index)
            pending.update(page_details)
            self._scan_auspicious_demons(values, page_index)
            self._scan_skin_tickets(values, page_index)
            boundary = self._scroll_boundary_state()
            if boundary == "bottom":
                logger.info("AssetSnapshot material grid reached bottom marker")
                break
            if page_index >= self.max_scan_swipes:
                logger.warning(f"AssetSnapshot scan reached max_scan_swipes={self.max_scan_swipes}")
                return False

            self._swipe_material_grid(
                start=MATERIAL_SWIPE_START,
                end=MATERIAL_SWIPE_END,
                control_name=self.S_MATERIAL_GRID_UP.name,
            )
            self._wait_for_material_grid_stability()
        else:
            return False

        pending.difference_update(self.quantity_observations)
        historical_missing = (historical_materials or set()) - self.quantity_observations.keys()
        targets = pending | historical_missing
        if targets:
            logger.info(f"AssetSnapshot rechecking {len(targets)} unconfirmed items")
            self._finish_material_details(values, page_index, boundary, pending, targets, page_details)
        return True

    def _remember_quantity(self, values: dict[str, int], variable: str, quantity: int) -> None:
        # The per-scan observations are also the cache, including confirmed zero.
        if variable in self.quantity_observations:
            return
        values[variable] = self.quantity_observations[variable] = quantity
        if hasattr(self, "observation_metadata"):
            metadata = getattr(self, "quantity_read_metadata", {}).get(variable, {"observedAt": utc_now()})
            self.observation_metadata[variable] = metadata

    def _scan_matched_materials(
        self, values: dict[str, int], page_index: int, *, only: set[str] | None = None,
    ) -> dict[str, tuple[int, int, int, int]]:
        slots = {}
        for rule, score, area in self._find_material_matches(page_index, only=only):
            variable = self.MATERIAL_RULE_TO_VARIABLE[id(rule)]
            if variable not in self.quantity_observations and (variable not in slots or score > slots[variable][0]):
                slots[variable] = (score, area)
        needs_detail = {}
        for variable, (_, area) in slots.items():
            quantity = self._read_material_quantity(area, variable_name=variable)
            if quantity is None:
                needs_detail[variable] = area
            else:
                self._remember_quantity(values, variable, quantity)
                logger.debug(f"AssetSnapshot material={variable} quantity={quantity} source=grid area={area}")
        return needs_detail

    def _finish_material_details(
        self, values: dict[str, int], page_index: int, boundary: str,
        pending: set[str], targets: set[str], page_details: dict[str, tuple[int, int, int, int]],
    ) -> None:
        for step in range(self.max_scan_swipes + 1):
            if step:
                before = self._material_grid_signature()
                self._swipe_material_grid(
                    start=MATERIAL_SWIPE_END, end=MATERIAL_SWIPE_START,
                    control_name=self.S_MATERIAL_GRID_DOWN.name,
                )
                self._wait_for_material_grid_stability()
                self._refresh_inventory_frame("material recheck")
                if not self.appear(self.I_CHECK_INVENTORY):
                    raise ScriptError("复查材料期间离开纳物库，保留旧历史")
                if self._material_grid_signature() == before:
                    break
                boundary = self._scroll_boundary_state()
                index = page_index + step
                page_details = self._scan_matched_materials(values, index, only=targets)
                pending.update(page_details)
                if targets & DEMON_VARIABLES:
                    self._scan_auspicious_demons(values, index)
                if targets & SKIN_TICKET_VARIABLES:
                    self._scan_skin_tickets(values, index)

            targets.difference_update(self.quantity_observations)
            for variable, area in page_details.items():
                if variable not in targets:
                    continue
                targets.remove(variable)
                detail = self._read_inventory_detail(
                    area, expected_variable=variable,
                    title_resolver=lambda text: MATERIAL_DETAIL_NAMES.get(normalize_inventory_title(text)),
                    control_name="asset_snapshot_material_detail",
                )
                if detail is not None:
                    _, quantity = detail
                    self._remember_quantity(values, variable, quantity)
                    logger.debug(f"AssetSnapshot material={variable} quantity={quantity} source=detail area={area}")
            if not targets or boundary == "top" or page_index == 0:
                break

        self.read_failures.update(pending - self.quantity_observations.keys())

    def _read_material_quantity(
        self,
        match_area: tuple[int, int, int, int],
        *,
        variable_name: str | None = None,
    ) -> int | None:
        roi = quantity_roi_from_card_match(match_area, variable_name=variable_name)
        # A clipped or faded last row is not a reliable quantity source.
        if roi[1] + roi[3] > 660:
            return None

        def read(*, filtered: bool):
            rule = RuleOcr(
                roi=roi, area=roi, mode="Single", method="Default", keyword="",
                name=f"asset_snapshot_quantity_{roi[0]}_{roi[1]}_{'filtered' if filtered else 'raw'}",
            )
            rule.filter_white = filtered
            boxes = rule.detect_and_ocr(self.device.image)
            if len(boxes) != 1:
                return None, None
            raw = boxes[0].ocr_text
            return parse_inventory_quantity(raw), raw

        result, raw = read(filtered=False)
        if result is None:
            return None
        # The tight 万象之魄 crop already avoids its artwork text. For other
        # materials, require agreement before caching a grid reading.
        if variable_name != "myriad_soul" and read(filtered=True)[0] != result:
            return None
        if variable_name and hasattr(self, "quantity_read_metadata"):
            self.quantity_read_metadata[variable_name] = self._quantity_metadata(raw)
        return result

    @staticmethod
    def _quantity_metadata(raw):
        text = str(raw).strip()
        unit = {"万": 10000, "亿": 100000000, "千": 1000}.get(text[-1:])
        decimals = len(text[:-1].split('.')[-1]) if unit and '.' in text else 0
        return {"observedAt": utc_now(), "rawText": text,
                "precision": "display_quantized" if unit else "exact",
                "displayUnitStep": max(1, int(Decimal(unit) / 10 ** decimals)) if unit else None}

    def _find_material_matches(
        self,
        page_index: int,
        *,
        only: set[str] | None = None,
    ) -> list[tuple[object, float, tuple[int, int, int, int]]]:
        rules = [
            rule for rule in self.MATERIAL_RULES
            if self.MATERIAL_RULE_TO_VARIABLE[id(rule)] not in DEMON_VARIABLES
            and (only is None or self.MATERIAL_RULE_TO_VARIABLE[id(rule)] in only)
        ]
        if not rules:
            return []
        results = self._match_many_with_frame_retry(
            rules,
            purpose=f"material page {page_index + 1}",
            threshold=0.0,
        )
        matches = []
        for rule, result in zip(rules, results):
            variable_name = self.MATERIAL_RULE_TO_VARIABLE[id(rule)]
            score = float(result.get("score", 0.0))
            roi_front = result.get("roi_front")
            status = classify_match_score(score, self.material_match_threshold)
            if variable_name in SKIN_TICKET_VARIABLES and status == "accepted":
                status = "candidate"
            record = {
                "page": page_index + 1,
                "variable_name": variable_name,
                "score": round(score, 6),
                "status": status,
            }
            if roi_front is not None:
                record["x"], record["y"], record["width"], record["height"] = [
                    int(value) for value in roi_front
                ]
            self.match_score_records.append(record)
            if (status == "accepted" and roi_front is not None
                    and variable_name not in SKIN_TICKET_VARIABLES):
                matches.append(
                    (
                        rule,
                        score,
                        tuple(int(value) for value in roi_front),
                    )
                )
        return sorted(matches, key=lambda item: item[2][1])

    def _scan_auspicious_demons(self, values: dict[str, int], page_index: int) -> None:
        if DEMON_VARIABLES <= self.quantity_observations.keys():
            return
        candidates = find_demon_candidates(self.device.image)
        counts = Counter(candidate.variable for candidate in candidates)
        for candidate in candidates:
            variable = candidate.variable
            if counts[variable] == 1 and variable in self.quantity_observations:
                detail = (variable, self.quantity_observations[variable])
            else:
                # The printed orange digits can corrupt the stock OCR even when
                # the star badge matches correctly. Confirm through the detail panel.
                detail = self._read_auspicious_demon_detail(candidate.area)
            if detail is None:
                self.read_failures.update({variable} if variable and counts[variable] == 1 else DEMON_VARIABLES)
                logger.warning(f"AssetSnapshot demon detail unconfirmed at {candidate.area[:2]}")
                quantity, method = None, "detail"
            else:
                variable, quantity = detail
                method = "cache" if variable in self.quantity_observations else "detail"
                self._remember_quantity(values, variable, quantity)
            record = {
                "page": page_index + 1, "kind": "auspicious_demon_verification",
                "area": list(candidate.area), "body_score": round(candidate.body_score, 6),
                "badge_scores": {name: round(score, 6) for name, score in candidate.badge_scores.items()},
                "grid_variable": candidate.variable, "variable_name": variable, "method": method,
                "quantity": quantity, "status": "accepted" if quantity is not None else "unconfirmed",
            }
            self.match_score_records.append(record)
            if quantity is not None and method == "detail":
                logger.info(f"AssetSnapshot demon {variable}: {quantity}")

    def _read_auspicious_demon_detail(self, area: tuple[int, int, int, int]) -> tuple[str, int] | None:
        return self._read_inventory_detail(
            area, expected_variable=None, title_resolver=demon_detail_variable,
            control_name="asset_snapshot_demon_detail",
        )

    def _click_inventory_card(self, area: tuple[int, int, int, int], control_name: str) -> bool:
        if getattr(self.device, "image", None) is None:
            return False
        x, y, _, _ = area
        height = min(32, 660 - (y + 22))
        if y + 22 < self.MATERIAL_GRID_ROI[1] or height < 12:
            return False
        click_area = (x + 23, y + 22, 45, height)
        self.device.click_record_clear()
        self.click(RuleClick(click_area, click_area, name=control_name))
        return True

    def _read_inventory_detail(
        self,
        area: tuple[int, int, int, int],
        *,
        expected_variable: str | None,
        title_resolver: Callable[[str], str | None],
        control_name: str,
    ) -> tuple[str, int] | None:
        if not self._click_inventory_card(area, control_name):
            return None
        previous = None
        for _ in range(3):
            time.sleep(0.4)
            self._refresh_inventory_frame("material detail")
            if not self.appear(self.I_CHECK_INVENTORY):
                raise ScriptError("读取材料详情期间离开纳物库，保留旧历史")
            if not inventory_card_selected(self.device.image, area):
                previous = None
                continue
            variable = None
            for rule in (self.O_MATERIAL_DETAIL_NAME, self.O_MATERIAL_DETAIL_NAME_RETRY):
                variable = title_resolver(rule.ocr_single_line(self.device.image))
                if variable is not None and (expected_variable is None or variable == expected_variable):
                    break
            if variable is None or (expected_variable is not None and variable != expected_variable):
                previous = None
                continue
            cached = self.quantity_observations.get(variable)
            raw = None if cached is not None else inventory_detail_quantity(
                self.O_MATERIAL_DETAIL_OWNED.ocr_single_line(self.device.image)
            )
            quantity = cached if cached is not None else parse_inventory_quantity(raw)
            if quantity is None:
                previous = None
                continue
            reading = (variable, quantity)
            if reading == previous:
                if raw is not None:
                    self.quantity_read_metadata[variable] = self._quantity_metadata(raw)
                return reading
            previous = reading
        return None

    @staticmethod
    def _ticket_region_rule(rule, roi):
        regional = copy(rule)
        regional.roi_back = roi
        return regional

    def _find_skin_ticket_candidates(self, page_index: int) -> list[SkinTicketCandidate]:
        self._refresh_inventory_frame("skin ticket candidates")
        result = self._image_request_with_frame_retry(
            "match_all_any", purpose="skin ticket body",
            rule_data=self.I_SKIN_TICKET_BODY.to_service_payload(),
            nms_threshold=0.3,
        )
        ticket_rules = {
            self.MATERIAL_RULE_TO_VARIABLE[id(rule)]: rule
            for rule in self.MATERIAL_RULES
            if self.MATERIAL_RULE_TO_VARIABLE[id(rule)] in SKIN_TICKET_VARIABLES
        }
        candidates = []
        grid_x, grid_y, grid_w, grid_h = self.MATERIAL_GRID_ROI
        for body_score, body_x, body_y, _, _ in result.get("matches", []):
            x, y = int(body_x) - TICKET_BODY_OFFSET[0], int(body_y) - TICKET_BODY_OFFSET[1]
            left, top = max(grid_x, x - 8), max(grid_y, y - 5)
            right, bottom = min(grid_x + grid_w, x + 103), min(grid_y + grid_h, y + 75)
            if right - left < 95 or bottom - top < 70:
                continue
            roi = (left, top, right - left, bottom - top)
            normal, sp = self._match_many_with_frame_retry(
                [self._ticket_region_rule(ticket_rules[name], roi)
                 for name in ("skin_ticket", "sp_skin_ticket")],
                purpose="skin ticket alternatives", threshold=0.0,
            )
            best = max((normal, sp), key=lambda item: item["score"])
            area = tuple(int(v) for v in best["roi_front"])
            badge_score = None
            if area[1] >= grid_y and area[1] + 76 <= 660:
                badge_roi = (area[0] + 47, area[1] + 50, 43, 26)
                badge = self._match_many_with_frame_retry(
                    [self._ticket_region_rule(self.I_SP_TICKET_BADGE, badge_roi)],
                    purpose="SP ticket badge", threshold=0.0,
                )[0]
                badge_score = float(badge["score"])
            normal_score, sp_score = float(normal["score"]), float(sp["score"])
            candidates.append(SkinTicketCandidate(
                area, float(body_score), normal_score, sp_score, badge_score,
                classify_skin_ticket(normal_score, sp_score, badge_score),
            ))
        return sorted(candidates, key=lambda candidate: candidate.area[1])

    def _scan_skin_tickets(self, values: dict[str, int], page_index: int) -> None:
        if SKIN_TICKET_VARIABLES <= self.quantity_observations.keys():
            return
        for candidate in self._find_skin_ticket_candidates(page_index):
            variable = candidate.variable_name
            record = {
                "page": page_index + 1, "kind": "skin_ticket_verification",
                "variable_name": variable, "body_score": candidate.body_score,
                "normal_score": candidate.normal_score, "sp_score": candidate.sp_score,
                "badge_score": candidate.badge_score, "area": list(candidate.area),
            }
            self.match_score_records.append(record)
            if variable in self.quantity_observations:
                quantity = self.quantity_observations[variable]
            else:
                detail = self._read_skin_ticket_detail(candidate.area, expected_variable=variable)
                if detail is None:
                    record["status"] = "detail_failed"
                    raise ScriptError("无法确认皮肤券类型或数量，保留旧历史，下次重试")
                variable, quantity = detail
            cached = variable in self.quantity_observations
            self._remember_quantity(values, variable, quantity)
            record.update(variable_name=variable, quantity=quantity, status="accepted",
                          method="cache" if cached else "detail")
            if not cached:
                logger.info(f"AssetSnapshot ticket {variable}: {quantity}")

    def _read_skin_ticket_detail(
        self,
        area: tuple[int, int, int, int],
        *,
        expected_variable: str | None,
    ) -> tuple[str, int] | None:
        if not self._click_inventory_card(area, "asset_snapshot_ticket_detail"):
            return None
        previous = None
        for _ in range(3):
            time.sleep(0.4)
            self._refresh_inventory_frame("skin ticket detail")
            if not self.appear(self.I_CHECK_INVENTORY):
                raise ScriptError("读取皮肤券详情期间离开纳物库，保留旧历史")
            if not skin_ticket_selected(self.device.image, area):
                previous = None
                continue
            variable = skin_ticket_name(self.O_TICKET_DETAIL_NAME.ocr(self.device.image))
            if variable is None or (expected_variable is not None and variable != expected_variable):
                previous = None
                continue
            quantity = self.quantity_observations.get(variable)
            text = None
            if quantity is None:
                boxes = self.O_TICKET_DETAIL_QUANTITY.detect_and_ocr(self.device.image)
                if len(boxes) == 1:
                    text = boxes[0].ocr_text
                    quantity = parse_inventory_quantity(text)
            if quantity is None:
                previous = None
                continue
            reading = (variable, quantity)
            if reading == previous:
                if text is not None and hasattr(self, "quantity_read_metadata"):
                    self.quantity_read_metadata[variable] = self._quantity_metadata(text)
                return reading
            previous = reading
        return None

    def _write_match_score_diagnostics(self) -> None:
        output = Path("log/asset_snapshot_material_match_scores.json")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(
                {
                    "threshold": self.material_match_threshold,
                    "category": self.scan_category,
                    "observedValues": self.quantity_observations,
                    "updatedAt": datetime.now().replace(microsecond=0).isoformat(),
                    "records": self.match_score_records,
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )

    def _reset_material_grid_to_top(self) -> None:
        previous_signature = None
        for _ in range(self.max_reset_swipes):
            self.screenshot()
            boundary = self._scroll_boundary_state()
            if boundary == "top":
                logger.info("AssetSnapshot material grid reached top marker")
                return
            signature = self._material_grid_signature()
            if signature == previous_signature:
                raise ScriptError("纳物库顶部复位无进展，保留旧历史")
            previous_signature = signature
            self._swipe_material_grid(
                start=(540, 205),
                end=(540, 635),
                control_name=self.S_MATERIAL_GRID_DOWN.name,
            )
            self._wait_for_material_grid_stability()
        self.screenshot()
        if self._scroll_boundary_state() != "top":
            raise ScriptError(f"纳物库复位达到 {self.max_reset_swipes} 次上限，未确认顶部")

    def _scroll_boundary_state(self) -> str:
        # Boundary matching happens after the per-card OCR and may otherwise use
        # a frame that has already expired in the image service.
        self._refresh_inventory_frame("scroll boundary")
        results = self._match_many_with_frame_retry(
            [self.I_SCROLL_THUMB_TOP, self.I_SCROLL_THUMB_BOTTOM],
            purpose="scroll boundary",
        )
        top = self.I_SCROLL_THUMB_TOP._apply_match_result(results[0])
        bottom = self.I_SCROLL_THUMB_BOTTOM._apply_match_result(results[1])
        state = scroll_boundary_state(top=top, bottom=bottom)
        logger.debug(f"AssetSnapshot scroll boundary: {state} top={top} bottom={bottom}")
        return state

    @staticmethod
    def _is_unknown_frame_error(error: BaseException) -> bool:
        """识别图像服务报告的过期/不存在 frame_id。"""
        return "Unknown frame id" in str(error)

    def _refresh_inventory_frame(self, purpose: str) -> None:
        """获取并注册一张新截图，避免长 OCR 后继续复用旧帧。"""
        self.screenshot()
        logger.debug(
            f"AssetSnapshot refreshed image frame for {purpose}: "
            f"frame_id={getattr(self.device, 'image_frame_id', None)}"
        )

    def _match_many_with_frame_retry(
        self,
        rules: list[object],
        *,
        purpose: str,
        threshold: float | None = None,
    ) -> list[dict]:
        """在同一截图帧上批量匹配，遇到失效帧时刷新并重试一次。"""
        return self._image_request_with_frame_retry(
            "match_many", purpose=purpose,
            rules_data=[rule.to_service_payload() for rule in rules], threshold=threshold,
        )

    def _image_request_with_frame_retry(self, method: str, *, purpose: str, **kwargs):
        for attempt in range(2):
            try:
                return getattr(get_image_client(), method)(
                    image=self.device.image,
                    frame_id=self.device.image_frame_id,
                    **kwargs,
                )
            except Exception as error:
                if not self._is_unknown_frame_error(error) or attempt:
                    raise
                logger.warning(f"AssetSnapshot frame retry: {purpose}")
                self._refresh_inventory_frame(f"retry {purpose}")
        raise RuntimeError(f"AssetSnapshot frame retry unexpectedly exhausted: {purpose}")

    def _swipe_material_grid(
        self,
        *,
        start: tuple[int, int],
        end: tuple[int, int],
        control_name: str,
    ) -> None:
        self.device.click_record_clear()
        p1, p2 = build_swipe_points(
            start,
            end,
            x_offset=self.swipe_random_x_offset,
            y_offset=self.swipe_random_y_offset,
        )
        before_signature = self._material_grid_signature()
        logger.debug(
            f"AssetSnapshot material swipe start: {p1} -> {p2}, "
            f"before_signature={before_signature}"
        )
        self.device.swipe(
            p1=list(p1),
            p2=list(p2),
            duration=self.swipe_duration,
            control_name=control_name,
        )

    def _wait_for_material_grid_stability(self) -> None:
        time.sleep(0.6)
        self.screenshot()
        before_signature = self._material_grid_signature()
        previous_signature = self._material_grid_signature()
        stable_frames = 0
        deadline = time.monotonic() + self.settle_timeout_seconds
        while time.monotonic() < deadline:
            time.sleep(self.settle_seconds)
            self.screenshot()
            signature = self._material_grid_signature()
            if signature == previous_signature:
                stable_frames += 1
                if stable_frames >= self.settle_stable_frames:
                    logger.debug(
                        "AssetSnapshot material swipe settled: "
                        f"changed={before_signature != signature}, "
                        f"before_signature={before_signature}, after_signature={signature}"
                    )
                    return
            else:
                stable_frames = 0
            previous_signature = signature

    def _material_grid_signature(self) -> int:
        image = np.asarray(self.device.image)
        x, y, width, height = self.MATERIAL_GRID_ROI
        region = image[y:y + height, x:x + width]
        return hash(region[::8, ::8].tobytes())


if __name__ == "__main__":
    import argparse
    from module.config.config import Config
    from module.device.device import Device
    from module.image.rpc import ensure_image_server_ready
    from module.ocr.rpc import ensure_ocr_server_ready

    parser = argparse.ArgumentParser(description="Run inventory snapshot workflow")
    parser.add_argument("--config", required=True)
    args = parser.parse_args()
    ensure_image_server_ready()
    ensure_ocr_server_ready()
    config = Config(args.config)
    device = Device(config)
    task = ScriptTask(config, device)
    print(json.dumps(task.execute_workflow(), ensure_ascii=False, indent=2, sort_keys=True))
