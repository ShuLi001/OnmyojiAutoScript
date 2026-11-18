from typing import ClassVar

from pydantic import ConfigDict, Field, model_validator

from tasks.Component.GeneralBattle.config_general_battle import GeneralBattleConfig
from tasks.Component.config_base import ConfigBase


class DungeonBattleConfig(GeneralBattleConfig):
    lock_team_enable: bool = Field(default=False, description='dungeon_lock_team_help')
    preset_enable: ClassVar[bool] = False
    preset_group: ClassVar[int] = 1
    preset_team: ClassVar[int] = 1
    enable_dungeon_loadout: bool = Field(default=False, description='enable_dungeon_loadout_help')
    dungeon_preset: str = Field(default='', description='dungeon_preset_help')

    @staticmethod
    def _order_battle_settings(schema: dict) -> None:
        properties = schema['properties']
        first = ('lock_team_enable', 'enable_dungeon_loadout', 'dungeon_preset')
        schema['properties'] = {key: properties.pop(key) for key in first} | properties

    model_config = ConfigDict(json_schema_extra=_order_battle_settings)

    @staticmethod
    def parse_lineup(value: str) -> tuple[int, int] | tuple[str, str] | None:
        value = value.strip()
        if not value:
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

    def get_lineup(self) -> tuple[int, int] | tuple[str, str] | None:
        return self.parse_lineup(self.dungeon_preset) if self.enable_dungeon_loadout else None


class DungeonLoadoutTaskConfig(ConfigBase):
    BATTLE_GROUP: ClassVar[str] = 'general_battle_config'
    LEGACY_DUNGEON_GROUP: ClassVar[str]
    LEGACY_SOUL_GROUP: ClassVar[str] = 'switch_soul_config'
    LEGACY_LAYER_FIELDS: ClassVar[tuple[str, ...]] = ()

    @model_validator(mode='before')
    @classmethod
    def migrate_loadout_config(cls, data):
        if not isinstance(data, dict):
            return data
        battle = data.get(cls.BATTLE_GROUP, {})
        soul = data.get(cls.LEGACY_SOUL_GROUP, {})
        if not isinstance(battle, dict) or not isinstance(soul, dict):
            return data
        data, battle = dict(data), dict(battle)
        old_enabled = battle.pop('preset_enable', False)
        old_group = battle.pop('preset_group', 1)
        old_team = battle.pop('preset_team', 1)
        data.pop(cls.LEGACY_SOUL_GROUP, None)

        if 'enable_dungeon_loadout' not in battle and 'dungeon_preset' not in battle:
            preset = f'{old_group},{old_team}' if old_enabled else None
            dungeon = data.get(cls.LEGACY_DUNGEON_GROUP, {})
            member = isinstance(dungeon, dict) and dungeon.get('user_status') == 'member'
            if not old_enabled or battle.get('lock_team_enable') or member:
                if soul.get('enable_switch_by_name'):
                    preset = f"{soul.get('group_name', '')},{soul.get('team_name', '')}"
                elif soul.get('enable'):
                    preset = soul.get('switch_group_team', '-1,-1')
            for field in cls.LEGACY_LAYER_FIELDS:
                if field in soul:
                    battle.setdefault(field, soul[field])
            if preset is not None or battle.get('auto_switch_soul'):
                battle.update(enable_dungeon_loadout=True, dungeon_preset=preset if preset is not None else '')
        return {**data, cls.BATTLE_GROUP: battle}
