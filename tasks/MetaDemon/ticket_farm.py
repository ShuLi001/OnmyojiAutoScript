"""超鬼王刷票阶段：启动时读取探索页，战斗中读取奖励页门票进度。"""

import importlib
import sys
from datetime import datetime, timedelta, time
from typing import Callable, NamedTuple

from module.exception import TaskEnd
from module.logger import logger
from tasks.GameUi.page import any_of, page_exploration, page_main, page_reward, random_click
from tasks.Component.GeneralBattle.general_battle import BattleAction
from tasks.MetaDemon.config import TicketFarmSource
from tasks.MetaDemon.assets import MetaDemonAssets


_REALM_RAID_TICKET_CAP = 30


class _RealmRaidNeeded(NamedTuple):
    tickets: int


def _read_realm_raid_tickets(image) -> int | None:
    current, remaining, total = MetaDemonAssets.O_MD_REALM_RAID_TICKETS.ocr_digit_counter(image)
    if total == _REALM_RAID_TICKET_CAP and 0 <= current <= total and current + remaining == total:
        return current
    return None


def _copy_task_config(config):
    # Config.__getattr__ 依赖 model，copy.copy 在重建未初始化对象时会递归。
    child_config = object.__new__(type(config))
    child_config.__dict__.update(config.__dict__)
    child_config.model = config.model.model_copy(deep=True)
    return child_config


class _TicketFarmTask:
    """子任务正常收尾，但不更新独立刷本任务的调度。"""

    ticket_farm_failed = False
    ticket_progress_callback = None
    ticket_farm_return_to_exploration = False
    ticket_farm_continuous = False
    ticket_round_progress = None

    def goto_page(self, destination, *args, **kwargs):
        if self.ticket_farm_return_to_exploration and destination.key == page_main.key:
            # 复用任务的常规起止落点改为探索页，随后直接走对应副本入口。
            destination = page_exploration
        return super().goto_page(destination, *args, **kwargs)

    def _register_custom_pages(self):
        super()._register_custom_pages()
        reward_page = self.navigator.resolve_page(page_reward)
        if reward_page is not None:
            reward_page.recognizer = any_of(MetaDemonAssets.I_MD_TICKET_DROP_POPUP, reward_page.recognizer)

    def _handle_reward(self, context, config):
        is_ticket_popup = self.appear(MetaDemonAssets.I_MD_TICKET_DROP_POPUP)
        # 必须先读取当前奖励帧，再交给原任务关闭奖励/处理队友邀请。
        if self.ticket_progress_callback is not None:
            current, _, total = MetaDemonAssets.O_MD_DAILY_TICKET_REWARD.ocr_digit_counter(self.device.image)
            if total > 0 and 0 <= current <= total:
                self.ticket_round_progress = (current, total)
                self.ticket_progress_callback((current, total))
        if is_ticket_popup:
            self.click(random_click(), interval=0.8)
            # 弹窗关闭后重新截图，再处理底层奖励页，避免沿用弹窗这一帧。
            return BattleAction.CONTINUE
        return super()._handle_reward(context, config)

    def set_next_run(self, task, finish=False, success=None, server=True, target=None):
        if success is False:
            self.ticket_farm_failed = True

    def run_general_battle(self, *args, **kwargs):
        self.ticket_round_progress = None
        result = super().run_general_battle(*args, **kwargs)
        if not result:
            self.ticket_farm_failed = True
        if self.ticket_farm_continuous:
            progress = self.ticket_round_progress
            if not result or progress is None:
                self.ticket_farm_failed = True
                logger.warning('超鬼王刷票战斗失败或本场门票未识别，停止当前副本刷票')
            elif progress[0] >= progress[1]:
                logger.info(f'超鬼王门票已达上限 {progress[0]}/{progress[1]}，结束当前副本刷票')
            else:
                logger.info(f'超鬼王战后门票 {progress[0]}/{progress[1]}，继续当前副本')
                return result
            # 让原任务的外层循环正常收尾，保留退队、关闭加成等清理动作。
            self.limit_count = self.current_count
            if self.ticket_farm_source == TicketFarmSource.EXPLORATION:
                self.config.exploration.exploration_config.minions_cnt = self.current_count
        return result


