# This Python file uses the following encoding: utf-8
"""日志英转中转换层（仅用于前端展示）。

设计目标
--------
1. 只在日志输出到前端之前做文本翻译, 服务端控制台与 ``./log`` 文件里的英文日志完全不变。
2. 不改动任何变量名、函数名、类名、配置键、文件路径、数字、URL、异常名、OCR 结果等。
3. 纯规则、无网络依赖: 整句模板优先, 未命中时按词/短语最长匹配做降级翻译。

对外接口
--------
- ``translate_message(message)``: 翻译一条日志的正文部分（不含时间戳/源码/级别头）。
- ``translate_log_text(text)``: 翻译整段日志文本, 逐行识别文件格式或 Flutter 管道格式,
  只翻译正文, 识别不出头部的行（如 traceback、分隔线）原样保留。
"""
from __future__ import annotations

import re

# ======================================================================================================================
# 整句模板
# ----------------------------------------------------------------------------------------------------------------------
# key 为"掩码后"的小写英文: 动态值统一写作 ``{}``; 纯字母的专有名词（OCR/ADB/MuMu 等）在
# 运行时会按原词小写保留, 所以 key 里直接写原词。value 中的占位符按英文出现顺序填充,
# 若中文语序调整, 可使用 {1} {2} 这种带序号的占位符。
# ======================================================================================================================
SENTENCES: dict[str, str] = {
    # ---------- server / gui ----------
    "oas web service startup done": "OAS Web 服务启动完成",
    "oas web service shutdown done": "OAS Web 服务关闭完成",
    "log cleanup finished": "历史日志清理完成",
    "internal server error:": "内部服务器错误:",
    "script {} is not running": "脚本 {} 未在运行",
    "script {} is already running": "脚本 {} 已在运行",
    "script {} is already running and first stop it": "脚本 {} 已在运行, 先停止它",
    "script {} is initialized": "脚本 {} 已初始化",
    "script {} process exit": "脚本 {} 进程退出",
    "script {} process is removed": "脚本 {} 进程已被移除",
    "start script {}": "启动脚本 {}",
    "stop script {}": "停止脚本 {}",
    "restart script {}": "重启脚本 {}",
    "add script {}": "添加脚本 {}",
    "remove script {}": "移除脚本 {}",
    "restart all script": "重启全部脚本",
    "stop all script": "停止全部脚本",
    "create script {} on port {}": "在端口 {2} 创建脚本 {1}",
    "kill all server": "结束所有服务",
    "kill the main process": "结束主进程",
    "kill push data thread": "结束推送数据线程",
    "error: {}": "错误: {}",
    "log error: {}": "日志错误: {}",
    "queueempty: {}": "队列已空: {}",
    "eoferror: {}": "管道结束 EOFError: {}",
    "update thread start": "更新线程启动",
    "update thread has already started": "更新线程已启动",
    "update thread get": "更新线程收到消息",
    "update thread error: {}": "更新线程错误: {}",
    "update tasks {}": "更新任务 {}",
    "{} log coroutine is cancelled": "{} 日志协程已取消",
    "{} state coroutine is cancelled": "{} 状态协程已取消",
    "process manager has no config {}": "进程管理器中没有配置 {}",
    "{} client {} is none": "{} 客户端 {} 为空",
    "{} process is dead, restart it": "{} 进程已死亡, 重启它",
    "{} port {} is none": "{} 端口 {} 为空",
    "gui set value of {} {}": "GUI 设置 {} 的值为 {}",
    "gui get value of {} {}": "GUI 获取 {} 的值为 {}",
    "gui get args of {} {}": "GUI 获取 {} 的参数 {}",
    "gui get mirror image of {}": "GUI 获取 {} 的镜像画面",
    "gui get {} task list": "GUI 获取 {} 任务列表",
    "port {} is in use": "端口 {} 已被占用",
    "port {} is not in use": "端口 {} 未被占用",
    "port {} is released": "端口 {} 已释放",

    # ---------- config / file ----------
    "auto save config": "自动保存配置",
    "config \"{}\" changed at {}": "配置 \"{}\" 在 {} 发生变更",
    "copy {} to {}": "复制 {} 到 {}",
    "copy task {} success": "复制任务 {} 成功",
    "copy task group {} success": "复制任务组 {} 成功",
    "setting.json not exists": "setting.json 不存在",
    "template.json not exists": "template.json 不存在",
    "{} update success": "{} 更新成功",
    "setting.json copy from template.json success": "已从 template.json 复制生成 setting.json",
    "unsupported config file extension: {}": "不支持的配置文件扩展名: {}",
    "read: {}": "读取: {}",
    "write: {}": "写入: {}",
    "delete {}": "删除 {}",
    "delete {} failed: {}": "删除 {} 失败: {}",
    "rename {} to {}": "重命名 {} 为 {}",
    "rename {} to {} failed: {}": "重命名 {} 为 {} 失败: {}",
    "import config {} to {}": "导入配置 {} 到 {}",
    "import task {} to {}": "导入任务 {} 到 {}",
    "{} file not found": "未找到文件 {}",
    "{} is not exists": "{} 不存在",
    "{} is exists": "{} 已存在",
    "{} is no inexistence": "{} 不存在",

    # ---------- scheduler / task framework ----------
    "no task pending": "没有挂起中的任务",
    "no task waiting or pending": "没有等待或挂起的任务",
    "no task named {}": "没有名为 {} 的任务",
    "no scheduler in {}": "{} 中没有调度器",
    "pending tasks: {}": "挂起的任务: {}",
    "task call: {}": "任务调用: {}",
    "task call: {} (skipped because disabled by user)": "任务调用: {}（用户已禁用, 跳过）",
    "please enable at least one task": "请至少启用一个任务",
    "please enable {} or manually login to azurlane": "请启用 {} 或手动登录游戏",
    "notifier: {}": "通知器: {}",
    "invalid priority: {}": "无效的优先级: {}",
    "invalid rule: {}": "无效的规则: {}",
    "invalid pending: {}": "无效的挂起任务: {}",
    "{} is running": "{} 正在运行",
    "invitation appearing": "出现好友邀请",
    "accept friend invitation": "接受好友邀请",
    "reject friend invitation": "拒绝好友邀请",
    "only accept jade invitation": "只接受勾玉邀请",
    "accept jade and food invitation": "接受勾玉和体力邀请",
    "ignore friend invitation": "忽略好友邀请",
    "deal with invitation done": "邀请处理完成",
    "save image: {}": "保存截图: {}",
    "push notify: {}": "推送通知: {}",

    # ---------- device / emulator ----------
    "detect device": "检测设备",
    "detect package": "检测应用包名",
    "get package list": "获取应用包列表",
    "find the only emulator, using it": "只找到一个模拟器, 使用该模拟器",
    "only one running emulator": "仅有一个模拟器在运行",
    "running emulators": "运行中的模拟器",
    "emulator instance": "模拟器实例",
    "find emulator instance": "查找模拟器实例",
    "found emulator instance: {}": "找到模拟器实例: {}",
    "detected emulators:": "检测到的模拟器:",
    "detect emulator from all emulators installed": "从所有已安装的模拟器中检测模拟器",
    "detect emulator from {}": "从 {} 检测模拟器",
    "no available devices": "没有可用的设备",
    "no such device exists, please restart the emulator or set a correct serial": "设备不存在, 请重启模拟器或设置正确的序列号",
    "device {} is offline, disconnect it before connecting": "设备 {} 离线, 请先断开后再连接",
    "device {} is unauthorized, please accept adb debugging on your device": "设备 {} 未授权, 请在设备上允许 ADB 调试",
    "device {} is is having a unknown status: {}": "设备 {} 处于未知状态: {}",
    "adb connect {} failed: {}": "ADB 连接 {} 失败: {}",
    "failed to connect {} after 3 trial, detect device status": "尝试 3 次后仍无法连接 {}, 检测设备状态",
    "failed to connect, return code {}": "连接失败, 返回码: {}",
    "retry {}() failed": "重试 {} 失败",
    "{} failed, retrying in {} seconds...": "{} 失败, {} 秒后重试...",
    "{}, retrying in {} seconds...": "{}, {} 秒后重试...",
    "start emulator": "启动模拟器",
    "emulator start": "模拟器启动",
    "emulator restart": "重启模拟器",
    "emulator stop": "停止模拟器",
    "kill emulator": "结束模拟器",
    "emulator start completed": "模拟器启动完成",
    "emulator start timeout": "模拟器启动超时",
    "failed to start emulator after 3 trial": "尝试 3 次后启动模拟器失败",
    "failed to start emulator after {} attempts": "尝试 {} 次后启动模拟器失败",
    "restart emulator failed for 3 times, please check your settings": "重启模拟器失败 3 次, 请检查设置",
    "restart simulator only works under windows platform": "重启模拟器仅支持 Windows 平台",
    "please set emulator resolution to 1280x720": "请将模拟器分辨率设置为 1280x720",
    "resolution not supported: {}x{}": "不支持的分辨率: {}x{}",
    "received pure black screenshots from emulator, color: {}": "模拟器截图为纯黑画面, 颜色值: {}",
    "unexpected screenshot: {}": "异常截图: {}",
    "screenshot interval set to {}s": "截图间隔设置为 {} 秒",
    "history click: {}": "历史点击: {}",
    "{}click {} @ {}": "点击 {} @ {}",
    "{}click {} @ {} {}": "点击 {} @ {} {}",
    "execute: {}": "执行命令: {}",
    "wait too long": "等待超时",
    "waiting for {}": "等待 {}",
    "animation stable @ {}": "动画已稳定 @ {}",
    "app start: {}": "启动应用: {}",
    "app stop: {}": "停止应用: {}",
    "app login": "应用登录",
    "app restart": "重启应用",
    "app start": "启动应用",
    "app stop": "停止应用",
    "add stuck record: {}": "新增卡死记录: {}",
    "disable stuck detection": "禁用卡死检测",
    "no app stop/start, because handleerror disabled": "HandleError 已禁用, 不重启应用",
    "too many click for a button: {}": "某按钮点击次数过多: {}",
    "too many click between 2 buttons: {}, {}": "两个按钮之间点击次数过多: {}, {}",
    "remove redundant forward: {}": "移除多余端口转发: {}",
    "create forward: {}": "创建端口转发: {}",
    "create reverse: {}": "创建反向连接: {}",
    "reuse forward: {}": "复用端口转发: {}",
    "reuse reverse: {}": "复用反向连接: {}",
    "restart adb": "重启 ADB",
    "restart atx": "重启 ATX",
    "reading realtime adb port": "读取实时 ADB 端口",
    "new adb port: {}": "新的 ADB 端口: {}",
    "match to dynamic port: {}": "匹配到动态端口: {}",
    "connecting to local emulator, using host {}": "连接本地模拟器, 使用主机 {}",
    "connecting to local network device, using host {}": "连接局域网设备, 使用主机 {}",
    "connecting to bluestacks hyper-v, using host {}": "连接 BlueStacks Hyper-V, 使用主机 {}",
    "connecting to unknown device, using host {}": "连接未知设备, 使用主机 {}",
    "connected to mqtt broker!": "已连接到 MQTT 服务器!",
    "connection refused - bad username or password. return code: {}": "连接被拒绝 - 用户名或密码错误。返回码: {}",
    "connection refused - server unavailable. return code: {}": "连接被拒绝 - 服务不可用。返回码: {}",
    "connection refused - incorrect protocol version. return code: {}": "连接被拒绝 - 协议版本不正确。返回码: {}",
    "connection refused - invalid client identifier. return code: {}": "连接被拒绝 - 客户端标识无效。返回码: {}",
    "connection refused - not authorised. return code: {}": "连接被拒绝 - 未授权。返回码: {}",
    "send `msg` to topic `{}`": "向主题 `{}` 发送消息",
    "received `{}` from `{}`": "从 `{}` 收到 `{}`",
    "msg must be a dict, but got {}": "消息必须是字典, 实际得到 {}",

    # ---------- ocr / image ----------
    "ocr [{}] detected in {}": "在 {2} 中 OCR 识别到 [{1}]",
    "no text detected": "未识别到文字",
    "no text detected in roi": "ROI 区域内未识别到文字",
    "unexpected ocr result: {}": "意外的 OCR 结果: {}",
    "invalid quantity: {}": "无效的数量: {}",
    "[{}]: no text detected": "[{}]: 未识别到文字",
    "[{}]: no text detected in roi": "[{}]: ROI 区域内未识别到文字",
    "[{}]: invalid quantity: {}": "[{}]: 无效的数量: {}",
    "[{}]: current {} is greater than total {}": "[{}]: 当前 {} 大于总数 {}",
    "template image is invalid: {}": "模板图片无效: {}",
    "load image failed": "加载图片失败",
    "load image success": "加载图片成功",
    "image is null": "图片为空",
    "save target image {}success": "保存目标图片 {}成功",

    # ---------- notify / update ----------
    "push notify success": "推送通知成功",
    "push notify failed!": "推送通知失败!",
    "fail to load onepush config, skip sending": "加载 onepush 配置失败, 跳过发送",
    "no provider specified, skip sending": "未指定通知渠道, 跳过发送",
    "return message:{}": "返回消息:{}",
    "http code:{}": "HTTP 状态码:{}",
    "git fetch failed": "Git 拉取失败",
    "git fetch failed: {}": "Git 拉取失败: {}",
    "git command timeout after {}s: {}": "Git 命令在 {} 秒后超时: {}",
    "git command failed: {}, error: {}": "Git 命令失败: {}, 错误: {}",
    "git command failed: {}, stderr: {}": "Git 命令失败: {}, stderr: {}",

    # ---------- runtime / wait ----------
    "close emulator during wait": "等待期间关闭模拟器",
    "close game during wait (next task exceeds close_game_limit_time)": "等待期间关闭游戏（下一任务超过 close_game_limit_time）",
    "close game during wait immediately (close_game_limit_time <= 0)": "立即在等待期间关闭游戏（close_game_limit_time <= 0）",
    "ensure game is closed during wait": "等待期间确保游戏已关闭",
    "ensure game stays at main page during wait": "等待期间确保游戏停留在主界面",
    "game is already closed during wait": "等待期间游戏已处于关闭状态",
    "game is still not running after restart recovery": "重启恢复后游戏仍未运行",
    "restart recovery completed, reschedule before continuing": "重启恢复完成, 继续执行前重新调度",
    "restart task failed during runtime recovery": "运行时恢复阶段重启任务失败",
    "gotomain failed while preparing idle state": "准备空闲状态时回到主界面失败",
    "server update active, close game instead of going to main": "服务更新中, 直接关闭游戏而不回主界面",
    "wake emulator before next task": "下一任务前唤醒模拟器",
    "wait before wake emulator: {}": "唤醒模拟器前等待: {}",
    "keep game running during short wait (next task within close_game_limit_time)": "短等待期间保持游戏运行（下一任务在 close_game_limit_time 内）",
    "stay_there (no action) during wait": "等待期间停留原地（不执行操作）",
    "stay_there during wait (emulator is down, with preheat)": "等待期间停留原地（模拟器已关闭, 带预热）",
    "emulator is down, keep close_emulator strategy and wait with preheat": "模拟器已关闭, 保持关闭模拟器策略并带预热等待",
    "target emulator is already offline, keep waiting without starting it": "目标模拟器已离线, 继续等待且不启动它",
    "probe target emulator failed: {}": "探测目标模拟器失败: {}",
    "invalid optimization_whentaskqueueempty: {}, fallback to stay_there": "无效的 Optimization_WhenTaskQueueEmpty: {}, 回退为停留原地",

    # ---------- benchmark ----------
    "benchmark": "性能测试",
    "benchmark test": "性能测试",
    "benchmark tests done": "性能测试完成",
    "benchmark results": "性能测试结果",
    "benchmark tests failed on func: {}": "性能测试在函数 {} 上失败",

    # ---------- business: reward / battle ----------
    "get reward": "领取奖励",
    "get reward success": "领取奖励成功",
    "get reward timeout": "领取奖励超时",
    "get all reward": "领取全部奖励",
    "claim rewards": "领取奖励",
    "claim rewards finished": "领取奖励完成",
    "start battle": "开始战斗",
    "start normal battle": "开始普通战斗",
    "start elite battle": "开始精英战斗",
    "start boss battle": "开始 Boss 战斗",
    "start battle process": "开始战斗流程",
    "battle win": "战斗胜利",
    "battle timeout": "战斗超时",
    "battle prepare": "战斗准备",
    "battle result is false": "战斗结果为失败",
    "battle process end": "战斗流程结束",
    "battle lost and exit": "战斗失败, 退出",
    "battle lost and then refresh": "战斗失败, 随后刷新",
    "battle num [{}]": "战斗次数 [{}]",
    "today is done, skip": "今日已完成, 跳过",
    "already bought": "已购买",
    "all bought": "全部已购买",
    "already feed": "已投喂",
    "already passed": "已通过",
    "no enough money": "金币不足",
    "money is enough": "金币充足",
    "money is not enough": "金币不足",
    "money is not enough 2": "金币不足 2",
    "money ocr failed": "金币 OCR 失败",
    "no reward and break": "没有奖励, 中断",
    "ocr error": "OCR 错误",
    "ocr failed, try again {}": "OCR 失败, 重试 {}",
    "click {}": "点击 {}",
    "click share": "点击分享",
    "click level reward": "点击等级奖励",
    "click medal": "点击勋章",
    "click prepare ensure button": "点击准备确认按钮",
    "switch to next friend": "切换到下一位好友",
    "this week has been obtained": "本周奖励已领取",
    "share timeout. the reward may have been obtained": "分享超时, 奖励可能已被领取",
    "you have completed the weekly trifles, skip": "每周琐事已完成, 跳过",
    "execute round failed, no ticket": "回合执行失败, 没有券了",
    "there is someone in the room and start the challenge": "房间内有人, 开始挑战",
    "wait for too long and start the challenge": "等待时间过长, 开始挑战",
    "not find true orochi": "未找到真大蛇",
    "appear task reward": "出现任务奖励",
    "appear level reward": "出现等级奖励",
    "no any level reward": "没有任何等级奖励",
    "select {} reward": "选择 {} 奖励",
    "collect exp": "收取经验",
    "collect placement reward": "收取放置奖励",
    "buy ap": "购买体力",
    "buy ap success": "购买体力成功",
    "buy ap failed": "购买体力失败",
    "buy sushi with {} jade": "用 {} 勾玉购买体力",
    "buy number is {}": "购买数量为 {}",
    "buy number is 0": "购买数量为 0",
    "remain number is 0": "剩余数量为 0",
    "remain number is {}, buy number is {}": "剩余数量为 {}, 购买数量为 {}",
    "remaining purchase quantity is {}, buy_number is {}": "剩余可购买数量为 {}, buy_number 为 {}",
    "delegation: {} start": "委派: {} 开始",
    "delegation: {} not found": "委派: 未找到 {}",
    "delegation: {} is in delegation": "委派: {} 正在委派中",
    "delegation one": "委派一次",
    "donate success!": "捐赠成功!",
    "donate success for {}!": "为 {} 捐赠成功!",
    "donate one": "捐赠一次",
    "donate button not appear, skip": "捐赠按钮未出现, 跳过",
    "duel battle": "斗技战斗",
    "duel battle end": "斗技战斗结束",
    "duel task is over time": "斗技任务因超时结束",
    "duel task is over score": "斗技任务因积分达标结束",
    "duel task is over honor": "斗技任务因荣誉达标结束",

    # ---------- chess ----------
    "chess game start": "对弈开始",
    "chess round {}": "对弈第 {} 回合",
    "chess game loop {}/{}": "对弈对局循环 {}/{}",
    "chess matchmaking complete: entered battle": "对弈匹配完成: 已进入战斗",
    "chess shop closed successfully": "对弈商店已成功关闭",
    "chess shop is already closed": "对弈商店已关闭",
    "chess shop is already open": "对弈商店已打开",
    "chess shop opened successfully": "对弈商店已成功打开",
    "chess shop failed to close before timeout": "对弈商店超时仍未关闭",
    "chess shop failed to open before timeout": "对弈商店超时仍未打开",
    "chess shop is closed, click market to open it": "对弈商店已关闭, 点击市场打开它",
    "chess shop is open, click market to close it": "对弈商店已打开, 点击市场关闭它",
    "chess coin is full: {}/{}": "对弈金币已满: {}/{}",
    "chess coin: {}/{}": "对弈金币: {}/{}",
    "stop buying {}: hyakki mode detected": "检测到百鬼夜行模式, 停止购买 {}",
    "stop opening chess shop: hyakki mode detected": "检测到百鬼夜行模式, 停止打开对弈商店",
    "stop chess shop purchase: hyakki mode detected": "检测到百鬼夜行模式, 停止对弈商店购买",
    "preparation stage {}/{}": "准备阶段 {}/{}",
    "click fire {} times, no fire left": "点击挑战 {} 次, 已无剩余挑战次数",
    "click fire {} success": "点击挑战 {} 成功",
    "click fire again success": "再次点击挑战成功",
}


