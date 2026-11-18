# This Python file uses the following encoding: utf-8
# @author runhey
# github https://github.com/runhey
from pydantic import Field

from tasks.Component.config_scheduler import Scheduler
from tasks.Component.QuickLoadout.dungeon_config import DungeonBattleConfig, DungeonLoadoutTaskConfig
from tasks.AreaBoss.config_boss import Boss


class AreaBossBattleConfig(DungeonBattleConfig):
    lock_team_enable: bool = Field(default=False, description='lock_team_enable_help')
    enable_dungeon_loadout: bool = Field(default=False, description='enable_area_boss_loadout_help')


class AreaBoss(DungeonLoadoutTaskConfig):
    BATTLE_GROUP = 'general_battle'
    LEGACY_DUNGEON_GROUP = 'boss'
    LEGACY_SOUL_GROUP = 'switch_soul'

    scheduler: Scheduler = Field(default_factory=Scheduler)
    boss: Boss = Field(default_factory=Boss)
    general_battle: AreaBossBattleConfig = Field(default_factory=AreaBossBattleConfig)


