# This Python file uses the following encoding: utf-8
# @author ohspecial
# github https://github.com/ohspecial
import random
from datetime import datetime, timedelta
import time

from module.exception import TaskEnd
from module.logger import logger
from module.config.weekly_schedule import next_weekly_run

from tasks.GameUi.game_ui import GameUi
from tasks.GuildBanquet.assets import GuildBanquetAssets
import tasks.GuildBanquet.page as pages


class ScriptTask(GameUi, GuildBanquetAssets):

    def run(self):
        if not self.check_date(datetime.now()):
            logger.warning("GuildBanquet is not available now")
            self.set_next_run(task='GuildBanquet', server=False, target=self.get_next_dt(datetime.now()))
            raise TaskEnd
        self.goto_page(pages.page_guild)
        self.screenshot()
        if not self.appear(self.I_BANQUET_FLAG):
            self.set_next_run(task='GuildBanquet', server=False, target=self.get_next_dt(datetime.now()))
            self.goto_page(pages.page_main)
            raise TaskEnd
        logger.info("Start guild banquet!")
        self.device.stuck_record_clear()
        max_wait_seconds = 660
        wait_interval_seconds = 6
        start_banquet_time = datetime.now()
        exp_full_appeared = False
        while True:
            self.screenshot()
            if datetime.now() - start_banquet_time > timedelta(seconds=max_wait_seconds):
                logger.info('Guild banquet timeout, exit')
                break
            if not self.appear(self.I_BANQUET_FLAG):
                logger.info("Guild banquet finished, exit")
                break
            logger.attr(f'{(datetime.now()-start_banquet_time).seconds}s',"Banquet ongoing, waiting...")
            if self.config.guild_banquet.guild_banquet_config.auto_switch_shikigami:
                if self.appear(self.I_BANQUET_EXP_FULL):
                    # 连续第2次识别到满了则进行更换, 防止是动画过渡导致的误识别
                    if exp_full_appeared:
                        self.switch_shikigami()
                    exp_full_appeared = True
                else:
                    exp_full_appeared = False
            self.device.stuck_record_clear()
            time.sleep(wait_interval_seconds)
        self.set_next_run(task='GuildBanquet', server=False, target=self.get_next_dt(datetime.now(), True))
        self.goto_page(pages.page_main)
        raise TaskEnd

    def switch_shikigami(self):
        """切换式神"""
        self.goto_page(pages.page_banquet_switch_shikigami)
        max_tries = 3
        while True:
            self.device.stuck_record_clear()
            self.screenshot()
            current_page = self.get_current_page()
            match current_page:
                case None:
                    time.sleep(0.5)
                case pages.page_banquet_switch_shikigami:
                    if max_tries <= 0:
                        logger.warning('Maybe shikigami not enough, exit switch')
                        break
                    cur, _, total = self.O_BANQUET_SHIKIGAMI_NUM.ocr_digit_counter(self.device.image)
                    if cur != total or cur == 0:
                        max_tries -= 1
                        if self.appear_then_click(self.I_BANQUET_CLEAR_ALL, interval=1.5):
                            time.sleep(random.randrange(6, 20, 2)/10)  # 两次点击之间稍微加点延迟
                        self.appear_then_click(self.I_BANQUET_ALL_PUT, interval=1.5)
                        continue
                    # 当前式神数量不为0且等于总数, 切换完毕
                    logger.info('Switch shikigami done, back to banquet')
                    self.appear_then_click(self.I_BANQUET_CONFIRM, interval=1.5)
                case pages.page_banquet_shikigami:
                    # 回到了式神展示界面, 说明已经切换完毕直接退出即可
                    break
                case _:
                    self.goto_page(pages.page_banquet_switch_shikigami)
        self.goto_page(pages.page_guild)

    def get_next_dt(self, now: datetime, success: bool = False) -> datetime:
        """获取下一次运行时间"""
        cfg = self.config.model.guild_banquet
        retry_delay = None if success else cfg.scheduler.failure_interval
        return next_weekly_run(cfg.weekly_run_times, now, retry_delay=retry_delay)

    def check_date(self, now: datetime) -> bool:
        """检查宴会今天是否可以运行"""
        return any(day == now.weekday() for day, _ in self.config.model.guild_banquet.weekly_run_times)


if __name__ == '__main__':
    from module.config.config import Config
    from module.device.device import Device
    c = Config('oas1')
    d = Device(c)
    t = ScriptTask(c, d)
    t.run()

