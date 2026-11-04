import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from module.exception import ScriptError
from tasks.AssetSnapshot.asset_snapshot import parse_top_resource_quantity
from tasks.AssetSnapshot.assets import VARIABLE_MAPPING
from tasks.AssetSnapshot.history import SnapshotStore
from tasks.AssetSnapshot.script_task import ScriptTask


class TopResourceQuantityTest(unittest.TestCase):
    def test_accepts_whole_numeric_text_and_game_units(self):
        for raw, expected in [
            ("9838", 9838), (" 9826 ", 9826), ("0", 0), (0, 0),
            ("6.1万", 61000), ("917万", 9170000), ("1亿", 100000000),
            ("2.3千", 2300), ("9,838", 9838), ("9，838", 9838),
        ]:
            with self.subTest(raw=raw):
                self.assertEqual(parse_top_resource_quantity(raw), expected)

    def test_rejects_mixed_text_instead_of_extracting_a_numeric_suffix(self):
        for raw in [
            "皖838", "9838皖", "勾玉9838", "9838+", "9O38", "O", "-838",
            "9 838", "9,83", "6.1万838", "1.2.3", "1万万", "", None,
        ]:
            with self.subTest(raw=raw):
                self.assertIsNone(parse_top_resource_quantity(raw))


class TopResourceReadingTest(unittest.TestCase):
    def task(self, variable="gold", raw="皖838"):
        task = object.__new__(ScriptTask)
        task.config = SimpleNamespace(config_name="test", asset_snapshot=None)
        task.device = SimpleNamespace(image=object(), image_frame_id=None)
        task.screenshot = Mock(side_effect=lambda: setattr(task.device, "image", object()))
        task.appear = Mock(return_value=True)
        task._select_category = Mock()
        task._reset_material_grid_to_top = Mock()
        task._scan_material_pages = Mock(return_value=True)
        task._write_match_score_diagnostics = Mock()
        rule = SimpleNamespace(roi=task.TOP_RESOURCE_ROIS[variable], ocr=Mock(return_value=raw))
        task.TOP_RESOURCE_OCR = {variable: rule}
        return task, rule

    def test_valid_initial_read_uses_no_fallback(self):
        task, rule = self.task(raw="9838")
        with patch("tasks.AssetSnapshot.script_task.RuleOcr") as fallback:
            self.assertEqual(task._scan_top_resources(), {"gold": 9838})
        rule.ocr.assert_called_once_with(task.device.image)
        fallback.assert_not_called()
        task.screenshot.assert_not_called()

    def test_mixed_read_retries_on_a_new_frame_and_recovers_complete_number(self):
        task, rule = self.task()
        first_image = task.device.image
        fallback_rule = Mock()
        fallback_rule.ocr.return_value = "9838"
        with patch("tasks.AssetSnapshot.script_task.RuleOcr", return_value=fallback_rule) as fallback, \
                patch("tasks.AssetSnapshot.script_task.time.sleep"):
            self.assertEqual(task._scan_top_resources(), {"gold": 9838})
        task.screenshot.assert_called_once()
        self.assertIsNot(task.device.image, first_image)
        fallback_rule.ocr.assert_called_once_with(task.device.image)
        x, _, width, _ = fallback.call_args.kwargs["roi"]
        self.assertLessEqual(x, rule.roi[0])
        self.assertGreaterEqual(x + width, rule.roi[0] + rule.roi[2])

    def test_persistent_mixed_text_exhausts_bounded_retries(self):
        task, _ = self.task()
        fallback_rule = Mock()
        fallback_rule.ocr.return_value = "皖838"
        with patch("tasks.AssetSnapshot.script_task.RuleOcr", return_value=fallback_rule) as fallback, \
                patch("tasks.AssetSnapshot.script_task.time.sleep"):
            with self.assertRaisesRegex(ScriptError, "gold"):
                task._scan_top_resources()
        self.assertEqual(task.screenshot.call_count, 2)
        self.assertEqual(fallback.call_count, 2)
        self.assertEqual(fallback_rule.ocr.call_count, 2)
        self.assertNotEqual(fallback.call_args_list[0].kwargs["roi"],
                            fallback.call_args_list[1].kwargs["roi"])

    def test_second_fallback_can_recover_after_another_mixed_read(self):
        task, _ = self.task()
        fallback_rule = Mock()
        fallback_rule.ocr.side_effect = ["皖838", "9838"]
        with patch("tasks.AssetSnapshot.script_task.RuleOcr", return_value=fallback_rule), \
                patch("tasks.AssetSnapshot.script_task.time.sleep"):
            self.assertEqual(task._scan_top_resources(), {"gold": 9838})
        self.assertEqual(task.screenshot.call_count, 2)
        self.assertIsNot(fallback_rule.ocr.call_args_list[0].args[0],
                         fallback_rule.ocr.call_args_list[1].args[0])

    def test_zero_soul_jade_still_uses_the_single_digit_fallback(self):
        task, _ = self.task(variable="soul_jade", raw="")
        fallback_rule = Mock()
        fallback_rule.ocr.return_value = "0"
        with patch("tasks.AssetSnapshot.script_task.RuleOcr", return_value=fallback_rule) as fallback, \
                patch("tasks.AssetSnapshot.script_task.time.sleep"):
            self.assertEqual(task._scan_top_resources(), {"soul_jade": 0})
        self.assertEqual(fallback.call_args.kwargs["roi"], (1185, 12, 30, 40))

    def test_single_digit_soul_jade_crop_cannot_supply_a_nonzero_balance(self):
        task, _ = self.task(variable="soul_jade", raw="")
        fallback_rule = Mock()
        fallback_rule.ocr.return_value = "8"
        with patch("tasks.AssetSnapshot.script_task.RuleOcr", return_value=fallback_rule), \
                patch("tasks.AssetSnapshot.script_task.time.sleep"):
            with self.assertRaisesRegex(ScriptError, "soul_jade"):
                task._scan_top_resources()

    def test_leaving_inventory_during_retry_aborts_before_using_fallback(self):
        task, _ = self.task()
        task.appear.return_value = False
        with patch("tasks.AssetSnapshot.script_task.RuleOcr") as fallback, \
                patch("tasks.AssetSnapshot.script_task.time.sleep"):
            with self.assertRaises(ScriptError):
                task._scan_top_resources()
        fallback.assert_not_called()

    def test_failed_top_resource_read_preserves_history_for_recent_and_full_scans(self):
        for force_full in (False, True):
            with self.subTest(force_full=force_full), tempfile.TemporaryDirectory() as root:
                task, _ = self.task()
                task._settings = Mock(return_value=SimpleNamespace(
                    force_full_scan=force_full, max_reset_swipes=3,
                    max_scan_swipes=10, match_threshold=.95,
                ))
                task._prepare_game = Mock()
                task.goto_page = Mock()
                store = SnapshotStore(root, "test", "device", "character", VARIABLE_MAPPING)
                values = dict.fromkeys(VARIABLE_MAPPING.values(), 0)
                values["jade"] = 9826
                store.save({"status": "ready", "updatedAt": "2026-11-01T18:58:06",
                            "values": values}, "composite", None)
                before = store.path.read_bytes()
                task._snapshot_store = Mock(return_value=store)
                fallback_rule = Mock()
                fallback_rule.ocr.return_value = "皖838"
                with patch("tasks.AssetSnapshot.script_task.RuleOcr", return_value=fallback_rule), \
                        patch("tasks.AssetSnapshot.script_task.time.sleep"):
                    with self.assertRaisesRegex(ScriptError, "gold"):
                        task.execute_workflow()
                self.assertEqual(store.path.read_bytes(), before)
                task._scan_material_pages.assert_not_called()
                self.assertEqual(task.goto_page.call_args.args[0].key, "page_main")
                task._select_category.assert_called_once_with(
                    "composite" if force_full else "recent",
                )


if __name__ == "__main__":
    unittest.main()
