# This Python file uses the following encoding: utf-8
# @author runhey
# github https://github.com/runhey
import time
import cv2
import numpy as np
from cached_property import cached_property
from datetime import datetime

from module.exception import TaskEnd, GameStuckError
from module.base.timer import Timer
from module.logger import logger
from module.atom.ocr import RuleOcr

from tasks.GameUi.game_ui import GameUi
from tasks.GameUi.page import page_main, page_secret_zones, page_shikigami_records, page_battle_result, page_exploration, any_of
from tasks.Secret.config import SecretConfig, Secret
from tasks.Secret.assets import SecretAssets
from tasks.Component.GeneralBattle.general_battle import ExitMatcher, GeneralBattle
from tasks.Component.GeneralBattle.config_general_battle import GeneralBattleConfig
from tasks.Component.SwitchSoul.switch_soul import SwitchSoul
from tasks.Component.GeneralBuff.config_buff import BuffClass
from tasks.WeeklyTrifles.assets import WeeklyTriflesAssets


def has_secret_dialogue_nameplate(image) -> bool:
    """识别标准秘闻对话框左右任一侧的红色姓名栏。"""
    if image.shape[:2] != (720, 1280):
        return False
    red, green, blue = cv2.split(image[525:580, 280:1020].astype(np.int16))
    mask = ((red > 90) & (red > green * 1.45) & (red > blue * 1.25)).astype(np.uint8) * 255
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((3, 15), dtype=np.uint8))
    _, _, components, _ = cv2.connectedComponentsWithStats(mask)
    return any(65 <= w <= 260 and 8 <= h <= 45 and pixels >= 350
               for _, _, w, h, pixels in components[1:])