# ======================================================================================================================
# 短语/单词词典（降级路径, 最长匹配优先）
# ======================================================================================================================
PHRASES: dict[str, str] = {
    # ----- 高频短语 -----
    "not running": "未运行",
    "already running": "已在运行",
    "is running": "运行中",
    "not found": "未找到",
    "not exists": "不存在",
    "not enough": "不足",
    "not support": "不支持",
    "does not support": "不支持",
    "no more": "没有更多",
    "no longer": "不再",
    "failed to": "未能",
    "try again": "重试",
    "task ended": "任务结束",
    "task reward": "任务奖励",
    "level reward": "等级奖励",
    "get reward": "领取奖励",
    "claim rewards": "领取奖励",
    "game start ready": "游戏启动就绪",
    "game start": "游戏启动",
    "purchase quantity": "购买数量",
    "remain number": "剩余数量",
    "remaining purchase quantity": "剩余可购买数量",
    "buy number": "购买数量",
    "current count": "当前数量",
    "current page": "当前页面",
    "current task": "当前任务",
    "current platform": "当前平台",
    "current window": "当前窗口",
    "current serial": "当前序列号",
    "battle count": "战斗次数",
    "run count": "运行次数",
    "total duration": "总时长",
    "screenshot size": "截图尺寸",
    "screenshot method": "截图方式",
    "control method": "控制方式",
    "device detection": "设备检测",
    "auto device detection": "自动设备检测",
    "auto package detection": "自动包名检测",
    "package detection": "包名检测",
    "package list": "应用包列表",
    "emulator instance": "模拟器实例",
    "emulator start": "模拟器启动",
    "emulator stop": "模拟器停止",
    "emulator restart": "模拟器重启",
    "custom command": "自定义命令",
    "window handle": "窗口句柄",
    "root handle": "根句柄",
    "force killing": "强制结束",
    "in time": "及时",
    "server update": "服务更新",
    "config reload": "配置重载",
    "reschedule scheduler": "重新调度计划任务",
    "during wait": "等待期间",
    "next task": "下一任务",
    "main page": "主界面",
    "main process": "主进程",
    "wake emulator": "唤醒模拟器",
    "quick loadout": "快速预设",
    "loadout panel": "预设面板",
    "mystery amulet": "神秘符咒",
    "black daruma": "黑蛋(御行达摩)",
    "white daruma": "白蛋(奉为达摩)",
    "daruma scrap": "达摩碎片",
    "broken amulet": "破碎符咒",
    "mystery shop": "神秘商店",
    "friendship points": "友情点",
    "chess shop": "对弈商店",
    "chess board": "对弈棋盘",
    "chess card": "对弈卡牌",
    "hand card": "手牌",
    "lineup card": "阵容卡牌",
    "lineup slot": "阵容槽位",
    "rank protection": "段位保护",
    "shop refresh": "商店刷新",
    "preparation stage": "准备阶段",
    "goldfish swap": "金鱼姬交换",
    "emergency cleanup": "紧急清理",
    "image fallback": "图像兜底",
    "glow fallback": "高亮兜底",
    "capture frame": "截取帧",
    "session created": "会话已创建",
    "session closed": "会话已关闭",
    "image server": "图像服务",
    "ocr server": "OCR 服务",
    "ocr worker": "OCR 工作进程",
    "model loaded": "模型已加载",
    "push notify": "推送通知",
    "return code": "返回码",
    "return message": "返回消息",
    "network device": "网络设备",
    "local network": "局域网",
    "local emulator": "本地模拟器",
    "protocol version": "协议版本",
    "client identifier": "客户端标识",
    "continuous learning mode enabled": "连续学习模式已启用",
    "six realms": "六道",
    "demon encounter": "逢魔之时",
    "area boss": "地域鬼王",
    "ryou toppa": "道馆突破",
    "float parade": "花车巡游",
    "daily trifles": "日常琐事",
    "weekly trifles": "每周琐事",
    "talisman pass": "花合战",
    "gold youkai": "金币妖怪",
    "experience youkai": "经验妖怪",
    "martial tournament": "为崽而战",
    "global game": "全局游戏",
    "souls tidy": "御魂整理",
    "fire land": "火地块",
    "shop land": "商店地块",
    "chaos land": "混沌地块",
    "arakawa goldfish": "荒川金鱼",
    "system card": "系统卡牌",
    "passive mode": "被动模式",
    "alternate layout": "备用布局",
    "selection panel": "选择面板",
    "jade marker": "勾玉标记",
    "jade area": "勾玉区域",
    "board position": "棋盘位置",
    "card sale": "卡牌出售",
    "hand cleanup": "手牌清理",
    "hand count": "手牌数量",
    "lineup protection": "阵容保护",
    "deploy position": "上阵位置",
    "sell": "出售",
    # ----- 否定 / 情态 -----
    "not recognized": "未识别",
    "not detected": "未检测到",
    "not appear": "未出现",
    "not confirmed": "未确认",
    "not visible": "不可见",
    "not closed": "未关闭",
    "not open": "未打开",
    "not ready": "未就绪",
    "not valid": "无效",
    "not match": "不匹配",
    "not equal": "不相等",
    "not installed": "未安装",
    "not provided": "未提供",
    "not available": "不可用",
    "not exist": "不存在",
    "not work": "不可用",
    "not use": "不使用",
    "identity not recognized": "身份未能识别",
    "unable to": "无法",
    "can not": "无法",
    "could not": "无法",
    "do not": "未",
    "did not": "未",
    "was not": "未",
    "have been": "已",
    "has been": "已",
    "falling back to": "回退到",
    "please check": "请检查",
    "try to": "尝试",
    "save rules": "保存规则",
    "economy operation": "经济操作",
    # ----- 复合专有名词（带连字符的标识符在分词时是一个整体） -----
    "discover-soul": "御魂发掘",
    "adb-reconnect": "ADB 重连",
    "emu-start": "模拟器启动",
    "emu-stop": "模拟器停止",
    "emu-instance": "模拟器实例",
    "last-seconds": "最后几秒",
    "non-lineup": "非阵容",
    "in-game": "游戏内",
    "game-over": "游戏结束",
    "game-end": "游戏结束",
    "result-page": "结果页",
    "failed-action": "失败操作",
    # ----- 工具/组件名 -----
    "annotator": "标注工具",
    "droidcast": "DroidCast",
    "scrcpy": "scrcpy",
    "minitouch": "MiniTouch",
    "minicap": "minicap",
    "nemuipc": "NemuIpc",
    "onepush": "OnePush",
    "mumu": "MuMu",
    "bluestacks": "BlueStacks",
    "ldplayer": "LDPlayer",
    "netcat": "netcat",
    # ----- 普通单词 -----
    "start": "启动", "starting": "启动中", "started": "已启动",
    "stop": "停止", "stopping": "停止中", "stopped": "已停止",
    "restart": "重启", "kill": "结束", "terminate": "终止",
    "wait": "等待", "waiting": "等待中", "wake": "唤醒",
    "enter": "进入", "entered": "已进入", "exit": "退出",
    "buy": "购买", "purchase": "购买", "purchased": "已购买",
    "bought": "已购买", "sold": "已出售", "shop": "商店",
    "store": "商店", "mall": "商城", "market": "市场",
    "click": "点击", "swipe": "滑动", "press": "按下", "drag": "拖拽",
    "reward": "奖励", "ticket": "券", "coin": "金币", "gold": "金币",
    "money": "金币", "jade": "勾玉", "price": "价格",
    "battle": "战斗", "challenge": "挑战", "fight": "战斗",
    "win": "胜利", "won": "胜利", "lost": "失败", "lose": "失败",
    "defeat": "击败",
    "success": "成功", "successful": "成功", "succeed": "成功",
    "fail": "失败", "failed": "失败", "failure": "失败",
    "error": "错误", "warning": "警告", "exception": "异常",
    "finish": "完成", "finished": "完成", "complete": "完成",
    "completed": "已完成", "done": "完成", "over": "结束",
    "ended": "已结束", "end": "结束",
    "skip": "跳过", "skipped": "已跳过",
    "detect": "检测", "detected": "检测到", "detection": "检测",
    "recognize": "识别", "recognized": "已识别",
    "identify": "识别", "identified": "已识别",
    "find": "找到", "found": "找到", "search": "搜索", "scan": "扫描",
    "appear": "出现", "appeared": "已出现",
    "disappear": "消失", "disappeared": "已消失",
    "visible": "可见", "show": "显示",
    "open": "打开", "opened": "已打开", "reopen": "重新打开",
    "close": "关闭", "closed": "已关闭",
    "refresh": "刷新", "reload": "重新加载", "reset": "重置",
    "retry": "重试", "retrying": "重试中",
    "attempt": "尝试", "attempts": "尝试次数",
    "enable": "启用", "enabled": "已启用",
    "disable": "禁用", "disabled": "已禁用",
    "valid": "有效", "invalid": "无效",
    "available": "可用", "unavailable": "不可用",
    "exist": "存在", "exists": "存在", "missing": "缺失",
    "online": "在线", "offline": "离线",
    "connect": "连接", "connected": "已连接", "connecting": "连接中",
    "disconnect": "断开", "refused": "被拒绝",
    "run": "运行", "running": "运行中", "launch": "启动",
    "task": "任务", "script": "脚本", "server": "服务",
    "service": "服务", "config": "配置", "emulator": "模拟器",
    "device": "设备", "app": "应用", "package": "应用包",
    "process": "进程", "thread": "线程", "port": "端口",
    "serial": "序列号", "host": "主机", "client": "客户端",
    "screenshot": "截图", "image": "图片", "frame": "帧",
    "template": "模板", "icon": "图标", "button": "按钮",
    "page": "页面", "screen": "屏幕", "window": "窗口",
    "panel": "面板", "popup": "弹窗", "dialog": "对话框",
    "current": "当前", "remain": "剩余", "remaining": "剩余的",
    "left": "剩余", "count": "数量", "number": "数量",
    "quantity": "数量", "total": "总计", "max": "最大",
    "limit": "上限", "interval": "间隔", "duration": "时长",
    "time": "时间", "times": "次数",
    "second": "秒", "seconds": "秒", "minute": "分钟",
    "minutes": "分钟", "hour": "小时", "hours": "小时",
    "today": "今天", "week": "周",
    "target": "目标", "area": "区域", "position": "位置",
    "location": "位置", "slot": "槽位", "layer": "层",
    "stage": "阶段", "phase": "阶段", "round": "回合",
    "mode": "模式", "level": "等级",
    "select": "选择", "selected": "已选择",
    "confirm": "确认", "confirmed": "已确认",
    "cancel": "取消", "switch": "切换", "choose": "选择",
    "team": "队伍", "group": "组", "lineup": "阵容",
    "shikigami": "式神", "soul": "御魂", "souls": "御魂",
    "skill": "技能", "buff": "增益", "card": "卡牌",
    "hand": "手牌", "board": "棋盘",
    "chess": "对弈", "duel": "斗技", "guild": "阴阳寮",
    "ryou": "寮", "shrine": "神社", "delegation": "委派",
    "orochi": "大蛇", "daruma": "达摩", "amulet": "符咒",
    "hyakki": "百鬼夜行", "hyakkiyakou": "百鬼夜行",
    "demon": "妖怪", "boss": "Boss",
    "ap": "体力", "sushi": "寿司(体力)", "exp": "经验",
    "score": "分数", "threshold": "阈值",
    "match": "匹配", "matched": "已匹配", "quality": "品质",
    "update": "更新", "updated": "已更新",
    "save": "保存", "saved": "已保存",
    "load": "加载", "loaded": "已加载",
    "copy": "复制", "rename": "重命名",
    "delete": "删除", "remove": "移除", "removed": "已移除",
    "create": "创建", "add": "添加", "added": "已添加",
    "import": "导入", "export": "导出",
    "upload": "上传", "download": "下载",
    "push": "推送", "send": "发送", "sent": "已发送",
    "receive": "收到", "received": "已收到",
    "check": "检查", "setting": "设置", "settings": "设置",
    "login": "登录", "logout": "登出", "account": "账号",
    "password": "密码", "username": "用户名",
    "prepare": "准备", "preparation": "准备",
    "ready": "就绪", "idle": "空闲", "pending": "挂起",
    "continue": "继续", "resume": "恢复",
    "return": "返回", "back": "返回", "next": "下一个",
    "last": "上一个", "previous": "之前的",
    "auto": "自动", "manual": "手动", "manually": "手动地",
    "unknown": "未知", "unexpected": "意外",
    "abnormal": "异常", "normal": "正常",
    "black": "黑色", "white": "白色", "red": "红色", "yellow": "黄色",
    "full": "已满", "empty": "空", "low": "低", "high": "高",
    "enough": "足够",
    "resolution": "分辨率", "orientation": "方向",
    "size": "尺寸", "width": "宽度", "height": "高度",
    "method": "方式", "rule": "规则", "strategy": "策略",
    "option": "选项", "category": "类别", "type": "类型",
    "status": "状态", "state": "状态", "result": "结果",
    "reason": "原因", "action": "操作", "operation": "操作",
    "function": "函数", "call": "调用",
    "video": "视频", "stream": "流", "mirror": "镜像",
    "human": "人工", "takeover": "接管",
    "question": "问题", "answer": "答案",
    "room": "房间", "friend": "好友", "invitation": "邀请",
    "feed": "投喂", "share": "分享",
    "notifier": "通知器", "notify": "通知", "notification": "通知",
    "recommend": "推荐", "recommended": "推荐的",
    "install": "安装", "uninstall": "卸载",
    "upgrade": "升级", "version": "版本",
    "support": "支持", "supported": "支持",
    "assume": "假定", "fallback": "回退",
    "obtained": "已获得", "accept": "接受",
    "reject": "拒绝", "ignore": "忽略",
    "daily": "每日", "weekly": "每周",
    "scrap": "碎片", "medal": "勋章", "honor": "荣誉",
    "charisma": "魅力", "scales": "鳞片",
    "consignment": "寄售", "bondlings": "宠物",
    "pet": "宠物", "banquet": "宴会",
    "sea": "海域", "moon": "月", "land": "地块",
    "explore": "探索", "exploration": "探索",
    "hunt": "狩猎", "kirin": "麒麟", "secret": "秘境",
    "nian": "年兽", "frog": "青蛙",
    "wanted": "悬赏", "quest": "任务", "gift": "礼物",
    "summon": "召唤", "costume": "皮肤",
    "kekkai": "结界", "utilize": "寄养",
    "goryou": "御灵", "realm": "结界",
    "elite": "精英", "skill": "技能",
    "recover": "恢复", "recovery": "恢复",
    "interrupt": "中断", "interrupted": "被中断",
    "block": "阻止", "blocked": "被阻止",
    "release": "释放", "free": "释放", "occupied": "占用",
    "capacity": "容量", "deploy": "上阵", "deployment": "上阵",
    "recall": "撤回", "equip": "装备", "equipment": "装备",
    "marker": "标记", "specifics": "详情", "glow": "光效",
    "avatar": "头像", "preserve": "保留", "progress": "进展",
    "submit": "提交", "submitted": "已提交",
    "lock": "锁定", "locked": "已锁定", "unlock": "解锁",
    "active": "活跃", "primary": "主要的", "numeric": "数字",
    "layout": "布局", "formation": "阵型",
    "candidate": "候选", "weight": "权重", "best": "最佳",
    "session": "会话", "crop": "裁剪", "scene": "场景",
    "record": "记录", "records": "记录", "stuck": "卡死",
    "random": "随机", "trigger": "触发",
    "drop": "丢弃", "dropped": "已丢弃",
    "schedule": "调度", "scheduler": "调度器",
    "scheduled": "已调度", "delay": "延迟", "delayed": "已延迟",
    "defer": "推迟", "queue": "队列",
    "broadcast": "广播", "topic": "主题", "broker": "消息服务器",
    "message": "消息", "param": "参数", "params": "参数",
    "provided": "提供", "require": "需要", "required": "必需",
    "specify": "指定", "registry": "注册表",
    "administrator": "管理员", "variable": "变量",
    "default": "默认", "dynamic": "动态",
    "realtime": "实时", "probe": "探测", "probed": "已探测",
    "startup": "启动", "minimize": "最小化",
    "minimizing": "最小化中", "focus": "焦点",
    "depth": "深度", "rate": "比率", "regex": "正则表达式",
    "selector": "选择器", "preset": "预设", "filter": "过滤器",
    "revise": "修正", "revised": "修正为",
    "digit": "数字", "pid": "PID", "apk": "APK",
    "socket": "socket", "loop": "循环", "index": "索引",
    "sequence": "序列", "value": "值", "code": "代码",
    "grigri": "祝福", "benefit": "增益",
    "hakuzosu": "白藏主", "goldfish": "金鱼",
    "bongna": "奉纳", "tidy": "整理",
    "global": "全局", "local": "本地", "remote": "远程",
    "safely": "安全地", "safe": "安全",
    "original": "原来的", "swap": "交换",
    "source": "来源", "history": "历史",
    "allowed": "允许的", "allow": "允许",
    "owner": "所有者", "player": "玩家", "players": "玩家",
    "offline": "离线", "online": "在线",
    "paid": "已支付", "pay": "支付",
    "occupy": "占用", "population": "人口",
    "attribute": "属性", "attributes": "属性",
    "clean": "干净", "cleanup": "清理",
    "sold_non_lineup": "已出售非阵容卡",
    "climb": "冲榜", "remain": "剩余",
    # ----- 高频小词 / 介词 / 副词（整句未命中时帮助中文成句） -----
    "cannot": "无法", "unable": "无法", "not": "未", "no": "无",
    "in": "在", "at": "在", "on": "在", "from": "从", "to": "到",
    "of": "的", "for": "为了", "with": "使用", "by": "由",
    "after": "之后", "before": "之前", "into": "进入", "within": "在...内",
    "without": "没有", "through": "通过", "via": "通过", "until": "直到",
    "between": "之间", "behind": "在后面",
    "because": "因为", "if": "如果", "when": "当", "during": "期间",
    "but": "但是", "however": "但是", "instead": "反而",
    "again": "再次", "still": "仍然", "already": "已经", "yet": "尚未",
    "once": "一次", "only": "只", "just": "刚", "even": "甚至", "also": "也",
    "then": "然后", "than": "比", "like": "像",
    "more": "更多", "less": "更少", "new": "新的", "old": "旧的",
    "same": "相同", "different": "不同", "other": "其他", "another": "另一个",
    "all": "全部", "any": "任何", "some": "一些", "each": "每个", "every": "每个",
    "both": "两者", "per": "每", "around": "大约", "approximately": "大约",
    "starts": "启动", "begins": "开始", "begin": "开始",
    "rules": "规则", "register": "注册", "disconnected": "已断开",
    "clear": "清除", "cleared": "已清空", "identity": "识别结果",
    "successfully": "成功地", "immediately": "立即", "directly": "直接",
    "top": "顶部", "bottom": "底部", "upper": "上方的", "lower": "下方的",
    "front": "前面", "center": "中心", "edge": "边缘", "corner": "角落",
    "first": "首先", "third": "第三",
    # ----- 语料高频补词 -----
    "is": "为", "are": "为", "was": "为", "were": "为", "be": "", "been": "已",
    "has": "有", "have": "有", "had": "已",
    "get": "获取", "got": "获取到", "set": "设置",
    "use": "使用", "using": "使用", "used": "使用",
    "can": "可以", "could": "可以", "would": "将", "should": "应", "will": "将",
    "do": "执行", "does": "执行", "did": "执行",
    "and": "且", "or": "或", "the": "", "a": "", "an": "",
    "it": "", "its": "其", "there": "", "s": "",
    "please": "请", "your": "你的", "you": "你", "we": "我们",
    "this": "该", "that": "该", "as": "作为", "one": "一个",
    "someone": "有人", "something": "某物", "none": "无",
    "game": "游戏", "gui": "GUI", "adb": "ADB", "ocr": "OCR", "oas": "OAS",
    "http": "HTTP", "frida": "Frida",
    "timeout": "超时", "file": "文件", "files": "文件",
    "handle": "句柄", "name": "名称", "instance": "实例", "instances": "实例",
    "path": "路径", "command": "命令", "connection": "连接",
    "execute": "执行", "executed": "已执行", "init": "初始化", "initialized": "已初始化",
    "runtime": "运行时", "log": "日志", "token": "令牌", "msg": "msg",
    "now": "现在", "too": "过于", "very": "很", "long": "长",
    "test": "测试", "tests": "测试", "testing": "测试中",
    "economy": "经济", "emergency": "紧急", "keep": "保持", "out": "出",
    "protect": "保护", "sale": "出售", "cards": "卡牌", "tickets": "券",
    "reached": "达到", "reach": "达到", "may": "可能",
    "devices": "设备", "emulators": "模拟器", "tasks": "任务", "images": "图片",
    "root": "root", "lobby": "大厅", "remains": "剩余", "ensure": "确保",
    "box": "宝箱", "confirmation": "确认", "donate": "捐赠", "donation": "捐赠",
    "luck": "运气", "similar": "相似", "debugger": "调试器", "correct": "正确的",
    "forward": "转发", "outside": "之外", "standard": "标准",
    "five": "五", "four": "四", "two": "两个", "thousand": "千", "day": "天",
    "attack": "攻击", "num": "数量", "possible": "可能", "track": "追踪",
    "safety": "安全", "strings": "字符串", "touch": "触摸", "fish": "鱼",
    "opening": "开启", "closing": "关闭中", "special": "特殊",
    "awake": "觉醒", "medium": "中级", "totem": "图腾", "alive": "存活",
    "emblem": "徽章", "rank": "段位", "cancelled": "已取消", "canceled": "已取消",
    "repeated": "重复", "matchmaking": "匹配", "fixed": "已固定",
    "collect": "收取", "retreat": "撤退", "overflow": "溢出", "preheat": "预热",
    "evict": "逐出", "multiple": "多个", "branch": "分支",
    "courtyard": "庭院", "main": "主", "onmyoji": "阴阳师",
    "quiz": "答题", "transition": "过渡", "zone": "区域",
    "throw": "抛出", "netherworld": "冥界", "capture": "捕获", "character": "角色",
    "hit": "命中", "func": "函数", "fetch": "拉取", "break": "中断",
    "changed": "已变更", "templates": "模板", "processed": "已处理",
    "items": "道具", "item": "道具", "corresponding": "对应的",
    "extension": "扩展名", "unsupported": "不支持的", "diagnostic": "诊断",
    "flush": "清空", "deploying": "上阵中", "maybe": "可能",
    "run": "运行", "runs": "运行", "resolve": "解析",
    "executable": "可执行文件", "control": "控制", "returning": "返回",
    "early": "提前", "activate": "激活", "activated": "已激活",
    "banned": "被禁用", "self": "己方", "also": "也",
    "positions": "位置", "order": "顺序", "continuation": "继续",
    "assumed": "假定", "visibly": "可见地", "toggle": "开关",
    "unconfirmed": "未确认", "games": "局", "handling": "处理",
    "pass": "轮次", "cycle": "循环", "atomic": "原子", "batch": "批次",
    "moving": "移动", "identification": "识别", "assigned": "已分配",
    "markers": "标记", "absent": "未出现", "frames": "帧",
    "context": "上下文", "conflict": "冲突", "recorded": "已记录",
    "reuse": "复用", "anchor": "锚点", "redeploy": "重新上阵",
    "clicks": "点击", "counts": "计数", "closes": "关闭",
    "one-shot": "单次",
}

