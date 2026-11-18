import random
import re
from time import sleep

import numpy as np

from module.atom.click import RuleClick
from module.atom.image import RuleImage
from module.atom.ocr import RuleOcr
from module.base.timer import Timer
from module.base.utils.utils import random_normal_distribution_int
from module.logger import logger
from tasks.Component.QuickLoadout.config import QuickLoadoutConfig, QuickLoadoutMode
from tasks.Component.QuickLoadout.quick_loadout import QuickLoadout, QuickLoadoutOcr


class ActivityQuickLoadout(QuickLoadout):
    """从活动页直接应用阵容；御魂不同时由出战确认框装配。"""

    LOADOUT_TASK_NAME: str
    LOADOUT_CONTROL_PREFIX: str
    LOADOUT_OPEN: RuleClick
    LOADOUT_DISMISS: RuleClick
    LOADOUT_FIGHT: RuleImage
    LOADOUT_INCOMPLETE: RuleImage
    LOADOUT_CONFIRM: RuleImage
    LOADOUT_PANEL_SCALE = 1.0

    PANEL_FROM_FIGHT = (-263, -333, 554, 388)
    PANEL_FROM_INCOMPLETE = (-168, -350, 554, 388)
    GROUP_OCR_ROI = (6, 12, 106, 353)
    GROUP_FIRST_Y = 35
    GROUP_ROW_HEIGHT = 50
    CLICK_FULL_GROUP_ROW = False
    FIRST_GROUP_NAMES = ('默认分组',)
    PRESET_OCR_ROI = (143, 8, 240, 319)
    NUMBERED_PRESET_OCR_ROI = (187, 8, 196, 319)
    PRESET_NUMBER_COLUMN = (155, 6, 32, 320)
    PRESET_NUMBER_COLUMN_FALLBACK = None
    PRESET_FIRST_Y = 27
    MAX_REWIND_SWIPES = 3

    def _loadout_budget_expired(self) -> bool:
        timer = getattr(self, '_loadout_timer', None)
        return timer is not None and timer.reached()

    def _search_list_row(self, ocr, to_top, down, max_down, find_row):
        """按当前画面找目标；每次滑动后再查，直到找到或用完次数。"""
        row = find_row(False)
        if row is not None:
            return row

        x, y, w, h = ocr.roi

        def visible_strip():
            return self.device.image[y:y + h:4, x:x + w:4].astype(np.int16)

        for swipe, limit, rewinding in ((to_top, self.MAX_REWIND_SWIPES, True), (down, max_down, False)):
            previous = visible_strip()
            stable = 0
            for _ in range(limit):
                if self._loadout_budget_expired():
                    return None
                self.swipe(swipe)
                if rewinding:
                    self.device.click_record_remove(swipe.name)
                sleep(0.6)
                self.screenshot()
                current = visible_strip()
                stable = stable + 1 if np.abs(current - previous).mean() < 2.5 else 0
                row = find_row(rewinding and stable >= 2)
                if row is not None:
                    return row
                if stable >= 2:
                    break
                previous = current
        return None

    def _activity_loadout_entry_visible(self) -> bool:
        raise NotImplementedError

    def _activity_loadout_panel_visible(self) -> bool:
        return self.appear(self.LOADOUT_FIGHT) or self.appear(self.LOADOUT_INCOMPLETE)

    def _locate_activity_loadout(self):
        for anchor, offset, label in (
            (self.LOADOUT_FIGHT, self.PANEL_FROM_FIGHT, '出战'),
            (self.LOADOUT_INCOMPLETE, self.PANEL_FROM_INCOMPLETE, '人数不足'),
        ):
            if self.appear(anchor):
                layout = self._build_quick_loadout_layout(anchor, offset, scale=self.LOADOUT_PANEL_SCALE)
                logger.info(f'{self.LOADOUT_TASK_NAME}已通过「{label}」定位预设窗口：{layout.panel}')
                return layout
        return None

    def _open_activity_loadout(self):
        timer = Timer(self.PANEL_OPEN_TIMEOUT).start()
        retry = None
        while not (timer.reached() or self._loadout_budget_expired()):
            self.screenshot()
            if self.appear(self.LOADOUT_CONFIRM):
                logger.warning(f'{self.LOADOUT_TASK_NAME}已有未处理的御魂确认弹窗，停止选择新阵容')
                return None
            layout = self._locate_activity_loadout()
            if layout is not None:
                return layout
            if (retry is None or retry.reached()) and self._click_activity_loadout_entry():
                retry = Timer(random.uniform(2, 3)).start()
        logger.warning(f'{self.LOADOUT_TASK_NAME}阵容面板打开超时')
        return None

    def _click_activity_loadout_entry(self) -> bool:
        if not self._activity_loadout_entry_visible():
            return False
        self.click(self.LOADOUT_OPEN)
        return True

    def _dismiss_activity_loadout(self) -> bool:
        timer = getattr(self, '_loadout_timer', None) or Timer(self.PANEL_CLOSE_TIMEOUT).start()
        while not timer.reached():
            self.screenshot()
            if not self._activity_loadout_panel_visible():
                return True
            self.click(self.LOADOUT_DISMISS, interval=1)
        if not self._activity_loadout_panel_visible():
            return True
        if self._loadout_budget_expired():
            self.click(self.LOADOUT_DISMISS)
        logger.warning(f'{self.LOADOUT_TASK_NAME}阵容面板关闭超时')
        return False

    def _find_name_y(self, ocr, target, results=None):
        # 精确区分“队伍1”和“队伍10”等相似名称；OCR 有时把行号和名称合成一段。
        if results is None:
            results = ocr.detect_and_ocr(self.device.image, logDisplay=False)
        matches = set()
        for result in results:
            text = result.ocr_text.strip()
            if ocr.name == 'quick_loadout_preset_name':
                text_without_index = re.sub(r'^\d+\s*', '', text)
            else:
                text_without_index = text
            if self._normalize_name(target) in {self._normalize_name(text), self._normalize_name(text_without_index)}:
                matches.add(self._result_center_y(result, ocr.roi[1]))
        return (matches.pop(), 1.0) if len(matches) == 1 else (None, 0.0)

    def _group_click_point(self, layout, y):
        if self.CLICK_FULL_GROUP_ROW:
            x, top, _, _ = layout.panel
            px = layout.pixels
            # 覆盖分组按钮内框，留出边线并避免点到相邻行。
            return (
                random_normal_distribution_int(x + px(7), x + px(113)),
                random_normal_distribution_int(max(top + px(12), y - px(22)),
                                               min(top + px(377), y + px(23))),
            )
        x, y = super()._group_click_point(layout, y)
        _, top, _, height = layout.group_ocr.roi
        y = max(top, min(y, top + height - 1))
        return (
            random_normal_distribution_int(x - 14, x + 15),
            random_normal_distribution_int(max(top, y - 7), min(top + height, y + 8)),
        )

    def _current_group_matches(self, layout, config) -> bool:
        ocr = layout.group_ocr
        x, panel_y, _, _ = layout.panel
        _, top, _, height = ocr.roi
        if config.mode == QuickLoadoutMode.OCR:
            row_y, _ = self._find_name_y(ocr, config.group_name)
        else:
            expected_y = panel_y + layout.pixels(self.GROUP_FIRST_Y + (config.group_number - 1) * self.GROUP_ROW_HEIGHT)
            # 只有可见的文字中心仍与编号行对齐时，才复用当前列表位置。
            results = ocr.detect_and_ocr(self.device.image, logDisplay=False)
            rows = {self._result_center_y(result, top) for result in results}
            matches = [y for y in rows if abs(y - expected_y) <= 5]
            row_y = matches[0] if len(matches) == 1 else None
        if row_y is None or not top + 6 <= row_y < top + height - 6:
            return False

        sample = self.device.image[row_y - 6:row_y + 7, x + layout.pixels(11):x + layout.pixels(22)]
        return self._group_is_highlighted(config, *np.median(sample, axis=(0, 1)))

    def _group_is_highlighted(self, config, red, green, blue):
        return red >= 235 and green >= 180 and red - green >= 20 and green - blue >= 45

    def _find_visible_lineup_y(self, layout, config):
        if config.mode == QuickLoadoutMode.NUMBER:
            return self._find_visible_preset_number_y(layout, config.preset_number)
        row_y, _ = self._find_name_y(layout.preset_ocr, config.preset_name)
        return row_y

    def _select_group(self, layout, config) -> bool:
        ocr = layout.group_ocr

        def find_group(at_top):
            if config.mode == QuickLoadoutMode.OCR:
                row, _ = self._find_name_y(ocr, config.group_name)
                return row

            first_y = layout.panel[1] + layout.pixels(self.GROUP_FIRST_Y)
            target_y = first_y + layout.pixels((config.group_number - 1) * self.GROUP_ROW_HEIGHT)
            results = ocr.detect_and_ocr(self.device.image, logDisplay=False)
            rows = [(self._result_center_y(r, ocr.roi[1]), self._normalize_name(r.ocr_text)) for r in results]
            # 编号分组需以列表顶部为基准，不能把滚动后的第一条当成第一组。
            at_top = at_top or any(abs(y - first_y) <= 5 and name in self.FIRST_GROUP_NAMES for y, name in rows)
            if at_top:
                return next((y for y, _ in rows if abs(y - target_y) <= 5), None)
            return None

        max_down = self.MAX_GROUP_SWIPES if config.mode == QuickLoadoutMode.OCR else 0
        row = self._search_list_row(ocr, layout.group_swipe_to_top, layout.group_swipe_down, max_down, find_group)
        if row is None or self._loadout_budget_expired():
            logger.warning(f'{self.LOADOUT_TASK_NAME}未找到分组：{config.group_name or config.group_number}')
            return False
        self.device.click(*self._group_click_point(layout, row), control_name=f'{self.LOADOUT_CONTROL_PREFIX.upper()}_GROUP')
        sleep(0.6)
        return True

    def _select_preset_row(self, layout, config):
        row = self._search_list_row(
            layout.preset_ocr, layout.preset_swipe_to_top, layout.preset_swipe_down,
            self.MAX_PRESET_SWIPES, lambda _: self._find_visible_lineup_y(layout, config),
        )
        if row is None:
            logger.warning(f'{self.LOADOUT_TASK_NAME}未找到预设：{config.preset_name or config.preset_number}')
        return row

    def _find_visible_preset_number_y(self, layout, target):
        # 滚动后各行不会对齐初始槽位。从实际可见编号推算目标行，再单独读取编号确认。
        y = self._find_preset_number_in_column(layout, target, self.PRESET_NUMBER_COLUMN)
        if y is None and self.PRESET_NUMBER_COLUMN_FALLBACK is not None and not self._loadout_budget_expired():
            return self._find_preset_number_in_column(layout, target, self.PRESET_NUMBER_COLUMN_FALLBACK)
        return y

    def _find_preset_number_in_column(self, layout, target, column):
        x, y, _, _ = layout.panel
        number_column = self._offset_roi(layout.panel, tuple(map(layout.pixels, column)))
        prefix = self.LOADOUT_CONTROL_PREFIX
        column_ocr = QuickLoadoutOcr(roi=number_column, area=number_column, mode='Full',
                                     method='Default', keyword='', name=f'{prefix}_numbers')
        for result in column_ocr.detect_and_ocr(self.device.image, logDisplay=False):
            text = result.ocr_text.strip()
            if not text.isdecimal():
                continue
            row_y = self._result_center_y(result, number_column[1]) + layout.pixels((target - int(text)) * self.PRESET_ROW_HEIGHT)
            if not y + layout.pixels(15) <= row_y <= y + layout.pixels(317):
                continue
            # 缩小到编号字形，并容许 OCR 框中心与字形中心有少量偏差。
            for offset in (0, -2, 2):
                roi = (x + layout.pixels(166), row_y + offset - layout.pixels(9), layout.pixels(14), layout.pixels(18))
                digit = RuleOcr(roi=roi, area=roi, mode='Digit', method='Default', keyword='', name=f'{prefix}_number')
                if digit.ocr(self.device.image) == target:
                    return row_y + offset
        return None

    @staticmethod
    def _lineup_click_regions(layout, row_y):
        x, y, _, _ = layout.panel
        px = layout.pixels
        top = max(y + px(11), row_y - px(15))
        bottom = min(y + px(327), row_y + px(70))
        body_top = min(bottom, row_y + px(19))
        # 上半行只点左侧，避开右上角的详情和御魂按钮；下半行覆盖整排式神。
        return [(x + px(139), top, px(286), body_top - top), (x + px(139), body_top, px(371), bottom - body_top)]

    def _confirm_activity_loadout(self):
        timer = Timer(self.PANEL_CLOSE_TIMEOUT).start()
        closed_frames = 0
        while not (timer.reached() or self._loadout_budget_expired()):
            self.screenshot()
            if self.appear(self.LOADOUT_CONFIRM):
                self.click(self.LOADOUT_CONFIRM, interval=0.8)
                closed_frames = 0
            elif not self._activity_loadout_panel_visible() and self._activity_loadout_entry_visible():
                closed_frames += 1
                if closed_frames >= 2:
                    return True
            else:
                closed_frames = 0
            sleep(0.2)
        logger.warning(f'{self.LOADOUT_TASK_NAME}阵容出战确认超时')
        return False

    def _apply_incomplete_loadout(self, layout, row_y) -> bool:
        return False

    def apply_activity_loadout(self, target: tuple[int, int] | tuple[str, str]) -> bool:
        group, team = target
        if isinstance(group, int):
            config = QuickLoadoutConfig(group_number=group, preset_number=team)
        else:
            config = QuickLoadoutConfig(mode=QuickLoadoutMode.OCR, group_name=group, preset_name=team)
        config.validate_target()
        layout = self._open_activity_loadout()
        if layout is None:
            return False

        applied = False
        try:
            if not self._current_group_matches(layout, config):
                if not self._select_group(layout, config):
                    return False
                self.screenshot()
            row_y = self._select_preset_row(layout, config)
            if row_y is None or self._loadout_budget_expired():
                return False
            areas = [roi for roi in self._lineup_click_regions(layout, row_y) if roi[3] > 0]
            if not areas:
                return False
            roi = random.choices(areas, weights=[w * h for _, _, w, h in areas])[0]
            self.click(RuleClick(roi, roi, f'{self.LOADOUT_CONTROL_PREFIX}_select'))
            sleep(0.4)
            self.screenshot()
            if self._loadout_budget_expired():
                return False
            if not self.appear(self.LOADOUT_FIGHT):
                incomplete = self.appear(self.LOADOUT_INCOMPLETE)
                if incomplete and self._apply_incomplete_loadout(layout, row_y):
                    # 只装配御魂，阵容未变。finally 仍需关闭预设面板。
                    return True
                reason = '人数不足' if incomplete else '不可出战'
                logger.warning(f'{self.LOADOUT_TASK_NAME}目标阵容{reason}：{target}')
                return False
            self.click(self.LOADOUT_FIGHT)
            applied = self._confirm_activity_loadout()
            if applied:
                logger.info(f'{self.LOADOUT_TASK_NAME}已应用阵容：{target}')
            return applied
        finally:
            if not applied:
                self.screenshot()
                if not self.appear(self.LOADOUT_CONFIRM):
                    self._dismiss_activity_loadout()
