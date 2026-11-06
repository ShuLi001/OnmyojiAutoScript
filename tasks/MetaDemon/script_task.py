# This Python file uses the following encoding: utf-8
# @author runhey
# github https://github.com/runhey
import time

import random
import re
from datetime import datetime, timedelta
from module.atom.image import RuleImage
from module.atom.ocr import RuleOcr

from tasks.Component.GeneralBattle.general_battle import GeneralBattle
from tasks.Component.SwitchSoul.switch_soul import SwitchSoul
from tasks.GameUi.game_ui import GameUi
from tasks.GameUi.page import page_kekkai_toppa, page_realm_raid
from tasks.MetaDemon.config import MetaDemon, BossType
from tasks.MetaDemon.assets import MetaDemonAssets
from tasks.MetaDemon.ticket_farm import TicketFarmMixin
import tasks.MetaDemon.page as ipages

from module.logger import logger
from module.exception import TaskEnd


class ScriptTask(TicketFarmMixin, GeneralBattle, SwitchSoul, GameUi, MetaDemonAssets):
    """超鬼王"""

    class State:
        done: bool = False
        switch_soul_done: bool = False
        synthesis_done: bool = False

    conf: MetaDemon = None
    cur_boss_type: BossType = None
    total_count: int = 0

    def _meta_demon_battle_key(self) -> str:
        """返回当前鬼王类型对应的通用战斗分组键。"""

        if self.cur_boss_type is None:
            return "meta_demon_default"
        return f"meta_demon_{self.cur_boss_type.name.lower()}"

    @property
    def enable_powerful_fire(self):
        powerful_list = self.conf.meta_demon_config.powerful_list_v
        return self.cur_boss_type is not None and self.cur_boss_type in powerful_list

    def before_run(self):
        self.State = type(self).State()
        self.cur_boss_type = None
        self.total_count = 0
        self.current_count = 0
        self.navigator.add_unknown_closer(self.I_MD_GET_YESTERDAY_REWARD)
        self.conf = self.config.meta_demon
        self.limit_time = self.conf.meta_demon_config.limit_time_v
        self.limit_count = self.conf.meta_demon_config.limit_count
        page_shikigami_records = self.navigator.resolve_page(ipages.page_shikigami_records)
        page_meta_demon_boss = self.navigator.resolve_page(ipages.page_meta_demon_boss)
        page_main = self.navigator.resolve_page(ipages.page_main)
        if page_shikigami_records is None or page_meta_demon_boss is None or page_main is None:
            raise RuntimeError("MetaDemon 页面 session 初始化失败")

        # 仅修改当前任务 session 内的跳转图，不污染全局页面定义
        page_shikigami_records.clear_transitions()
        page_shikigami_records.connect(
            page_meta_demon_boss,
            self.I_UI_BACK_YELLOW,
            key="page_shikigami_records->page_meta_demon_boss",
        )
        page_meta_demon_boss.connect(
            page_shikigami_records,
            MetaDemonAssets.I_MD_SHIKIGAMI,
            key="page_meta_demon_boss->page_shikigami_records",
        )
        page_main.remove_transition(key="page_main->page_shikigami_records")
        # 式神录的返回按钮只会回到进入它的页面，不能借结界突破抄近路进入活动。
        for definition in (page_realm_raid, page_kekkai_toppa):
            page = self.navigator.resolve_page(definition)
            if page is not None:
                page.remove_transition(destination=page_shikigami_records)

    def run(self):
        self.before_run()
        if not self.run_ticket_farm():
            retry_interval = max(self.conf.scheduler.wait_interval, timedelta(seconds=1))
            self.set_next_run('MetaDemon', server=False, target=datetime.now() + retry_interval)
            self.finish_task()
            return
        # 鬼王战斗的时长单独计算，不包含刷票耗时。
        self.start_time = datetime.now()
        self.goto_page(ipages.page_meta_demon_boss)
        while True:
            self.update_global_state()
            if self.State.done:
                break
            self.screenshot()
            current_page = self.get_current_page()
            match current_page:
                case ipages.page_meta_demon:
                    self.goto_page(ipages.page_meta_demon_boss)
                case ipages.page_meta_demon_boss:
                    if self.check_and_prepare_battle():
                        self.start_battle()
                case ipages.page_battle:
                    self.battle_wait(False)
                case ipages.page_reward | ipages.page_battle_result:
                    self.click(ipages.random_click(), interval=0.6)
                case _:
                    time.sleep(random.uniform(0.7, 1.4))
        self.set_next_run(task="MetaDemon", success=True)
        self.finish_task()

    def start_battle(self):
        logger.hr('Click fire, start battle')
        while True:
            self.screenshot()
            if self.is_in_battle(False):
                self.total_count += 1
                self.run_general_battle(
                    self.conf.switch_soul.get_general_battle_conf(self.cur_boss_type),
                    battle_key=self._meta_demon_battle_key(),
                )
                break
            if self.appear(self.I_MD_DRINK_TEA, interval=1.2):  # 出现喝茶弹窗
                if self.conf.meta_demon_config.auto_tea:
                    self.click(self.I_MD_DRINK_TEA)  # 喝茶
                    continue
                # 不喝茶则结束任务安排下一次运行
                self.ui_click_until_disappear(self.I_MD_CLOSE_POPUP, interval=0.6)
                self.set_next_run('MetaDemon', target=datetime.now() + self.conf.scheduler.wait_interval)
                self.finish_task()
            if self.appear(self.I_MD_FIRE, interval=0.8):
                self.click(self.C_MD_FIRE)
                continue

    def battle_wait(self, random_click_swipt_enable: bool) -> bool:
        self.device.stuck_record_add('BATTLE_STATUS_S')
        self.device.click_record_clear()
        logger.info(f"Start battle process on {self.cur_boss_type.name if self.cur_boss_type else 'None'}")
        win = False
        while True:
            self.screenshot()
            if self.appear(self.I_MD_SUMMON_BOSS, interval=0.8) or \
                    self.appear(self.I_MD_SWITCH_TICKET, interval=0.8) or \
                    self.appear(self.I_MD_FIRE, interval=0.8):
                break
            if self.appear(self.I_WIN, interval=0.8):
                win = True
                self.click(ipages.random_click())
                continue
            if self.appear(self.I_FALSE, interval=0.8):
                win = False
                self.click(ipages.random_click())
                continue
            if self.appear(self.I_MD_SETTLING, interval=3.5):
                logger.info('wait result')
                time.sleep(random.uniform(3, 5))
                continue
        total_run_time = datetime.now() - self.start_time
        logger.info(f'battle win: {win}')
        logger.info(f'battle count: {self.total_count}/{self.limit_count}')
        logger.info(f'time count: {total_run_time.total_seconds():.1f}s/{self.limit_time.total_seconds()}s')
        return win

    def update_global_state(self):
        if datetime.now() - self.start_time >= self.limit_time or \
                self.total_count >= self.limit_count:
            self.State.done = True

    def check_and_prepare_battle(self) -> bool:
        """检查并做战斗前的准备工作
        :return: True可以战斗, False不能战斗
        """
        logger.hr('battle prepare', 2)
        if not self.check_fatigue():
            return False
        self.synthesis_boss_ticket()
        return self.check_and_switch_ticket() and self.check_and_switch_soul() and self.check_and_switch_powerful()

    def synthesis_boss_ticket(self):
        """合成鬼王"""
        if self.State.synthesis_done:
            return
        logger.hr('synthesis boss ticket')
        self.State.synthesis_done = True
        if len(self.conf.meta_demon_config.synthesis_list_v) <= 0:
            return
        type_ticket_dict: dict[BossType, tuple[RuleImage, int]] = {
            BossType.ONE_STAR: (self.I_MD_SYNTHESIS_ONE_STAR, 3),
            BossType.TWO_STARS: (self.I_MD_SYNTHESIS_TWO_STAR, 3),
            BossType.THREE_STARS: (self.I_MD_SYNTHESIS_THREE_STAR, 3),
            BossType.FOUR_STARS: (self.I_MD_SYNTHESIS_FOUR_STAR, 3),
            BossType.FIVE_STARS: (self.I_MD_SYNTHESIS_FIVE_STAR, 2),
        }
        synthesis_list = self.conf.meta_demon_config.synthesis_list_v
        self.ui_click(self.I_MD_SYNTHESIS, self.I_MD_START_SYNTHESIS, interval=0.6)
        for boss_type in synthesis_list:
            self.do_synthesis(type_ticket_dict[boss_type][0], type_ticket_dict[boss_type][1], boss_type)
        self.ui_click(self.I_MD_CLOSE_POPUP, self.I_MD_SHIKIGAMI, interval=0.6)  # 关闭弹窗退回到鬼王界面

    def _read_synthesis_row(self, boss_type: BossType) -> tuple[str, int | None]:
        """读取目标行的真实星级文字和已放入数量，不以行模板存在代替选中校验。"""
        offset = (boss_type.value - 1) * 100
        title_roi = (304, 154 + offset, 164, 34)
        count_roi = (306, 214 + offset, 155, 29)
        title_rule = RuleOcr(name='md_synthesis_row_title', mode='Single', method='Default',
                             roi=title_roi, area=title_roi, keyword='')
        count_rule = RuleOcr(name='md_synthesis_row_added', mode='Single', method='Default',
                             roi=count_roi, area=count_roi, keyword='')
        title = re.sub(r'\s+', '', title_rule.ocr_single(self.device.image))
        added = re.sub(r'\s+', '', count_rule.ocr_single(self.device.image))
        match = re.fullmatch(r'已放入[:：]?(\d+)', added)
        return title, int(match.group(1)) if match else None

    def do_synthesis(self, target_boss_ticket: RuleImage, need_ticket: int, boss_type: BossType):
        """开始合成鬼王
        :param target_boss_ticket: 目标鬼王级别门票
        :param need_ticket: 合成当前级别鬼王需要的门票数量
        :param boss_type: 配置要求合成的星级，用于核对行文字和已放入数量
        """
        expected_title = ('一', '二', '三', '四', '五')[boss_type.value - 1] + '星裂变之眼'
        reward_deadline = None
        while True:
            self.screenshot()
            if self.appear(self.I_MD_SYNTHESIS_NEED_MONEY, interval=0.8):  # 出现花钱购买合成券
                self.ui_click(self.I_MD_CLOSE_POPUP, self.I_MD_START_SYNTHESIS, interval=0.6)  # 关闭购买弹窗
                break
            if self.appear(self.I_UI_REWARD, interval=0.8):  # 出现获得奖励说明合成成功
                logger.info(f'合成结果已确认: {expected_title}')
                self.click(ipages.random_click(), interval=0.6)
                reward_deadline = None
                continue
            if reward_deadline is not None:
                if time.monotonic() >= reward_deadline:
                    logger.warning(f'未确认合成结果，停止重复点击: {expected_title}')
                    break
                time.sleep(0.2)
                continue
            if not self.appear(target_boss_ticket):
                logger.warning(f'合成目标条目未识别，跳过: {expected_title}')
                break
            actual_title, added = self._read_synthesis_row(boss_type)
            if actual_title != expected_title:
                logger.warning(f'合成星级校验失败: 期望 {expected_title}, 实际 {actual_title!r}，跳过')
                break
            if added is None:
                if not self.appear_then_click(target_boss_ticket, interval=2):
                    break
                # 选择行后必须读新画面，禁止用选择前的截图直接点击合成。
                self.screenshot()
                actual_title, added = self._read_synthesis_row(boss_type)
            logger.info(f'合成材料检查: 期望 {expected_title}, 实际 {actual_title!r}, 已放入 {added}/{need_ticket}')
            if actual_title != expected_title or added != need_ticket:
                logger.warning('合成材料星级或数量未确认，跳过本次合成')
                break
            if not self.appear_then_click(self.I_MD_START_SYNTHESIS, interval=2.5):
                break
            reward_deadline = time.monotonic() + 15
        logger.info(f'合成处理结束: {expected_title}')

    def check_fatigue(self):
        logger.hr('Check fatigue')
        current, remain, total = self.O_MD_FATIGUE.ocr_digit_counter(self.device.image)
        # 不喝茶且当前疲劳度已满
        if not self.conf.meta_demon_config.auto_tea and (current > total or remain < 0):
            self.set_next_run('MetaDemon', target=datetime.now() + self.conf.scheduler.wait_interval)
            self.finish_task()
        return True

    def check_and_switch_ticket(self):
        """切换鬼王门票并更新当前鬼王级别"""
        logger.hr('Summon boss')
        # 打开切换门票弹窗
        while True:
            self.screenshot()
            if self.appear(self.I_MD_FIRE, interval=1.2):  # 可以直接挑战鬼王则退出
                return True
            if self.appear(self.I_MD_GET_BOSS, interval=0.6):  # 打开弹窗了
                break
            if self.appear(self.I_MD_TICKET_EMPTY, interval=0.6):  # 任何门票都没有了
                self.State.done = True
                logger.info('Not have any boss ticket, exit')
                return False
            if self.appear(self.I_MD_SWITCH_TICKET, interval=0.6):
                self.click(self.C_MD_SWITCH_TICKET)
                continue
        type_ticket_dict: dict[BossType, RuleImage] = {
            BossType.ONE_STAR: self.I_MD_ONE_STAR,
            BossType.TWO_STARS: self.I_MD_TWO_STARS,
            BossType.THREE_STARS: self.I_MD_THREE_STARS,
            BossType.FOUR_STARS: self.I_MD_FOUR_STARS,
            BossType.FIVE_STARS: self.I_MD_FIVE_STARS,
            BossType.SIX_STARS: self.I_MD_SIX_STARS,
        }
        # 获取所有存在的鬼王门票
        can_fire_list = [boss_type for boss_type, ticket_rule_image in type_ticket_dict.items() if
                         self.appear(ticket_rule_image)]
        if len(can_fire_list) <= 0:
            self.State.done = True
            logger.info('No remain boss ticket, exit')
            self.ui_click_until_disappear(self.I_MD_CLOSE_POPUP, interval=0.6)
            return False
        # 根据存在的鬼王门票和配置的鬼王序列过滤出需要召唤的鬼王门票
        need_fire_list = [boss_type for boss_type in self.conf.meta_demon_config.fire_sequence_v if
                          boss_type in can_fire_list]
        if len(need_fire_list) <= 0:
            self.State.done = True
            logger.info('There is no boss that needs to be attacked, exit')
            self.ui_click_until_disappear(self.I_MD_CLOSE_POPUP, interval=0.6)
            return False
        # 第一次进来或上次一鬼王类型与这一次不同, 则需要切换御魂和预设
        if self.cur_boss_type is None or self.cur_boss_type != need_fire_list[0]:
            if not self.conf.switch_soul.switch_once:
                self.State.switch_soul_done = False
            self.current_count = 0
        self.cur_boss_type = need_fire_list[0]  # 更新当前鬼王级别
        target_ticket_rule_image = type_ticket_dict[self.cur_boss_type]
        selected = False
        logger.info(f'Summon {self.cur_boss_type.name.lower()} boss')
        while True:
            self.screenshot()
            if self.appear(self.I_MD_FIRE):  # 可以挑战鬼王则退出
                return True
            if selected and self.appear(self.I_MD_CHECK_SELECTED, interval=0.6):
                selected_x, selected_y = self.I_MD_CHECK_SELECTED.coord()
                x, y, w, h = target_ticket_rule_image.roi_front
                if x <= selected_x <= x + w:  # 确定选中目标鬼王门票, 召唤鬼王
                    self.ui_click_until_disappear(self.I_MD_GET_BOSS, interval=0.6)
                    continue
            if self.appear_then_click(target_ticket_rule_image, interval=0.6):  # 选择对应鬼王门票
                selected = True
                continue
        return False

    def check_and_switch_powerful(self) -> bool:
        """检查并切换是否开启强力"""
        logger.hr('process power fire')
        if not self.appear(self.I_MD_FIRE):
            self.goto_page(ipages.page_meta_demon_boss)
            self.screenshot()
            if not self.appear(self.I_MD_FIRE):  # 处于boss界面但是没有挑战按钮
                return False
        powerful_list = self.conf.meta_demon_config.powerful_list_v
        # 当前boss类型未知或不在强力列表中则使用普通追击
        if self.cur_boss_type is None or self.cur_boss_type not in powerful_list:
            self.ui_click(self.I_MD_ENABLE_POWERFUL_FIRE, self.I_MD_DISABLE_POWERFUL_FIRE, interval=0.6)
            return True
        # 已知类型且在强力列表中则开启强力追击
        self.ui_click(self.I_MD_DISABLE_POWERFUL_FIRE, self.I_MD_ENABLE_POWERFUL_FIRE, interval=0.6)
        return True

    def check_and_switch_soul(self) -> bool:
        """切换御魂"""
        if not self.conf.switch_soul.enable:
            return True
        if self.State.switch_soul_done:
            return True
        logger.hr('Switch soul')
        self.State.switch_soul_done = True
        self.goto_page(ipages.page_shikigami_records)
        if self.conf.switch_soul.switch_once:  # 只切换一次则将配置的鬼王御魂全部切换
            for boss_type in self.conf.meta_demon_config.fire_sequence_v:
                switch_type, (group, team) = self.conf.switch_soul.get_switch_by_enum(boss_type)
                if switch_type is None:
                    continue
                if switch_type == 'int':
                    self.run_switch_soul((group, team))
                if switch_type == 'str':
                    self.run_switch_soul_by_name(group, team)
            self.goto_page(ipages.page_meta_demon_boss)
            return True
        # 当前鬼王类型未知, 无法切换御魂
        if self.cur_boss_type is None:
            logger.error(f'cur_boss_type is None')
            self.goto_page(ipages.page_meta_demon_boss)
            return False
        switch_type, (group, team) = self.conf.switch_soul.get_switch_by_enum(self.cur_boss_type)
        if switch_type is None:
            logger.info(f'No soul preset configured for {self.cur_boss_type.name.lower()}, skip')
            self.goto_page(ipages.page_meta_demon_boss)
            return True
        if switch_type == 'int':
            self.run_switch_soul((group, team))
        if switch_type == 'str':
            self.run_switch_soul_by_name(group, team)
        self.goto_page(ipages.page_meta_demon_boss)
        return True

    def finish_task(self):
        self.goto_page(ipages.page_main)
        raise TaskEnd


if __name__ == '__main__':
    from module.config.config import Config
    from module.device.device import Device

    c = Config('oas1')
    d = Device(c)
    t = ScriptTask(c, d)

    t.run()
