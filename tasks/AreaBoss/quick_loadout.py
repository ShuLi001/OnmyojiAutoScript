from copy import copy

from module.atom.click import RuleClick
from tasks.AreaBoss.assets import AreaBossAssets
from tasks.Component.QuickLoadout.dungeon import DungeonQuickLoadout


class AreaBossQuickLoadout(DungeonQuickLoadout, AreaBossAssets):
    LOADOUT_TASK_NAME = '地域鬼王'
    LOADOUT_CONTROL_PREFIX = 'area_boss_loadout'
    LOADOUT_ENTRY = AreaBossAssets.I_AB_LOADOUT_ENTRY
    LOADOUT_OPEN = AreaBossAssets.C_AB_LOADOUT_OPEN
    LOADOUT_DISMISS = AreaBossAssets.C_AB_LOADOUT_DISMISS
    LOADOUT_ALREADY_EQUIPPED = AreaBossAssets.I_AB_LOADOUT_ALREADY_EQUIPPED
    LOADOUT_INCOMPLETE = copy(DungeonQuickLoadout.LOADOUT_INCOMPLETE)
    LOADOUT_INCOMPLETE.roi_front = [773, 578, 318, 20]
    # 没有「分享战绩」时，右侧入口和面板会上移约 85 像素。
    LOADOUT_INCOMPLETE.roi_back = (755, 474, 346, 132)
    LOADOUT_INCOMPLETE.threshold = 0.78  # 提示条半透明，详情背景会影响分数。
    LOADOUT_FIGHT = copy(DungeonQuickLoadout.LOADOUT_FIGHT)
    LOADOUT_FIGHT.roi_front = [868, 562, 118, 43]
    LOADOUT_FIGHT.roi_back = (838, 460, 180, 154)

    def _activity_loadout_entry_visible(self) -> bool:
        return self.appear(self.I_AB_CLOSE_RED) and self.appear(self.LOADOUT_ENTRY)

    def _click_activity_loadout_entry(self) -> bool:
        if not self._activity_loadout_entry_visible():
            return False
        x, y = self.LOADOUT_ENTRY.roi_front[:2]
        width, height = self.LOADOUT_OPEN.roi_front[2:]
        # 模板只裁图标中心；将完整图标的点击框跟随命中位置平移。
        area = (x - 14, y - 10, width, height)
        self.click(RuleClick(area, area, self.LOADOUT_OPEN.name))
        return True
