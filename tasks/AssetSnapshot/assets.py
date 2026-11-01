from __future__ import annotations

import json
from pathlib import Path

from module.atom.click import RuleClick
from module.atom.image import RuleImage
from module.atom.ocr import RuleOcr
from module.atom.swipe import RuleSwipe

from tasks.AssetSnapshot.asset_snapshot import (
    MATERIAL_GRID_ROI,
    MATERIAL_MATCH_TEMPLATE_SIZE,
    MATERIAL_SWIPE_END,
    MATERIAL_SWIPE_START,
    TOP_RESOURCE_VARIABLES,
    load_variable_mapping,
    material_variables,
)

TASK_ROOT = Path(__file__).resolve().parent
MAPPING_PATH = TASK_ROOT / "asset_snapshot_variables.json"
TEMPLATE_CATALOG_PATH = TASK_ROOT / "assets" / "templates" / "template_catalog.json"
VARIABLE_MAPPING = load_variable_mapping(MAPPING_PATH)
MATERIAL_MAPPING = material_variables(VARIABLE_MAPPING)
TEMPLATE_CATALOG = json.loads(TEMPLATE_CATALOG_PATH.read_text(encoding="utf-8"))
MATERIAL_TEMPLATE_CATALOG = [
    entry for entry in TEMPLATE_CATALOG if entry["kind"] == "material"
]

class AssetSnapshotAssets:
    """资产快照识别规则，坐标基于 1280x720 游戏画面。"""

    VARIABLE_MAPPING = VARIABLE_MAPPING
    MATERIAL_MAPPING = MATERIAL_MAPPING
    MATERIAL_GRID_ROI = MATERIAL_GRID_ROI

    # The crop contains only the building, below the roaming courtyard cat.
    I_INVENTORY_ENTRY = RuleImage(
        roi_front=(326, 627, 47, 30),
        roi_back=(290, 615, 110, 72),
        threshold=0.85,
        method="Template matching",
        file="./tasks/AssetSnapshot/assets/inventory_entry.png",
    )

    I_CHECK_INVENTORY = RuleImage(
        roi_front=(86, 14, 106, 47),
        roi_back=(12, 8, 280, 61),
        threshold=0.82,
        method="Template matching",
        file="./tasks/AssetSnapshot/assets/inventory_title.png",
    )
    I_TAB_COMPOSITE = RuleImage(
        roi_front=(58, 189, 173, 53),
        roi_back=(58, 189, 173, 53),
        threshold=0.82,
        method="Template matching",
        file="./tasks/AssetSnapshot/assets/tab_zonghe.png",
    )
    I_SCROLL_THUMB_TOP = RuleImage(
        roi_front=(792, 162, 43, 43),
        roi_back=(792, 162, 43, 43),
        threshold=0.85,
        method="Template matching",
        file="./tasks/AssetSnapshot/assets/scroll_thumb_top.png",
    )
    I_SCROLL_THUMB_BOTTOM = RuleImage(
        roi_front=(792, 644, 43, 43),
        roi_back=(792, 644, 43, 43),
        threshold=0.85,
        method="Template matching",
        file="./tasks/AssetSnapshot/assets/scroll_thumb_bottom.png",
    )
    C_TAB_COMPOSITE = RuleClick(
        roi_front=(58, 189, 173, 53),
        roi_back=(58, 189, 173, 53),
        name="asset_snapshot_composite",
    )
    I_TAB_RECENT = RuleImage(
        roi_front=(58, 249, 173, 53),
        roi_back=(58, 249, 173, 53),
        threshold=0.95,
        method="Template matching",
        file="./tasks/AssetSnapshot/assets/tab_zuijin.png",
    )
    C_TAB_RECENT = RuleClick(
        roi_front=(75, 258, 136, 36),
        roi_back=(75, 258, 136, 36),
        name="asset_snapshot_recent",
    )
    S_MATERIAL_GRID_UP = RuleSwipe(
        roi_front=(*MATERIAL_SWIPE_START, 2, 2),
        roi_back=(*MATERIAL_SWIPE_END, 2, 2),
        mode="vector",
        name="asset_snapshot_material_grid_up",
    )
    S_MATERIAL_GRID_DOWN = RuleSwipe(
        roi_front=(*MATERIAL_SWIPE_END, 2, 2),
        roi_back=(*MATERIAL_SWIPE_START, 2, 2),
        mode="vector",
        name="asset_snapshot_material_grid_down",
    )

    TOP_RESOURCE_ROIS = {
        "gold": (526, 14, 94, 39),
        "stamina": (725, 14, 96, 39),
        "jade": (924, 14, 98, 39),
        "soul_jade": (1118, 14, 84, 39),
    }

    TOP_RESOURCE_OCR = {
        variable_name: RuleOcr(
            roi=roi,
            area=roi,
            mode="Single",
            method="Default",
            keyword="",
            name=f"asset_snapshot_{variable_name}",
        )
        for variable_name, roi in TOP_RESOURCE_ROIS.items()
    }

    MATERIAL_RULES = [
        RuleImage(
            roi_front=(0, 0, *MATERIAL_MATCH_TEMPLATE_SIZE),
            roi_back=MATERIAL_GRID_ROI,
            threshold=0.95,
            method="Template matching",
            file=f"./tasks/AssetSnapshot/assets/templates/{entry['template_path']}",
        )
        for entry in MATERIAL_TEMPLATE_CATALOG
    ]

    MATERIAL_RULE_TO_VARIABLE = {
        id(rule): entry["variable_name"]
        for rule, entry in zip(MATERIAL_RULES, MATERIAL_TEMPLATE_CATALOG)
    }

    DETAIL_HOLD_OCR = RuleOcr(
        roi=(860, 146, 160, 39),
        area=(860, 146, 160, 39),
        mode="Quantity",
        method="Default",
        keyword="",
        name="asset_snapshot_detail_hold",
    )
