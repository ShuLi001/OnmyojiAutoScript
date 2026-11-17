# This Python file uses the following encoding: utf-8
# @author runhey
# github https://github.com/runhey
import numpy as np

from module.base.timer import Timer
from module.exception import RequestHumanTakeover, GameTooManyClickError, GameStuckError
from module.logger import logger
from tasks.GameUi.assets import GameUiAssets
from tasks.GameUi.chess_battle import ChessBattleNavigationMixin
from tasks.Restart.assets import RestartAssets
from tasks.base_task import BaseTask

DESKTOP_MPAY_CLOSE_LIMIT = 5


def _has_login_animation_bars(image: np.ndarray) -> bool:
    """识别安卓开场动画的横向黑边，排除启动时的全黑画面。"""
    height, width = image.shape[:2]
    if width <= height:
        return False

    # 避开右上角的跳过按钮；稀疏采样即可判断黑边。
    columns = slice(int(width * 0.15), int(width * 0.78), 4)

    def dark_fraction(start: float, end: float) -> float:
        band = image[int(height * start):int(height * end):4, columns]
        return float((band.max(axis=2) <= 18).mean())

    return (
        dark_fraction(0.035, 0.085) >= 0.95
        and dark_fraction(0.91, 0.965) >= 0.95
        and dark_fraction(0.23, 0.78) < 0.85
    )


