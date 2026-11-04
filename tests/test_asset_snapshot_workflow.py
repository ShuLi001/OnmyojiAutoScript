import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from module.exception import ScriptError
from tasks.AssetSnapshot.assets import VARIABLE_MAPPING
from tasks.AssetSnapshot.script_task import ScriptTask


class SnapshotHistoryTest(unittest.TestCase):
    def store(self, root, profile="test", character=""):
        from tasks.AssetSnapshot.history import SnapshotStore
        return SnapshotStore(root, profile, "192.168.5.110:5555", character, VARIABLE_MAPPING)

    def test_full_baseline_survives_reload_and_identity_isolation(self):
        with tempfile.TemporaryDirectory() as root:
            store = self.store(root)
            self.assertIsNone(store.load())
            payload = {"status": "ready", "updatedAt": "2026-11-01T16:00:00",
                       "values": dict.fromkeys(VARIABLE_MAPPING.values(), 0)}
            payload["values"]["mystic_talisman"] = 32
            store.save(payload, "composite", None)
            history = store.load()
            self.assertEqual(history["snapshot"]["values"]["mystic_talisman"], 32)
            self.assertIsNone(self.store(root, profile="other").load())
            self.assertIsNone(self.store(root, character="other").load())
            payload["updatedAt"] = "2026-11-01T17:00:00"
            store.save(payload, "recent", history)
            self.assertEqual(store.load()["fullScanCompletedAt"], "2026-11-01T16:00:00")

    def test_corrupt_incomplete_and_foreign_baselines_are_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            store = self.store(root)
            store.path.parent.mkdir(parents=True, exist_ok=True)
            for text in ["{broken", "{}", json.dumps({"status": "ready", "values": {"gold": 1}})]:
                store.path.write_text(text, encoding="utf-8")
                self.assertIsNone(store.load())
            with self.assertRaises(ValueError):
                store.save({"status": "ready", "values": {}}, "recent", None)


