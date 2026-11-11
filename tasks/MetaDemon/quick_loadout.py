import random
import re
from copy import copy
from time import sleep

import numpy as np

from module.atom.click import RuleClick
from module.atom.ocr import RuleOcr
from module.base.timer import Timer
from module.base.utils.utils import random_normal_distribution_int
from module.logger import logger
from tasks.Component.QuickLoadout.config import QuickLoadoutConfig, QuickLoadoutMode
from tasks.Component.QuickLoadout.quick_loadout import QuickLoadout, QuickLoadoutOcr
from tasks.MetaDemon.assets import MetaDemonAssets


class MetaDemonQuickLoadout(QuickLoadout, MetaDemonAssets):
    """从活动页直接应用阵容；御魂不同时由出战确认框装配。"""

    PANEL_FROM_FIGHT = (-263, -333, 554, 388)
    GROUP_OCR_ROI = (6, 12, 106, 353)
    GROUP_FIRST_Y = 35
    GROUP_ROW_HEIGHT = 50
    # 租借队伍没有编号徽标，标题从队伍卡片更靠左的位置开始。
    PRESET_OCR_ROI = (143, 8, 240, 319)
    PRESET_FIRST_Y = 27
    MAX_REWIND_SWIPES = 3

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
        return self.appear(self.I_MD_LOADOUT_GEAR) or self.appear(self.I_MD_LOADOUT_GEAR_LEGACY)

    def _open_activity_loadout(self):
        timer = Timer(self.PANEL_OPEN_TIMEOUT).start()
        while not timer.reached():
            self.screenshot()
            if self.appear(self.I_MD_LOADOUT_CONFIRM):
                logger.warning('超鬼王已有未处理的御魂确认弹窗，停止选择新阵容')
                return None
            if self.appear(self.I_MD_LOADOUT_FIGHT):
                return self._build_quick_loadout_layout(self.I_MD_LOADOUT_FIGHT)
            if self.appear(self.I_MD_LOADOUT_INCOMPLETE):
                # 人数不足会用提示代替出战按钮，提示与按钮之间的偏移固定。
                x, y = self.I_MD_LOADOUT_INCOMPLETE.roi_front[:2]
                anchor = copy(self.I_MD_LOADOUT_FIGHT)
                anchor.roi_front = (x + 95, y - 17, *anchor.roi_front[2:])
                return self._build_quick_loadout_layout(anchor)
            if self._activity_loadout_entry_visible():
                self.click(self.C_MD_LOADOUT_OPEN, interval=1)
        logger.warning('超鬼王阵容面板打开超时')
        return None

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
        rental = False
        if config.mode == QuickLoadoutMode.OCR:
            row_y, _ = self._find_name_y(ocr, config.group_name)
            rental = self._normalize_name(config.group_name) == '队伍租借'
        else:
            expected_y = panel_y + self.GROUP_FIRST_Y + (config.group_number - 1) * self.GROUP_ROW_HEIGHT
            # 只有可见的文字中心仍与编号行对齐时，才复用当前列表位置。
            results = ocr.detect_and_ocr(self.device.image, logDisplay=False)
            rows = {self._result_center_y(result, top) for result in results}
            matches = [y for y in rows if abs(y - expected_y) <= 5]
            row_y = matches[0] if len(matches) == 1 else None
        if row_y is None or not top + 6 <= row_y < top + height - 6:
            return False

        # 普通分组用深黄色高亮；活动限定的租借标签有独立的亮粉状态。
        sample = self.device.image[row_y - 6:row_y + 7, x + 11:x + 22]
        red, green, blue = np.median(sample, axis=(0, 1))
        if rental:
            return red >= 240 and red - green >= 30 and blue - green >= 8
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

            first_y = layout.panel[1] + self.GROUP_FIRST_Y
            target_y = first_y + (config.group_number - 1) * self.GROUP_ROW_HEIGHT
            results = ocr.detect_and_ocr(self.device.image, logDisplay=False)
            rows = [(self._result_center_y(r, ocr.roi[1]), self._normalize_name(r.ocr_text)) for r in results]
            # 编号分组需以列表顶部为基准，不能把滚动后的第一条当成第一组。
            at_top = at_top or any(abs(y - first_y) <= 5 and name in ('默认分组', '队伍租借') for y, name in rows)
            if at_top:
                return next((y for y, _ in rows if abs(y - target_y) <= 5), None)
            return None

        max_down = self.MAX_GROUP_SWIPES if config.mode == QuickLoadoutMode.OCR else 0
        row = self._search_list_row(ocr, layout.group_swipe_to_top, layout.group_swipe_down, max_down, find_group)
        if row is None:
            logger.warning(f'超鬼王未找到分组：{config.group_name or config.group_number}')
            return False
        self.device.click(*self._group_click_point(layout, row), control_name='MD_LOADOUT_GROUP')
        sleep(0.6)
        return True

    def _select_preset_row(self, layout, config):
        row = self._search_list_row(
            layout.preset_ocr, layout.preset_swipe_to_top, layout.preset_swipe_down,
            self.MAX_PRESET_SWIPES, lambda _: self._find_visible_lineup_y(layout, config),
        )
        if row is None:
            logger.warning(f'超鬼王未找到预设：{config.preset_name or config.preset_number}')
        return row

    def _find_visible_preset_number_y(self, layout, target):
        # 滚动后各行不会对齐初始槽位。从实际可见编号推算目标行，再单独读取编号确认。
        x, y, _, _ = layout.panel
        number_column = (x + 155, y + 6, 32, 320)
        column_ocr = QuickLoadoutOcr(roi=number_column, area=number_column, mode='Full',
                                     method='Default', keyword='', name='md_loadout_numbers')
        for result in column_ocr.detect_and_ocr(self.device.image, logDisplay=False):
            text = result.ocr_text.strip()
            if not text.isdecimal():
                continue
            row_y = self._result_center_y(result, number_column[1]) + (target - int(text)) * self.PRESET_ROW_HEIGHT
            if not y + 15 <= row_y <= y + 317:
                continue
            # 缩小到编号字形，并容许 OCR 框中心与字形中心有少量偏差。
            for offset in (0, -2, 2):
                roi = (x + 166, row_y + offset - 9, 14, 18)
                digit = RuleOcr(roi=roi, area=roi, mode='Digit', method='Default', keyword='', name='md_loadout_number')
                if digit.ocr(self.device.image) == target:
                    return row_y + offset
        return None

    @staticmethod
    def _lineup_click_regions(panel, row_y):
        x, y, _, _ = panel
        top = max(y + 11, row_y - 15)
        bottom = min(y + 327, row_y + 70)
        body_top = min(bottom, row_y + 19)
        # 上半行只点左侧，避开右上角的详情和御魂按钮；下半行覆盖整排式神。
        return [(x + 139, top, 286, body_top - top), (x + 139, body_top, 371, bottom - body_top)]

    def _confirm_activity_loadout(self):
        timer = Timer(self.PANEL_CLOSE_TIMEOUT).start()
        closed_frames = 0
        while not timer.reached():
            self.screenshot()
            if self.appear(self.I_MD_LOADOUT_CONFIRM):
                self.click(self.I_MD_LOADOUT_CONFIRM, interval=0.8)
                closed_frames = 0
            elif (not self.appear(self.I_MD_LOADOUT_FIGHT)
                  and not self.appear(self.I_MD_LOADOUT_INCOMPLETE)
                  and self._activity_loadout_entry_visible()):
                closed_frames += 1
                if closed_frames >= 2:
                    return True
            else:
                closed_frames = 0
            sleep(0.2)
        logger.warning('超鬼王阵容出战确认超时')
        return False

    def apply_activity_loadout(self, target: tuple[int, int] | tuple[str, str]) -> bool:
        group, team = target
        if isinstance(group, int):
            config = QuickLoadoutConfig(group_number=group, preset_number=team)
        else:
            config = QuickLoadoutConfig(mode=QuickLoadoutMode.OCR, group_name=group, preset_name=team)
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
            if row_y is None:
                return False
            areas = [roi for roi in self._lineup_click_regions(layout.panel, row_y) if roi[3] > 0]
            if not areas:
                return False
            roi = random.choices(areas, weights=[w * h for _, _, w, h in areas])[0]
            self.click(RuleClick(roi, roi, 'md_loadout_select'))
            sleep(0.4)
            self.screenshot()
            if not self.appear(self.I_MD_LOADOUT_FIGHT):
                logger.warning(f'超鬼王目标阵容不可出战：{target}')
                return False
            self.click(self.I_MD_LOADOUT_FIGHT)
            applied = self._confirm_activity_loadout()
            if applied:
                logger.info(f'超鬼王已应用阵容：{target}')
            return applied
        finally:
            if not applied:
                self.screenshot()
                if not self.appear(self.I_MD_LOADOUT_CONFIRM):
                    anchor = (self.I_MD_LOADOUT_INCOMPLETE if self.appear(self.I_MD_LOADOUT_INCOMPLETE)
                              else self.I_MD_LOADOUT_FIGHT)
                    self._dismiss_quick_loadout(anchor, self.C_MD_LOADOUT_DISMISS)
