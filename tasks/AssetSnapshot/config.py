from pydantic import Field

from tasks.Component.config_base import ConfigBase
from tasks.Component.config_scheduler import Scheduler


class AssetSnapshotConfig(ConfigBase):
    force_full_scan: bool = Field(default=False, description="asset_force_full_scan_help")
    full_scan_interval_hours: int = Field(default=0, ge=0, le=8760, description="asset_full_scan_interval_help")
    history_generation: int = Field(default=0, ge=0, description="asset_history_generation_help")
    max_reset_swipes: int = Field(default=3, ge=0, le=3)
    max_scan_swipes: int = Field(default=10, ge=0, le=10)
    match_threshold: float = Field(default=0.95, ge=0.80, le=1.0)


class AssetSnapshot(ConfigBase):
    scheduler: Scheduler = Field(default_factory=Scheduler)
    asset_snapshot_config: AssetSnapshotConfig = Field(default_factory=AssetSnapshotConfig)