# ======================================================================================================================
# 保护规则：把不能翻译的内容替换成私有区单字符占位符
# ======================================================================================================================
_PROTECT_PATTERNS: list[re.Pattern] = [
    # Rich markup 标签 [bold] [/bold]（标签必须以字母开头, 避免误吞 [30] 这类数字中括号）
    re.compile(r"\[/?[a-zA-Z][a-zA-Z0-9_#, .]*\]"),
    # URL
    re.compile(r"https?://[^\s<>\"'\[\]|]+"),
    # Windows 盘符路径 / 注册表路径
    re.compile(r"[A-Za-z]:\\[^\s<>\"'|*?]+"),
    re.compile(r"HKEY_[A-Za-z0-9_\\]+"),
    # Windows 相对路径  module\device\connection.py（至少含一个反斜杠）
    re.compile(r"[A-Za-z0-9_.\-]+(?:\\[A-Za-z0-9_.\-]+)+"),
    # Unix / 相对路径（斜杠后必须含字母, 避免把 600/600 里的 /600 当路径）
    re.compile(r"(?:\.\./|\./|/)[A-Za-z0-9_.\-/\\]*[A-Za-z][A-Za-z0-9_.\-/\\]*"),
    # 具体文件名（可带行号）
    re.compile(
        r"\b[\w.\-]+\.(?:py|txt|json|ya?ml|apk|png|jpe?g|gif|dll|exe|qm|xml|csv|log|bat|ico|mp4|jar|so|md|html?|qrc)(?::\d+)?\b"
    ),
    # 127.0.0.1:5555 形式的 IP:端口
    re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}(?::\d+)?\b"),
    # 点分配置/模块名（必须在异常名之前, 否则 Alas.Error.HandleError 会被截断）
    re.compile(r"\b[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+\b"),
    # 异常 / 特殊类名
    re.compile(r"\b[A-Za-z_][A-Za-z0-9_]*(?:Error|Exception|Expired|Takeover)\b"),
    # 带括号的函数调用  func_name()
    re.compile(r"\b[A-Za-z_][A-Za-z0-9_]*\(\)"),
    # key=value 结构（配置键名与值整体保护, 如 session=abc-1、attempt={}/2、hand_count={}）
    re.compile(r"\b[a-z_][a-z0-9_]*=(?:\{[^}]*\}|\"[^\"]*\"|'[^']*'|[^\s,;:\[\]{}()|]+)"),
    # 下划线 / 含数字标识符（变量名、配置键、枚举值）
    re.compile(r"\b[A-Za-z_][A-Za-z0-9_]*[_][A-Za-z0-9_]+\b"),
    re.compile(r"\b[A-Za-z]+[0-9][A-Za-z0-9_]*\b"),
    # 引号内容（引号本身保留, 只保护内部）, 回填时用
    re.compile(r"\"([^\"\n]*)\""),
    re.compile(r"'([^'\n]*)'"),
    re.compile(r"`([^`\n]*)`"),
    # 中括号内容（括号保留）
    re.compile(r"\[([^\]\n]{0,80})\]"),
    # 十六进制
    re.compile(r"\b0x[0-9a-fA-F]+\b"),
    # printf / format 占位符  %s %d {0} {}
    re.compile(r"%(?:\.\d+)?[sdrf%]"),
    re.compile(r"\{\d*\}"),
    # 数字（含时间/尺寸/百分比单位）
    re.compile(r"\b\d+(?:\.\d+)?(?:x\d+)*(?::\d+)?(?:px|fps|ms|s|m|h|%)?\b"),
    # 纯大写缩写 OCR / ADB / ROI / WSA ...
    re.compile(r"\b[A-Z][A-Z0-9_]{1,}\b"),
    # CamelCase 类名/标识符  PackageName / DroidCast / RequestHuman
    re.compile(r"\b[A-Z][a-z]+(?:[A-Z][a-z0-9]+)+\b"),
]

