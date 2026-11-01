import unittest
from types import SimpleNamespace

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
