# This Python file uses the following encoding: utf-8
# @author runhey
# github https://github.com/runhey
from time import sleep
from datetime import datetime

from module.exception import TaskEnd
from module.logger import logger
from module.base.timer import Timer
from module.config.weekly_schedule import next_weekly_run

from tasks.GameUi.game_ui import GameUi
from tasks.GameUi.page import page_main, page_guild
from tasks.Component.GeneralBattle.general_battle import GeneralBattle
from tasks.Component.GeneralBattle.config_general_battle import GeneralBattleConfig
from tasks.DemonRetreat.config import DemonRetreat
from tasks.DemonRetreat.quick_loadout import DemonRetreatQuickLoadout


class ScriptTask(GameUi, GeneralBattle, DemonRetreatQuickLoadout):

    def run(self):
        """
        首领退治主函数
        """
        cfg: DemonRetreat = self.config.demon_retreat
        if not self.check_date(datetime.now()):
            logger.warning("Demon retreat is not available now")
            self.set_next_run(task='DemonRetreat', server=False, target=self.get_next_dt(datetime.now()))
            raise TaskEnd
        # 进入首领退治
        if not self.goto_demon_retreat():
            logger.warning("Failed to enter demon retreat")
            if self.appear_then_click(self.I_DEMON_BACK_CHECK, interval=1):
                pass
            self.goto_page(page_main)
            self.set_next_run(task='DemonRetreat', server=False, target=self.get_next_dt(datetime.now()))
            raise TaskEnd

        try:
            target = cfg.get_lineup()
            lineup_ready = target is None or self.apply_activity_loadout(target)
        except ValueError as error:
            logger.warning(f'首领退治阵容配置无效：{error}')
            lineup_ready = False
        if not lineup_ready:
            logger.warning('首领退治阵容未应用，结束本轮挑战')
            self.set_next_run(task='DemonRetreat', server=False, target=self.get_next_dt(datetime.now()))
            raise TaskEnd

        # 首领退治战斗
        success = self.demon_retreat()

        # 战斗结束 回到寮信息界面 准备领取奖励
        # 先返回
        while 1:
            self.screenshot()
            if self.appear_then_click(self.I_PRAY, interval=1):
                logger.warning("Claim rewards")
            if self.appear_then_click(self.I_HUNT, interval=1):
                continue
            if self.appear_then_click(self.I_REWARD_ALL, interval=1.5):
                self.ui_reward_appear_click(True)
                logger.info('Claim rewards finished')
                break
            if self.appear(self.I_RANK_LSIT):
                logger.info("No rewards to claim")
                if self.appear_then_click(self.I_DEMON_BACK_CHECK, interval=1):
                    break

        self.goto_page(page_main)
        # 设置下次运行时间
        self.set_next_run(task='DemonRetreat', server=False, target=self.get_next_dt(datetime.now(), success))
        raise TaskEnd

    def goto_demon_retreat(self) -> bool:
        """
        进入首领退治
        """
        cfg: DemonRetreat = self.config.demon_retreat
        logger.info("Entering demon_retreat")
        self.screenshot()
        if self.appear(self.I_HUNT_CHECK):
            self.appear_then_click(self.I_QUIT_BACK, interval=1)
            return True
        self.goto_page(page_guild)

        goto_demon_retreat_num = 0
        while 1:
            self.screenshot()
            # 进入神社
            if self.appear_then_click(self.I_SHRINE, interval=1):
                logger.info("Enter I_SHRINE")
                continue
            # 进入首领退治
            if self.appear_then_click(self.I_HUNT, interval=1.5):
                goto_demon_retreat_num += 1

            # 确保不离开退治
            if self.appear_then_click(self.I_QUIT_BACK, interval=1):
                pass
            if self.appear(self.I_HUNT_CHECK):
                if self.appear_then_click(self.I_QUIT_BACK, interval=1):
                    pass
                logger.info("Enter demon_retreat success")
                return True

            # 周六打完了，但是迟到了只能领取奖励
            if self.appear_then_click(self.I_REWARD_ALL, interval=1):
                logger.info("Already challenged demon_retreat")
                sleep(1)
                if self.appear_then_click(self.I_DEMON_BACK_CHECK, interval=1):
                    pass
                logger.info(f"The next time the demon retreat is next Saturday")
                self.custom_next_run(task='DemonRetreat', custom_time=cfg.demon_retreat_time.custom_run_time,
                                     time_delta=7)
                raise TaskEnd

            if self.appear(self.I_RANK_LSIT):
                logger.info("Enter demon_retreat false")
                return False
            # 超过五次没有进入进入认为失败
            if goto_demon_retreat_num >= 3:
                break
        return False

    def demon_retreat(self):
        cfg: DemonRetreat = self.config.demon_retreat
        logger.hr('demon retreat', 2)

        # 来晚了直接进入战斗
        if not set(self.O_LATER_ENTER_CHECK.ocr(image=self.device.image)).intersection(set("集结")):
            logger.info("arrive later")
            self.ui_click_until_disappear(self.I_ENTER_FIRE, interval=1)
            self.device.stuck_record_add('BATTLE_STATUS_S')
            success = self.run_demon_battle(cfg.general_battle)
        else:
            # 等待进入战斗
            sleep(5)
            self.device.stuck_record_add('BATTLE_STATUS_S')
            self.wait_until_disappear(self.I_DEMON_GATHER)
            self.device.stuck_record_clear()
            self.device.stuck_record_add('BATTLE_STATUS_S')
            success = self.run_demon_battle(cfg.general_battle)

        return success

    def run_demon_battle(self, config: GeneralBattleConfig = None) -> bool:
        """
        重写通用战斗
        三轮战斗 战斗过程中检测挑战
        """
        logger.hr("General battle start", 2)
        self.current_count += 1
        logger.info(f"Current count: {self.current_count}")
        if config is None:
            config = GeneralBattleConfig()

        # 未锁定队伍时，等待准备界面并确认。
        if not config.lock_team_enable:
            logger.info("Lock team is not enable")
            # 点击准备按钮
            self.wait_until_appear(self.I_PREPARE_HIGHLIGHT)
            self.wait_until_appear(self.I_BUFF)
            while 1:
                self.screenshot()
                if not self.appear(self.I_BUFF):
                    break
                if self.appear_then_click(self.I_PREPARE_HIGHLIGHT, interval=1.5):
                    continue

            logger.info("Click prepare ensure button")

            # 照顾一下某些模拟器慢的
            sleep(0.1)

        # 绿标
        self.wait_until_disappear(self.I_BUFF)
        if self.is_in_battle(False):
            self.green_mark(config.green_enable, config.green_mark, config.green_mark_type, config.green_mark_name)

        win = self.battle_wait(config.random_click_swipt_enable)
        if win:
            return True
        else:
            return False

    def battle_wait(self, random_click_swipt_enable: bool) -> bool:
        """
        重写 三轮战斗 战斗过程中点击准备 返回到寮信息界面
        :param random_click_swipt_enable:
        :return:
        """
        self.device.stuck_record_add('BATTLE_STATUS_S')
        self.device.click_record_clear()
        # 战斗过程 随机点击和滑动 防封 并点击 准备
        logger.info("Start battle process")
        stuck_timer = Timer(180)
        stuck_timer.start()
        while 1:
            self.screenshot()
            if self.appear(self.I_WIN):
                logger.info('Battle win')
                self.ui_click_until_disappear(self.I_WIN)
                return True
            # 战斗过程中出现准备
            if self.appear_then_click(self.I_PREPARE_HIGHLIGHT, interval=1.5):
                self.device.stuck_record_clear()
                self.device.stuck_record_add('BATTLE_STATUS_S')
            # 如果出现失败 就点击，返回False
            if self.appear(self.I_FALSE, threshold=0.8):
                logger.info("Battle result is false")
                self.ui_click_until_disappear(self.I_FALSE)
                return False
            # 如果三分钟还没打完，再延长五分钟
            if stuck_timer and stuck_timer.reached():
                stuck_timer = None
                self.device.stuck_record_clear()
                self.device.stuck_record_add('BATTLE_STATUS_S')

    def get_next_dt(self, now: datetime, success: bool = False) -> datetime:
        """获取下一次退治运行时间"""
        cfg = self.config.model.demon_retreat
        return next_weekly_run(
            cfg.weekly_run_times, now, retry_delay=cfg.scheduler.failure_interval, skip_today=success,
        )

    def check_date(self, now: datetime) -> bool:
        """检查当前日期是否可以运行退治"""
        return any(day == now.weekday() for day, _ in self.config.model.demon_retreat.weekly_run_times)


if __name__ == '__main__':
    from module.config.config import Config
    from module.device.device import Device
    c = Config('日常1')
    d = Device(c)
    t = ScriptTask(c, d)
    t.screenshot()

    t.run()

