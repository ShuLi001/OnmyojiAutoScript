# This Python file uses the following encoding: utf-8
# @author runhey
# github https://github.com/runhey
from pydantic import Field
from enum import Enum

from tasks.Component.config_scheduler import Scheduler
from tasks.Component.config_base import ConfigBase, Time
from tasks.Component.QuickLoadout.dungeon_config import DungeonBattleConfig, DungeonLoadoutTaskConfig

class GoryouClass(str, Enum):
    RANDOM = '随机',
    Dark_Divine_Dragon = '暗神龙',
    Dark_Hakuzousu = '暗白蔵主',
    Dark_Black_Panther = '暗黑豹',
    Dark_Peacock = '暗孔雀'

class GoryouConfig(ConfigBase):
    # 限制时间
    limit_time: Time = Field(default=Time(minute=30), description='limit_time_help')
    # 限制次数
    limit_count: int = Field(default=30, description='limit_count_help')
    # 类型
    goryou_class: GoryouClass = Field(default=GoryouClass.RANDOM, description='goryou_class_help')


class GoryouBattleConfig(DungeonBattleConfig):
    enable_dungeon_loadout: bool = Field(default=False, description='enable_goryou_loadout_help')


class GoryouRealm(DungeonLoadoutTaskConfig):
    LEGACY_DUNGEON_GROUP = 'goryou_config'

    scheduler: Scheduler = Field(default_factory=Scheduler)
    goryou_config: GoryouConfig = Field(default_factory=GoryouConfig)
    general_battle_config: GoryouBattleConfig = Field(default_factory=GoryouBattleConfig)

