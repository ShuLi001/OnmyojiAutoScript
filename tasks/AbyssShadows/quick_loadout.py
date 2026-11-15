from tasks.AbyssShadows.assets import AbyssShadowsAssets
from tasks.Component.QuickLoadout.activity import ActivityQuickLoadout
from tasks.Component.QuickLoadout.config import QuickLoadoutMode
from tasks.MetaDemon.assets import MetaDemonAssets


class AbyssShadowsQuickLoadout(ActivityQuickLoadout, AbyssShadowsAssets):
    LOADOUT_TASK_NAME = '狭间暗域'
    LOADOUT_CONTROL_PREFIX = 'abyss_loadout'
    LOADOUT_OPEN = AbyssShadowsAssets.C_ABYSS_LOADOUT_OPEN
    LOADOUT_DISMISS = AbyssShadowsAssets.C_ABYSS_LOADOUT_DISMISS

    LOADOUT_FIGHT = MetaDemonAssets.I_MD_LOADOUT_FIGHT
    LOADOUT_INCOMPLETE = MetaDemonAssets.I_MD_LOADOUT_INCOMPLETE
    LOADOUT_CONFIRM = MetaDemonAssets.I_MD_LOADOUT_CONFIRM
    PRESET_OCR_ROI = (187, 8, 196, 319)
    CLICK_FULL_GROUP_ROW = True

    def _activity_loadout_entry_visible(self) -> bool:
        return self.appear(self.I_ABYSS_LOADOUT_ENTRY)

    def _current_group_matches(self, layout, config) -> bool:
        # 按编号选组时先确认列表顶部，避免把滚动后的高亮行当作目标编号。
        return config.mode == QuickLoadoutMode.OCR and super()._current_group_matches(layout, config)
