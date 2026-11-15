# This Python file uses the following encoding: utf-8
# @author runhey
# github https://github.com/runhey
from typing import ClassVar

from pydantic import ConfigDict, Field, model_validator

from module.config.weekly_schedule import WeeklyRunTimes
from tasks.Component.GeneralBattle.config_general_battle import GeneralBattleConfig
from tasks.Component.config_scheduler import Scheduler
from tasks.Component.config_base import ConfigBase, Time


class DemonRetreatTime(ConfigBase):
    # 自定义运行时间
    custom_run_time: Time = Field(default=Time(hour=10, minute=0, second=0), description='demon_retreat_time_help')


class DemonRetreatBattleConfig(GeneralBattleConfig):
    lock_team_enable: bool = Field(default=False, description='demon_retreat_lock_team_help')
    # 首领退治使用任务页预设，不保存通用战斗的旧版预设字段。
    preset_enable: ClassVar[bool] = False
    preset_group: ClassVar[int] = 1
    preset_team: ClassVar[int] = 1
    enable_switch_loadout_in_dr: bool = Field(default=False, description='demon_retreat_switch_loadout_help')
    demon_retreat_preset: str = Field(default='', description='demon_retreat_preset_help')

    @staticmethod
    def _order_battle_settings(schema: dict) -> None:
        properties = schema['properties']
        first = ('lock_team_enable', 'enable_switch_loadout_in_dr', 'demon_retreat_preset')
        schema['properties'] = {key: properties.pop(key) for key in first} | properties

    model_config = ConfigDict(json_schema_extra=_order_battle_settings)


class DemonRetreat(ConfigBase):
    scheduler: Scheduler = Field(default_factory=Scheduler)
    demon_retreat_time: DemonRetreatTime = Field(default_factory=DemonRetreatTime)
    general_battle: DemonRetreatBattleConfig = Field(default_factory=DemonRetreatBattleConfig)

    @property
    def weekly_run_times(self) -> WeeklyRunTimes:
        return ((5, self.demon_retreat_time.custom_run_time),)

    @model_validator(mode='before')
    @classmethod
    def migrate_loadout_config(cls, data):
        if not isinstance(data, dict):
            return data
        battle = data.get('general_battle', {})
        soul = data.get('switch_soul_config', {})
        if not isinstance(battle, dict) or not isinstance(soul, dict):
            return data
        data, battle = dict(data), dict(battle)
        old_enabled = battle.pop('preset_enable', False)
        old_group = battle.pop('preset_group', 1)
        old_team = battle.pop('preset_team', 1)
        data.pop('switch_soul_config', None)

        if 'enable_switch_loadout_in_dr' not in battle and 'demon_retreat_preset' not in battle:
            # 保留旧版实际生效的目标；仅启用了编号预设时，锁定阵容也可沿用它。
            preset = f'{old_group},{old_team}' if old_enabled else None
            if not old_enabled or battle.get('lock_team_enable'):
                if soul.get('enable_switch_by_name'):
                    preset = f"{soul.get('group_name', '')},{soul.get('team_name', '')}"
                elif soul.get('enable'):
                    preset = soul.get('switch_group_team', '-1,-1')
            if preset is not None:
                battle.update(enable_switch_loadout_in_dr=True, demon_retreat_preset=preset)
        return {**data, 'general_battle': battle}

    def get_lineup(self) -> tuple[int, int] | tuple[str, str] | None:
        battle = self.general_battle
        value = battle.demon_retreat_preset.strip()
        if not battle.enable_switch_loadout_in_dr or not value:
            return None
        parts = [part.strip() for part in value.replace('，', ',').split(',')]
        if len(parts) != 2 or not all(parts):
            raise ValueError('阵容须填写组号,队伍号或分组名称,队伍名称')
        group, team = parts
        if (group, team) == ('-1', '-1'):
            return None
        if group.isdecimal() and team.isdecimal():
            return int(group), int(team)
        return group, team
