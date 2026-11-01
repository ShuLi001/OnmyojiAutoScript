from __future__ import annotations

import json
import time
import re
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
    quantity_roi_from_card_match,
    scroll_boundary_state,
)
from tasks.AssetSnapshot.assets import AssetSnapshotAssets
from tasks.AssetSnapshot.config import AssetSnapshotConfig
from tasks.AssetSnapshot.history import SnapshotStore
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
            raw = rule.ocr(self.device.image)
            quantity = self._parse_ocr_quantity(raw)
            if quantity is None:
                # Right-aligned single digits need a tighter crop than multi-digit values.
                retry_roi = (1185, 12, 30, 40) if variable_name == "soul_jade" else rule.roi
                fallback = RuleOcr(roi=retry_roi, area=retry_roi, mode="Single", method="Default",
                                   keyword="", name=f"asset_snapshot_{variable_name}_retry")
                quantity = self._parse_ocr_quantity(fallback.ocr(self.device.image))
                if variable_name == "soul_jade" and quantity != 0:
                    quantity = None
            if quantity is None:
                raise ScriptError(f"顶部资源 OCR 未能读取: {variable_name}")
            values[variable_name] = quantity
        return values

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
                quantity = self._read_material_quantity(area)
                if quantity is not None and score > self.quantity_match_scores.get(variable_name, -1.0):
                    values[variable_name] = quantity
                    self.quantity_observations[variable_name] = quantity
                    self.quantity_match_scores[variable_name] = score
                logger.debug(f"AssetSnapshot material={variable_name} score={score:.6f} quantity={quantity} area={area}")

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

    def _read_material_quantity(self, match_area: tuple[int, int, int, int]) -> int | None:
        roi = quantity_roi_from_card_match(match_area)
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
            if status == "accepted" and roi_front is not None:
                matches.append(
                    (
                        rule,
                        score,
                        tuple(int(value) for value in roi_front),
                    )
                )
        return sorted(matches, key=lambda item: item[2][1])

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
        rules_data = [rule.to_service_payload() for rule in rules]
        for attempt in range(2):
            try:
                return get_image_client().match_many(
                    rules_data=rules_data,
                    image=self.device.image,
                    frame_id=self.device.image_frame_id,
                    threshold=threshold,
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