# 哪些保护规则是"括号保留、只保护内部"（引号与中括号）
_INNER_PATTERN_INDEXES: set[int] = set()
for _idx, _pat in enumerate(_PROTECT_PATTERNS):
    if _pat.pattern.startswith(("\"(", "'(", "`(", r"\[(")):
        _INNER_PATTERN_INDEXES.add(_idx)

_SENTINEL_BASE = 0xE000
_ALPHA_ONLY = re.compile(r"[A-Za-z]+")
_WORD_RE = re.compile(r"[A-Za-z]+(?:-[A-Za-z0-9]+)*")
_SENTINEL_RE = re.compile(r"[\ue000-\uf8ff]")


def _protect(text: str) -> tuple[str, list[str]]:
    """按规则顺序把敏感/动态内容替换成占位符。"""
    values: list[str] = []

    def add(value: str) -> str:
        values.append(value)
        return chr(_SENTINEL_BASE + len(values) - 1)

    for idx, pattern in enumerate(_PROTECT_PATTERNS):
        inner_only = idx in _INNER_PATTERN_INDEXES

        def repl(match: re.Match) -> str:
            if inner_only and match.lastindex:
                outer_open = match.group(0)[0]
                outer_close = match.group(0)[-1]
                inner = match.group(1)
                if inner == "":
                    return match.group(0)
                return outer_open + add(inner) + outer_close
            return add(match.group(0))

        text = pattern.sub(repl, text)
    return text, values


