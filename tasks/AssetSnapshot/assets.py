from __future__ import annotations

import json
from pathlib import Path

from module.atom.click import RuleClick
from module.atom.image import RuleImage
from module.atom.ocr import RuleOcr
from module.atom.swipe import RuleSwipe

from tasks.AssetSnapshot.asset_snapshot import (
    DEFAULT_MATERIAL_MATCH_THRESHOLD,
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
MATERIAL_MATCH_TEMPLATES = [
    (entry["variable_name"], path)
    for entry in MATERIAL_TEMPLATE_CATALOG
    for path in [entry["template_path"], *entry.get("variants", [])]
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

    # Stay left of the purchase '+' button at x=820 and later.
    C_STAMINA_DETAIL = RuleClick(
        roi_front=(674, 16, 143, 30), roi_back=(674, 16, 143, 30),
        name="asset_snapshot_stamina_detail",
    )
    I_STAMINA_DETAIL = RuleImage(
        roi_front=(420, 130, 80, 35), roi_back=(414, 122, 105, 51),
        threshold=0.90, method="Template matching",
        file="./tasks/AssetSnapshot/assets/stamina_detail_title.png",
    )
    O_STAMINA_DETAIL_NAME = RuleOcr(
        roi=(420, 130, 120, 35), area=(420, 130, 120, 35),
        mode="Single", method="Default", keyword="",
        name="asset_snapshot_stamina_detail_name",
    )
    O_STAMINA_DETAIL_OWNED = RuleOcr(
        roi=(420, 164, 190, 34), area=(420, 164, 190, 34),
        mode="Single", method="Default", keyword="",
        name="asset_snapshot_stamina_detail_owned",
    )
    C_STAMINA_DETAIL_CLOSE = RuleClick(
        roi_front=(970, 550, 190, 75), roi_back=(970, 550, 190, 75),
        name="asset_snapshot_stamina_detail_close",
    )

    # ADB coordinates: include the jade icon and number field, exclude '+'.
    C_JADE_DETAIL = RuleClick(
        roi_front=(876, 16, 143, 30), roi_back=(876, 16, 143, 30),
        name="asset_snapshot_jade_detail",
    )
    I_JADE_DETAIL = RuleImage(
        roi_front=(624, 130, 80, 35), roi_back=(618, 122, 105, 51),
        threshold=0.90, method="Template matching",
        file="./tasks/AssetSnapshot/assets/jade_detail_title.png",
    )
    O_JADE_DETAIL_NAME = RuleOcr(
        roi=(624, 130, 120, 35), area=(624, 130, 120, 35),
        mode="Single", method="Default", keyword="",
        name="asset_snapshot_jade_detail_name",
    )
    O_JADE_DETAIL_OWNED = RuleOcr(
        roi=(624, 164, 190, 34), area=(624, 164, 190, 34),
        mode="Single", method="Default", keyword="",
        name="asset_snapshot_jade_detail_owned",
    )
    # The gutter between category buttons and cards cannot activate an item.
    C_JADE_DETAIL_CLOSE = RuleClick(
        roi_front=(240, 540, 22, 100), roi_back=(240, 540, 22, 100),
        name="asset_snapshot_jade_detail_close",
    )

    MATERIAL_RULES = [
        RuleImage(
            roi_front=(0, 0, *MATERIAL_MATCH_TEMPLATE_SIZE),
            roi_back=MATERIAL_GRID_ROI,
            threshold=DEFAULT_MATERIAL_MATCH_THRESHOLD,
            method="Template matching",
            file=f"./tasks/AssetSnapshot/assets/templates/{template_path}",
        )
        for _, template_path in MATERIAL_MATCH_TEMPLATES
    ]

    MATERIAL_RULE_TO_VARIABLE = {
        id(rule): variable_name
        for rule, (variable_name, _) in zip(MATERIAL_RULES, MATERIAL_MATCH_TEMPLATES)
    }

    DETAIL_HOLD_OCR = RuleOcr(
        roi=(860, 146, 160, 39),
        area=(860, 146, 160, 39),
        mode="Quantity",
        method="Default",
        keyword="",
        name="asset_snapshot_detail_hold",
    )

    I_SKIN_TICKET_BODY = RuleImage(
        roi_front=(0, 0, 67, 45),
        roi_back=MATERIAL_GRID_ROI,
        threshold=0.90,
        method="Template matching",
        file="./tasks/AssetSnapshot/assets/skin_ticket_body.png",
    )
    I_SP_TICKET_BADGE = RuleImage(
        roi_front=(0, 0, 30, 17),
        roi_back=MATERIAL_GRID_ROI,
        threshold=0.80,
        method="Template matching",
        file="./tasks/AssetSnapshot/assets/sp_ticket_badge.png",
    )
    O_TICKET_DETAIL_NAME = RuleOcr(
        roi=(855, 110, 250, 39), area=(855, 110, 250, 39),
        mode="Single", method="Default", keyword="",
        name="asset_snapshot_ticket_detail_name",
    )
    O_TICKET_DETAIL_QUANTITY = RuleOcr(
        roi=(930, 148, 180, 36), area=(930, 148, 180, 36),
        mode="Single", method="Default", keyword="",
        name="asset_snapshot_ticket_detail_quantity",
    )
    O_MATERIAL_DETAIL_NAME = RuleOcr(
        roi=(849, 111, 228, 42), area=(849, 111, 228, 42),
        mode="Single", method="Default", keyword="",
        name="材料详情名称",
    )
    O_MATERIAL_DETAIL_NAME_RETRY = RuleOcr(
        roi=(850, 105, 255, 42), area=(850, 105, 255, 42),
        mode="Single", method="Default", keyword="",
        name="材料详情名称复核",
    )
    O_MATERIAL_DETAIL_OWNED = RuleOcr(
        roi=(850, 150, 192, 34), area=(850, 150, 192, 34),
        mode="Single", method="Default", keyword="",
        name="材料详情持有量",
    )
