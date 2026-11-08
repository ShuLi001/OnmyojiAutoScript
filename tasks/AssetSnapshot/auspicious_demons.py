from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np

from tasks.AssetSnapshot.asset_snapshot import MATERIAL_GRID_ROI, normalize_inventory_title


DEMON_NAMES = {
    "four_star_auspicious_demon": "四星青吉鬼",
    "five_star_auspicious_demon": "五星青吉鬼",
    "six_star_auspicious_demon": "六星青吉鬼",
}
DEMON_VARIABLES = frozenset(DEMON_NAMES)
GRID_COLUMNS = (271, 373, 476, 578, 681)
GRID_VISIBLE_BOTTOM = 660
BODY_X, BODY_Y = 18, 9
BODY_THRESHOLD = 0.85


@dataclass(frozen=True)
class DemonCandidate:
    area: tuple[int, int, int, int]
    body_score: float
    variable: str | None
    badge_scores: dict[str, float]


def _orange_mask(image: np.ndarray) -> np.ndarray:
    hsv = cv2.cvtColor(image, cv2.COLOR_RGB2HSV)
    return cv2.inRange(hsv, (3, 145, 140), (27, 255, 255)).astype(bool)


@lru_cache(maxsize=1)
def _templates() -> tuple[np.ndarray, dict[str, np.ndarray]]:
    directory = Path(__file__).parent / "assets/templates/full_cells/material"
    masks = {}
    for variable, name in DEMON_NAMES.items():
        png = np.fromfile(directory / f"{name}.png", dtype=np.uint8)
        card = cv2.cvtColor(cv2.imdecode(png, cv2.IMREAD_COLOR), cv2.COLOR_BGR2RGB)
        if variable == "four_star_auspicious_demon":
            body = card[BODY_Y:60, BODY_X:80].copy()
        masks[variable] = _orange_mask(card[72:90, 6:42])
    return body, masks


def _classify_badge(image: np.ndarray, x: int, y: int, masks: dict[str, np.ndarray]):
    if y + 92 > GRID_VISIBLE_BOTTOM:
        return None, {}
    # The white stock count can cover the rightmost digits. Use the left orange
    # strokes only, with a small tolerance around the aligned grid origin.
    sample = _orange_mask(image[y + 70:y + 92, x + 5:x + 43])
    patches = [sample[dy:dy + 18, dx:dx + 36] for dy in range(5) for dx in range(3)]
    scores = {
        variable: max(
            2 * np.count_nonzero(patch & mask)
            / max(1, np.count_nonzero(patch) + np.count_nonzero(mask))
            for patch in patches
        )
        for variable, mask in masks.items()
    }
    hsv = cv2.cvtColor(image[y + 8:y + 27, x + 6:x + 20], cv2.COLOR_RGB2HSV)
    purple = np.count_nonzero(cv2.inRange(hsv, (121, 65, 45), (166, 255, 255))) / hsv.shape[0] / hsv.shape[1]
    four_star = "four_star_auspicious_demon"
    if purple >= 0.55 and scores[four_star] >= 0.72:
        return four_star, scores
    first, second, *_ = sorted(scores, key=scores.get, reverse=True)
    if purple <= 0.10 and first != four_star and scores[first] >= 0.84 and scores[first] - scores[second] >= 0.19:
        return first, scores
    return None, scores


def find_demon_candidates(image: np.ndarray | None) -> list[DemonCandidate]:
    if image is None:
        return []
    body, masks = _templates()
    gx, gy, width, _ = MATERIAL_GRID_ROI
    peaks = cv2.matchTemplate(image[gy:GRID_VISIBLE_BOTTOM, gx:gx + width], body, cv2.TM_CCOEFF_NORMED)
    candidates = []
    while True:
        _, score, _, (px, py) = cv2.minMaxLoc(peaks)
        if score < BODY_THRESHOLD:
            break
        # Suppress all nearby peaks for this card, without hiding an adjacent card.
        peaks[max(0, py - 40):py + 41, max(0, px - 40):px + 41] = -1
        x, y = gx + px - BODY_X, gy + py - BODY_Y
        column = min(GRID_COLUMNS, key=lambda center: abs(x - center))
        if abs(x - column) > 10 or y + 54 > GRID_VISIBLE_BOTTOM:
            continue
        variable, scores = _classify_badge(image, column, y, masks)
        candidates.append(DemonCandidate((column, y, 95, 70), score, variable, scores))
    return sorted(candidates, key=lambda candidate: (candidate.area[1], candidate.area[0]))


def demon_detail_variable(text: object) -> str | None:
    title = normalize_inventory_title(text)
    title = {"4": "四", "5": "五", "6": "六"}.get(title[:1], title[:1]) + title[1:]
    return next((variable for variable, name in DEMON_NAMES.items() if title == name), None)
