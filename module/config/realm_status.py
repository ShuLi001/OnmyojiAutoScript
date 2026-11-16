"""Last observed in-game realm timers and cards for each script profile."""

import math
import sqlite3
from contextlib import closing
from datetime import timedelta
from pathlib import Path
from time import time
from typing import Literal, NamedTuple

from module.config.utils import configured_device_id
from module.logger import logger

_DATABASE = Path("config/realm_status.sqlite3")
RealmTimer = Literal["foster", "card"]


class RealmCard(NamedTuple):
    kind: str
    value: int


def realm_resource_card(name: str, value: int) -> RealmCard | None:
    kind = {"太鼓": "taiko", "斗鱼": "fish"}.get(name)
    return RealmCard(kind, value) if kind and value > 0 else None


def _identity(config):
    return (
        config.config_name,
        configured_device_id(config),
        str(config.restart.login_character_config.character),
    )


def record_realm_timer(
    config, timer: RealmTimer, remaining: timedelta | None, *,
    empty=False, card: RealmCard | None = None,
):
    """Store a real timer reading, a confirmed empty slot, or an unreadable timer."""
    expires_at = None if remaining is None else time() + remaining.total_seconds()
    state = "empty" if empty else "unknown" if expires_at is None else "timed"
    try:
        with closing(sqlite3.connect(_DATABASE)) as db, db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("""
                CREATE TABLE IF NOT EXISTS realm_timer (
                    profile TEXT, device TEXT, character TEXT, timer TEXT,
                    state TEXT NOT NULL, expires_at REAL,
                    card_kind TEXT, card_value INTEGER,
                    PRIMARY KEY (profile, device, character, timer)
                )
            """)
            columns = {column[1] for column in db.execute("PRAGMA table_info(realm_timer)")}
            if "card_kind" not in columns:
                db.execute("ALTER TABLE realm_timer ADD COLUMN card_kind TEXT")
                db.execute("ALTER TABLE realm_timer ADD COLUMN card_value INTEGER")
            identity = (*_identity(config), timer)
            if card is None and state == "timed":
                # A repeated OCR reading can shift the estimated end by a few seconds.
                previous = db.execute("""
                    SELECT card_kind, card_value FROM realm_timer
                    WHERE profile = ? AND device = ? AND character = ? AND timer = ?
                      AND card_kind IS NOT NULL AND abs(expires_at - ?) <= 10
                """, (*identity, expires_at)).fetchone()
                if previous:
                    card = RealmCard(*previous)
            db.execute("""
                INSERT INTO realm_timer (
                    profile, device, character, timer, state, expires_at, card_kind, card_value
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (profile, device, character, timer)
                DO UPDATE SET state = excluded.state, expires_at = excluded.expires_at,
                    card_kind = excluded.card_kind, card_value = excluded.card_value
            """, (*identity, state, expires_at, *(card or (None, None))))
    except sqlite3.Error as error:
        logger.warning(f"Could not save realm timer {timer}: {error}")


def observe_realm_timer(
    config, timer: RealmTimer, ocr, image, *, card: RealmCard | None = None,
) -> timedelta:
    """Publish only validated readings while keeping the scheduler's OCR fallback."""
    text = ocr.ocr_single(image)
    remaining = ocr.parse_time(text, strict=True)
    record_realm_timer(config, timer, remaining, card=card)
    if remaining is not None:
        return remaining
    return ocr.parse_time(text) if text else timedelta(0)


def read_realm_timers(config):
    result = {timer: {"state": "unknown"} for timer in ("foster", "card")}
    if not _DATABASE.exists():
        return result
    try:
        with closing(sqlite3.connect(_DATABASE)) as db:
            db.row_factory = sqlite3.Row
            rows = db.execute("""
                SELECT * FROM realm_timer
                WHERE profile = ? AND device = ? AND character = ?
            """, _identity(config)).fetchall()
    except sqlite3.Error as error:
        logger.warning(f"Could not read realm timers: {error}")
        return result

    now = time()
    for row in rows:
        timer, state, expires_at = row["timer"], row["state"], row["expires_at"]
        if state == "timed":
            remaining = max(0, math.ceil(expires_at - now))
            result[timer] = {
                "state": "active" if remaining > 0 else "expired",
                "remaining_seconds": remaining,
            }
        else:
            result[timer] = {"state": state}
        if (
            result[timer]["state"] in ("active", "unknown")
            and "card_kind" in row.keys()
            and row["card_kind"]
        ):
            result[timer]["card"] = {"kind": row["card_kind"], "value": row["card_value"]}
    return result


def update_realm_timer_profile(name: str, new_name: str | None = None):
    """Keep saved timers with the profile when it is renamed or deleted."""
    if not _DATABASE.exists():
        return
    try:
        with closing(sqlite3.connect(_DATABASE)) as db, db:
            if new_name is None:
                db.execute("DELETE FROM realm_timer WHERE profile = ?", (name,))
            else:
                db.execute("UPDATE realm_timer SET profile = ? WHERE profile = ?", (new_name, name))
    except sqlite3.Error as error:
        logger.warning(f"Could not update realm timer profile: {error}")
