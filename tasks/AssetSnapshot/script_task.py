from __future__ import annotations

import json
import time
import re
from copy import copy
from datetime import datetime
from pathlib import Path
from typing import Mapping

import numpy as np

from module.atom.ocr import RuleOcr
from module.exception import ScriptError, TaskEnd
from module.image.rpc import get_image_client
from module.logger import logger
from tasks.GameUi.game_ui import GameUi

from tasks.AssetSnapshot.asset_snapshot import (
    build_empty_snapshot,
    build_snapshot_payload,
    build_swipe_points,
    classify_match_score,
    merge_snapshot_values,
    MATERIAL_SWIPE_END,
    MATERIAL_SWIPE_START,
    normalize_quantity,
    parse_stamina_detail_quantity,
    parse_top_resource_quantity,
    quantity_roi_from_card_match,
    scroll_boundary_state,
)
from tasks.AssetSnapshot.assets import AssetSnapshotAssets
from tasks.AssetSnapshot.config import AssetSnapshotConfig
from tasks.AssetSnapshot.history import SnapshotStore
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
    material_match_threshold = 0.95

    def _settings(self) -> AssetSnapshotConfig:
        task_config = getattr(self.config, "asset_snapshot", None)
        return task_config.asset_snapshot_config if task_config else AssetSnapshotConfig()

    def _snapshot_store(self) -> SnapshotStore:
        return SnapshotStore(
            Path("config/asset_snapshot"), self.config.config_name,
            str(self.config.script.device.serial),
            str(self.config.restart.login_character_config.character),
            self.VARIABLE_MAPPING,
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
        category = "composite" if history is None or self._settings().force_full_scan else "recent"
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
        store.save(payload, category, history)
        logger.info(f"AssetSnapshot saved {category} snapshot: {store.path}")
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
        self.quantity_match_scores = {}
        self.ticket_detail_cache = {}
        self.scan_category = category
        self.screenshot()
        if not self.appear(self.I_CHECK_INVENTORY):
            raise ScriptError("当前页面不是纳物库，停止资产识别")

        self._select_category(category)
        self._reset_material_grid_to_top()

        values = (merge_snapshot_values(self.VARIABLE_MAPPING, previous_values)
                  if category == "recent" else build_empty_snapshot(self.VARIABLE_MAPPING))
        values.update(self._scan_top_resources())
        try:
            if not self._scan_material_pages(values):
                raise ScriptError("纳物库扫描达到滑动上限，保留旧历史，下次重试")
        finally:
            self._write_match_score_diagnostics()
        values["eternal_divine_talisman"] = 0
        payload = build_snapshot_payload(
            values,
            updated_at=datetime.now().replace(microsecond=0).isoformat(),
        )
        logger.info(f"AssetSnapshot payload: {json.dumps(payload, ensure_ascii=False, sort_keys=True)}")
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
                    logger.info(
                        f"AssetSnapshot top resource={variable_name} raw={raw!r} "
                        f"quantity={quantity} roi={roi} attempt={attempt}"
                    )
                    break
                logger.warning(
                    f"AssetSnapshot rejected top resource={variable_name} "
                    f"raw={raw!r} roi={roi} attempt={attempt}"
                )
            else:
                raise ScriptError(f"顶部资源 OCR 未能读取: {variable_name}")
        return values

    def _read_stamina_detail(self) -> int:
        if not self.appear(self.I_STAMINA_DETAIL):
            self.device.click_record_clear()
            self.click(self.C_STAMINA_DETAIL)
        try:
            previous = None
            for _ in range(4):
                time.sleep(0.3)
                self._refresh_inventory_frame("stamina detail")
                if not self.appear(self.I_CHECK_INVENTORY):
                    raise ScriptError("读取体力详情期间离开纳物库，保留旧历史")
                if not self.appear(self.I_STAMINA_DETAIL):
                    previous = None
                    continue
                name = str(self.O_STAMINA_DETAIL_NAME.ocr(self.device.image)).strip()
                if name != "体力":
                    previous = None
                    continue
                raw = self.O_STAMINA_DETAIL_OWNED.ocr(self.device.image)
                quantity = parse_stamina_detail_quantity(raw)
                logger.info(f"AssetSnapshot stamina detail raw={raw!r} quantity={quantity}")
                if quantity is not None and quantity == previous:
                    return quantity
                previous = quantity
            raise ScriptError("体力详情未能确认精确数量，保留旧历史")
        finally:
            self._close_stamina_detail()

    def _close_stamina_detail(self) -> None:
        for _ in range(3):
            if not self.appear(self.I_CHECK_INVENTORY):
                raise ScriptError("关闭体力详情期间离开纳物库，保留旧历史")
            if not self.appear(self.I_STAMINA_DETAIL):
                return
            self.device.click_record_clear()
            self.click(self.C_STAMINA_DETAIL_CLOSE)
            time.sleep(0.3)
            self._refresh_inventory_frame("close stamina detail")
        if not self.appear(self.I_CHECK_INVENTORY) or self.appear(self.I_STAMINA_DETAIL):
            raise ScriptError("无法确认体力详情已关闭，停止扫描并保留旧历史")

    def _scan_material_pages(self, values: dict[str, int]) -> bool:
        previous_signature = None
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
                    return True
                logger.warning("AssetSnapshot swipe made no progress inside list")
                return False
            previous_signature = signature

            matches = self._find_material_matches(page_index)
            for rule, score, area in matches:
                variable_name = self.MATERIAL_RULE_TO_VARIABLE[id(rule)]
                quantity = self._read_material_quantity(area, variable_name=variable_name)
                if quantity is not None and score > self.quantity_match_scores.get(variable_name, -1.0):
                    values[variable_name] = quantity
                    self.quantity_observations[variable_name] = quantity
                    self.quantity_match_scores[variable_name] = score
                logger.debug(f"AssetSnapshot material={variable_name} score={score:.6f} quantity={quantity} area={area}")

            self._scan_skin_tickets(values, page_index)
            boundary = self._scroll_boundary_state()
            if boundary == "bottom":
                logger.info("AssetSnapshot material grid reached bottom marker")
                return True
            if page_index >= self.max_scan_swipes:
                logger.warning(f"AssetSnapshot scan reached max_scan_swipes={self.max_scan_swipes}")
                return False

            self._swipe_material_grid(
                start=MATERIAL_SWIPE_START,
                end=MATERIAL_SWIPE_END,
                control_name=self.S_MATERIAL_GRID_UP.name,
            )
            self._wait_for_material_grid_stability()
        return False

    @staticmethod
    def _parse_ocr_quantity(raw: object) -> int | None:
        text = str(raw).strip() if raw is not None else ""
        return normalize_quantity(raw) if re.search(r"[0-9OoIl丨]", text) else None

    def _read_material_quantity(
        self,
        match_area: tuple[int, int, int, int],
        *,
        variable_name: str | None = None,
    ) -> int | None:
        roi = quantity_roi_from_card_match(match_area, variable_name=variable_name)
        # The inventory fades out the last row at y=660, above the panel boundary.
        visible_height = min(roi[3], 660 - roi[1])
        if visible_height < 18:
            return None
        roi = (roi[0], roi[1], roi[2], visible_height)
        rule = RuleOcr(
            roi=roi,
            area=roi,
            mode="Quantity",
            method="Default",
            keyword="",
            name=f"asset_snapshot_quantity_{roi[0]}_{roi[1]}",
        )
        # Keep the detector's number box: whole-line OCR also reads artwork lettering.
        boxes = rule.detect_and_ocr(self.device.image)
        return self._parse_ocr_quantity(boxes[0].ocr_text) if boxes else None

    def _find_material_matches(
        self,
        page_index: int,
    ) -> list[tuple[object, float, tuple[int, int, int, int]]]:
        results = self._match_many_with_frame_retry(
            self.MATERIAL_RULES,
            purpose=f"material page {page_index + 1}",
            threshold=0.0,
        )
        matches = []
        for rule, result in zip(self.MATERIAL_RULES, results):
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
        for candidate in self._find_skin_ticket_candidates(page_index):
            variable = candidate.variable_name
            record = {
                "page": page_index + 1, "kind": "skin_ticket_verification",
                "variable_name": variable, "body_score": candidate.body_score,
                "normal_score": candidate.normal_score, "sp_score": candidate.sp_score,
                "badge_score": candidate.badge_score, "area": list(candidate.area),
            }
            self.match_score_records.append(record)
            quantity = None
            if variable == "skin_ticket":
                quantity = self._read_material_quantity(candidate.area, variable_name=variable)
            elif variable == "sp_skin_ticket":
                quantity = self.ticket_detail_cache.get(variable)
            if quantity is None:
                detail = self._read_skin_ticket_detail(candidate.area, expected_variable=variable)
                if detail is None:
                    record["status"] = "detail_failed"
                    raise ScriptError("无法确认皮肤券类型或数量，保留旧历史，下次重试")
                variable, quantity = detail
                self.ticket_detail_cache[variable] = quantity
            record.update(variable_name=variable, quantity=quantity, status="accepted")
            score = candidate.score_for(variable)
            if score > self.quantity_match_scores.get(variable, -1.0):
                values[variable] = quantity
                self.quantity_observations[variable] = quantity
                self.quantity_match_scores[variable] = score
            logger.info(
                f"AssetSnapshot ticket={variable} quantity={quantity} "
                f"score={score:.6f} SP_badge_score={candidate.badge_score}"
            )

    def _read_skin_ticket_detail(
        self,
        area: tuple[int, int, int, int],
        *,
        expected_variable: str | None,
    ) -> tuple[str, int] | None:
        self.device.click_record_clear()
        self.device.click(area[0] + 45, area[1] + 30, control_name="asset_snapshot_ticket_detail")
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
            boxes = self.O_TICKET_DETAIL_QUANTITY.detect_and_ocr(self.device.image)
            text = "".join(str(box.ocr_text).strip() for box in boxes)
            if not re.fullmatch(r"\d+(?:\.\d+)?[万亿千]?", text):
                previous = None
                continue
            reading = (variable, normalize_quantity(text))
            logger.info(
                f"AssetSnapshot ticket detail={variable} quantity={reading[1]} "
                f"OCR_scores={[round(float(box.score), 6) for box in boxes]}"
            )
            if reading == previous:
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
                logger.warning(
                    f"AssetSnapshot image frame expired during {purpose}; "
                    "refreshing screenshot and retrying"
                )
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
        logger.info(
            f"AssetSnapshot material swipe start: {p1} -> {p2}, "
            f"before_signature={before_signature}"
        )
        self.device.swipe(
            p1=list(p1),
            p2=list(p2),
            duration=self.swipe_duration,
            control_name=control_name,
        )
        logger.info("AssetSnapshot material swipe dispatched")

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
                    logger.info(
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
