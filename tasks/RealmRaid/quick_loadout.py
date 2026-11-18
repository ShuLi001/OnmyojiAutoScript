from module.atom.image import RuleImage
from module.logger import logger
from tasks.Component.QuickLoadout.activity import ActivityQuickLoadout
from tasks.Component.QuickLoadout.config import QuickLoadoutMode
from tasks.MetaDemon.assets import MetaDemonAssets
from tasks.RealmRaid.assets import RealmRaidAssets
from tasks.RealmRaid.loadout_config import RaidBattleConfig


class RaidQuickLoadout(ActivityQuickLoadout):
    RAID_PAGE_CHECK: RuleImage
    LOADOUT_CONTROL_PREFIX = 'raid_loadout'
    LOADOUT_OPEN = RealmRaidAssets.C_RAID_LOADOUT_OPEN
    LOADOUT_DISMISS = RealmRaidAssets.C_RAID_LOADOUT_DISMISS
    LOADOUT_FIGHT = MetaDemonAssets.I_MD_LOADOUT_FIGHT
    LOADOUT_INCOMPLETE = RealmRaidAssets.I_RAID_LOADOUT_INCOMPLETE
    LOADOUT_CONFIRM = MetaDemonAssets.I_MD_LOADOUT_CONFIRM
    FIRST_GROUP_NAMES = ('默认分组', '副本')
    PRESET_OCR_ROI = ActivityQuickLoadout.NUMBERED_PRESET_OCR_ROI
    PRESET_NUMBER_COLUMN = (159, 6, 23, 320)
    CLICK_FULL_GROUP_ROW = True

    def _activity_loadout_entry_visible(self) -> bool:
        return self.appear(self.RAID_PAGE_CHECK) and self.appear(RealmRaidAssets.I_RAID_LOADOUT_ENTRY)

    def _current_group_matches(self, layout, config) -> bool:
        # 编号依赖列表顶部；滚动后不能仅凭高亮行的位置判断组号。
        return config.mode == QuickLoadoutMode.OCR and super()._current_group_matches(layout, config)

    def apply_raid_loadout(self, config: RaidBattleConfig) -> bool:
        try:
            target = config.get_lineup()
            if target is None or self.apply_activity_loadout(target):
                return True
        except ValueError as error:
            logger.warning(f'{self.LOADOUT_TASK_NAME}阵容配置无效：{error}')
        logger.warning(f'{self.LOADOUT_TASK_NAME}阵容未应用，结束本轮挑战')
        return False
