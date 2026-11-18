from tasks.Component.QuickLoadout.activity import ActivityQuickLoadout
from tasks.DemonRetreat.assets import DemonRetreatAssets
from tasks.MetaDemon.assets import MetaDemonAssets


class DemonRetreatQuickLoadout(ActivityQuickLoadout, DemonRetreatAssets):
    LOADOUT_TASK_NAME = '首领退治'
    LOADOUT_CONTROL_PREFIX = 'dr_loadout'
    LOADOUT_OPEN = DemonRetreatAssets.C_DR_LOADOUT_OPEN
    LOADOUT_DISMISS = DemonRetreatAssets.C_DR_LOADOUT_DISMISS

    LOADOUT_FIGHT = MetaDemonAssets.I_MD_LOADOUT_FIGHT
    LOADOUT_INCOMPLETE = MetaDemonAssets.I_MD_LOADOUT_INCOMPLETE
    LOADOUT_CONFIRM = MetaDemonAssets.I_MD_LOADOUT_CONFIRM
    PRESET_OCR_ROI = ActivityQuickLoadout.NUMBERED_PRESET_OCR_ROI
    CLICK_FULL_GROUP_ROW = True

    def _activity_loadout_entry_visible(self) -> bool:
        return self.appear(self.I_HUNT_CHECK)
