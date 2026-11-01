from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Mapping

from module.logger import logger


class SnapshotStore:
    """Keep completed baselines separate from scheduler configuration and diagnostics."""

    def __init__(self, root: str | Path, profile: str, serial: str, character: str,
                 mapping: Mapping[str, str]):
        self.identity = {"config": profile, "serial": serial, "character": character}
        self.variables = set(mapping.values())
        digest = hashlib.sha256(json.dumps(self.identity, sort_keys=True).encode()).hexdigest()[:24]
        self.path = Path(root) / f"{digest}.json"

    def _valid(self, document: object) -> bool:
        if not isinstance(document, dict):
            return False
        snapshot = document.get("snapshot")
        if not isinstance(snapshot, dict):
            return False
        values = snapshot.get("values")
        return (
            document.get("schemaVersion") == 1
            and document.get("identity") == self.identity
            and bool(document.get("fullScanCompletedAt"))
            and snapshot.get("status") == "ready"
            and bool(snapshot.get("updatedAt"))
            and isinstance(values, dict)
            and set(values) == self.variables
            and all(type(value) is int and value >= 0 for value in values.values())
        )

    def load(self) -> dict | None:
        if not self.path.exists():
            return None
        try:
            document = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            logger.warning(f"AssetSnapshot history unreadable, use full scan: {self.path}")
            return None
        if not self._valid(document):
            logger.warning(f"AssetSnapshot history invalid, use full scan: {self.path}")
            return None
        return document

    def save(self, snapshot: dict, category: str, previous: dict | None) -> None:
        if category not in {"composite", "recent"}:
            raise ValueError("unknown snapshot category")
        if category == "recent" and not self._valid(previous):
            raise ValueError("recent scan requires a completed full baseline")
        document = {
            "schemaVersion": 1,
            "identity": self.identity,
            "fullScanCompletedAt": snapshot.get("updatedAt") if category == "composite"
                else previous["fullScanCompletedAt"],
            "lastCategory": category,
            "snapshot": snapshot,
        }
        if not self._valid(document):
            raise ValueError("cannot persist incomplete asset snapshot")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(prefix=self.path.stem, suffix=".tmp", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(document, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp_name, self.path)
        finally:
            Path(temp_name).unlink(missing_ok=True)