# 整句 key 中的 {} 在匹配时可对应: 一个占位符（任意被保护的动态值）、一个普通英文单词
# （如任务名 Exploration 这类 TitleCase 但不是 CamelCase 的词不会被保护）、
# 或源码模板里未格式化的字面占位符 {} / {1} / %s（偶尔会直接出现在日志中）。
_SLOT_ALT = r"(?:[\ue000-\uf8ff]|[A-Za-z][A-Za-z0-9_.\-]*|\{\}|\{\d+\}|%[sdrf])"


def _build_sentence_pattern(key: str) -> re.Pattern:
    """把整句 key 编译为正则: 转义固定文本, ``{}`` 变为捕获组, 槽位后紧跟的 ``()`` 可选。"""
    parts = key.split("{}")
    pattern = re.escape(parts[0])
    for part in parts[1:]:
        pattern += "(" + _SLOT_ALT + ")"
        # "retry {}() failed" 这类 key: 实际占位值 screenshot() 已含括号, 令字面 () 可选
        if part.startswith("\\(\\)"):
            pattern += r"(?:\(\))?"
            part = part[4:]
        pattern += re.escape(part)
    return re.compile("^" + pattern + "$", re.IGNORECASE)


# 单 key 模式（命中后用于取分组）与一个总 alternation 模式（未命中时只跑一次正则）
_KEY_PATTERNS: dict[str, re.Pattern] = {key: _build_sentence_pattern(key) for key in SENTENCES}
_MASTER_SENTENCE_RE = re.compile(
    "^(?:" + "|".join("(?P<g%d>%s)" % (i, pat.pattern[1:-1]) for i, pat in enumerate(_KEY_PATTERNS.values())) + ")$",
    re.IGNORECASE,
)
_KEY_ORDER = list(_KEY_PATTERNS.keys())


