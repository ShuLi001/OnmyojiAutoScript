from copy import copy
from time import sleep

from module.atom.click import RuleClick
from module.base.timer import Timer
from module.logger import logger
from tasks.Component.GeneralBattle.assets import GeneralBattleAssets
from tasks.Component.QuickLoadout.activity import ActivityQuickLoadout
from tasks.Component.QuickLoadout.assets import QuickLoadoutAssets
from tasks.Component.QuickLoadout.config import QuickLoadoutMode
from tasks.Component.SwitchSoul.switch_soul import SwitchSoul
from tasks.GameUi.page import page_shikigami_records
from tasks.MetaDemon.assets import MetaDemonAssets


class DungeonQuickLoadout(ActivityQuickLoadout, SwitchSoul):
    LOADOUT_CONTROL_PREFIX = 'dungeon_loadout'
    LOADOUT_ENTRY = QuickLoadoutAssets.I_DUNGEON_LOADOUT_ENTRY
    LOADOUT_OPEN = QuickLoadoutAssets.C_DUNGEON_LOADOUT_OPEN
    LOADOUT_DISMISS = QuickLoadoutAssets.C_DUNGEON_LOADOUT_DISMISS
    LOADOUT_FIGHT = MetaDemonAssets.I_MD_LOADOUT_FIGHT
    LOADOUT_INCOMPLETE = MetaDemonAssets.I_MD_LOADOUT_INCOMPLETE
    LOADOUT_CONFIRM = MetaDemonAssets.I_MD_LOADOUT_CONFIRM
    LOADOUT_ALREADY_EQUIPPED = None
    FIRST_GROUP_NAMES = ('默认分组', '副本')
    PRESET_OCR_ROI = ActivityQuickLoadout.NUMBERED_PRESET_OCR_ROI
    PRESET_NUMBER_COLUMN = (159, 6, 23, 320)
    PRESET_NUMBER_COLUMN_FALLBACK = (166, 6, 15, 320)
    CLICK_FULL_GROUP_ROW = True
    BATTLE_LOADOUT_TIMEOUT = 20

    def _apply_incomplete_loadout(self, layout, row_y) -> bool:
        x, _, _, _ = layout.panel
        icon = copy(QuickLoadoutAssets.I_DUNGEON_EQUIP_SOUL)
        # 图标与队伍标题同行；局内面板没有图标时不按坐标盲点。
        icon.roi_back = (x + layout.pixels(462), row_y - layout.pixels(20),
                         layout.pixels(40), layout.pixels(44))
        if layout.scale != 1.0:
            icon.method = icon.METHOD_MULTI_SCALE_TEMPLATE_MATCH
            icon.scale_range = (layout.scale, layout.scale)
        if not self.appear(icon):
            return False
        self.click(icon)
        timer = Timer(self.PANEL_CLOSE_TIMEOUT).start()
        confirmed = False
        while not (timer.reached() or self._loadout_budget_expired()):
            self.screenshot()
            if self.appear(self.LOADOUT_CONFIRM):
                self.click(self.LOADOUT_CONFIRM, interval=0.8)
                confirmed = True
            elif self.LOADOUT_ALREADY_EQUIPPED is not None and self.appear(self.LOADOUT_ALREADY_EQUIPPED):
                logger.info(f'{self.LOADOUT_TASK_NAME}当前阵容已使用预设御魂')
                return True
            elif confirmed and self._activity_loadout_panel_visible():
                logger.info(f'{self.LOADOUT_TASK_NAME}预设人数不足，已装配御魂，保留当前阵容')
                return True
            sleep(0.15)
        return False

    def _activity_loadout_entry_visible(self) -> bool:
        return self.appear(self.LOADOUT_ENTRY) and self.appear(self.I_FORM_TEAM)

    def _current_group_matches(self, layout, config) -> bool:
        return config.mode == QuickLoadoutMode.OCR and super()._current_group_matches(layout, config)

    def _apply_first_dungeon_battle_preset(self):
        target = getattr(self, '_first_battle_lineup', None)
        if self.current_count != 1 or target is None:
            return
        self._first_battle_lineup = None
        loadout = DungeonBattleLoadout(self)
        try:
            applied = loadout.apply_activity_loadout(target)
        except ValueError as error:
            logger.warning(f'{self.LOADOUT_TASK_NAME}首场战斗预设无法应用：{error}')
            applied = False
        if not applied:
            logger.warning(f'{self.LOADOUT_TASK_NAME}首场战斗预设未应用，使用当前阵容：{target}')
        self.screenshot()

    def apply_dungeon_loadout(self, get_lineup, enter_page, *, member: bool, team_battle: bool = False) -> bool:
        self._first_battle_lineup = None
        try:
            target = get_lineup()
            if target is None:
                return True
            if team_battle:
                self._first_battle_lineup = target
            if member:
                # 队员等邀请直接进房，沿用式神录的装配御魂流程。
                group, team = target
                if isinstance(group, int):
                    if not (1 <= group <= 7 and team >= 1):
                        raise ValueError('队伍预设编号无效')
                    if team > 4:
                        logger.info('式神录按编号仅支持前四队，首场准备时应用目标预设')
                        return True
                self.goto_page(page_shikigami_records)
                if isinstance(group, int):
                    self.run_switch_soul(target)
                else:
                    self.run_switch_soul_by_name(group, team)
                return True
            if enter_page() is not False and self.apply_activity_loadout(target):
                return True
        except ValueError as error:
            logger.warning(f'{self.LOADOUT_TASK_NAME}阵容配置无效：{error}')
        logger.warning(f'{self.LOADOUT_TASK_NAME}阵容未应用，结束本轮挑战')
        return False