class ScriptTask(GameUi, GeneralBattle, SwitchSoul, SecretAssets):
    lay_list = ['壹', '贰', '叁', '肆', '伍', '陆', '柒', '捌', '玖', '拾']

    def _exit_matcher(self) -> ExitMatcher:
        return self.I_SE_FIRE

    @cached_property
    def match_layer(self) -> dict:
        return {
            '壹': 1, '贰': 2,
            '叁': 3, '肆': 4,
            '伍': 5, '陆': 6,
            '柒': 7, '捌': 8,
            '玖': 9, '拾': 10,
        }

    @cached_property
    def battle_config(self) -> GeneralBattleConfig:
        conf = self.config.model.secret.general_battle
        conf.lock_team_enable = False
        return conf

    def before_run(self):
        battle_result = self.navigator.resolve_page(page_battle_result)
        battle_result.recognizer = any_of(self.I_SE_BATTLE_WIN, battle_result.recognizer)

    def run_secret_battle(self, config=None, buff=None, battle_key="secret", exit_matcher=None) -> bool:
        """仅在秘闻战斗返回后处理剧情和可选的角色强化展示。"""
        destination = exit_matcher if exit_matcher is not None else self.I_SE_FIRE
        success = self.run_general_battle(config, buff=buff, battle_key=battle_key, exit_matcher=destination)
        self.finish_secret_battle(destination)
        return success

    def finish_secret_battle(self, destination: ExitMatcher) -> None:
        """推进已确认的战后对话，直到连续两帧回到挑战或探索页。"""
        timeout = Timer(30).start()
        last_state = None
        stable_frames = 0
        last_action = None
        last_text = None
        while not timeout.reached():
            self.screenshot()
            if self.appear(self.I_SE_POST_BATTLE_DIALOGUE) and has_secret_dialogue_nameplate(self.device.image):
                state = 'dialogue'
            elif self.appear(self.I_SE_POST_BATTLE_UPGRADE):
                state = 'upgrade'
            elif self._evaluate_exit_matcher(destination) or self.match_page_once(page_exploration):
                state = 'done'
            else:
                state = None
            stable_frames = stable_frames + 1 if state is not None and state == last_state else 1
            last_state = state
            if state is None or stable_frames < 2:
                continue
            if state == 'done':
                logger.info('秘闻战后收尾完成，已回到挑战或探索页面')
                return

            text = None
            if state == 'dialogue':
                text = cv2.inRange(self.device.image[610:680, 320:920], (180, 160, 110), (255, 255, 255))
            # 只有状态或正文确实推进时才清理同一按钮的历史，避免长剧情误触连点保护。
            if state != last_action or (text is not None and last_text is not None
                                        and np.count_nonzero(text != last_text) >= 100):
                self.device.click_record_remove(self.C_SE_POST_BATTLE_ADVANCE.name)
                last_text = text
            last_action = state
            if self.click(self.C_SE_POST_BATTLE_ADVANCE, interval=0.8):
                logger.info('推进秘闻战后对话' if state == 'dialogue' else '关闭秘闻角色强化展示')
                stable_frames = 0
        raise GameStuckError('秘闻战后收尾超时，未回到挑战或探索页面')

    def run(self):
        self.before_run()
        self.check_time()
        secret: Secret = self.config.secret
        con = secret.secret_config
        if secret.switch_soul.enable:
            self.goto_page(page_shikigami_records)
            self.run_switch_soul(secret.switch_soul.switch_group_team)
        if secret.switch_soul.enable_switch_by_name:
            self.goto_page(page_shikigami_records)
            self.run_switch_soul_by_name(secret.switch_soul.group_name, secret.switch_soul.team_name)
        self.goto_page(page_secret_zones)

        # 进入
        success = True
        self.ui_click(self.I_SE_ENTER, self.I_SE_FIRE)
        time.sleep(1)  # 有一个很傻逼的动画
        self.screenshot()
        if not self.appear(self.I_SE_PLACEMENT):
            logger.warning('Unsuccessful entry. You must have entered the secret zone before.')
            success = False

        # 开始
        logger.info('Start secret zone')
        first_battle = True
        while 1:
            self.screenshot()
            if not success:
                logger.warning('Secret zone failed to enter, skip')
                break
            if not self.appear(self.I_SE_FIRE):
                continue
            if self.appear(self.I_SE_FINISHED_1):
                logger.info('Secret zone finished')
                break
            layer = self.find_battle()
            logger.info(f'Current layer: {layer}')
            if not layer:
                if self.appear(WeeklyTriflesAssets.I_WT_SE_SHARE):
                    logger.warning('You have completed the weekly trifles, skip')
                    break
                text = self.O_SE_TOTAL_TIME.ocr_single(self.device.image)
                if '尚未' not in text:
                    logger.warning('You have completed the weekly trifles, skip')
                    break
                continue
            if layer >= 6:
                first_battle = False
            if first_battle and layer <= 5:
                first_battle = False
                buff = []
                if con.secret_gold_50:
                    buff.append(BuffClass.GOLD_50)
                if con.secret_gold_100:
                    buff.append(BuffClass.GOLD_100)
                if buff is []:
                    buff = None
                self.click_battle()
                success = self.run_secret_battle(self.battle_config, buff=buff, battle_key="secret")
                continue
            if not first_battle and layer == 6:
                # 第六次关闭加成，但是发现没有这个接口。。。！！！居然没有注意到
                buff = []
                if con.secret_gold_50:
                    buff.append(BuffClass.GOLD_50_CLOSE)
                if con.secret_gold_100:
                    buff.append(BuffClass.GOLD_100_CLOSE)
                if buff is []:
                    buff = None
                self.click_battle()
                success = self.run_secret_battle(self.battle_config, buff=buff, battle_key="secret")
                continue
            elif not first_battle and layer == 9 and con.layer_9:
                self.click_battle()
                success = self.run_secret_battle(self.battle_config, battle_key="secret")
                continue
            elif not first_battle and layer == 10 and con.layer_10:
                self.click_battle()
                success = self.run_secret_battle(self.battle_config, battle_key="secret")
                break
            elif not first_battle:
                # 其他层
                self.click_battle()
                success = self.run_secret_battle(self.battle_config, battle_key="secret")
                continue

        self.goto_page(page_main)
        if con.secret_gold_50 or con.secret_gold_100:
            self.open_buff()
            if con.secret_gold_50:
                self.gold_50(False)
            if con.secret_gold_100:
                self.gold_100(False)
            self.close_buff()
        self.set_next_run(task='Secret', success=True, finish=True)
        raise TaskEnd('Secret')

    def find_battle(self, screenshot: bool = False) -> int or None:
        """
        自动寻找挑战的层数并且选定 , 找不到会向下划一点
        :return: 如果找得到返回层数，找不到返回None
        """

        def confirm_layer(ocr_target: RuleOcr, roi=None) -> int or None:
            """
            检查层数， 启用函数check_layer
            :param ocr_target:
            :param roi:
            :return:
            """
            ocr_target.roi[0] = int(roi[0]) - 118
            ocr_target.roi[1] = int(roi[1]) + 37
            # print(f'检测到的未通过ROI: {roi}')
            # print(f'检测到的勾玉数量ROI: {ocr_target.roi}')
            jade_num = ocr_target.ocr(self.device.image)
            if isinstance(jade_num, str):
                logger.warning(f'OCR failed, try again {jade_num}')
                return None
            elif not isinstance(jade_num, int):
                logger.warning(f'OCR failed, try again {jade_num}')
                return None
            if jade_num < 7:
                # 第一个的时候可能是没有检测到
                gold_number = self.O_SE_GOLD.ocr(self.device.image)
                if isinstance(gold_number, int) and (gold_number == 10000 or gold_number == 18000):
                    logger.info(f'No find jade number, but find gold number {gold_number}')
                    return 1
                return None
            elif jade_num > 70:
                logger.warning(f'OCR failed, try again {jade_num}')
                return None
            # 勾玉数量 = 层数 * 7
            try:
                lr = jade_num // 7
                return lr
            except TypeError:
                logger.warning(f'OCR failed, try again {jade_num}')
                return None

        if screenshot:
            self.screenshot()
        if self.appear(self.I_CHAT_CLOSE_BUTTON):
            self.ui_click_until_disappear(self.I_CHAT_CLOSE_BUTTON, interval=2)
        text_pos = self.O_SE_NO_PASS.ocr(self.device.image)
        if text_pos != (0, 0, 0, 0):
            # 如果能找得到 未通关 ，那可以挑战
            layer = confirm_layer(self.O_SE_JADE, text_pos)
            if layer:
                self.C_SE_CLICK_LAYER.roi_front = text_pos
                self.click(self.C_SE_CLICK_LAYER, interval=1)
                return layer
            else:
                return None

        else:
            # 如果不是就向下滑动，继续找或者是判断
            last_text_pos = self.O_SE_NO_PASS_LAST.ocr(self.device.image)
            if last_text_pos != (0, 0, 0, 0):
                # 如果是后面找得到
                layer = confirm_layer(self.O_SE_JADE, last_text_pos)

                # 有个bug 十层的发现不了
                if not layer and last_text_pos[1] > 520:
                    layer = 10

                if layer:
                    self.C_SE_CLICK_LAYER.roi_front = last_text_pos
                    self.click(self.C_SE_CLICK_LAYER, interval=1)
                    return layer
                else:
                    return None

            else:
                # 如果不是就一直滑动
                self.swipe(self.S_SE_DOWN_SEIPE, interval=3)
                time.sleep(2)

    def click_battle(self):
        while 1:
            self.screenshot()
            if not self.appear(self.I_SE_FIRE):
                break
            if self.appear_then_click(self.I_SE_FIRE, interval=1):
                continue

    def check_time(self) -> None:
        """
        周一早上不能打
        @return:
        """
        time_now = datetime.now()
        if time_now.weekday() == 0 and time_now.hour < 8:
            self.set_next_run(task='Secret',
                              finish=True,
                              target=time_now.replace(hour=9, minute=0, second=0, microsecond=0))
            raise TaskEnd('Secret')


if __name__ == '__main__':
    from module.config.config import Config
    from module.device.device import Device

    c = Config('oas1')
    d = Device(c)
    t = ScriptTask(c, d)
    t.screenshot()

    t.run()