def _match_sentence(masked: str, values: list[str]):
    """尝试整句匹配, 命中返回 (中文模板, 槽位值列表), 否则返回 None。"""
    # 纯字母占位（OCR/类名等）还原为原词参与固定文本匹配, 非字母占位保持占位符
    def literalize(match: re.Match) -> str:
        value = values[ord(match.group(0)) - _SENTINEL_BASE]
        return value if _ALPHA_ONLY.fullmatch(value) else match.group(0)

    literal_masked = " ".join(_SENTINEL_RE.sub(literalize, masked).split())
    candidates = (literal_masked, literal_masked[:-1]) if literal_masked.endswith(".") else (literal_masked,)
    for candidate in candidates:
        if not _MASTER_SENTENCE_RE.match(candidate):
            continue
        for key, pattern in zip(_KEY_ORDER, _KEY_PATTERNS.values()):
            detail = pattern.match(candidate)
            if detail is None:
                continue
            slots: list[str] = []
            for group in detail.groups():
                if len(group) == 1 and 0xE000 <= ord(group) <= 0xF8FF:
                    slots.append(values[ord(group) - _SENTINEL_BASE])
                else:
                    slots.append(group)
            return SENTENCES[key], slots
    return None


def _fill_template(template: str, values: list[str]) -> str:
    """按顺序把中文模板里的 {} 替换为动态值; 支持 {1} {2} 显式序号。"""
    if re.search(r"\{\d+\}", template):
        def repl(match: re.Match) -> str:
            i = int(match.group(1)) - 1
            return values[i] if 0 <= i < len(values) else match.group(0)
        return re.sub(r"\{(\d+)\}", repl, template)
    for value in values:
        template = template.replace("{}", value, 1)
    return template