class SnapshotWorkflowTest(unittest.TestCase):
    def task(self):
        task = object.__new__(ScriptTask)
        task.config = SimpleNamespace(config_name="test", asset_snapshot=None)
        task.device = SimpleNamespace(image=None)
        task.screenshot = Mock()
        task.appear = Mock(return_value=True)
        task._select_category = Mock()
        task._reset_material_grid_to_top = Mock()
        task._scan_top_resources = Mock(return_value={"gold": 25})
        task._write_match_score_diagnostics = Mock()
        task._scan_skin_tickets = Mock()
        return task

    def test_recent_preserves_unseen_and_failed_ocr_but_updates_explicit_zero(self):
        task = self.task()
        previous = dict.fromkeys(VARIABLE_MAPPING.values(), 0)
        previous.update(mystic_talisman=32, seal=25, skin_ticket=3)
        task.MATERIAL_RULES = [object(), object()]
        task.MATERIAL_RULE_TO_VARIABLE = dict(zip(map(id, task.MATERIAL_RULES), ["mystic_talisman", "skin_ticket"]))
        task._find_material_matches = Mock(return_value=[
            (task.MATERIAL_RULES[0], .99, (271, 230, 95, 70)),
            (task.MATERIAL_RULES[1], .99, (373, 230, 95, 70))])
        task._read_material_quantity = Mock(side_effect=[None, 0])
        task._scroll_boundary_state = Mock(return_value="bottom")
        task._material_grid_signature = Mock(return_value=1)
        payload = task.scan(category="recent", previous_values=previous)
        self.assertEqual(payload["values"]["seal"], 25)
        self.assertEqual(payload["values"]["mystic_talisman"], 32)
        self.assertEqual(payload["values"]["skin_ticket"], 0)
        self.assertEqual(payload["values"]["gold"], 25)

    def test_full_scan_retains_missing_history_and_disables_removed_template(self):
        task = self.task()
        task._scan_material_pages = Mock(return_value=True)
        payload = task.scan(category="composite", previous_values={"seal": 99, "eternal_divine_talisman": 1})
        self.assertEqual(payload["values"]["seal"], 99)
        self.assertEqual(payload['assets']['seal']['quantity'], 99)
        self.assertEqual(payload['assets']['seal']['source'], 'assumed_zero')
        self.assertEqual(payload["values"]["eternal_divine_talisman"], 0)

    def test_limit_failure_does_not_report_ready(self):
        task = self.task()
        task._scan_material_pages = Mock(return_value=False)
        with self.assertRaises(ScriptError):
            task.scan()

    def test_removed_limited_talisman_is_not_rechecked_or_carried_from_history(self):
        for category in ("composite", "recent"):
            with self.subTest(category=category):
                task = self.task()
                task._scan_material_pages = Mock(return_value=True)
                payload = task.scan(category=category, previous_values={"limited_mystic_talisman": 99})
                self.assertEqual(payload["values"]["limited_mystic_talisman"], 0)
                self.assertEqual(payload["assets"]["limited_mystic_talisman"]["quantity"], 0)
                self.assertEqual(payload["assets"]["limited_mystic_talisman"]["readStatus"], "unsupported")
                task._scan_material_pages.assert_called_once()

    def test_partial_bottom_row_is_not_sent_to_ocr(self):
        task = self.task()
        task.device.image = __import__("numpy").zeros((720, 1280, 3), dtype="uint8")
        with patch("tasks.AssetSnapshot.script_task.RuleOcr") as ocr:
            self.assertIsNone(task._read_material_quantity((271, 600, 95, 70)))
            ocr.assert_not_called()

    def test_repeated_weaker_read_does_not_overwrite_better_quantity(self):
        task = self.task()
        task.max_scan_swipes = 1
        task.quantity_observations = {}
        task.quantity_match_scores = {}
        rule = object()
        task.MATERIAL_RULE_TO_VARIABLE = {id(rule): "seal"}
        task._find_material_matches = Mock(side_effect=[
            [(rule, .99, (271, 230, 95, 70))],
            [(rule, .96, (271, 250, 95, 70))],
        ])
        task._read_material_quantity = Mock(side_effect=[3919, 319])
        task._material_grid_signature = Mock(side_effect=[1, 2])
        task._scroll_boundary_state = Mock(side_effect=["middle", "bottom"])
        task._swipe_material_grid = Mock()
        task._wait_for_material_grid_stability = Mock()
        values = {"seal": 0}
        self.assertTrue(task._scan_material_pages(values))
        self.assertEqual(values["seal"], 3919)

    def test_failed_swipe_in_middle_is_not_a_completed_scan(self):
        task = self.task()
        task.max_scan_swipes = 1
        task.quantity_observations = {}
        task.quantity_match_scores = {}
        task._find_material_matches = Mock(return_value=[])
        task._material_grid_signature = Mock(return_value=1)
        task._scroll_boundary_state = Mock(return_value="middle")
        task._swipe_material_grid = Mock()
        task._wait_for_material_grid_stability = Mock()
        self.assertFalse(task._scan_material_pages({}))

    def test_cold_start_reuses_login_service_then_global_navigation(self):
        task = self.task()
        task.device.app_is_running = Mock(return_value=False)
        task.device.app_start = Mock()
        task.device.wait_app_start_ready = Mock()
        task.goto_page = Mock(return_value=True)
        with patch("tasks.AssetSnapshot.script_task.LoginService") as login:
            task._prepare_game()
            task.device.app_start.assert_called_once()
            task.device.wait_app_start_ready.assert_called_once()
            login.return_value.app_handle_login.assert_called_once()
        self.assertEqual(task.goto_page.call_args.args[0].key, "page_main")

    def test_detected_number_box_distinguishes_ocr_failure_from_zero(self):
        task = self.task()
        with patch("tasks.AssetSnapshot.script_task.RuleOcr") as ocr:
            ocr.return_value.detect_and_ocr.return_value = []
            self.assertIsNone(task._read_material_quantity((271, 230, 95, 70)))
            ocr.return_value.detect_and_ocr.return_value = [SimpleNamespace(ocr_text=0)]
            self.assertEqual(task._read_material_quantity((271, 230, 95, 70)), 0)

    def test_myriad_soul_uses_its_number_crop_at_any_card_position(self):
        task = self.task()
        with patch("tasks.AssetSnapshot.script_task.RuleOcr") as ocr:
            ocr.return_value.detect_and_ocr.return_value = [SimpleNamespace(ocr_text=25)]
            for card, expected_roi in [
                ((271, 291, 95, 70), (338, 361, 27, 23)),
                ((373, 400, 95, 70), (440, 470, 27, 23)),
            ]:
                with self.subTest(card=card):
                    self.assertEqual(
                        task._read_material_quantity(card, variable_name="myriad_soul"), 25,
                    )
                    self.assertEqual(ocr.call_args.kwargs["roi"], expected_roi)
                    self.assertFalse(ocr.return_value.filter_white)

            task._read_material_quantity((271, 291, 95, 70), variable_name="myriad_disc")
            self.assertEqual(ocr.call_args.kwargs["roi"], (311, 355, 55, 31))

    def test_task_registered_in_default_config_menu_and_scheduler(self):
        from module.config.config_model import ConfigModel
        from module.config.config_menu import ConfigMenu
        from module.config.config_manual import ConfigManual
        model = ConfigModel()
        self.assertEqual(ConfigModel.type("asset_snapshot"), "AssetSnapshot")
        self.assertIn("asset_snapshot_config", model.script_task("AssetSnapshot"))
        self.assertFalse(model.asset_snapshot.scheduler.enable)
        self.assertIn("AssetSnapshot", ConfigMenu().menu["Daily Task"])
        self.assertIn("AssetSnapshot", ConfigManual.SCHEDULER_PRIORITY)
        template = json.loads(Path("config/template.json").read_text(encoding="utf-8"))
        self.assertEqual(template["asset_snapshot"], model.asset_snapshot.model_dump(mode="json"))

    def test_navigation_failure_never_saves_baseline(self):
        task = self.task()
        task._prepare_game = Mock()
        task.goto_page = Mock(side_effect=[True, RuntimeError("return failed")])
        task.scan = Mock(return_value={"status": "ready", "updatedAt": "now", "values": {}})
        store = Mock()
        store.load.return_value = None
        task._snapshot_store = Mock(return_value=store)
        with self.assertRaises(RuntimeError):
            task.execute_workflow()
        store.save.assert_not_called()

    def test_automatic_workflow_chooses_category_then_saves_after_return(self):
        task = self.task()
        task._prepare_game = Mock()
        events = []
        task.goto_page = Mock(side_effect=lambda page, **kw: events.append(page.key) or True)
        task.scan = Mock(return_value={"status": "ready", "values": {}})
        store = Mock()
        store.save.side_effect = lambda *args: events.append("save")
        task._snapshot_store = Mock(return_value=store)
        for history, category in [(None, "composite"), ({"snapshot": {"values": {"seal": 5}}}, "recent")]:
            store.load.return_value = history
            task.execute_workflow()
            self.assertEqual(task.scan.call_args.kwargs["category"], category)
            self.assertEqual(events[-2:], ["page_main", "save"])


if __name__ == "__main__":
    unittest.main()
