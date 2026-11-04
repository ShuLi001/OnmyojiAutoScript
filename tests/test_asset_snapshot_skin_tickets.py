import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import cv2
import numpy as np

from module.exception import ScriptError
from module.image.rpc import ImageClient
from module.image.runtime import ImageRuntime
from tasks.AssetSnapshot.script_task import ScriptTask
from tasks.AssetSnapshot.skin_tickets import (
    SkinTicketCandidate,
    classify_skin_ticket,
    skin_ticket_name,
    skin_ticket_selected,
)


ROOT = Path(__file__).resolve().parents[1]
PAGES = ROOT / "tasks/AssetSnapshot/assets/templates/qa/raw_pages"


def read_page(number):
    data = np.fromfile(PAGES / f"page_{number}.png", dtype=np.uint8)
    return cv2.cvtColor(cv2.imdecode(data, cv2.IMREAD_COLOR), cv2.COLOR_BGR2RGB)


def make_task():
    task = object.__new__(ScriptTask)
    task.device = SimpleNamespace(image=None, image_frame_id=None,
                                  click=Mock(), click_record_clear=Mock())
    task.screenshot = Mock()
    task.appear = Mock(return_value=True)
    task.match_score_records = []
    task.quantity_match_scores = {}
    task.quantity_observations = {}
    task.ticket_detail_cache = {}
    task.material_match_threshold = 0.90
    return task


class SkinTicketMatchingTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.runtime = ImageRuntime({"worker_count": 2})
        cls.client = object.__new__(ImageClient)
        cls.client.client = cls.runtime

    @classmethod
    def tearDownClass(cls):
        cls.runtime.shutdown()

    def test_original_inventory_pages_do_not_cross_classify_tickets(self):
        expected = {1: [], 2: [], 3: [], 4: ["sp_skin_ticket"],
                    5: ["sp_skin_ticket", "skin_ticket"], 6: ["skin_ticket"]}
        task = make_task()
        with patch("tasks.AssetSnapshot.script_task.get_image_client", return_value=self.client):
            for page_number, variables in expected.items():
                with self.subTest(page=page_number):
                    task.device.image = read_page(page_number)
                    found = task._find_skin_ticket_candidates(page_number - 1)
                    self.assertEqual([candidate.variable_name for candidate in found], variables)
                    self.assertEqual(len({candidate.area for candidate in found}), len(variables))
                    if page_number == 5:
                        self.assertEqual(found[0].area[:2], (373, 275))
                        self.assertEqual(found[1].area[:2], (681, 377))

    def test_missing_or_inconclusive_badge_requires_details(self):
        self.assertIsNone(classify_skin_ticket(.98, .90, None))
        self.assertIsNone(classify_skin_ticket(.98, .90, .60))
        self.assertIsNone(classify_skin_ticket(.94, .93, .20))
        self.assertIsNone(classify_skin_ticket(.99, .91, .95))
        self.assertEqual(classify_skin_ticket(.98, .90, .20), "skin_ticket")
        self.assertEqual(classify_skin_ticket(.91, .98, .95), "sp_skin_ticket")

    def test_selection_requires_border_at_the_clicked_card(self):
        image = read_page(1)
        self.assertTrue(skin_ticket_selected(image, (271, 188, 95, 70)))
        self.assertFalse(skin_ticket_selected(image, (373, 188, 95, 70)))

    def test_regular_matching_does_not_accept_ticket_cross_matches(self):
        task = make_task()
        ticket_rules = [r for r in task.MATERIAL_RULES
                        if task.MATERIAL_RULE_TO_VARIABLE[id(r)] in {"skin_ticket", "sp_skin_ticket"}]
        task.MATERIAL_RULES = ticket_rules
        task._match_many_with_frame_retry = Mock(return_value=[
            {"score": .98, "roi_front": [681, 272, 95, 70]},
            {"score": .91, "roi_front": [677, 271, 95, 70]},
        ])
        self.assertEqual(task._find_material_matches(5), [])

    def test_page_scan_updates_both_tickets_before_bottom_exit(self):
        task = make_task()
        task.device.image = read_page(5)
        task._find_material_matches = Mock(return_value=[])
        task._read_material_quantity = Mock(return_value=333)
        task._read_skin_ticket_detail = Mock(return_value=("sp_skin_ticket", 6))
        task._scroll_boundary_state = Mock(return_value="bottom")
        values = {"skin_ticket": 0, "sp_skin_ticket": 0}
        with patch("tasks.AssetSnapshot.script_task.get_image_client", return_value=self.client):
            self.assertTrue(task._scan_material_pages(values))
        self.assertEqual(values, {"skin_ticket": 333, "sp_skin_ticket": 6})


