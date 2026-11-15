from tasks.Component.QuickLoadout.activity import ActivityQuickLoadout
from tasks.MetaDemon.assets import MetaDemonAssets


class MetaDemonQuickLoadout(ActivityQuickLoadout, MetaDemonAssets):
    LOADOUT_TASK_NAME = '超鬼王'
    LOADOUT_CONTROL_PREFIX = 'md_loadout'
    LOADOUT_OPEN = MetaDemonAssets.C_MD_LOADOUT_OPEN
    LOADOUT_DISMISS = MetaDemonAssets.C_MD_LOADOUT_DISMISS
    LOADOUT_FIGHT = MetaDemonAssets.I_MD_LOADOUT_FIGHT
    LOADOUT_INCOMPLETE = MetaDemonAssets.I_MD_LOADOUT_INCOMPLETE
    LOADOUT_CONFIRM = MetaDemonAssets.I_MD_LOADOUT_CONFIRM
    FIRST_GROUP_NAMES = ('默认分组', '队伍租借')

    def _activity_loadout_entry_visible(self) -> bool:
        return self.appear(self.I_MD_LOADOUT_GEAR) or self.appear(self.I_MD_LOADOUT_GEAR_LEGACY)

    def _group_is_highlighted(self, config, red, green, blue):
        if self._normalize_name(config.group_name) == '队伍租借':
            return red >= 240 and red - green >= 30 and blue - green >= 8
        return super()._group_is_highlighted(config, red, green, blue)
