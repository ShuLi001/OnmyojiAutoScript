from typing import ClassVar

from pydantic import ConfigDict, Field, model_validator

from tasks.Component.GeneralBattle.config_general_battle import GeneralBattleConfig
from tasks.Component.config_base import ConfigBase


class RaidBattleConfig(GeneralBattleConfig):
    lock_team_enable: bool = Field(default=False, description='raid_lock_team_help')
    preset_enable: ClassVar[bool] = False
    preset_group: ClassVar[int] = 1
    preset_team: ClassVar[int] = 1
    enable_raid_loadout: bool = Field(default=False, description='enable_raid_loadout_help')
    raid_preset: str = Field(default='', description='raid_preset_help')

    @staticmethod
    def _order_battle_settings(schema: dict) -> None:
        properties = schema['properties']
        first = ('lock_team_enable', 'enable_raid_loadout', 'raid_preset')
        schema['properties'] = {key: properties.pop(key) for key in first} | properties

    model_config = ConfigDict(json_schema_extra=_order_battle_settings)

    def get_lineup(self) -> tuple[int, int] | tuple[str, str] | None:
        value = self.raid_preset.strip()
        if not self.enable_raid_loadout or not value:
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


class RaidLoadoutTaskConfig(ConfigBase):
    @model_validator(mode='before')
    @classmethod
    def migrate_loadout_config(cls, data):
        if not isinstance(data, dict):
            return data
        battle = data.get('general_battle_config', {})
        soul = data.get('switch_soul_config', {})
        if not isinstance(battle, dict) or not isinstance(soul, dict):
            return data
        data, battle = dict(data), dict(battle)
        old_enabled = battle.pop('preset_enable', False)
        old_group = battle.pop('preset_group', 1)
        old_team = battle.pop('preset_team', 1)
        data.pop('switch_soul_config', None)

        if 'enable_raid_loadout' not in battle and 'raid_preset' not in battle:
            preset = f'{old_group},{old_team}' if old_enabled else None
            if not old_enabled or battle.get('lock_team_enable'):
                if soul.get('enable_switch_by_name'):
                    preset = f"{soul.get('group_name', '')},{soul.get('team_name', '')}"
                elif soul.get('enable'):
                    preset = soul.get('switch_group_team', '-1,-1')
            if preset is not None:
                battle.update(enable_raid_loadout=True, raid_preset=preset)
        return {**data, 'general_battle_config': battle}