def _translate_words(masked: str) -> str:
    """整句未命中时的词/短语级最长匹配翻译。"""
    tokens: list[tuple[int, int, str]] = []
    for match in _WORD_RE.finditer(masked):
        tokens.append((match.start(), match.end(), match.group(0)))

    pieces: list[str] = []
    cursor = 0
    i = 0
    while i < len(tokens):
        start, end, word = tokens[i]
        pieces.append(masked[cursor:start])
        translated = None
        consume = 1
        max_span = min(4, len(tokens) - i)
        # 最长匹配
        for span in range(max_span, 0, -1):
            words = [tokens[i + k][2] for k in range(span)]
            # 短语必须由多个被空白隔开的单词组成
            if span > 1:
                gap_start = tokens[i][1]
                gap_end = tokens[i + 1][0]
                if masked[gap_start:gap_end] != " ":
                    continue
            phrase = " ".join(w.lower() for w in words)
            if phrase in PHRASES:
                translated = PHRASES[phrase]
                consume = span
                break
        pieces.append(translated if translated is not None else word)
        cursor = tokens[i + consume - 1][1]
        i += consume
    pieces.append(masked[cursor:])
    return "".join(pieces)


def _restore(masked: str, values: list[str]) -> str:
    """还原占位符; 被保护内容可能嵌套（如 kv 值里含 IP 占位符）, 循环还原至稳定。"""
    def repl(match: re.Match) -> str:
        index = ord(match.group(0)) - _SENTINEL_BASE
        return values[index]

    result = masked
    for _ in range(8):
        if not _SENTINEL_RE.search(result):
            break
        new_result = _SENTINEL_RE.sub(repl, result)
        if new_result == result:
            break
        result = new_result
    return result


