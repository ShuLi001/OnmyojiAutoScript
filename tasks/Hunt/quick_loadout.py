from copy import copy

from module.atom.click import RuleClick
from tasks.Component.QuickLoadout.dungeon import DungeonQuickLoadout
from tasks.Hunt.assets import HuntAssets


class NetherworldQuickLoadout(DungeonQuickLoadout, HuntAssets):
    LOADOUT_TASK_NAME = '阴界之门'
    LOADOUT_CONTROL_PREFIX = 'netherworld_loadout'
    LOADOUT_ENTRY = HuntAssets.I_NW_LOADOUT_ENTRY
    LOADOUT_DISMISS = RuleClick((600, 518, 25, 35), (600, 518, 25, 35), 'nw_loadout_dismiss')

    LOADOUT_FIGHT = copy(DungeonQuickLoadout.LOADOUT_FIGHT)
    LOADOUT_FIGHT.roi_front = [295, 514, 118, 43]
    LOADOUT_FIGHT.roi_back = (277, 499, 160, 71)
    LOADOUT_INCOMPLETE = copy(DungeonQuickLoadout.LOADOUT_INCOMPLETE)
    LOADOUT_INCOMPLETE.roi_front = [200, 531, 318, 20]
    LOADOUT_INCOMPLETE.roi_back = (183, 515, 354, 45)
    LOADOUT_INCOMPLETE.threshold = 0.78  # 半透明提示条会与详情页背景混合。

    def _activity_loadout_entry_visible(self) -> bool:
        return self.appear(self.I_NW_CHALLAGE) and self.appear(self.LOADOUT_ENTRY)

    def _click_activity_loadout_entry(self) -> bool:
        if not self._activity_loadout_entry_visible():
            return False
        self.click(self.LOADOUT_ENTRY)
        return True
