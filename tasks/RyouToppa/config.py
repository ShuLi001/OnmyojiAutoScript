from pydantic import BaseModel, Field
from enum import Enum
from tasks.Component.config_base import Time
from tasks.Component.config_scheduler import Scheduler
from tasks.RealmRaid.loadout_config import RaidBattleConfig, RaidLoadoutTaskConfig



class RaidConfig(BaseModel):
    # 限制时间
    limit_time: Time = Field(default=Time(minute=30), description='limit_time_help')
    # 限制次数
    limit_count: int = Field(default=50, description='limit_count_help')
    # 攻破完成后指定下次运行时间
    next_ryoutoppa_time: Time = Field(default=Time(hour=7, minute=0, second=0))
    # 是否跳过难度较高的结界，失败后不再攻打该结界
    skip_difficult: bool = Field(default=True, description='skip_difficult_help')
    # 寮管理开启寮突破
    ryou_access: bool = Field(default=False, description='ryou_access_help')
    # 正式进攻会设定 2s - 10s 的随机延迟，避免攻击间隔及其相近被检测为脚本。
    random_delay: bool = Field(default=False, description='random_delay_help')

    # 打完没票了 0/6 => 失败
    # 突破压根没开  +> 失败
    # 时间打满了  成功
    # 次数打满了  成功
    # 打完了（有失败的但是大不了） 成功



class RyouToppa(RaidLoadoutTaskConfig):
    scheduler: Scheduler = Field(default_factory=Scheduler)
    raid_config: RaidConfig = Field(default_factory=RaidConfig)
    general_battle_config: RaidBattleConfig = Field(default_factory=RaidBattleConfig)
