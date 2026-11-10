# This Python file uses the following encoding: utf-8
# @author runhey
# github https://github.com/runhey
from datetime import timedelta, time
from tasks.Component.config_base import ConfigBase, TimeDelta, Time, dynamic_hide
from pydantic import Field, model_validator
from enum import Enum, IntEnum
from tasks.Component.config_scheduler import Scheduler


class BossType(IntEnum):
    ONE_STAR = 1
    TWO_STARS = 2
    THREE_STARS = 3
    FOUR_STARS = 4
    FIVE_STARS = 5
    SIX_STARS = 6
    MONEY = 7

    @property
    def lineup_key(self) -> str:
        if BossType.ONE_STAR <= self <= BossType.FOUR_STARS:
            return 'one_to_four_stars'
        return self.name.lower()


class MetaDemonConfig(ConfigBase):
    limit_time: Time = Field(default=Time(minute=45), description='limit_time_help')
    limit_count: int = Field(default=50, description='limit_count_help')
    auto_tea: bool = Field(default=False, description='疲劳度满时是否自动喝茶, 关闭则自动根据调度器等待间隔时间安排下一次调度')
    fire_sequence: str = Field(default='1 2 3 4', description='攻击顺序:从左到右,空格分隔(1:一星鬼王,2:二星鬼王...)\n例:3 2(先攻击三星鬼王然后二星鬼王)')
    powerful_list: str = Field(default='', description='开启强力鬼王列表(空格分隔),例:4 5(四星鬼王和五星鬼王开启强力追击)')
    synthesis_list: str = Field(default='1', description='鬼王合成列表(空格分隔),支持1-5星合成,例:1 2 3(合成一星,二星,三星鬼王)')

    @property
    def limit_time_v(self) -> timedelta:
        if isinstance(self.limit_time, time):
            return timedelta(hours=self.limit_time.hour, minutes=self.limit_time.minute, seconds=self.limit_time.second)
        return self.limit_time

    @property
    def fire_sequence_v(self) -> list[BossType]:
        sequence_text = self.fire_sequence.strip()
        if sequence_text == '':
            return []
        fire_num_list = sequence_text.split(' ')
        fire_boss_type_list = [BossType(int(num_text)) for num_text in fire_num_list]
        return fire_boss_type_list

    @property
    def powerful_list_v(self) -> list[BossType]:
        powerful_list_text = self.powerful_list.strip()
        if powerful_list_text == '':
            return []
        powerful_num_list = powerful_list_text.split(' ')
        powerful_boss_type_list = [BossType(int(num_text)) for num_text in powerful_num_list]
        return powerful_boss_type_list

    @property
    def synthesis_list_v(self) -> list[BossType]:
        synthesis_list_text = self.synthesis_list.strip()
        if synthesis_list_text == '':
            return []
        synthesis_num_list = synthesis_list_text.split(' ')
        synthesis_boss_type_list = [BossType(int(num_text)) for num_text in synthesis_num_list]
        return synthesis_boss_type_list


class MetaDemonSwitchSoulConfig(ConfigBase):
    enable: bool = Field(default=False, description='在超鬼王活动页同时切换阵容和御魂。填写组号,队伍号（如1,2）或分组名称,队伍名称；留空则沿用当前阵容')
    one_to_four_stars: str = Field(default='', description='一至四星鬼王共用的御魂及阵容预设配置')
    five_stars: str = Field(default='', description='五星鬼王的御魂及阵容预设配置')
    six_stars: str = Field(default='', description='六星鬼王的御魂及阵容预设配置')

    @model_validator(mode='before')
    @classmethod
    def migrate_low_star_lineup(cls, data):
        if not isinstance(data, dict) or 'one_to_four_stars' in data:
            return data
        for key in ('one_star', 'two_stars', 'three_stars', 'four_stars'):
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                return {**data, 'one_to_four_stars': value}
        return data

    def get_lineup(self, boss_type: BossType) -> tuple[int, int] | tuple[str, str] | None:
        value = getattr(self, boss_type.lineup_key, '').strip()
        if not value:
            return None
        parts = [part.strip() for part in value.replace('，', ',').split(',')]
        if len(parts) != 2 or not all(parts):
            raise ValueError('阵容须填写组号,队伍号或分组名称,队伍名称')
        group, team = parts
        if group.isdecimal() and team.isdecimal():
            return int(group), int(team)
        return group, team


class TicketFarmSource(str, Enum):
    EVO_ZONE = 'EvoZone'
    OROCHI = 'Orochi'
    EXPLORATION = 'Exploration'


class MetaDemonTicketFarmConfig(ConfigBase):
    enable: bool = Field(default=False, description='先刷门票，开始时从探索页读取进度，战斗中从奖励页读取；达到每日上限后攻打超鬼王，识别失败时暂停本轮')
    battle_task: TicketFarmSource = Field(default=TicketFarmSource.EVO_ZONE, description='直接复用所选任务的层数、阵容、组队等配置，在奖励页关闭前读取当日门票数量')
    limit_time: Time = Field(default=Time(minute=30), description='本轮刷门票的最长时间；未到每日上限则等待后重试，不进入超鬼王战斗')


class MetaDemonScheduler(Scheduler):
    wait_interval: TimeDelta = Field(default=TimeDelta(hours=1, minutes=40), description='疲劳度满时等多长时间后再次运行本任务,建议设置等待完全恢复疲劳度所需的时间\n例:100分钟恢复100点疲劳度,再次运行必定可以继续战斗')

    hide_fields = dynamic_hide('server_update', 'delay_date')


class MetaDemon(ConfigBase):
    scheduler: MetaDemonScheduler = Field(default_factory=MetaDemonScheduler)
    ticket_farm: MetaDemonTicketFarmConfig = Field(default_factory=MetaDemonTicketFarmConfig)
    meta_demon_config: MetaDemonConfig = Field(default_factory=MetaDemonConfig)
    switch_soul: MetaDemonSwitchSoulConfig = Field(default_factory=MetaDemonSwitchSoulConfig)
