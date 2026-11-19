import unittest
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np

from tasks.WantedQuests.script_task import ScriptTask, is_wq_detail_title


class WantedQuestDetailTitleTests(unittest.TestCase):
    def test_accepts_ordinary_wanted_quest_title(self):
        self.assertTrue(is_wq_detail_title("悬赏目标：击败3个骨女"))


    def test_accepts_cooperation_wanted_quest_title(self):
        self.assertTrue(is_wq_detail_title("自己击败山童"))


    def test_rejects_empty_detail_title(self):
        self.assertFalse(is_wq_detail_title(""))


    def test_rejects_exploration_list_text(self):
        self.assertFalse(is_wq_detail_title("悬赏封印 0/5"))


class FakeOcr:
    def __init__(self, text):
        self.text = text

    def ocr(self, image):
        return self.text


def make_task(target_text="", visible_rules=()):
    task = object.__new__(ScriptTask)
    task.device = SimpleNamespace(image=object())
    task.O_WQ_TARGET_NEW = FakeOcr(target_text)
    task.I_GOTO_NEW_1 = object()
    task.I_GOTO_NEW_2 = object()
    task.I_GOTO_NEW_3 = object()
    task.I_GOTO_NEW_4 = object()
    task.I_DETAIL_CLOSE_NEW = object()
    task.appear = lambda rule: rule in visible_rules
    return task


class WantedQuestDetailPageTests(unittest.TestCase):
    def test_accepts_cooperation_detail_title(self):
        task = make_task("自己击败山童")
        self.assertTrue(task.is_new_wq_detail())

    def test_accepts_detail_when_goto_button_is_visible(self):
        task = make_task("", visible_rules=(task_rule := object(),))
        task.I_GOTO_NEW_1 = task_rule
        self.assertTrue(task.is_new_wq_detail())

    def test_accepts_detail_when_close_button_is_visible(self):
        task = make_task("", visible_rules=(task_rule := object(),))
        task.I_DETAIL_CLOSE_NEW = task_rule
        self.assertTrue(task.is_new_wq_detail())

    def test_rejects_list_text_without_detail_controls(self):
        task = make_task("悬赏封印 0/5")
        self.assertFalse(task.is_new_wq_detail())

    def test_unwanted_quest_is_skipped_on_next_list_scan(self):
        goto = object()
        task = make_task("悬赏目标：击败1个青蛙瓷器", visible_rules=(goto,))
        task.I_GOTO_NEW_1 = goto
        task.unwanted_boss_name_list = ["青蛙瓷器"]
        task.appear_then_click = Mock()
        task.I_MYSTERY_QUESTION = Mock()
        task.I_MYSTERY_QUESTION.match.return_value = False
        task.O_WQ_TEXT_ALL = Mock(roi=(0, 0, 100, 720))

        def progress(text, y):
            box = np.array([[42, y], [71, y], [71, y + 15], [42, y + 15]])
            return SimpleNamespace(ocr_text=text, box=box)

        task.O_WQ_TEXT_ALL.detect_and_ocr.return_value = [progress("071", 435)]
        current, _, total, task.O_WQ_TEXT_ALL.area = task.find_wq(task.device.image)
        self.assertFalse(task.execute_mission(total - current))
        task.appear_then_click.assert_called_once_with(task.I_DETAIL_CLOSE_NEW, interval=1)

        for text in ("0/1", "071"):
            with self.subTest(text=text):
                task.O_WQ_TEXT_ALL.detect_and_ocr.return_value = [progress(text, 434), progress("0/1", 535)]
                self.assertEqual(task.find_wq(task.device.image), (0, 1, 1, [42, 535, 29, 15]))
