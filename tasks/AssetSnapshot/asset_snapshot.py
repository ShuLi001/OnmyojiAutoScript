from __future__ import annotations

import json
import random
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Mapping

TOP_RESOURCE_VARIABLES = frozenset({"gold", "stamina", "jade", "soul_jade"})

MATERIAL_GRID_ROI = (271, 188, 505, 495)
CELL_SIZE = (95, 95)
MATERIAL_MATCH_TEMPLATE_SIZE = (95, 70)
ICON_IN_CELL_OFFSET = (7, 7)
QUANTITY_RELATIVE_TO_CELL = (40, 64, 55, 31)
SWIPE_ROWS = 3.5
SWIPE_RANDOM_X_OFFSET = 18
SWIPE_RANDOM_Y_OFFSET = 10
MATERIAL_SWIPE_START = (540, 560)
MATERIAL_SWIPE_END = (540, 300)


def load_variable_mapping(path: str | Path) -> dict[str, str]:
    mapping = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(mapping, dict) or not mapping:
        raise ValueError("asset snapshot mapping must be a non-empty object")
    if any(not isinstance(key, str) or not isinstance(value, str) for key, value in mapping.items()):
        raise ValueError("asset snapshot mapping keys and values must be strings")
    if len(set(mapping.values())) != len(mapping):
        raise ValueError("asset snapshot variable names must be unique")
    return mapping


def material_variables(mapping: Mapping[str, str]) -> dict[str, str]:
    return {
        source_name: variable_name
        for source_name, variable_name in mapping.items()
        if variable_name not in TOP_RESOURCE_VARIABLES
    }


def build_empty_snapshot(mapping: Mapping[str, str]) -> dict[str, int]:
    return {variable_name: 0 for variable_name in mapping.values()}


def merge_snapshot_values(
    mapping: Mapping[str, str],
    values: Mapping[str, int],
) -> dict[str, int]:
    snapshot = build_empty_snapshot(mapping)
    for variable_name, value in values.items():
        if variable_name in snapshot:
            snapshot[variable_name] = max(0, int(value))
    return snapshot


def quantity_roi_from_cell(cell_origin: tuple[int, int]) -> tuple[int, int, int, int]:
    cell_x, cell_y = cell_origin
    rel_x, rel_y, width, height = QUANTITY_RELATIVE_TO_CELL
    return cell_x + rel_x, cell_y + rel_y, width, height


def quantity_roi_from_match(match_area: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    match_x, match_y, _, _ = match_area
    cell_x = match_x - ICON_IN_CELL_OFFSET[0]
    cell_y = match_y - ICON_IN_CELL_OFFSET[1]
    return quantity_roi_from_cell((cell_x, cell_y))


def quantity_roi_from_card_match(match_area: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    """Derive the quantity crop from a 95x70 material template match."""
    return quantity_roi_from_cell((match_area[0], match_area[1]))


def build_swipe_points(
    start: tuple[int, int],
    end: tuple[int, int],
    *,
    random_seed: int | None = None,
    x_offset: int = SWIPE_RANDOM_X_OFFSET,
    y_offset: int = SWIPE_RANDOM_Y_OFFSET,
) -> tuple[tuple[int, int], tuple[int, int]]:
    """Add bounded jitter without changing the vertical swipe direction."""
    source = random.Random(random_seed) if random_seed is not None else random
    start_point = (
        start[0] + source.randint(-x_offset, x_offset),
        start[1] + source.randint(-y_offset, y_offset),
    )
    end_point = (
        end[0] + source.randint(-x_offset, x_offset),
        end[1] + source.randint(-y_offset, y_offset),
    )
    return start_point, end_point


def scroll_boundary_state(*, top: bool, bottom: bool) -> str:
    if top and not bottom:
        return "top"
    if bottom and not top:
        return "bottom"
    if not top and not bottom:
        return "middle"
    return "unknown"


def classify_match_score(score: float, threshold: float = 0.95) -> str:
    return "accepted" if float(score) >= threshold else "below_threshold"


def normalize_quantity(raw: object) -> int:
    if raw is None:
        return 0
    text = str(raw).strip().replace(",", "").replace("，", "")
    if not text:
        return 0

    replacements = {
        "O": "0",
        "o": "0",
        "I": "1",
        "l": "1",
        "丨": "1",
        "S": "5",
        "B": "8",
    }
    text = "".join(replacements.get(char, char) for char in text)
    match = re.search(r"\d+(?:\.\d+)?", text)
    if not match:
        return 0

    try:
        value = Decimal(match.group(0))
    except InvalidOperation:
        return 0

    multiplier = Decimal(1)
    if "亿" in text:
        multiplier = Decimal(100000000)
    elif "万" in text:
        multiplier = Decimal(10000)
    elif "千" in text:
        multiplier = Decimal(1000)

    return max(0, int(value * multiplier))


def build_snapshot_payload(values: Mapping[str, int], updated_at: str) -> dict[str, object]:
    return {
        "status": "ready",
        "updatedAt": updated_at,
        "values": dict(values),
    }