class LoginService(
    ChessBattleNavigationMixin,
    BaseTask,
    RestartAssets,
    GameUiAssets,
):
    character: str

    def __init__(self, *wargs, **kwargs):
        super().__init__(*wargs, **kwargs)
        self.character = self.config.restart.login_character_config.character
        self.O_LOGIN_SPECIFIC_SERVE.keyword = self.character

    def _app_handle_login(self) -> bool:
        """
        最终是在庭院界面
        :return:
        """
        logger.hr('App login')
        self.device.stuck_record_add('LOGIN_CHECK')

        confirm_timer = Timer(1.5, count=2).start()
        orientation_timer = Timer(10)
        skip_login_animation = True
        skip_click_mx_cnt = 5
        desktop = self.device.is_desktop
        animation_frames = 0
        login_success = False
        popup_count = 0

        def handle_desktop_login_popup() -> bool:
            nonlocal popup_count
            if not self.device.is_desktop or not self.device.find_desktop_login_popup():
                return False
            popup_count += 1
            if popup_count > DESKTOP_MPAY_CLOSE_LIMIT:
                raise GameStuckError('Desktop MPay login popup keeps reappearing')
            if (not self.device.desktop_confirm_login_popup()
                    and self.device.find_desktop_login_popup()):
                raise GameStuckError('Desktop MPay login popup cannot be closed')
            return True

        while 1:
            if handle_desktop_login_popup():
                continue
            if not login_success and orientation_timer.reached():
                self.device.get_orientation()
                orientation_timer.reset()

            image = self.screenshot()
            if not desktop and skip_login_animation and skip_click_mx_cnt > 0:
                animation_frames = animation_frames + 1 if _has_login_animation_bars(image) else 0
            if handle_desktop_login_popup():
                continue
            if self.appear_then_click(
                self.I_RETURN_CHESS_CANCEL,
                interval=0.8,
            ):
                logger.info(
                    'Cancel returning to interrupted Chess battle; '
                    'wait for result flow'
                )
                continue
            if self.appear(self.I_CHECK_CHESS):
                logger.info(
                    'Login recovery reached Chess lobby; '
                    'finish recovery without returning to courtyard'
                )
                return True
            if self.chess_result_flow_visible():
                logger.info(
                    'Login recovery detected unfinished Chess result flow'
                )
                self.return_to_chess_lobby()
                return True
            # 游戏更新流程页面1：下载模式选择，点击"确认"按钮
            # 必须在I_CANCEL_BATTLE之前，否则取消按钮模板会误匹配更新弹窗的"取消"按钮
            if self.ocr_appear_click(self.O_LOGIN_UPDATE_CONFIRM, interval=5):
                logger.info('Game update: download mode selected, click confirm')
                self.device.stuck_record_clear()
                continue
            # 游戏更新流程页面2：资源下载确认弹窗，点击"确定"按钮
            if self.ocr_appear_click(self.O_LOGIN_UPDATE_OK, interval=5):
                logger.info('Game update: resource download confirm, click OK to start download')
                self.device.stuck_record_clear()
                continue
            if self.appear_then_click(self.I_CANCEL_BATTLE, interval=0.8):
                logger.info('Cancel continue battle')
                continue
            if self.appear(self.I_CHECK_MAIN, interval=0.2) and not self.appear(self.I_MAIN_GOTO_SHIKIGAMI_RECORDS):
                logger.info('The main had already appeared, but shikigami records had not yet appeared')
                skip_login_animation = False
                if self.click(self.C_LOGIN_SCROLL_CLOSE_AREA, interval=2):
                    continue
            if self.appear(self.I_MAIN_GOTO_SHIKIGAMI_RECORDS, interval=0.2):
                if confirm_timer.reached():
                    logger.info('Login to main confirm (shikigami records button appears)')
                    login_success = True
                    break
            else:
                confirm_timer.reset()
            if self.appear(self.I_MAIN_GOTO_SHIKIGAMI_RECORDS, interval=0.5):
                logger.info('Login success: shikigami records button appears')
                login_success = True
                skip_login_animation = False
            if self.appear(self.I_HARVEST_ZIDU, interval=1):
                self.I_HARVEST_ZIDU.roi_front[0] -= 200
                self.I_HARVEST_ZIDU.roi_front[1] -= 200
                if self.click(self.I_HARVEST_ZIDU, interval=2):
                    logger.info('Close zidu')
                continue
            if self.appear_then_click(self.I_UI_CONFIRM_SAMLL, interval=2.5):
                logger.info('Soul overflow confirm')
                continue
            if self.appear_then_click(self.I_LOGIN_LOAD_DOWN, interval=1):
                logger.info('Download inbetweening')
                continue
            if self.appear_then_click(self.I_WATCH_VIDEO_CANCEL, interval=0.6):
                logger.info('Close video')
                continue
            if self.appear_then_click(self.I_LOGIN_RED_CLOSE, interval=0.6):
                logger.info('Close red close')
                continue
            if self.appear_then_click(self.I_LOGIN_YELLOW_CLOSE, interval=0.6):
                logger.info('Close yellow close')
                continue
            if self.appear_then_click(self.I_LOGIN_LOGIN_GOTO_BIND_PHONE):
                while 1:
                    self.screenshot()
                    if self.appear_then_click(self.I_LOGIN_LOGIN_CANCEL_BIND_PHONE):
                        logger.info("Close bind phone")
                        break
                continue
            from tasks.Component.GeneralInvite.assets import GeneralInviteAssets as gia
            if self.appear_then_click(gia.I_I_REJECT, interval=0.8):
                logger.info("reject invites")
                continue
            if self.appear_then_click(self.I_LOGIN_LOGIN_ONMYOJI_GENIE):
                logger.info("click onmyoji genie")
                continue
            if self.appear(self.I_LOGIN_SPECIFIC_SERVE, interval=0.6) \
                    and self.ocr_appear_click(self.O_LOGIN_SPECIFIC_SERVE, interval=0.6):
                while True:
                    self.screenshot()
                    if self.appear(self.I_LOGIN_SPECIFIC_SERVE):
                        self.click(self.C_LOGIN_ENSURE_LOGIN_CHARACTER_IN_SAME_SVR, interval=2)
                        continue
                    break
                logger.info('login specific user')
                continue

            if self.appear(self.I_CREATE_ACCOUNT):
                logger.warning('Appear create account')
                raise GameStuckError('Appear create account')
            if self.appear(self.I_CHARACTARS, interval=1):
                logger.info('误入区服设置')
                self.device.click(x=106, y=535)
                continue
            if self.appear(self.I_EARLY_SERVER) and self.appear_then_click(self.I_EARLY_SERVER_CANCEL):
                logger.info('Cancel switch from early server to normal server')
                continue

            # 桌面端维持原行为；安卓端点满后仍可直接识别「跳过」。
            if self.appear(self.I_LOGIN_8, interval=0.6) or (desktop and skip_click_mx_cnt <= 0):
                skip_login_animation = False
            if skip_login_animation:
                if self.ocr_appear_click(self.O_LOGIN_ANIMATION_SKIP, interval=2.5):
                    continue
                if (skip_click_mx_cnt > 0 and (desktop or animation_frames >= 2)
                        and self.click(self.C_LOGIN_ANIMATION_CENTER, interval=5)):
                    skip_click_mx_cnt -= 1

            if self.ocr_appear_click(self.O_LOGIN_ENTER_GAME, interval=3):
                skip_login_animation = False  # 进入登录页面后不再处理登录动画逻辑
                self.wait_until_appear(self.I_LOGIN_SPECIFIC_SERVE, True, wait_time=5)
                continue

        return login_success

    def app_handle_login(self) -> bool:
        self.device.stuck_record_clear()
        self.device.click_record_clear()
        try:
            logged_in = self._app_handle_login()
            if self.device.is_desktop:
                if not logged_in:
                    raise GameStuckError('Desktop client did not reach a logged-in page')
                self.device.desktop_mark_logged_in()
            return True
        except (GameTooManyClickError, GameStuckError) as e:
            if self.device.is_desktop:
                raise  # Restart 清理失败的客户端并决定是否重试。
            logger.warning(e)
            self.device.app_stop()
            self.device.app_start()

        logger.critical('Login failed')
        logger.critical('Onmyoji server may be under maintenance, or you may lost network connection')
        raise RequestHumanTakeover

    def set_specific_usr(self, character: str):
        self.character = character
        self.O_LOGIN_SPECIFIC_SERVE.keyword = character
