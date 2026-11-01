import unittest
from pathlib import Path

from tasks.AssetSnapshot.asset_snapshot import (
    MATERIAL_SWIPE_END,
    MATERIAL_SWIPE_START,
    MATERIAL_MATCH_TEMPLATE_SIZE,
    build_empty_snapshot,
    build_swipe_points,
    classify_match_score,
    load_variable_mapping,
    merge_snapshot_values,
    normalize_quantity,
    quantity_roi_from_card_match,
    quantity_roi_from_match,
    scroll_boundary_state,
)
from tasks.AssetSnapshot.script_task import ScriptTask
from tasks.AssetSnapshot.assets import AssetSnapshotAssets

ROOT = Path(__file__).resolve().parents[1]
MAPPING = ROOT.parent / "OASX" / "assets" / "asset_snapshot_variables.json"
ASSET_DIR = ROOT / "tasks" / "AssetSnapshot" / "assets" / "icons"


class AssetSnapshotContractTest(unittest.TestCase):
    def test_mapping_has_a_renamed_icon_for_every_source_icon(self):
        mapping = load_variable_mapping(MAPPING)
        source_dir = ROOT.parent / "图标"

        self.assertEqual(len(mapping), 73)
        self.assertEqual(len(set(mapping.values())), len(mapping))
        self.assertEqual({p.stem for p in source_dir.glob("*.png")}, set(mapping))
        self.assertEqual(
            {p.name for p in ASSET_DIR.glob("*.png")},
            {f"{variable}.png" for variable in mapping.values()},
        )

    def test_material_quantity_roi_is_derived_from_match_area(self):
        self.assertEqual(
            quantity_roi_from_match((280, 198, 80, 80)),
            (313, 255, 55, 31),
        )

    def test_gemini_card_template_quantity_roi_uses_card_origin(self):
        self.assertEqual(
            quantity_roi_from_card_match((271, 188, *MATERIAL_MATCH_TEMPLATE_SIZE)),
            (311, 252, 55, 31),
        )

    def test_material_rules_use_gemini_templates_and_high_threshold(self):
        self.assertEqual(len(AssetSnapshotAssets.MATERIAL_RULES), 68)
        self.assertTrue(
            all(
                "tasks/AssetSnapshot/assets/templates/material/" in rule.file
                for rule in AssetSnapshotAssets.MATERIAL_RULES
            )
        )
        self.assertTrue(all(rule.threshold >= 0.95 for rule in AssetSnapshotAssets.MATERIAL_RULES))
        self.assertTrue(all(rule.roi_front[2:] == list(MATERIAL_MATCH_TEMPLATE_SIZE) for rule in AssetSnapshotAssets.MATERIAL_RULES))

    def test_match_score_status_only_accepts_scores_at_or_above_threshold(self):
        self.assertEqual(classify_match_score(0.95), "accepted")
        self.assertEqual(classify_match_score(0.9499), "below_threshold")

    def test_normalize_quantity_supports_game_units_and_ocr_noise(self):
        self.assertEqual(normalize_quantity("6506万"), 65060000)
        self.assertEqual(normalize_quantity("2.3万"), 23000)
        self.assertEqual(normalize_quantity("1亿"), 100000000)
        self.assertEqual(normalize_quantity("O"), 0)
        self.assertEqual(normalize_quantity(""), 0)

    def test_output_contains_every_variable_and_missing_values_are_zero(self):
        mapping = load_variable_mapping(MAPPING)
        empty = build_empty_snapshot(mapping)
        self.assertEqual(set(empty), set(mapping.values()))
        self.assertTrue(all(value == 0 for value in empty.values()))

        merged = merge_snapshot_values(mapping, {"gold": 7940000})
        self.assertEqual(merged["gold"], 7940000)
        self.assertEqual(merged["stamina"], 0)
        self.assertEqual(merged["colorful_star_candy"], 0)

    def test_swipe_points_keep_direction_and_apply_bounded_random_offsets(self):
        points = build_swipe_points(
            MATERIAL_SWIPE_START,
            MATERIAL_SWIPE_END,
            random_seed=7,
            x_offset=18,
            y_offset=10,
        )
        (x1, y1), (x2, y2) = points
        self.assertLess(y2, y1)
        self.assertLessEqual(abs(x1 - MATERIAL_SWIPE_START[0]), 18)
        self.assertLessEqual(abs(x2 - MATERIAL_SWIPE_END[0]), 18)
        self.assertLessEqual(abs(y1 - MATERIAL_SWIPE_START[1]), 10)
        self.assertLessEqual(abs(y2 - MATERIAL_SWIPE_END[1]), 10)
        self.assertEqual(abs(MATERIAL_SWIPE_START[1] - MATERIAL_SWIPE_END[1]), 260)

    def test_swipe_duration_is_longer_than_the_default_fast_gesture(self):
        self.assertEqual(ScriptTask.swipe_duration, (0.45, 0.65))

    def test_scan_has_separate_finite_limits_for_reset_and_downward_scan(self):
        self.assertEqual(ScriptTask.max_reset_swipes, 3)
        self.assertEqual(ScriptTask.max_scan_swipes, 10)

    def test_scroll_boundary_state_distinguishes_top_bottom_and_middle(self):
        self.assertEqual(scroll_boundary_state(top=True, bottom=False), "top")
        self.assertEqual(scroll_boundary_state(top=False, bottom=True), "bottom")
        self.assertEqual(scroll_boundary_state(top=False, bottom=False), "middle")
        self.assertEqual(scroll_boundary_state(top=True, bottom=True), "unknown")


if __name__ == "__main__":
    unittest.main()
