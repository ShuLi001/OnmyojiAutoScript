# This Python file uses the following encoding: utf-8
# @author runhey
# github https://github.com/runhey
from time import sleep
from datetime import time, datetime, timedelta

from tasks.Sougenbi.assets import SougenbiAssets
from tasks.Sougenbi.config import SougenbiConfig, SougenbiClass
from tasks.Component.GeneralBattle.general_battle import GeneralBattle
from tasks.Component.QuickLoadout.dungeon import DungeonQuickLoadout
from tasks.GameUi.game_ui import GameUi
from tasks.GameUi.page import any_of, page_main, page_soul_zones
from module.logger import logger
from module.exception import TaskEnd

class ScriptTask(GeneralBattle, GameUi, DungeonQuickLoadout, SougenbiAssets):
    LOADOUT_TASK_NAME = '业原火'

    def _activity_loadout_entry_visible(self) -> bool:
        return self.appear(self.I_S_CHECK_SOUGENBI) and self.appear(self.LOADOUT_ENTRY)

    def run(self):
        con = self.config.sougenbi
        s_con: SougenbiConfig = con.sougenbi_config
        limit_time = con.sougenbi_config.limit_time
        self.limit_time: timedelta = timedelta(hours=limit_time.hour, minutes=limit_time.minute,
                                               seconds=limit_time.second)
        if s_con.buff_enable:
            self.goto_page(page_main)
            self.open_buff()
            if s_con.buff_gold_50_click:
                self.gold_50(True)
            if s_con.buff_gold_100_click:
                self.gold_100(True)
            if s_con.buff_exp_50_click:
                self.exp_50(True)
            if s_con.buff_exp_100_click:
                self.exp_100(True)
            self.close_buff()

        self.goto_page(page_soul_zones)
        while 1:
            self.screenshot()
            if self.appear(self.I_S_CHECK_SOUGENBI):
                break
            if self.appear_then_click(self.I_S_SOUGENBI, interval=1):
                continue
        logger.info('Click sougenbi in soul zones')
        sleep(0.5)
        image_target = None
        click_target = None
        number_target = None
        match con.sougenbi_config.sougenbi_class:
            case SougenbiClass.GREED:
                image_target = self.I_S_FIRE_GREED
                click_target = self.C_C_GREED
                number_target = self.O_S_GREED
            case SougenbiClass.Anger:
                image_target = self.I_S_FIRE_ANGER
                click_target = self.C_C_ANGER
                number_target = self.O_S_ANGER
            case SougenbiClass.Foolery:
                image_target = self.I_S_FIRE_FOOLERY
                click_target = self.C_C_FOOLERY
                number_target = self.O_S_FOOLERY
            case _:
                raise ValueError('Sougenbi class error')
        self.check_lock(con.general_battle_config.lock_team_enable, self.I_S_TEAM_LOCK, self.I_S_TEAM_UNLOCK)
        while 1:
            self.screenshot()
            if self.appear(image_target):
                break
            if self.click(click_target, interval=0.5):
                pass

        lineup_ready = self.apply_dungeon_loadout(con.general_battle_config.get_lineup, lambda: None, member=False)
        # 阵容未应用时仍走收尾，关闭本轮开启的加成。
        while lineup_ready:
            self.screenshot()

            if not self.appear(self.I_S_CHECK_SOUGENBI):
                continue
            if self.current_count >= con.sougenbi_config.limit_count:
                logger.info('Sougenbi count limit out')
                break
            if datetime.now() - self.start_time >= self.limit_time:
                logger.info('Sougenbi time limit out')
                break
            ticket = number_target.ocr(self.device.image)
            if ticket == 0:
                break

            # 点击挑战
            while 1:
                self.screenshot()
                if self.appear_then_click(self.I_S_FIRE, interval=1):
                    pass
                if not self.appear(self.I_S_FIRE):
                    self.run_general_battle(
                        config=con.general_battle_config,
                        exit_matcher=any_of(self.I_S_FIRE, self.I_S_CHECK_SOUGENBI),
                    )
                    break
        self.goto_page(page_main)
        if s_con.buff_enable:
            self.open_buff()
            if s_con.buff_gold_50_click:
                self.gold_50(False)
            if s_con.buff_gold_100_click:
                self.gold_100(False)
            if s_con.buff_exp_50_click:
                self.exp_50(False)
            if s_con.buff_exp_100_click:
                self.exp_100(False)
            self.close_buff()

        self.set_next_run("Sougenbi", success=lineup_ready, finish=True)
        raise TaskEnd







if __name__ == '__main__':
    from module.config.config import Config
    from module.device.device import Device
    c = Config('test')
    d = Device(c)
    t = ScriptTask(c, d)
    t.screenshot()

    t.run()
    # print(t.appear(t.I_S_FOOLERY, threshold=0.97))

