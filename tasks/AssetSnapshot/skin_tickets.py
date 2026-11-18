from __future__ import annotations

import re
from dataclasses import dataclass

from tasks.AssetSnapshot.asset_snapshot import inventory_card_selected as skin_ticket_selected


SKIN_TICKET_VARIABLES = frozenset({"skin_ticket", "sp_skin_ticket"})
TICKET_BODY_OFFSET = (10, 6)
TICKET_CANDIDATE_THRESHOLD = 0.90
SP_BADGE_THRESHOLD = 0.80
SP_BADGE_ABSENT_THRESHOLD = 0.45
TICKET_SCORE_MARGIN = 0.03


@dataclass
class SkinTicketCandidate:
    area: tuple[int, int, int, int]
    body_score: float
    normal_score: float
    sp_score: float
    badge_score: float | None
    variable_name: str | None


def classify_skin_ticket(
    normal_score: float,
    sp_score: float,
    badge_score: float | None,
) -> str | None:
    if badge_score is None:
        return None
    if (
        badge_score >= SP_BADGE_THRESHOLD
        and sp_score >= TICKET_CANDIDATE_THRESHOLD
        and sp_score >= normal_score - TICKET_SCORE_MARGIN
    ):
        return "sp_skin_ticket"
    if (
        badge_score <= SP_BADGE_ABSENT_THRESHOLD
        and normal_score >= TICKET_CANDIDATE_THRESHOLD
        and normal_score - sp_score >= TICKET_SCORE_MARGIN
    ):
        return "skin_ticket"
    return None


def skin_ticket_name(text: object) -> str | None:
    name = re.sub(r"\s+", "", str(text)).upper()
    if name in {"SP皮肤券", "SP皮肤劵"}:
        return "sp_skin_ticket"
    if name in {"皮肤券", "皮肤劵"}:
        return "skin_ticket"
    return None
