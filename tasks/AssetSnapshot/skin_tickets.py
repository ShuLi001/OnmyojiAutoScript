from __future__ import annotations

import re
from dataclasses import dataclass

import numpy as np


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

    def score_for(self, variable_name: str) -> float:
        return self.sp_score if variable_name == "sp_skin_ticket" else self.normal_score


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


def skin_ticket_selected(image: np.ndarray, area: tuple[int, int, int, int]) -> bool:
    """Confirm the cyan selection border before trusting the details panel."""
    x, y, _, _ = area
    height, width = image.shape[:2]
    card = image[max(0, y - 3):min(height, y + 98), max(0, x - 3):min(width, x + 98)]
    if not card.size:
        return False
    card = card.astype(np.int16)
    ring = np.zeros(card.shape[:2], dtype=bool)
    ring[:8, :] = ring[-8:, :] = True
    ring[:, :8] = ring[:, -8:] = True
    cyan = (
        (card[:, :, 1] > 170) & (card[:, :, 2] > 170)
        & (card[:, :, 1] - card[:, :, 0] > 60)
        & (card[:, :, 2] - card[:, :, 0] > 70)
    )
    return np.count_nonzero(cyan & ring) >= 60
