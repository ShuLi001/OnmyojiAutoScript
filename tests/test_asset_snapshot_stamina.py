import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, call, patch

from module.exception import ScriptError
from tasks.AssetSnapshot.asset_snapshot import parse_stamina_detail_quantity
from tasks.AssetSnapshot.assets import VARIABLE_MAPPING
from tasks.AssetSnapshot.history import SnapshotStore
from tasks.AssetSnapshot.script_task import ScriptTask


class StaminaDetailTest(unittest.TestCase):
    def task(self, *, popup_open=False):
        task = object.__new__(ScriptTask)
        task.device = SimpleNamespace(image=object(), click_record_clear=Mock())
        task._refresh_inventory_frame = Mock()
        task.O_STAMINA_DETAIL_NAME = SimpleNamespace(ocr=Mock(return_value="体力"))
        task.O_STAMINA_DETAIL_OWNED = SimpleNamespace(ocr=Mock(return_value="已拥有:60994"))
        state = {"popup_open": popup_open, "inventory": True, "opens": True, "closes": True}

        def appear(target):
            return state["inventory"] if target is task.I_CHECK_INVENTORY else state["popup_open"]

        def click(target):
            if target is task.C_STAMINA_DETAIL and state["opens"]:
                state["popup_open"] = True
            elif target is task.C_STAMINA_DETAIL_CLOSE and state["closes"]:
                state["popup_open"] = False

        task.appear = Mock(side_effect=appear)
        task.click = Mock(side_effect=click)
        return task, state

    def test_owned_label_requires_a_complete_exact_integer(self):
        for raw, expected in [("已拥有:60994", 60994), (" 已拥有：60994 ", 60994),
                              ("已拥有: 0", 0)]:
            with self.subTest(raw=raw):
                self.assertEqual(parse_stamina_detail_quantity(raw), expected)
        for raw in ["已拥有:皖994", "已拥有:6.1万", "60994", "持有:60994",
                    "已拥有:-1", "已拥有:60994/100", "已拥有:60994abc", "", None]:
            with self.subTest(raw=raw):
                self.assertIsNone(parse_stamina_detail_quantity(raw))

    def test_random_click_spans_icon_and_number_without_reaching_plus(self):
        task, _ = self.task()
        for _ in range(1000):
            x, y = task.C_STAMINA_DETAIL.coord()
            self.assertTrue(674 <= x <= 817)
            self.assertTrue(16 <= y <= 46)
            self.assertLess(x, 820)

    @patch("tasks.AssetSnapshot.script_task.time.sleep")
    def test_clicks_once_reads_two_stable_values_then_closes(self, _sleep):
        task, state = self.task()
        self.assertEqual(task._read_stamina_detail(), 60994)
        self.assertEqual(task.click.call_args_list,
                         [call(task.C_STAMINA_DETAIL), call(task.C_STAMINA_DETAIL_CLOSE)])
        self.assertEqual(task.O_STAMINA_DETAIL_OWNED.ocr.call_count, 2)
        self.assertEqual(task._refresh_inventory_frame.call_count, 3)
        self.assertFalse(state["popup_open"])

    @patch("tasks.AssetSnapshot.script_task.time.sleep")
    def test_reuses_and_closes_an_existing_stamina_popup(self, _sleep):
        task, state = self.task(popup_open=True)
        self.assertEqual(task._read_stamina_detail(), 60994)
        task.click.assert_called_once_with(task.C_STAMINA_DETAIL_CLOSE)
        self.assertFalse(state["popup_open"])

    @patch("tasks.AssetSnapshot.script_task.time.sleep")
    def test_wrong_title_is_not_used_for_quantity(self, _sleep):
        task, state = self.task()
        task.O_STAMINA_DETAIL_NAME.ocr.return_value = "勾玉"
        with self.assertRaises(ScriptError):
            task._read_stamina_detail()
        task.O_STAMINA_DETAIL_OWNED.ocr.assert_not_called()
        self.assertFalse(state["popup_open"])

    @patch("tasks.AssetSnapshot.script_task.time.sleep")
    def test_waits_for_stable_exact_quantity_and_accepts_zero(self, _sleep):
        for readings, expected in [
            (["已拥有:60994", "已拥有:60995", "已拥有:60995"], 60995),
            (["已拥有:皖994", "已拥有:60994", "已拥有:60994"], 60994),
            (["已拥有:0", "已拥有:0"], 0),
        ]:
            with self.subTest(readings=readings):
                task, _ = self.task()
                task.O_STAMINA_DETAIL_OWNED.ocr.side_effect = readings
                self.assertEqual(task._read_stamina_detail(), expected)

    @patch("tasks.AssetSnapshot.script_task.time.sleep")
    def test_missing_popup_stops_after_one_open_click(self, _sleep):
        task, state = self.task()
        state["opens"] = False
        with self.assertRaises(ScriptError):
            task._read_stamina_detail()
        task.click.assert_called_once_with(task.C_STAMINA_DETAIL)
        task.O_STAMINA_DETAIL_OWNED.ocr.assert_not_called()

    @patch("tasks.AssetSnapshot.script_task.time.sleep")
    def test_invalid_detail_is_closed_and_never_falls_back_to_rounded_header(self, _sleep):
        task, state = self.task()
        task.TOP_RESOURCE_OCR = {
            "stamina": SimpleNamespace(roi=(725, 14, 96, 39), ocr=Mock(return_value="6.1万")),
        }
        task.O_STAMINA_DETAIL_OWNED.ocr.return_value = "已拥有:皖994"
        with self.assertRaises(ScriptError):
            task._scan_top_resources()
        self.assertFalse(state["popup_open"])

    @patch("tasks.AssetSnapshot.script_task.time.sleep")
    def test_top_resource_scan_replaces_rounded_header_with_popup_quantity(self, _sleep):
        task, state = self.task()
        task.TOP_RESOURCE_OCR = {
            "stamina": SimpleNamespace(roi=(725, 14, 96, 39), ocr=Mock(return_value="6.1万")),
            "jade": SimpleNamespace(roi=(924, 14, 98, 39), ocr=Mock(return_value="9838")),
        }
        self.assertEqual(task._scan_top_resources(), {"stamina": 60994, "jade": 9838})
        self.assertFalse(state["popup_open"])

    @patch("tasks.AssetSnapshot.script_task.time.sleep")
    def test_failed_close_aborts_even_when_quantity_is_valid(self, _sleep):
        task, state = self.task()
        state["closes"] = False
        with self.assertRaises(ScriptError):
            task._read_stamina_detail()
        self.assertEqual(task.click.call_args_list.count(call(task.C_STAMINA_DETAIL_CLOSE)), 3)

    @patch("tasks.AssetSnapshot.script_task.time.sleep")
    def test_leaving_inventory_never_clicks_close_on_another_page(self, _sleep):
        task, state = self.task()
        task._refresh_inventory_frame.side_effect = lambda purpose: state.update(inventory=False)
        with self.assertRaises(ScriptError):
            task._read_stamina_detail()
        task.click.assert_called_once_with(task.C_STAMINA_DETAIL)

    @patch("tasks.AssetSnapshot.script_task.time.sleep")
    def test_detail_failure_preserves_history_in_recent_and_full_scans(self, _sleep):
        for force_full in (False, True):
            with self.subTest(force_full=force_full), tempfile.TemporaryDirectory() as root:
                task, _ = self.task()
                task._settings = Mock(return_value=SimpleNamespace(
                    force_full_scan=force_full, max_reset_swipes=3,
                    max_scan_swipes=10, match_threshold=.95,
                ))
                task._prepare_game = Mock()
                task.goto_page = Mock()
                task.screenshot = Mock()
                task._select_category = Mock()
                task._reset_material_grid_to_top = Mock()
                task._scan_material_pages = Mock()
                task.TOP_RESOURCE_OCR = {
                    "stamina": SimpleNamespace(roi=(725, 14, 96, 39), ocr=Mock(return_value="6.1万")),
                }
                task.O_STAMINA_DETAIL_OWNED.ocr.return_value = "已拥有:皖994"
                store = SnapshotStore(root, "test", "device", "character", VARIABLE_MAPPING)
                values = dict.fromkeys(VARIABLE_MAPPING.values(), 0)
                values["stamina"] = 60994
                store.save({"status": "ready", "updatedAt": "2026-11-01T21:00:00",
                            "values": values}, "composite", None)
                before = store.path.read_bytes()
                task._snapshot_store = Mock(return_value=store)
                with self.assertRaises(ScriptError):
                    task.execute_workflow()
                self.assertEqual(store.path.read_bytes(), before)
                task._scan_material_pages.assert_not_called()


if __name__ == "__main__":
    unittest.main()