class SkinTicketReadingTest(unittest.TestCase):
    def test_sp_uses_detail_quantity_and_caches_it_for_overlapping_pages(self):
        task = make_task()
        task._find_skin_ticket_candidates = Mock(return_value=[
            SkinTicketCandidate((373, 275, 95, 70), .99, .91, .99, .95, "sp_skin_ticket"),
        ])
        task._read_skin_ticket_detail = Mock(return_value=("sp_skin_ticket", 1234))
        task._read_material_quantity = Mock(return_value=156)
        values = {"sp_skin_ticket": 0}
        task._scan_skin_tickets(values, 4)
        task._scan_skin_tickets(values, 5)
        self.assertEqual(values["sp_skin_ticket"], 1234)
        task._read_material_quantity.assert_not_called()
        task._read_skin_ticket_detail.assert_called_once()

    def test_uncertain_type_uses_name_and_quantity_from_details(self):
        task = make_task()
        task._find_skin_ticket_candidates = Mock(return_value=[
            SkinTicketCandidate((373, 275, 95, 70), .97, .94, .93, .60, None),
        ])
        task._read_skin_ticket_detail = Mock(return_value=("sp_skin_ticket", 6))
        values = {"skin_ticket": 233, "sp_skin_ticket": 0}
        task._scan_skin_tickets(values, 4)
        self.assertEqual(values, {"skin_ticket": 233, "sp_skin_ticket": 6})
        self.assertIsNone(task._read_skin_ticket_detail.call_args.kwargs["expected_variable"])

    def test_failed_details_do_not_overwrite_history(self):
        task = make_task()
        task._find_skin_ticket_candidates = Mock(return_value=[
            SkinTicketCandidate((373, 275, 95, 70), .97, .94, .93, None, None),
        ])
        task._read_skin_ticket_detail = Mock(return_value=None)
        values = {"skin_ticket": 233, "sp_skin_ticket": 6}
        with self.assertRaises(ScriptError):
            task._scan_skin_tickets(values, 4)
        self.assertEqual(values, {"skin_ticket": 233, "sp_skin_ticket": 6})

    def test_detail_waits_for_selection_correct_name_and_stable_quantity(self):
        task = make_task()
        task.device.image = read_page(5)
        task.O_TICKET_DETAIL_NAME = Mock()
        task.O_TICKET_DETAIL_NAME.ocr.side_effect = ["皮肤券", "SP皮肤券", "SP皮肤券"]
        task.O_TICKET_DETAIL_QUANTITY = Mock()
        task.O_TICKET_DETAIL_QUANTITY.detect_and_ocr.return_value = [
            SimpleNamespace(ocr_text="1234", score=.98),
        ]
        with patch("tasks.AssetSnapshot.script_task.skin_ticket_selected", return_value=True), \
                patch("tasks.AssetSnapshot.script_task.time.sleep"):
            result = task._read_skin_ticket_detail((373, 275, 95, 70),
                                                   expected_variable="sp_skin_ticket")
        self.assertEqual(result, ("sp_skin_ticket", 1234))

    def test_detail_rejects_stale_panel_when_card_not_selected(self):
        task = make_task()
        task.device.image = read_page(5)
        task.O_TICKET_DETAIL_NAME = Mock()
        with patch("tasks.AssetSnapshot.script_task.time.sleep"):
            self.assertIsNone(task._read_skin_ticket_detail((373, 275, 95, 70),
                                                            expected_variable=None))
        task.O_TICKET_DETAIL_NAME.ocr.assert_not_called()

    def test_detail_name_requires_exact_ticket_name(self):
        self.assertEqual(skin_ticket_name("SP 皮肤券"), "sp_skin_ticket")
        self.assertEqual(skin_ticket_name("皮肤券"), "skin_ticket")
        self.assertIsNone(skin_ticket_name("典藏礼券"))


if __name__ == "__main__":
    unittest.main()
