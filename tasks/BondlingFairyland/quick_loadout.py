from copy import copy

from tasks.BondlingFairyland.assets import BondlingFairylandAssets as Assets
from tasks.Component.QuickLoadout.dungeon import DungeonQuickLoadout


class BondlingQuickLoadout(DungeonQuickLoadout):
    def __init__(self, task, *, search: bool):
        self.device = task.device
        self.screenshot = task.screenshot
        self.appear = task.appear
        self.click = task.click
        self.swipe = task.swipe
        self.LOADOUT_ENTRY = copy(DungeonQuickLoadout.LOADOUT_ENTRY)
        self.LOADOUT_ENTRY.roi_front = DungeonQuickLoadout.LOADOUT_ENTRY.roi_front.copy()
        if search:
            self.LOADOUT_TASK_NAME = '契灵探查'
            self.LOADOUT_CONTROL_PREFIX = 'bondling_search_loadout'
            self.LOADOUT_ENTRY.roi_back = (925, 549, 77, 65)
            self.LOADOUT_OPEN = Assets.C_BF_LOADOUT_OPEN
            self.LOADOUT_DISMISS = Assets.C_BF_LOADOUT_DISMISS
            self._page_check = Assets.I_BF_SEARSH
        else:
            self.LOADOUT_TASK_NAME = '契灵结契'
            self.LOADOUT_CONTROL_PREFIX = 'bondling_catch_loadout'
            self.LOADOUT_ENTRY.roi_back = (753, 549, 77, 65)
            self.LOADOUT_OPEN = Assets.C_BALL_LOADOUT_OPEN
            self.LOADOUT_DISMISS = Assets.C_BALL_LOADOUT_DISMISS
            self._page_check = Assets.I_BALL_HELP

    def _activity_loadout_entry_visible(self) -> bool:
        return self.appear(self._page_check) and self.appear(self.LOADOUT_ENTRY)