class DungeonBattleLoadout(DungeonQuickLoadout):
    """局内准备页的 1.25 倍预设面板。"""

    LOADOUT_FIGHT = GeneralBattleAssets.I_PRESET_ENSURE
    PANEL_FROM_FIGHT = (-329, -420, 694, 487)
    PANEL_FROM_INCOMPLETE = (-199, -424, 694, 487)
    LOADOUT_PANEL_SCALE = 1.25
    LOADOUT_INCOMPLETE = copy(GeneralBattleAssets.I_PRESENT_LESS_THAN_5)
    LOADOUT_INCOMPLETE.roi_back = (205, 630, 455, 74)
    BATTLE_ENTRY = copy(GeneralBattleAssets.I_PRESET)
    BATTLE_ENTRY.roi_back = (20, 636, 72, 81)
    LOADOUT_DISMISS = RuleClick((932, 151, 35, 38), (932, 151, 35, 38), 'dungeon_battle_loadout_dismiss')
    PANEL_OPEN_TIMEOUT = DungeonQuickLoadout.BATTLE_LOADOUT_TIMEOUT
    # 局内 OCR 把菱形编号并入标题时会把正文误读为“2金币”；从编号右侧开始。
    PRESET_OCR_ROI = (185, 8, 215, 319)

    def __init__(self, task):
        self.LOADOUT_TASK_NAME = task.LOADOUT_TASK_NAME
        self.device = task.device
        self.screenshot = task.screenshot
        self.appear = task.appear
        self.click = task.click
        self.swipe = task.swipe
        self.appear_then_click = task.appear_then_click
        self._loadout_timer = Timer(self.PANEL_OPEN_TIMEOUT).start()

    def _activity_loadout_entry_visible(self) -> bool:
        return (self.appear(self.BATTLE_ENTRY) or self.appear(GeneralBattleAssets.I_PRESET_WIT_NUMBER)
                or self.appear(GeneralBattleAssets.O_PRESET_FULL))

    def _click_activity_loadout_entry(self) -> bool:
        for entry in (self.BATTLE_ENTRY, GeneralBattleAssets.I_PRESET_WIT_NUMBER,
                      GeneralBattleAssets.O_PRESET_FULL):
            if self.appear_then_click(entry):
                return True
        return False
