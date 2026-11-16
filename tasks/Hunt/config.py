# This Python file uses the following encoding: utf-8
# @author runhey
# github https://github.com/runhey
from datetime import timedelta
from pydantic import Field, field_validator, model_validator
from tasks.Component.QuickLoadout.dungeon_config import DungeonBattleConfig

from tasks.Component.config_scheduler import Scheduler
from tasks.Component.config_base import ConfigBase, Time, dynamic_hide


class HuntTime(ConfigBase):
    # 自定义运行时间
    kirin_time: Time = Field(default=Time(hour=19, minute=0, second=0))
    netherworld_time: Time = Field(default=Time(hour=19, minute=0, second=0))


class HuntGeneralBattleConfig(DungeonBattleConfig):
    hunt_hide_fields = dynamic_hide('lock_team_enable')


class KirinBattleConfig(HuntGeneralBattleConfig):
    enable_dungeon_loadout: bool = Field(default=False, description='enable_kirin_loadout_help')


class NetherWorldBattleConfig(HuntGeneralBattleConfig):
    enable_dungeon_loadout: bool = Field(default=False, description='enable_netherworld_loadout_help')
    continuous_battle: bool = True

    @field_validator('continuous_battle', mode='after')
    @classmethod
    def validate_continuous_battle(cls, v):
        return True


class Hunt(ConfigBase):
    scheduler: Scheduler = Field(default_factory=Scheduler)
    hunt_time: HuntTime = Field(default_factory=HuntTime)
    kirin_battle_config: KirinBattleConfig = Field(default_factory=KirinBattleConfig)
    netherworld_battle_config: NetherWorldBattleConfig = Field(default_factory=NetherWorldBattleConfig)

    @model_validator(mode='before')
    @classmethod
    def migrate_loadout_config(cls, data):
        if not isinstance(data, dict):
            return data
        hunt = data.get('hunt_config', {})
        if not isinstance(hunt, dict):
            return data

        migrated, hunt = dict(data), dict(hunt)
        for kind in ('kirin', 'netherworld'):
            preset = hunt.pop(f'{kind}_group_team', '-1,-1')
            key = f'{kind}_battle_config'
            battle = data.get(key, {})
            if not isinstance(battle, dict):
                continue

            battle = dict(battle)
            old_enabled = battle.pop('preset_enable', False)
            old_group = battle.pop('preset_group', 1)
            old_team = battle.pop('preset_team', 1)
            if 'enable_dungeon_loadout' not in battle and 'dungeon_preset' not in battle:
                if old_enabled and not battle.get('lock_team_enable'):
                    preset = f'{old_group},{old_team}'
                if isinstance(preset, str) and preset.strip() not in ('', '-1,-1'):
                    battle.update(enable_dungeon_loadout=True, dungeon_preset=preset)
            migrated[key] = battle
        if hunt:
            migrated['hunt_config'] = hunt
        else:
            migrated.pop('hunt_config', None)
        return migrated
