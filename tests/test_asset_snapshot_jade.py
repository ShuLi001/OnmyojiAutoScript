import unittest
from types import SimpleNamespace
from unittest.mock import Mock, call, patch

from module.exception import ScriptError
import test_asset_snapshot_stamina as stamina_tests


class JadeDetailTest(unittest.TestCase):
    def task(self, opened=False):
        task, state = stamina_tests.StaminaDetailTest().task(popup_open=opened)
        task.O_JADE_DETAIL_NAME = SimpleNamespace(ocr=Mock(return_value="勾玉"))
        task.O_JADE_DETAIL_OWNED = SimpleNamespace(ocr=Mock(return_value="已拥有:11058"))
        task.observation_metadata = {}

        def click(target):
            if target is task.C_JADE_DETAIL and state["opens"]:
                state["popup_open"] = True
            elif target is task.C_JADE_DETAIL_CLOSE and state["closes"]:
                state["popup_open"] = False

        task.click.side_effect = click
        task.TOP_RESOURCE_OCR = {
            "jade": SimpleNamespace(roi=(924, 14, 98, 39), ocr=Mock(return_value="皖838")),
        }
        return task, state

    @patch("tasks.AssetSnapshot.script_task.time.sleep")
    def test_reads_popup_directly_even_when_header_would_be_invalid(self, _):
        task, state = self.task()
        self.assertEqual(task._scan_top_resources(), {"jade": 11058})
        task.TOP_RESOURCE_OCR["jade"].ocr.assert_not_called()
        self.assertEqual(task.click.call_args_list,
                         [call(task.C_JADE_DETAIL), call(task.C_JADE_DETAIL_CLOSE)])
        self.assertEqual(task.O_JADE_DETAIL_OWNED.ocr.call_count, 2)
        self.assertFalse(state["popup_open"])
        self.assertEqual(task.observation_metadata["jade"]["precision"], "exact")
        self.assertEqual(task.observation_metadata["jade"]["rawText"], "已拥有:11058")

    @patch("tasks.AssetSnapshot.script_task.time.sleep")
    def test_existing_popup_is_reused_and_closed(self, _):
        task, _state = self.task(opened=True)
        self.assertEqual(task._read_jade_detail(), 11058)
        task.click.assert_called_once_with(task.C_JADE_DETAIL_CLOSE)

    @patch("tasks.AssetSnapshot.script_task.time.sleep")
    def test_wrong_title_rejects_stale_quantity(self, _):
        task, state = self.task()
        task.O_JADE_DETAIL_NAME.ocr.return_value = "体力"
        with self.assertRaises(ScriptError):
            task._read_jade_detail()
        task.O_JADE_DETAIL_OWNED.ocr.assert_not_called()
        self.assertFalse(state["popup_open"])

    @patch("tasks.AssetSnapshot.script_task.time.sleep")
    def test_rounded_or_mixed_detail_never_falls_back_to_header(self, _):
        for raw in ("已拥有:1.1万", "已拥有:皖838", ""):
            task, state = self.task()
            task.O_JADE_DETAIL_OWNED.ocr.return_value = raw
            with self.assertRaises(ScriptError):
                task._scan_top_resources()
            self.assertFalse(state["popup_open"])
            self.assertNotIn("jade", task.observation_metadata)

    @patch("tasks.AssetSnapshot.script_task.time.sleep")
    def test_waits_for_two_matching_values_including_zero(self, _):
        for readings, expected in [(["已拥有:11058", "已拥有:11059", "已拥有:11059"], 11059),
                                    (["已拥有:0", "已拥有:0"], 0)]:
            task, _state = self.task()
            task.O_JADE_DETAIL_OWNED.ocr.side_effect = readings
            self.assertEqual(task._read_jade_detail(), expected)

    @patch("tasks.AssetSnapshot.script_task.time.sleep")
    def test_missing_popup_opens_only_once(self, _):
        task, state = self.task()
        state["opens"] = False
        with self.assertRaises(ScriptError):
            task._read_jade_detail()
        task.click.assert_called_once_with(task.C_JADE_DETAIL)

    @patch("tasks.AssetSnapshot.script_task.time.sleep")
    def test_failed_close_aborts_scan(self, _):
        task, state = self.task()
        state["closes"] = False
        with self.assertRaises(ScriptError):
            task._scan_top_resources()

    def test_clicks_exclude_purchase_and_item_use_buttons(self):
        task, _state = self.task()
        for _ in range(500):
            x, y = task.C_JADE_DETAIL.coord()
            self.assertTrue(876 <= x <= 1019 and 16 <= y <= 46)
            self.assertLess(x, 1022)
            x, y = task.C_JADE_DETAIL_CLOSE.coord()
            self.assertTrue(240 <= x <= 262 and 540 <= y <= 640)


if __name__ == "__main__":
    unittest.main()
