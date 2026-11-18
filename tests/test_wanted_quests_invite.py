import unittest
from unittest.mock import Mock

from tasks.WantedQuests.config import CooperationType
from tasks.WantedQuests.script_task import ScriptTask


def make_task(visible_rules):
    task = object.__new__(ScriptTask)
    task.appear = lambda rule: rule.name in visible_rules
    task.screenshot = Mock()
    task.invite_random = Mock()
    return task


class WantedQuestInviteTests(unittest.TestCase):
    def test_random_invites_include_purple_buttons_on_each_card(self):
        task = make_task({f'INVITE_WQ_INVITE_{index}_PURPLE' for index in range(1, 4)})

        task.invite_five()

        self.assertEqual(
            [call.args[0].name for call in task.invite_random.call_args_list],
            [f'INVITE_WQ_INVITE_{index}_PURPLE' for index in range(1, 4)],
        )

    def test_random_invites_handle_mixed_colors_and_skip_missing_button(self):
        task = make_task({'INVITE_WQ_INVITE_1', 'INVITE_WQ_INVITE_3_PURPLE'})

        task.invite_five()

        self.assertEqual(
            [call.args[0].name for call in task.invite_random.call_args_list],
            ['INVITE_WQ_INVITE_1', 'INVITE_WQ_INVITE_3_PURPLE'],
        )

    def test_random_invites_process_card_once_when_both_templates_match(self):
        task = make_task({'INVITE_WQ_INVITE_2', 'INVITE_WQ_INVITE_2_PURPLE'})

        task.invite_five()

        task.invite_random.assert_called_once_with(task.I_WQ_INVITE_2)

    def test_cooperation_info_keeps_purple_button_for_vip_invitation(self):
        task = make_task({'INVITE_WQ_INVITE_3_PURPLE'})
        purple = task.I_WQ_INVITE_3_PURPLE
        jade = task.I_WQ_COOPERATION_TYPE_JADE_3
        task.appear = lambda rule: rule is purple or rule is jade

        info = task.get_cooperation_info()

        self.assertEqual(len(info), 1)
        self.assertEqual(info[0]['type'], CooperationType.Jade)
        self.assertIs(info[0]['inviteBtn'], purple)