class _TicketFarmExploration(_TicketFarmTask):
    realm_raid_tickets = None
    _realm_raid_checked_after = -1

    def check_exit(self, current_page) -> bool:
        if super().check_exit(current_page):
            return True
        if current_page == page_exploration and self.current_count != self._realm_raid_checked_after:
            self._realm_raid_checked_after = self.current_count
            tickets = _read_realm_raid_tickets(self.device.image)
            threshold = max(1, self._config.scrolls.scrolls_threshold)
            if tickets is not None and tickets >= threshold:
                self.realm_raid_tickets = tickets
        # 交给探索原有的 post_process 退回地图、关闭加成。
        return self.realm_raid_tickets is not None

    def run_on_exp_entrance(self):
        if self.current_count != self._realm_raid_checked_after:
            # 到章节入口时才回地图检查，不在每场战斗后退出副本。
            if not self.goto_page(page_exploration, skip_first_screenshot=False):
                self._realm_raid_checked_after = self.current_count
            return
        return super().run_on_exp_entrance()


def run_farming_battle(config, device, source: TicketFarmSource, remaining: timedelta,
                       on_ticket_progress: Callable[[tuple[int, int]], None] | None = None,
                       *, skip_initial_raid_check: bool = False) -> bool | _RealmRaidNeeded:
    """一次进入副本后持续刷票，达到上限或出错时由原任务正常收尾。"""
    source = TicketFarmSource(source)
    module = importlib.import_module(f'tasks.{source.value}.script_task')
    # 保留原模块名，让 GameUi 正确识别子任务的页面分类。
    adapter = _TicketFarmExploration if source == TicketFarmSource.EXPLORATION else _TicketFarmTask
    task_class = type(f'TicketFarm{source.value}', (adapter, module.ScriptTask),
                      {'__module__': module.__name__})
    child_config = _copy_task_config(config)
    task_key, group_key = {
        TicketFarmSource.EVO_ZONE: ('evo_zone', 'evo_zone_config'),
        TicketFarmSource.OROCHI: ('orochi', 'orochi_config'),
        TicketFarmSource.EXPLORATION: ('exploration', 'exploration_config'),
    }[source]
    task_config = getattr(child_config.model, task_key)
    battle_config = getattr(task_config, group_key)
    if source == TicketFarmSource.EXPLORATION:
        battle_config.minions_cnt = sys.maxsize
        task_config.scrolls.scrolls_enable = False
    else:
        battle_config.limit_count = sys.maxsize
    seconds = max(1, min(86399, int(remaining.total_seconds())))
    battle_config.limit_time = time(seconds // 3600, seconds % 3600 // 60, seconds % 60)
    task_config.general_battle_config.continuous_battle = False
    task_config.general_battle_config.max_continuous = 1
    task_config.general_battle_config.quick_exit = False
    task = task_class(config=child_config, device=device)
    task.ticket_progress_callback = on_ticket_progress
    task.ticket_farm_continuous = True
    task.ticket_farm_source = source
    # 加成按钮在庭院中；明确启用加成时保留原任务的准备和收尾路径。
    if source == TicketFarmSource.EXPLORATION:
        if skip_initial_raid_check:
            # 个人突破可能按配置留票；继续刷一个章节后再检查，避免原地反复触发。
            task._realm_raid_checked_after = task.current_count
        needs_courtyard = any((battle_config.buff_gold_50_click, battle_config.buff_gold_100_click,
                               battle_config.buff_exp_50_click, battle_config.buff_exp_100_click))
    else:
        needs_courtyard = battle_config.soul_buff_enable
    task.ticket_farm_return_to_exploration = not needs_courtyard
    try:
        result = task.run()
    except TaskEnd:
        result = None
    if result is False or task.ticket_farm_failed:
        return False
    if source == TicketFarmSource.EXPLORATION and task.realm_raid_tickets is not None:
        return _RealmRaidNeeded(task.realm_raid_tickets)
    return task.current_count > 0


def _clear_farming_realm_raid(config, device) -> None:
    from tasks.RealmRaid.script_task import ScriptTask

    class TicketFarmRealmRaid(ScriptTask):
        __module__ = ScriptTask.__module__

        def set_next_run(self, task, finish=False, success=None, server=True, target=None):
            # 超鬼王在当前调用内清票，不更新个人突破的独立调度。
            pass

    child_config = _copy_task_config(config)
    try:
        TicketFarmRealmRaid(config=child_config, device=device).run()
    except TaskEnd:
        pass


class TicketFarmMixin:
    def read_daily_ticket_progress(self) -> tuple[int, int] | None:
        """仅从探索页的 50/50 等计数返回 (当前数量, 每日上限)。

        每次导航、截图并确认页面后读取，不使用活动页或本地累计。
        页面确认失败或计数无效时返回 None。
        """
        if not self.goto_page(page_exploration, skip_first_screenshot=False):
            return None
        self.screenshot()
        if not self.confirm_page(page_exploration):
            return None
        current, _, total = self.O_MD_DAILY_TICKET_EXPLORATION.ocr_digit_counter(self.device.image)
        if total <= 0 or not 0 <= current <= total:
            return None
        return current, total

    def run_ticket_farm(self) -> bool:
        """仅在未启用刷票或已确认达到每日上限时进入超鬼王战斗。"""
        farm = self.conf.ticket_farm
        if not farm.enable:
            return True
        duration = timedelta(hours=farm.limit_time.hour, minutes=farm.limit_time.minute,
                             seconds=farm.limit_time.second)
        deadline = datetime.now() + duration
        progress = self.read_daily_ticket_progress()
        skip_initial_raid_check = False

        def remember_reward_progress(value):
            nonlocal progress
            progress = value

        while True:
            if not isinstance(progress, tuple) or len(progress) != 2 or \
                    any(type(value) is not int for value in progress) or \
                    progress[0] < 0 or progress[1] <= 0:
                logger.warning('超鬼王门票数量识别失败，暂停刷票并等待重试')
                return False
            count, daily_limit = progress
            logger.info(f'超鬼王今日门票: {count}/{daily_limit}')
            if count >= daily_limit:
                logger.info('超鬼王今日门票已达上限，先返回庭院，再进入活动挑战鬼王')
                if not self.goto_page(page_main, skip_first_screenshot=False):
                    logger.warning('超鬼王刷票结束后未能返回庭院，暂停进入活动')
                    return False
                return True
            remaining = deadline - datetime.now()
            if remaining.total_seconds() <= 0:
                logger.info('超鬼王本轮刷票时间已到，等待下次调度继续刷票')
                return False
            # 每场都必须收到新的奖励页读数；不沿用上一场读数或返回探索页补读。
            progress = None
            result = run_farming_battle(self.config, self.device, farm.battle_task, remaining,
                                        on_ticket_progress=remember_reward_progress,
                                        skip_initial_raid_check=skip_initial_raid_check)
            skip_initial_raid_check = False
            if isinstance(result, _RealmRaidNeeded):
                if datetime.now() >= deadline:
                    logger.info('超鬼王本轮刷票时间已到，下次再清结界挑战券')
                    return False
                logger.info(f'结界挑战券 {result.tickets}/{_REALM_RAID_TICKET_CAP} 已达阈值，暂离超鬼王刷票并清票')
                _clear_farming_realm_raid(self.config, self.device)
                # 个人突破决定何时结束；回到同一超鬼王任务后只读取活动门票。
                logger.info('个人突破已结束，返回超鬼王任务')
                progress = self.read_daily_ticket_progress()
                skip_initial_raid_check = True
                continue
            if not result:
                logger.warning('超鬼王刷票副本未完成战斗，等待下次调度重试')
                return False
