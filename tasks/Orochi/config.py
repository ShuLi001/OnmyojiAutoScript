# This Python file uses the following encoding: utf-8
# @author runhey
# github https://github.com/runhey
from pydantic import BaseModel, Field
from enum import Enum
from datetime import datetime, time

from tasks.Component.config_scheduler import Scheduler
from tasks.Component.config_base import ConfigBase, Time
from tasks.Component.GeneralInvite.config_invite import InviteConfig
from tasks.Component.QuickLoadout.dungeon_config import DungeonBattleConfig, DungeonLoadoutTaskConfig


class UserStatus(str, Enum):
    LEADER = 'leader'
    MEMBER = 'member'
    ALONE = 'alone'
    WILD = 'wild'  # 还不打算实现

class Layer(str, Enum):
    ONE = '壹层'
    TWO = '贰层'
    THREE = '叁层'
    FOUR = '肆层'
    FIVE = '伍层'
    SIX = '陆层'
    SEVEN = '柒层'
    EIGHT = '捌层'
    NINE = '玖层'
    TEN = '拾层'
    ELEVEN = '悲鸣'
    TWELVE = '神罚'
    THIRTEEN = '虚无'


class OrochiConfig(ConfigBase):
    # 身份
    user_status: UserStatus = Field(default=UserStatus.LEADER, description='user_status_help')
    # 层数
    layer: Layer = Field(default=Layer.ELEVEN, description='layer_help')
    # 限制时间
    limit_time: Time = Field(default=Time(minute=30), description='limit_time_help')
    # 限制次数
    limit_count: int = Field(default=30, description='limit_count_help')
    # 是否开启御魂加成
    soul_buff_enable: bool = Field(default=False, description='soul_buff_enable_help')
    # 是否御魂结束检测是否出现真蛇
    check_true_orochi_enable: bool = Field(default=False, description='check_true_orochi_enable_help')

class OrochiBattleConfig(DungeonBattleConfig):
    auto_switch_soul: bool = Field(default=False, description='auto_switch_soul_orochi_help')
    # 十层 config
    ten_switch: str = Field(default='-1,-1', description='ten_switch_help')
    # 悲鸣 config
    eleven_switch: str = Field(default='-1,-1', description='eleven_switch_help')
    # 神罚 config
    twelve_switch: str = Field(default='-1,-1', description='twelve_switch_help')
    # 虚无 config
    thirteen_switch: str = Field(default='-1,-1', description='thirteen_switch_help')

    def get_lineup(self, layer: Layer | None = None) -> tuple[int, int] | tuple[str, str] | None:
        if self.enable_dungeon_loadout and self.auto_switch_soul:
            field = {
                Layer.TEN: 'ten_switch', Layer.ELEVEN: 'eleven_switch',
                Layer.TWELVE: 'twelve_switch', Layer.THIRTEEN: 'thirteen_switch',
            }.get(layer)
            if field and (target := self.parse_lineup(getattr(self, field))) is not None:
                return target
        return super().get_lineup()


class Orochi(DungeonLoadoutTaskConfig):
    LEGACY_DUNGEON_GROUP = 'orochi_config'
    LEGACY_SOUL_GROUP = 'switch_soul'
    LEGACY_LAYER_FIELDS = ('auto_switch_soul', 'ten_switch', 'eleven_switch', 'twelve_switch', 'thirteen_switch')

    scheduler: Scheduler = Field(default_factory=Scheduler)
    orochi_config: OrochiConfig = Field(default_factory=OrochiConfig)
    invite_config: InviteConfig = Field(default_factory=InviteConfig)
    general_battle_config: OrochiBattleConfig = Field(default_factory=OrochiBattleConfig)