def translate_message(message: str) -> str:
    """翻译一条日志正文。

    Args:
        message: 不含时间戳/源码位置/级别的日志正文, 可以含 Rich markup、变量值等。

    Returns:
        翻译后的中文正文; 不含英文字母或无法识别的内容原样返回。
    """
    if not message or not re.search(r"[A-Za-z]", message):
        return message

    masked, values = _protect(message)
    matched = _match_sentence(masked, values)
    if matched is not None:
        template, slots = matched
        return _restore(_fill_template(template, slots), values)

    translated_masked = _translate_words(masked)
    result = _restore(translated_masked, values)
    # 冠词/系动词等可能映射为空串, 归一多余空白
    return re.sub(r"[ \t]{2,}", " ", result).strip() if result != message else message


# 日志行头: 文件格式
_FILE_LINE_RE = re.compile(
    r"^(?P<head>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3}) \| "
    r"(?P<source>.+?) \|\s+(?P<level>[A-Z]+)\s+\| "
    r"(?P<msg>.*?)(?P<eol>\r?\n)?$"
)
# 日志行头: Flutter/GUI 管道格式  INFO | 12:00:00.000 | message
_FLUTTER_LINE_RE = re.compile(
    r"^(?P<level>[A-Z]+)\s*\|\s*"
    r"(?P<time>\d{2}:\d{2}:\d{2}\.\d{3})\s*\|\s*"
    r"(?P<msg>.*?)(?P<eol>\r?\n)?$"
)


def translate_log_line(line: str) -> str:
    """翻译单行日志, 自动识别两种行头格式; 不识别的行原样返回。"""
    matched = _FILE_LINE_RE.match(line)
    if matched:
        message = translate_message(matched.group("msg"))
        return (
            f"{matched.group('head')} | {matched.group('source')} | "
            f"{matched.group('level')} | {message}{matched.group('eol') or ''}"
        )
    matched = _FLUTTER_LINE_RE.match(line)
    if matched:
        message = translate_message(matched.group("msg"))
        return (
            f"{matched.group('level')} | {matched.group('time')} | "
            f"{message}{matched.group('eol') or ''}"
        )
    return line


def translate_log_text(text: str) -> str:
    """逐行翻译整段日志文本（traceback、分隔线等无行头内容会原样保留）。"""
    if not text:
        return text
    return "".join(translate_log_line(line) for line in text.splitlines(keepends=True))
