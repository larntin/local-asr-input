"""本声（Local ASR Input）：免费开源的本地语音输入工具。
热键录音 -> faster-whisper 本机识别 -> 弹窗编辑（可选 LLM 整理）-> 粘贴回原窗口。

用法：双击 start.bat（后台运行，日志写到 local_asr_input.log），或 python local_asr_input.py（带控制台）
  - 快捷键都在同目录的 config.json 里配置（首次运行自动生成），默认：
      F9             全局：开始录音 / 结束录音；弹窗打开时再按 = 接着说，结果插到光标处
      Enter          弹窗内：上屏（复制到剪贴板 + 粘贴到原窗口，不回车）
      Shift+Enter    弹窗内：换行
      Esc            弹窗内：取消（LLM 优化中按 = 放弃优化）
      Ctrl+L / ✦     弹窗内：用大模型把文字整理成提示词（Ctrl+Z 撤回原文）
      Ctrl+Alt+F9    全局：退出程序
  - 识别结果自动整理标点（﹐﹑ → ，、；挨着中文的英文标点 → 全角）
  - ✦ 默认走阿里百炼（OpenAI 兼容接口），地址和 key 从环境变量读，见 config.json 的 llm 项
  - 所有设置集中在 ⚙ 设置对话框（弹窗右下角 ✦ 左边，或托盘右键「设置」），保存后立即生效
  - 托盘图标颜色表示状态：灰=模型加载中 绿=就绪 红=录音中 橙=识别中 紫=LLM 优化中
    右键菜单：设置 / 重启（重新读取配置）/ 打开日志 / 退出
  - 只允许运行一个实例，重复启动会弹提示
"""

import ctypes
import base64
import hashlib
import io
import json
import logging
import logging.handlers
import math
import os
import queue
import re
import signal
import subprocess
import sys
import threading
import time
import tkinter as tk
import wave
from ctypes import wintypes
from tkinter import ttk

import numpy as np
import pystray
import sounddevice as sd
from faster_whisper import WhisperModel
from PIL import Image, ImageDraw, ImageTk

from i18n import CONFIG_HELP, EN_DEFAULTS, UI_LANGUAGES, current_language, set_ui_language, system_language, t

__version__ = "0.2.0"
FROZEN = getattr(sys, "frozen", False)  # PyInstaller 打包后的 exe
# 配置和日志放在程序旁边：exe 版是 exe 所在目录，源码版是 .py 所在目录
APP_DIR = os.path.dirname(sys.executable if FROZEN else os.path.abspath(__file__))
LOG_FILE = os.path.join(APP_DIR, "local_asr_input.log")
CONFIG_FILE = os.environ.get("LOCAL_ASR_INPUT_CONFIG") or os.path.join(APP_DIR, "config.json")
SAMPLE_RATE = 16000
PASTE_DELAY_MS = 120  # 切回原窗口后等多久再粘贴
UI_FONT = "Microsoft YaHei UI"
COLORS = {
    "border": "#343844", "bg": "#1b1d23", "bar": "#15171c", "fg": "#e9eaee", "muted": "#8a8f9c",
    "llm_bg": "#2b2940", "llm_hover": "#3b3760", "llm_fg": "#c9b8ff",
}
ACCENTS = {"loading": "#8a8f9c", "idle": "#4cc38a", "editing": "#4cc38a", "recording": "#ff5a5f", "transcribing": "#ffb547", "optimizing": "#b18cff"}

# 每天零点换新文件（local_asr_input.log.2026-09-23 这样），只留最近 7 天
handlers = [logging.handlers.TimedRotatingFileHandler(LOG_FILE, when="midnight", backupCount=7, encoding="utf-8")]
if sys.stdout is not None:  # pythonw 下没有控制台
    handlers.append(logging.StreamHandler(sys.stdout))
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S", handlers=handlers)
log = logging.getLogger("asr")
logging.getLogger("faster_whisper").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)  # 每次调 LLM 的请求行太啰嗦
# 后台线程里没被捕获的异常也记到日志
threading.excepthook = lambda a: log.error(f"[线程异常] {a.thread.name}", exc_info=(a.exc_type, a.exc_value, a.exc_traceback))

set_ui_language("auto")  # 读到配置后 main() 会按 ui_language 再设一次

# ---------------- Win32 ----------------
user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
user32.GetForegroundWindow.restype = wintypes.HWND
user32.SetForegroundWindow.argtypes = [wintypes.HWND]
user32.BringWindowToTop.argtypes = [wintypes.HWND]
user32.IsWindow.argtypes = [wintypes.HWND]
user32.IsIconic.argtypes = [wintypes.HWND]
user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.GetWindowThreadProcessId.restype = wintypes.DWORD
user32.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
kernel32.CreateMutexW.restype = wintypes.HANDLE
kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

VK_CONTROL, VK_MENU, VK_V = 0x11, 0x12, 0x56
KEYEVENTF_KEYUP = 0x2
INPUT_KEYBOARD = 1
SW_RESTORE = 9
WM_HOTKEY, WM_QUIT = 0x0312, 0x0012
MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN, MOD_NOREPEAT = 0x1, 0x2, 0x4, 0x8, 0x4000


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class MOUSEINPUT(ctypes.Structure):  # 只为让 union 大小正确
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]


def send_keys(*vks):
    """依次按下 vks，再倒序松开，例如 send_keys(VK_CONTROL, VK_V)。"""
    seq = [(vk, 0) for vk in vks] + [(vk, KEYEVENTF_KEYUP) for vk in reversed(vks)]
    arr = (INPUT * len(seq))(*[INPUT(INPUT_KEYBOARD, _INPUTUNION(ki=KEYBDINPUT(vk, 0, fl, 0, 0))) for vk, fl in seq])
    user32.SendInput(len(seq), arr, ctypes.sizeof(INPUT))


def window_title(hwnd):
    buf = ctypes.create_unicode_buffer(256)
    user32.GetWindowTextW(hwnd, buf, 256)
    return buf.value


def focus_window(hwnd):
    """把 hwnd 切到前台。挂到当前前台线程的输入队列上借用它的前台权限，不行再模拟一次 Alt。"""
    if not hwnd or not user32.IsWindow(hwnd):
        return False
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, SW_RESTORE)
    for attempt in range(2):
        if user32.GetForegroundWindow() == hwnd:
            return True
        cur = kernel32.GetCurrentThreadId()
        fg_tid = user32.GetWindowThreadProcessId(user32.GetForegroundWindow(), None)
        attached = bool(fg_tid) and fg_tid != cur and user32.AttachThreadInput(cur, fg_tid, True)
        try:
            if attempt:
                send_keys(VK_MENU)
            user32.BringWindowToTop(hwnd)
            user32.SetForegroundWindow(hwnd)
        finally:
            if attached:
                user32.AttachThreadInput(cur, fg_tid, False)
    return user32.GetForegroundWindow() == hwnd


def message_box(text):
    user32.MessageBoxW(None, text, t("app_name"), 0x40 | 0x40000)  # 信息图标 + 置顶


def acquire_single_instance():
    """用命名互斥量保证同一份配置只有一个实例；返回的句柄要一直持有，进程退出时系统自动释放。"""
    key = hashlib.md5(os.path.abspath(CONFIG_FILE).lower().encode()).hexdigest()[:12]
    handle = kernel32.CreateMutexW(None, False, f"Local\\local_asr_input_{key}")
    if ctypes.get_last_error() == 183:  # ERROR_ALREADY_EXISTS
        return None
    return handle


def wait_for_process_exit(pid, timeout_ms=10000):
    handle = kernel32.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE
    if handle:
        kernel32.WaitForSingleObject(handle, timeout_ms)
        kernel32.CloseHandle(handle)


# ---------------- 快捷键解析 ----------------
# 修饰键名 -> (RegisterHotKey 用的 MOD_*, Tk 修饰名)
MODIFIERS = {"ctrl": (MOD_CONTROL, "Control"), "alt": (MOD_ALT, "Alt"), "shift": (MOD_SHIFT, "Shift"), "win": (MOD_WIN, None)}
# 按键名 -> (虚拟键码, Tk keysym)
KEYS = {
    "enter": (0x0D, "Return"), "esc": (0x1B, "Escape"), "escape": (0x1B, "Escape"), "space": (0x20, "space"),
    "tab": (0x09, "Tab"), "backspace": (0x08, "BackSpace"), "insert": (0x2D, "Insert"), "delete": (0x2E, "Delete"),
    "home": (0x24, "Home"), "end": (0x23, "End"), "pageup": (0x21, "Prior"), "pagedown": (0x22, "Next"),
    "pause": (0x13, "Pause"), "scrolllock": (0x91, "Scroll_Lock"),
    **{f"f{i}": (0x6F + i, f"F{i}") for i in range(1, 25)},
    **{c.lower(): (ord(c), c.lower()) for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"},
    **{c: (ord(c), c) for c in "0123456789"},
}


def parse_key(spec):
    """"Ctrl+Alt+F9" -> (mods, vk, tk_sequence)；tk_sequence 为 None 表示不能用在弹窗里（含 Win 键）。"""
    parts = [p.strip().lower() for p in str(spec).split("+") if p.strip()]
    if not parts or parts[-1] not in KEYS or any(m not in MODIFIERS for m in parts[:-1]):
        raise ValueError(t("err_key_unknown", spec=repr(spec)))
    mods, tk_mods = 0, []
    for m in parts[:-1]:
        mods |= MODIFIERS[m][0]
        tk_mods.append(MODIFIERS[m][1])
    vk, keysym = KEYS[parts[-1]]
    tk_seq = None if None in tk_mods else "<" + "-".join(tk_mods + ["Key", keysym]) + ">"
    return mods, vk, tk_seq


KEY_DISPLAY = {"enter": "Enter", "esc": "Esc", "space": "Space", "tab": "Tab", "backspace": "Backspace",
               "insert": "Insert", "delete": "Delete", "home": "Home", "end": "End", "pageup": "PageUp",
               "pagedown": "PageDown", "pause": "Pause", "scrolllock": "ScrollLock"}
KEYSYM_TO_NAME = {}
for _name, (_vk, _keysym) in KEYS.items():
    KEYSYM_TO_NAME.setdefault(_keysym.lower(), _name)  # Escape 优先对应 esc


def spec_from_event(e):
    """Tk 按键事件 -> "Ctrl+Alt+F9"；只按了修饰键或不支持的键返回 None。"""
    name = KEYSYM_TO_NAME.get(e.keysym.lower())
    if name is None:
        return None
    mods = [m for m, bit in (("Ctrl", 0x4), ("Alt", 0x20000), ("Shift", 0x1)) if e.state & bit]
    return "+".join(mods + [KEY_DISPLAY.get(name) or name.upper()])


# ---------------- 标点整理 ----------------
SMALL_FORM_PUNCT = str.maketrans("﹐﹑﹔﹕﹖﹗", "，、；：？！")  # Whisper 常吐出的小号标点
ASCII_TO_FULL = {",": "，", "?": "？", "!": "！", ":": "：", ";": "；"}
CJK = r"\u4e00-\u9fff\u3400-\u4dbf"


def normalize_punctuation(text):
    """小号标点转常规；挨着中文的英文标点转全角；中文后的英文句号转「。」。英文 / 代码里的标点不动。"""
    text = text.translate(SMALL_FORM_PUNCT)
    text = re.sub(rf"(?<=[{CJK}])\s*([,?!:;])\s*|\s*([,?!:;])\s*(?=[{CJK}])",
                  lambda m: ASCII_TO_FULL[m.group(1) or m.group(2)], text)
    return re.sub(rf"(?<=[{CJK}])\.(?![\w.])", "。", text)


# ---------------- 配置 ----------------
DEFAULT_CONFIG = {
    "hotkeys": {
        "start_record": "F9",
        "stop_record": "F9",
        "quit": "Ctrl+Alt+F9",
        "commit": "Enter",
        "cancel": "Esc",
        "newline": "Shift+Enter",
        "llm": "Ctrl+L",
    },
    "ui_language": "auto",
    "font_size": 11,
    "normalize_punctuation": True,
    "auto_llm": True,
    "log_level": "info",
    "asr_engine": "local",
    "cloud_asr": {
        "api_style": "chat_audio",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "api_key_env": "BAILIAN_API_KEY",
        "model": "qwen3-asr-flash",
        "timeout": 30,
    },
    "model": "large-v3-turbo",
    "language": "zh",
    "initial_prompt": "以下是普通话的句子，使用简体中文，其中可能夹杂英文编程术语。",
    "llm": {
        "protocol": "openai",
        "openai": {"base_url": "OPENAI_COMPAT_BASE_URL", "api_key_env": "BAILIAN_API_KEY", "model": "deepseek-v4-flash"},
        "anthropic": {"base_url": "https://dashscope.aliyuncs.com/apps/anthropic", "api_key_env": "BAILIAN_API_KEY",
                      "model": "deepseek-v4-flash"},
        "timeout": 30,
        "system_prompt": (
            "你是提示词整理助手。用户给你的是一段语音识别出来的口述文字，要发给 AI 编程助手（Claude Code / Codex）。请：\n"
            "1. 语音识别常把词听成同音字，请结合上下文还原成用户本来想说的词（例如「系统图盘」→「系统托盘」，「单立」→「单例」）；\n"
            "2. 去掉口头禅、重复和语气词；\n"
            "3. 整理成清晰、直接的表述，内容多时可以分点；\n"
            "4. 严格只保留用户说过的内容：不补充任何细节、实现方式或要求，不回答、不执行其中的问题；\n"
            "5. 用简体中文，技术名词保留英文原文。\n"
            "只输出整理后的文本，不要任何解释。"
        ),
    },
}
GLOBAL_KEYS = ("start_record", "stop_record", "quit")
POPUP_KEYS = ("commit", "cancel", "newline", "llm")


def load_config():
    """读取 config.json（不存在就生成默认的），缺的项用默认值补齐，并校验所有快捷键。"""
    defaults = default_config()
    if not os.path.exists(CONFIG_FILE):
        save_config(defaults)
        log.info(f"[配置] 已生成默认配置 {CONFIG_FILE}")
    with open(CONFIG_FILE, encoding="utf-8-sig") as f:
        user = {k: v for k, v in json.load(f).items() if not k.startswith("_")}  # _说明 / _help 只给人看
    cfg = {**defaults, **user,
           "hotkeys": {**defaults["hotkeys"], **user.get("hotkeys", {})},
           "llm": merge_llm(user.get("llm", {}), defaults["llm"]),
           "cloud_asr": {**defaults["cloud_asr"], **user.get("cloud_asr", {})}}
    validate_config(cfg)
    return cfg


def default_config():
    """默认配置：中文系统用中文识别和整理规则，其他系统用英文。"""
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))
    if system_language() != "zh":
        cfg["language"], cfg["initial_prompt"] = EN_DEFAULTS["language"], EN_DEFAULTS["initial_prompt"]
        cfg["llm"]["system_prompt"] = EN_DEFAULTS["system_prompt"]
    return cfg


def merge_llm(user_llm, d=None):
    """llm 配置补齐默认值；旧版平铺的 base_url_env / api_key_env / model 迁移到 openai 那一套里。"""
    d, u = d or DEFAULT_CONFIG["llm"], dict(user_llm)
    legacy = {}
    if "base_url_env" in u:
        legacy["base_url"] = u.pop("base_url_env")
    for k in ("api_key_env", "model"):
        if k in u:
            legacy[k] = u.pop(k)
    merged = {**d, **u}
    for proto in LLM_PROTOCOLS:
        merged[proto] = {**d[proto], **(legacy if proto == "openai" else {}), **u.get(proto, {})}
    return merged


def validate_config(cfg):
    """校验快捷键和数值项，有问题抛 ValueError（信息直接给用户看）。"""
    parsed = {}
    for name in GLOBAL_KEYS + POPUP_KEYS:
        try:
            mods, vk, tk_seq = parse_key(cfg["hotkeys"][name])
        except ValueError as e:
            raise ValueError(t("err_field", name=f"hotkeys.{name}", err=e)) from None
        if name in POPUP_KEYS and tk_seq is None:
            raise ValueError(t("err_win_global", name=f"hotkeys.{name}"))
        parsed[name] = (mods, vk)
    # 同一组里不能撞键（开始 / 结束录音允许相同 = 来回切换）
    for group in (("start_record", "quit"), ("stop_record", "quit"), POPUP_KEYS):
        seen = {}
        for name in group:
            if parsed[name] in seen:
                raise ValueError(t("err_key_conflict", a=f"hotkeys.{name}", b=f"hotkeys.{seen[parsed[name]]}"))
            seen[parsed[name]] = name
    if not (isinstance(cfg["font_size"], int) and 8 <= cfg["font_size"] <= 40):
        raise ValueError(t("err_font"))
    llm = cfg["llm"]
    if llm["protocol"] not in LLM_PROTOCOLS:
        raise ValueError(t("err_protocol", opts=" / ".join(LLM_PROTOCOLS)))
    if not llm[llm["protocol"]]["model"].strip():
        raise ValueError(t("err_llm_model"))
    if cfg["log_level"] not in LOG_LEVELS:
        raise ValueError(t("err_log_level", opts=" / ".join(LOG_LEVELS)))
    if cfg["ui_language"] not in UI_LANGUAGES:
        raise ValueError(t("err_ui_language", opts=" / ".join(UI_LANGUAGES)))
    if not (isinstance(cfg["llm"]["timeout"], int) and 1 <= cfg["llm"]["timeout"] <= 300):
        raise ValueError(t("err_timeout"))
    if cfg["asr_engine"] not in ASR_ENGINES:
        raise ValueError(t("err_asr_engine", opts=" / ".join(ASR_ENGINES)))
    ca = cfg["cloud_asr"]
    if ca["api_style"] not in ASR_API_STYLES:
        raise ValueError(t("err_api_style", opts=" / ".join(ASR_API_STYLES)))
    if cfg["asr_engine"] == "cloud" and not ca["model"].strip():
        raise ValueError(t("err_cloud_model"))
    if not (isinstance(ca["timeout"], int) and 1 <= ca["timeout"] <= 300):
        raise ValueError(t("err_cloud_timeout"))


LOG_LEVELS = {"info": logging.INFO, "error": logging.WARNING}  # error 档也保留警告，出问题时更好查
AUTO_LLM_MIN_CHARS = 6  # 自动优化时，少于这么多字（如「好的」「继续」）直接保留原文


LLM_PROTOCOLS = {"openai": "OpenAI", "anthropic": "Anthropic"}


def resolve_base_url(value):
    """接口地址可以直接写 URL，也可以写环境变量名（取它的值）。"""
    v = (value or "").strip()
    return v if v.lower().startswith(("http://", "https://")) else os.environ.get(v, "").strip()


def llm_configured(llm):
    """当前协议的地址和 key 都能取到。没配置时自动优化直接跳过，不打扰、也不会把文字发出去。"""
    prof = llm[llm["protocol"]]
    return bool(resolve_base_url(prof["base_url"]) and os.environ.get(prof["api_key_env"].strip(), "").strip())


def describe_llm(llm):
    """「Anthropic · deepseek-v4-flash」这样的简短描述，给界面和日志用。"""
    return f"{LLM_PROTOCOLS[llm['protocol']]} · {llm[llm['protocol']]['model']}"


ASR_ENGINES = ("local", "cloud")
ASR_API_STYLES = ("chat_audio", "transcriptions")


def wav_bytes(audio):
    """16k 单声道 float32 -> WAV 文件内容（只在内存里，不落盘）。"""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes((np.clip(audio, -1, 1) * 32767).astype(np.int16).tobytes())
    return buf.getvalue()


def cloud_transcribe(c, audio, language):
    """云端识别。api_style：
    chat_audio      —— POST {base}/chat/completions，消息里带 input_audio（阿里百炼 qwen3-asr-flash 等）
    transcriptions  —— POST {base}/audio/transcriptions，multipart 上传文件（OpenAI whisper-1、Groq 等）
    """
    import httpx
    base_url = resolve_base_url(c["base_url"])
    api_key = os.environ.get(c["api_key_env"].strip(), "").strip()
    if not base_url:
        raise RuntimeError(t("err_url", url=repr(c["base_url"])))
    if not api_key:
        raise RuntimeError(t("err_key_env", env=c["api_key_env"]))
    url, data = base_url.rstrip("/"), wav_bytes(audio)
    headers = {"Authorization": f"Bearer {api_key}"}
    if c["api_style"] == "transcriptions":
        form = {"model": c["model"], **({"language": language} if language else {})}
        r = httpx.post(url + "/audio/transcriptions", headers=headers, timeout=c["timeout"],
                       files={"file": ("audio.wav", data, "audio/wav")}, data=form)
        if r.status_code >= 400:
            raise RuntimeError(f"HTTP {r.status_code}：{r.text[:300]}")
        return (r.json().get("text") or "").strip()
    audio_part = {"type": "input_audio", "input_audio": {"data": "data:audio/wav;base64," + base64.b64encode(data).decode()}}
    body = {"model": c["model"], "stream": False, "messages": [{"role": "user", "content": [audio_part]}]}
    if "aliyuncs.com" in base_url:  # 百炼专有参数：指定语言、数字转成阿拉伯数字
        body["asr_options"] = {"enable_itn": True, **({"language": language} if language else {})}
    r = httpx.post(url + "/chat/completions", headers=headers, timeout=c["timeout"], json=body)
    if r.status_code >= 400:
        raise RuntimeError(f"HTTP {r.status_code}：{r.text[:300]}")
    content = r.json()["choices"][0]["message"]["content"]
    if isinstance(content, list):
        content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
    return (content or "").strip()


def llm_complete(llm, system, text, max_tokens=2048):
    """按 llm["protocol"] 走 OpenAI 或 Anthropic 协议，返回回复文字；出错抛异常。"""
    proto = llm["protocol"]
    prof = llm[proto]
    base_url = resolve_base_url(prof["base_url"])
    api_key = os.environ.get(prof["api_key_env"].strip(), "").strip()
    if not base_url:
        raise RuntimeError(t("err_url", url=repr(prof["base_url"])))
    if not api_key:
        raise RuntimeError(t("err_key_env", env=prof["api_key_env"]))
    if proto == "openai":
        from openai import OpenAI  # 用到时才导入，不拖慢启动
        client = OpenAI(base_url=base_url, api_key=api_key, timeout=llm["timeout"])
        # enable_thinking 是阿里百炼的专有参数（关掉 qwen3 等模型的思考，快很多）；别家（如 OpenAI 官方）遇到不认识的参数会报错
        extra = {"enable_thinking": False} if "aliyuncs.com" in base_url else {}
        resp = client.chat.completions.create(
            model=prof["model"], temperature=0.2, extra_body=extra,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": text}],
        )
        return (resp.choices[0].message.content or "").strip()
    # Anthropic Messages API：地址写到 /v1 为止或写到根都行
    import httpx
    url = base_url.rstrip("/")
    url += "/messages" if url.endswith("/v1") else "/v1/messages"
    r = httpx.post(url, timeout=llm["timeout"], headers={"x-api-key": api_key, "anthropic-version": "2023-06-01"},
                   json={"model": prof["model"], "max_tokens": max_tokens, "temperature": 0.2, "system": system,
                         "thinking": {"type": "disabled"},  # 不关的话模型先「思考」，又慢又可能把额度用光、正文为空
                         "messages": [{"role": "user", "content": text}]})
    if r.status_code >= 400:
        raise RuntimeError(f"HTTP {r.status_code}：{r.text[:300]}")
    return "".join(b.get("text", "") for b in r.json().get("content", []) if b.get("type") == "text").strip()


def apply_log_level(level):
    logging.getLogger().setLevel(LOG_LEVELS[level])


def save_config(cfg):
    order = ["hotkeys", "ui_language", "font_size", "normalize_punctuation", "auto_llm", "log_level",
             "asr_engine", "model", "language", "initial_prompt", "cloud_asr", "llm"]
    lang = current_language()
    data = {"_说明" if lang == "zh" else "_help": CONFIG_HELP[lang]}
    data |= {k: cfg[k] for k in order if k in cfg} | {k: v for k, v in cfg.items() if k not in order and not k.startswith("_")}
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def hotkey_loop(events, hotkeys, result):
    """用 RegisterHotKey 注册系统热键（不依赖键盘钩子，不会失效），收到后投递到事件队列。
    注册结果放进 result：None = 成功，否则是注册失败的那个键。收到 WM_QUIT 后注销热键、线程结束。"""
    start, stop = parse_key(hotkeys["start_record"]), parse_key(hotkeys["stop_record"])
    if start[:2] == stop[:2]:
        regs = [("toggle", hotkeys["start_record"])]
    else:
        regs = [("start", hotkeys["start_record"]), ("stop", hotkeys["stop_record"])]
    regs.append(("quit", hotkeys["quit"]))
    registered = []
    try:
        for hid, (action, spec) in enumerate(regs, 1):
            mods, vk, _ = parse_key(spec)
            if not user32.RegisterHotKey(None, hid, mods | MOD_NOREPEAT, vk):
                result.put(spec)
                return
            registered.append(hid)
        log.info("[热键] 已注册：" + "，".join(f"{a}={s}" for a, s in regs))
        result.put(None)
        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == WM_HOTKEY:
                action = regs[msg.wParam - 1][0]
                events.put(("hotkey", action))
    finally:
        for hid in registered:  # 热键只能由注册它的线程注销
            user32.UnregisterHotKey(None, hid)


# ---------------- 托盘图标 ----------------
def make_icon(color):
    """画一个简单的麦克风图标。"""
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((22, 6, 42, 40), radius=10, fill=color)
    d.arc((14, 20, 50, 50), start=0, end=180, fill=color, width=4)
    d.line((32, 50, 32, 58), fill=color, width=4)
    d.line((22, 58, 42, 58), fill=color, width=4)
    return img


def make_gear(size, color):
    """画 ⚙ 设置图标：先画 4 倍大再缩小，边缘平滑。"""
    s = size * 4
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    c, teeth = s / 2, 8
    outer, inner, hole = s * 0.48, s * 0.34, s * 0.14
    pts = []
    for i in range(teeth * 4):  # 每个齿 4 个点：齿根-齿顶-齿顶-齿根
        a = 2 * math.pi * (i - 0.5) / (teeth * 4)
        r = outer if i % 4 in (1, 2) else inner
        pts.append((c + r * math.cos(a), c + r * math.sin(a)))
    d.polygon(pts, fill=color)
    d.ellipse((c - hole, c - hole, c + hole, c + hole), fill=(0, 0, 0, 0))
    return img.resize((size, size), Image.LANCZOS)


TRAY_COLORS = {"loading": "#9e9e9e", "idle": "#2e7d32", "editing": "#2e7d32", "recording": "#d32f2f", "transcribing": "#ef6c00", "optimizing": "#7e57c2"}


# ---------------- 录音 / 识别 ----------------
class Recorder:
    def __init__(self):
        self.stream = None
        self.chunks = []
        self.rate = SAMPLE_RATE
        self.level = 0.0  # 最近一块音频的音量（RMS），界面用来画音量条

    def start(self):
        self.chunks = []
        self.level = 0.0

        def callback(indata, frames, time_info, status):
            self.chunks.append(indata[:, 0].copy())
            self.level = float(np.sqrt(np.mean(indata[:, 0] ** 2)))

        try:
            self.stream = sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="float32", callback=callback)
            self.rate = SAMPLE_RATE
        except Exception:
            # 设备不支持 16k 就用默认采样率录，之后再重采样
            self.rate = int(sd.query_devices(kind="input")["default_samplerate"])
            self.stream = sd.InputStream(samplerate=self.rate, channels=1, dtype="float32", callback=callback)
        self.stream.start()

    def stop(self):
        if self.stream is None:
            return np.zeros(0, dtype=np.float32)
        self.stream.stop()
        self.stream.close()
        self.stream = None
        audio = np.concatenate(self.chunks) if self.chunks else np.zeros(0, dtype=np.float32)
        if self.rate != SAMPLE_RATE and len(audio):
            n = int(len(audio) * SAMPLE_RATE / self.rate)
            audio = np.interp(np.linspace(0, len(audio) - 1, n), np.arange(len(audio)), audio).astype(np.float32)
        return audio


def load_model(name, language):
    warmup = np.zeros(SAMPLE_RATE, dtype=np.float32)
    for device, compute_type in (("cuda", "float16"), ("cpu", "int8")):
        for local_only in (True, False):
            try:
                model = WhisperModel(name, device=device, compute_type=compute_type, local_files_only=local_only)
                list(model.transcribe(warmup, language=language)[0])  # CUDA 库缺失会在这里才报错
                return model, device
            except Exception as e:
                log.warning(f"[模型] {device}/{'本地' if local_only else '下载'} 失败：{e}")
    raise RuntimeError("模型加载失败")


# ---------------- 设置对话框 ----------------
class SettingsDialog:
    """⚙ 所有配置集中在这里；保存时校验、立即生效（不重启），再写 config.json。"""

    HOTKEY_NAMES = ("start_record", "stop_record", "quit", "commit", "cancel", "newline", "llm")
    WHISPER_MODELS = ["large-v3-turbo", "medium", "small", "large-v3"]
    LANGUAGES = ["zh", "en", "ja", "ko"]
    LLM_MODELS = ["deepseek-v4-flash", "qwen3-max", "qwen-plus", "qwen-flash"]
    CLOUD_ASR_MODELS = ["qwen3-asr-flash", "whisper-1", "whisper-large-v3-turbo", "gpt-4o-mini-transcribe"]


    def __init__(self, app):
        self.app = app
        self.capturing = None  # 正在录入快捷键的输入框
        cfg, c = app.cfg, COLORS
        self.scale = scale = app.root.winfo_fpixels("1i") / 96
        px = lambda v: round(v * scale)
        zh = current_language() == "zh"
        self.label_width = px(110 if zh else 160)  # 英文标签更长
        width = px(600 if zh else 660)
        self.log_level_names = {"info": t("log_info"), "error": t("log_error")}
        self.ui_lang_names = {k: (t("lang_auto") if v is None else v) for k, v in UI_LANGUAGES.items()}

        w = self.win = tk.Toplevel(app.root)
        w.withdraw()
        w.title(t("settings_title", app=t("app_name")))
        w.configure(bg=c["bg"])
        w.attributes("-topmost", True)
        w.resizable(False, False)
        w.protocol("WM_DELETE_WINDOW", self.close)
        w.bind("<Escape>", lambda e: self.close())
        w.report_callback_exception = app.root.report_callback_exception

        style = ttk.Style(w)
        style.theme_use("clam")
        style.configure("Dark.TCombobox", fieldbackground=c["bar"], background=c["bar"], foreground=c["fg"],
                        arrowcolor=c["muted"], bordercolor=c["border"], lightcolor=c["bar"], darkcolor=c["bar"],
                        selectbackground=c["bar"], selectforeground=c["fg"], padding=px(4))
        style.map("Dark.TCombobox", fieldbackground=[("readonly", c["bar"])], foreground=[("readonly", c["fg"])])
        w.option_add("*TCombobox*Listbox.background", c["bar"])
        w.option_add("*TCombobox*Listbox.foreground", c["fg"])
        w.option_add("*TCombobox*Listbox.selectBackground", "#3d4455")
        w.option_add("*TCombobox*Listbox.font", (UI_FONT, 10))

        self.entry_style = dict(bg=c["bar"], fg=c["fg"], insertbackground=c["fg"], relief="flat", font=(UI_FONT, 10),
                                highlightthickness=1, highlightbackground=c["border"], highlightcolor=ACCENTS["optimizing"])
        # 三个页签：✦ LLM / 快捷键 / 常规（显示 + 识别）。自己画页签栏：ttk.Notebook 选中时会放大上移，看着跳
        self.tab_bar = tk.Frame(w, bg=c["bar"], padx=px(14))
        self.tab_bar.pack(fill="x")
        self.content = tk.Frame(w, bg=c["bg"])
        self.content.pack(fill="both", expand=True)
        self.tab_list = []  # [(标题, 内容 Frame, 文字 Label, 下划线 Frame)]

        llm = cfg["llm"]
        self.tab_llm = self._tab(t("tab_llm"))
        saved_url = resolve_base_url(llm[llm["protocol"]]["base_url"]) or t("addr_invalid")
        cur = tk.Label(self.body, text=t("current", desc=describe_llm(llm), url=saved_url), bg=c["bg"], fg=c["llm_fg"],
                       font=(UI_FONT, 9), anchor="w", justify="left")
        cur.grid(row=self.row, column=0, columnspan=2, sticky="w", pady=(0, px(10)))
        self.row += 1

        # 协议切换：两套配置各自保存，切换只是换显示哪一套
        self.proto_var = tk.StringVar(value=llm["protocol"])
        seg = tk.Frame(self.body, bg=c["border"], padx=1, pady=1)
        self.proto_btns = {}
        for proto, name in LLM_PROTOCOLS.items():
            b = tk.Label(seg, text=name, font=(UI_FONT, 10), padx=px(16), pady=px(3), cursor="hand2")
            b.pack(side="left")
            b.bind("<Button-1>", lambda e, proto=proto: self._select_proto(proto))
            self.proto_btns[proto] = b
        self._row(t("protocol"), seg, sticky="w")

        self.proto_vars, self.proto_frames = {}, {}
        outer_body, outer_row = self.body, self.row
        for proto in LLM_PROTOCOLS:
            f = tk.Frame(outer_body, bg=c["bg"])
            f.columnconfigure(0, minsize=self.label_width)
            f.columnconfigure(1, weight=1)
            f.grid(row=outer_row, column=0, columnspan=2, sticky="we")
            self.body, self.row = f, 0
            v = {k: tk.StringVar(value=llm[proto][k]) for k in ("model", "base_url", "api_key_env")}
            self._row(t("model"), self._combo(v["model"], self.LLM_MODELS))
            self._row(t("api_url"), self._url_entry(v["base_url"]))
            self._row(t("api_key_env"), self._env_entry(v["api_key_env"]))
            for var in v.values():  # 改了配置，上次的测试结果就不作数了
                var.trace_add("write", lambda *_: hasattr(self, "test_label") and self.test_label.config(text=""))
            self.proto_vars[proto], self.proto_frames[proto] = v, f
        self.body, self.row = outer_body, outer_row + 1

        test = tk.Frame(self.body, bg=c["bg"])
        self._button(test, t("test_conn"), self._test_llm).pack(side="left")
        self.test_label = tk.Label(test, text="", bg=c["bg"], fg=c["muted"], font=(UI_FONT, 9), anchor="w",
                                   justify="left", wraplength=px(330))
        self.test_label.pack(side="left", padx=(px(10), 0))
        self._row("", test, sticky="w")
        self._select_proto(llm["protocol"])
        self.timeout_var = tk.StringVar(value=str(llm["timeout"]))
        self._row(t("timeout"), tk.Spinbox(self.body, from_=1, to=300, textvariable=self.timeout_var, width=6,
                                        buttonbackground=c["bar"], **self.entry_style), sticky="w")
        self.system_text = tk.Text(self.body, height=7, width=1, wrap="char", undo=True, padx=px(6), pady=px(4),
                                   **self.entry_style)
        self.system_text.insert("1.0", llm["system_prompt"])
        self._row(t("system_prompt"), self.system_text, sticky="nsew", top=True)
        self.body.rowconfigure(self.row - 1, weight=1)  # 对话框按最高的页签定高，多出来的高度都给整理规则框

        self.tab_keys = self._tab(t("tab_keys"))
        self._hint(t("hint_keys"))
        self.hotkey_vars, self.entry_vars = {}, {}
        for name in self.HOTKEY_NAMES:
            var = tk.StringVar(value=cfg["hotkeys"][name])
            e = tk.Entry(self.body, textvariable=var, state="readonly", readonlybackground=c["bar"], cursor="hand2",
                         **{k: v for k, v in self.entry_style.items() if k != "bg"})
            e.bind("<FocusIn>", lambda ev, e=e: self._capture_start(e))
            e.bind("<FocusOut>", lambda ev: self._capture_stop())
            e.bind("<KeyPress>", lambda ev, var=var: self._capture_key(ev, var))
            e.bind("<Button-1>", lambda ev, e=e: e.focus_set())
            self._row(t("hk_" + name), e)
            self.hotkey_vars[name] = self.entry_vars[e] = var

        self.tab_general = self._tab(t("tab_general"))
        self._section(t("sec_display"))
        self.ui_lang_var = tk.StringVar(value=self.ui_lang_names[cfg["ui_language"]])
        cb = self._combo(self.ui_lang_var, list(self.ui_lang_names.values()), width=14)
        cb.configure(state="readonly")
        self._row(t("ui_lang"), cb, sticky="w")
        self.font_var = tk.StringVar(value=str(cfg["font_size"]))
        self._row(t("font_size"), tk.Spinbox(self.body, from_=8, to=40, textvariable=self.font_var, width=6,
                                        buttonbackground=c["bar"], **self.entry_style), sticky="w")
        self._section(t("sec_asr"))
        self.engine_names = {"local": t("engine_local"), "cloud": t("engine_cloud")}
        self.engine_var = tk.StringVar(value=self.engine_names[cfg["asr_engine"]])
        cb = self._combo(self.engine_var, list(self.engine_names.values()), width=22)
        cb.configure(state="readonly")
        cb.bind("<<ComboboxSelected>>", lambda e: self._select_engine(self._engine()))
        self._row(t("asr_engine"), cb, sticky="w")
        # 本机 / 云端各一组，放在同一行位置，只显示选中的那组
        outer_body, outer_row = self.body, self.row
        self.engine_frames = {}
        for engine in ASR_ENGINES:
            f = tk.Frame(outer_body, bg=c["bg"])
            f.columnconfigure(0, minsize=self.label_width)
            f.columnconfigure(1, weight=1)
            f.grid(row=outer_row, column=0, columnspan=2, sticky="we")
            self.body, self.row = f, 0
            self.engine_frames[engine] = f
            if engine == "local":
                self.model_var = tk.StringVar(value=cfg["model"])
                self._row(t("whisper_model"), self._combo(self.model_var, self.WHISPER_MODELS))
                self.prompt_var = tk.StringVar(value=cfg["initial_prompt"])
                self._row(t("asr_prompt"), tk.Entry(self.body, textvariable=self.prompt_var, **self.entry_style))
            else:
                ca = cfg["cloud_asr"]
                self._hint(t("hint_cloud"))
                self.style_names = {"chat_audio": t("style_chat_audio"), "transcriptions": t("style_transcriptions")}
                self.style_var = tk.StringVar(value=self.style_names[ca["api_style"]])
                scb = self._combo(self.style_var, list(self.style_names.values()))
                scb.configure(state="readonly")
                self._row(t("api_style"), scb)
                self.cloud_vars = {k: tk.StringVar(value=ca[k]) for k in ("model", "base_url", "api_key_env")}
                self._row(t("cloud_model"), self._combo(self.cloud_vars["model"], self.CLOUD_ASR_MODELS))
                self._row(t("api_url"), self._url_entry(self.cloud_vars["base_url"]))
                self._row(t("api_key_env"), self._env_entry(self.cloud_vars["api_key_env"]))
                test = tk.Frame(self.body, bg=c["bg"])
                self._button(test, t("test_conn"), self._test_asr).pack(side="left")
                self.asr_test_label = tk.Label(test, text="", bg=c["bg"], fg=c["muted"], font=(UI_FONT, 9), anchor="w",
                                               justify="left", wraplength=px(330))
                self.asr_test_label.pack(side="left", padx=(px(10), 0))
                self._row("", test, sticky="w")
                for var in [self.style_var, *self.cloud_vars.values()]:
                    var.trace_add("write", lambda *_: self.asr_test_label.config(text=""))
        self.body, self.row = outer_body, outer_row + 1
        self.lang_var = tk.StringVar(value=cfg["language"])
        self._row(t("asr_lang"), self._combo(self.lang_var, self.LANGUAGES, width=8), sticky="w")
        self.punct_var = tk.BooleanVar(value=cfg["normalize_punctuation"])
        self._row("", self._check(t("chk_punct"), self.punct_var))
        self.auto_llm_var = tk.BooleanVar(value=cfg["auto_llm"])
        self._row("", self._check(t("chk_auto_llm"), self.auto_llm_var))
        self._section(t("sec_log"), t("hint_log"))
        self.log_level_var = tk.StringVar(value=self.log_level_names[cfg["log_level"]])
        cb = self._combo(self.log_level_var, list(self.log_level_names.values()))
        cb.configure(state="readonly")
        self._row(t("log_level"), cb)

        foot = tk.Frame(w, bg=c["bar"], padx=px(22), pady=px(10))
        foot.pack(fill="x")
        self.error = tk.Label(foot, text="", bg=c["bar"], fg=ACCENTS["recording"], font=(UI_FONT, 10),
                              anchor="w", justify="left", wraplength=px(330))
        self.error.pack(side="left", fill="x", expand=True)
        self._button(foot, t("save"), self.save, primary=True).pack(side="right")
        self._button(foot, t("cancel"), self.close).pack(side="right", padx=px(8))

        self._select_engine("cloud")
        w.update_idletasks()
        self.content.config(width=width, height=max(f.winfo_reqheight() for _, f, _, _ in self.tab_list))
        self._select_engine(cfg["asr_engine"])
        self.content.pack_propagate(False)
        self.select_tab(self.tab_list[0][1])
        w.update_idletasks()
        ww, wh = width, w.winfo_reqheight()
        w.geometry(f"{ww}x{wh}+{(w.winfo_screenwidth() - ww) // 2}+{max(0, (w.winfo_screenheight() - wh) // 2)}")
        w.deiconify()
        try:  # Win11 深色标题栏
            hwnd = wintypes.HWND(int(w.wm_frame(), 16))
            dark = ctypes.c_int(1)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(dark), ctypes.sizeof(dark))
        except Exception:
            pass
        self.focus()

    # ---------- 布局小工具 ----------
    def _tab(self, title):
        """新建一个页签，之后的 _section / _row 都加到这个页签里。"""
        px = lambda v: round(v * self.scale)
        c = COLORS
        f = tk.Frame(self.content, bg=c["bg"], padx=px(22), pady=px(16))
        f.columnconfigure(0, minsize=self.label_width)  # 各页签标签列同宽，切换时输入框不左右错位
        f.columnconfigure(1, weight=1)
        item = tk.Frame(self.tab_bar, bg=c["bar"], cursor="hand2")
        item.pack(side="left", padx=(0, px(4)), pady=(px(8), 0))
        label = tk.Label(item, text=title, bg=c["bar"], fg=c["muted"], font=(UI_FONT, 10), padx=px(14), pady=px(6))
        label.pack()
        line = tk.Frame(item, bg=c["bar"], height=px(2))  # 选中时的下划线
        line.pack(fill="x")
        for widget in (item, label, line):
            widget.bind("<Button-1>", lambda e, f=f: self.select_tab(f))
        self.tab_list.append((title, f, label, line))
        self.body, self.row = f, 0
        return f

    def select_tab(self, frame):
        c = COLORS
        for _, f, label, line in self.tab_list:
            on = f is frame
            label.config(fg=c["llm_fg"] if on else c["muted"])
            line.config(bg=c["llm_fg"] if on else c["bar"])
            if on:
                f.pack(fill="both", expand=True)
            else:
                f.pack_forget()

    def current_tab(self):
        return next(title for title, f, _, _ in self.tab_list if f.winfo_manager())

    def _hint(self, text):
        px = lambda v: round(v * self.scale)
        tk.Label(self.body, text=text, bg=COLORS["bg"], fg=COLORS["muted"], font=(UI_FONT, 9), anchor="w")             .grid(row=self.row, column=0, columnspan=2, sticky="w", pady=(0, px(10)))
        self.row += 1

    def _section(self, title, hint=""):
        c, px = COLORS, lambda v: round(v * self.scale)
        f = tk.Frame(self.body, bg=c["bg"])
        f.grid(row=self.row, column=0, columnspan=2, sticky="we", pady=(px(14) if self.row else 0, px(6)))
        tk.Label(f, text=title, bg=c["bg"], fg=c["llm_fg"], font=(UI_FONT, 11, "bold")).pack(side="left")
        if hint:
            tk.Label(f, text=hint, bg=c["bg"], fg=c["muted"], font=(UI_FONT, 9)).pack(side="left", padx=px(10))
        self.row += 1

    def _row(self, label, widget, sticky="we", top=False):
        c, px = COLORS, lambda v: round(v * self.scale)
        tk.Label(self.body, text=label, bg=c["bg"], fg=c["muted"], font=(UI_FONT, 10), anchor="ne" if top else "e") \
            .grid(row=self.row, column=0, sticky="ne" if top else "e", padx=(0, px(12)), pady=px(3))
        widget.grid(row=self.row, column=1, sticky=sticky, pady=px(3), ipady=px(2) if isinstance(widget, tk.Entry) else 0)
        self.row += 1

    def _check(self, text, var):
        c = COLORS
        return tk.Checkbutton(self.body, text=text, variable=var, bg=c["bg"], fg=c["fg"], selectcolor=c["bar"],
                              activebackground=c["bg"], activeforeground=c["fg"], font=(UI_FONT, 10), anchor="w")

    def _combo(self, var, values, width=None):
        cb = ttk.Combobox(self.body, textvariable=var, values=values, style="Dark.TCombobox", font=(UI_FONT, 10))
        if width:
            cb.configure(width=width)
        return cb

    def _select_proto(self, proto):
        c = COLORS
        self.proto_var.set(proto)
        for p, b in self.proto_btns.items():
            b.config(bg=c["llm_bg"] if p == proto else c["bar"], fg=c["llm_fg"] if p == proto else c["muted"])
        for p, f in self.proto_frames.items():
            f.grid() if p == proto else f.grid_remove()
        if hasattr(self, "test_label"):
            self.test_label.config(text="")

    def _engine(self):
        return {v: k for k, v in self.engine_names.items()}[self.engine_var.get()]

    def _select_engine(self, engine):
        for e, f in self.engine_frames.items():
            f.grid() if e == engine else f.grid_remove()

    def _collect_cloud_asr(self):
        ca = dict(self.app.cfg["cloud_asr"])
        ca.update({k: v.get().strip() for k, v in self.cloud_vars.items()})
        ca["api_style"] = {v: k for k, v in self.style_names.items()}[self.style_var.get()]
        return ca

    def _test_asr(self):
        """用当前填的云端配置识别一段 1 秒的静音，看接口通不通。"""
        ca = self._collect_cloud_asr()
        self.asr_test_label.config(text=t("testing", desc=ca["model"]), fg=COLORS["muted"])
        box = {}

        def work():
            t0 = time.time()
            try:
                reply = cloud_transcribe(ca, np.zeros(SAMPLE_RATE, dtype=np.float32), self.lang_var.get().strip())
                box["ok"] = t("test_ok", sec=time.time() - t0, reply=repr(reply[:20]))
            except Exception as e:
                box["err"] = f"✗ {str(e)[:160]}"

        def poll():
            if not self.alive():
                return
            if box:
                ok = "ok" in box
                self.asr_test_label.config(text=box.get("ok") or box.get("err"), fg=ACCENTS["idle"] if ok else ACCENTS["recording"])
                log.info(f"[设置] 测试云端识别 {ca['model']}：{box.get('ok') or box.get('err')}")
            else:
                self.win.after(100, poll)
        threading.Thread(target=work, name="asr-test", daemon=True).start()
        poll()

    def _url_entry(self, var):
        """接口地址：可填 URL 或环境变量名，下面显示实际会用的地址。"""
        c = COLORS
        f = tk.Frame(self.body, bg=c["bg"])
        tk.Entry(f, textvariable=var, **self.entry_style).pack(fill="x", ipady=round(2 * self.scale))
        shown = tk.Label(f, bg=c["bg"], font=(UI_FONT, 9), anchor="w", justify="left", wraplength=round(420 * self.scale))
        shown.pack(fill="x")

        def refresh(*_):
            url = resolve_base_url(var.get())
            shown.config(text=f"→ {url}" if url else t("url_bad"),
                         fg=c["muted"] if url else ACCENTS["recording"])
        var.trace_add("write", refresh)
        refresh()
        return f

    def _collect_llm(self):
        """对话框里当前填的 LLM 配置（未保存的也算）。"""
        llm = json.loads(json.dumps(self.app.cfg["llm"]))
        llm["protocol"] = self.proto_var.get()
        for proto, v in self.proto_vars.items():
            llm[proto] = {k: var.get().strip() for k, var in v.items()}
        llm["system_prompt"] = self.system_text.get("1.0", "end-1c").strip()
        try:
            llm["timeout"] = int(self.timeout_var.get())
        except ValueError:
            pass
        return llm

    def _test_llm(self):
        """用当前填的配置发一条很短的请求，看通不通。"""
        llm = self._collect_llm()
        self.test_label.config(text=t("testing", desc=describe_llm(llm)), fg=COLORS["muted"])
        box = {}

        def work():
            t0 = time.time()
            try:
                reply = llm_complete(llm, "Reply with just: OK", "ping", max_tokens=16)
                box["ok"] = t("test_ok", sec=time.time() - t0, reply=reply[:20])
            except Exception as e:
                box["err"] = f"✗ {str(e)[:160]}"

        def poll():
            if not self.alive():
                return
            if box:
                ok = "ok" in box
                self.test_label.config(text=box.get("ok") or box.get("err"), fg=ACCENTS["idle"] if ok else ACCENTS["recording"])
                log.info(f"[设置] 测试 {describe_llm(llm)}：{box.get('ok') or box.get('err')}")
            else:
                self.win.after(100, poll)
        threading.Thread(target=work, name="llm-test", daemon=True).start()
        poll()

    def _env_entry(self, var):
        """环境变量名输入框，右边显示这个变量当前有没有设置。"""
        c = COLORS
        f = tk.Frame(self.body, bg=c["bg"])
        tk.Entry(f, textvariable=var, **self.entry_style).pack(side="left", fill="x", expand=True, ipady=round(2 * self.scale))
        status = tk.Label(f, bg=c["bg"], font=(UI_FONT, 10), width=8, anchor="w")
        status.pack(side="left", padx=(round(8 * self.scale), 0))

        def refresh(*_):
            ok = bool(os.environ.get(var.get().strip()))
            status.config(text=t("env_set") if ok else t("env_unset"), fg=ACCENTS["idle"] if ok else ACCENTS["recording"])
        var.trace_add("write", refresh)
        refresh()
        return f

    def _button(self, parent, text, command, primary=False):
        c = COLORS
        bg, fg, hover = (ACCENTS["idle"], "#0f1a14", "#63d49c") if primary else (c["border"], c["fg"], "#454a58")
        b = tk.Label(parent, text=text, bg=bg, fg=fg, font=(UI_FONT, 10, "bold" if primary else "normal"),
                     padx=round(14 * self.scale), pady=round(5 * self.scale), cursor="hand2")
        b.bind("<Button-1>", lambda e: command())
        b.bind("<Enter>", lambda e: b.config(bg=hover))
        b.bind("<Leave>", lambda e: b.config(bg=bg))
        return b

    # ---------- 快捷键录入 ----------
    def _capture_start(self, entry):
        self.capturing = entry
        entry.config(fg=ACCENTS["optimizing"])

    def _capture_stop(self):
        if self.capturing is not None:
            self.capturing.config(fg=COLORS["fg"])
        self.capturing = None

    def _capture_key(self, e, var):
        spec = spec_from_event(e)
        if spec:
            var.set(spec)
        return "break"  # 不让 Esc 之类的键触发对话框自己的快捷键

    def capture_spec(self, spec):
        """全局热键被系统截走、到不了输入框，由 App 转交过来。"""
        if self.capturing is not None:
            self.entry_vars[self.capturing].set(spec)

    # ---------- 打开 / 保存 / 关闭 ----------
    def alive(self):
        try:
            return bool(self.win.winfo_exists())
        except tk.TclError:
            return False

    def focus(self):
        self.win.deiconify()
        self.win.lift()
        focus_window(int(self.win.wm_frame(), 16))
        self.win.focus_force()

    def close(self):
        self.capturing = None
        if self.alive():
            self.win.destroy()

    def save(self):
        new = json.loads(json.dumps(self.app.cfg))  # 深拷贝
        for name, var in self.hotkey_vars.items():
            new["hotkeys"][name] = var.get().strip()
        try:
            new["font_size"] = int(self.font_var.get())
            new["llm"]["timeout"] = int(self.timeout_var.get())
        except ValueError:
            self.error.config(text=t("err_int"))
            return
        new["model"] = self.model_var.get().strip()
        new["language"] = self.lang_var.get().strip()
        new["initial_prompt"] = self.prompt_var.get().strip()
        new["normalize_punctuation"] = bool(self.punct_var.get())
        new["asr_engine"] = self._engine()
        new["cloud_asr"] = self._collect_cloud_asr()
        new["auto_llm"] = bool(self.auto_llm_var.get())
        new["log_level"] = {v: k for k, v in self.log_level_names.items()}[self.log_level_var.get()]
        new["ui_language"] = {v: k for k, v in self.ui_lang_names.items()}[self.ui_lang_var.get()]
        new["llm"] = self._collect_llm()
        if not new["model"]:
            self.error.config(text=t("err_model_empty"))
            return
        try:
            validate_config(new)
        except ValueError as e:
            msg = str(e)
            q = lambda key: t("field_quote", label=t(key))  # 内部名字换成界面上的叫法
            for name in self.HOTKEY_NAMES:
                msg = msg.replace(f"hotkeys.{name}", q("hk_" + name))
            self.error.config(text=msg.replace("llm.timeout", q("timeout")).replace("llm.model", q("model"))
                              .replace("font_size", q("font_size")).replace("cloud_asr.model", q("cloud_model")))
            tab = self.tab_keys if "hotkeys." in str(e) else self.tab_llm if "llm." in str(e) else self.tab_general
            self.select_tab(tab)
            return
        try:
            self.app.apply_config(new)
        except ValueError as e:  # 新的全局热键被别的软件占了，已恢复旧键
            self.error.config(text=str(e))
            self.select_tab(self.tab_keys)
            return
        save_config(new)
        log.info("[设置] 已保存")
        self.close()


# ---------------- 界面 ----------------
class App:
    def __init__(self, cfg):
        self.cfg = cfg
        self.keys = cfg["hotkeys"]
        self.events = queue.Queue()
        self.recorder = Recorder()
        self.model = None
        self.state = "loading"  # loading / idle / recording / transcribing / editing / optimizing
        self.target_hwnd = None
        self.restart = False
        self.notice = None  # (类型, 截止时间)：empty / error / wait
        self.llm_seq = 0  # 每次优化加 1，用来丢弃已放弃的旧结果
        self.settings = None  # 打开着的设置对话框
        self.model_gen = 0  # 每次换模型加 1，用来丢弃已作废的加载结果
        self.hotkey_thread = None

        self.root = tk.Tk()
        self.root.title(t("app_name"))
        # Tk 回调里的异常默认只打到 stderr（pythonw 下直接丢失），改为记日志
        self.root.report_callback_exception = lambda *exc: log.error("[界面异常]", exc_info=exc)
        self.root.attributes("-topmost", True)
        self.root.protocol("WM_DELETE_WINDOW", self.cancel)
        self._build_ui()
        self.root.withdraw()

        self.tray = pystray.Icon(
            "local_asr_input", make_icon(TRAY_COLORS["loading"]), f"{t('app_name')}: " + self._tray_text(),
            menu=pystray.Menu(
                pystray.MenuItem(lambda item: t("tray_status", s=self._tray_text()), None, enabled=False),
                pystray.MenuItem(lambda item: t("tray_llm", s=describe_llm(self.cfg["llm"])), None, enabled=False),
                # 文字每次打开菜单时现取，切换界面语言后不用重建菜单
                pystray.MenuItem(lambda item: t("menu_settings"), lambda: self.events.put(("settings", None))),
                pystray.MenuItem(lambda item: t("menu_restart"), lambda: self.events.put(("restart", None))),
                pystray.MenuItem(lambda item: t("menu_log"), lambda: os.startfile(LOG_FILE)),
                pystray.MenuItem(lambda item: t("menu_quit"), lambda: self.events.put(("quit", None))),
            ),
        )
        threading.Thread(target=self.tray.run, name="tray", daemon=True).start()
        self._reload_model()
        failed = self._start_hotkeys(self.keys)
        if failed:
            self.events.put(("fatal", t("hotkey_failed", spec=failed, path=CONFIG_FILE)))
        self.root.after(50, self._poll)

    # ---------- 设置热加载 ----------
    def apply_config(self, new):
        """设置保存后直接用上新配置，不重启。新的全局热键注册不上（被别的软件占了）时恢复旧键，抛 ValueError。"""
        old = self.cfg
        if [new["hotkeys"][k] for k in GLOBAL_KEYS] != [old["hotkeys"][k] for k in GLOBAL_KEYS]:
            self._stop_hotkeys()
            failed = self._start_hotkeys(new["hotkeys"])
            if failed:
                lost = self._start_hotkeys(old["hotkeys"])
                if lost:  # 旧键也注册不上了（极少见），没有热键没法用，只能退出
                    self.events.put(("fatal", t("hotkey_failed", spec=lost, path=CONFIG_FILE)))
                raise ValueError(t("hotkey_taken", spec=failed))
        self.cfg, self.keys = new, new["hotkeys"]
        if any(new["hotkeys"][k] != old["hotkeys"][k] for k in POPUP_KEYS):
            self._bind_popup_keys(old["hotkeys"])
        if new["font_size"] != old["font_size"]:
            self._apply_font_size()
        apply_log_level(new["log_level"])
        set_ui_language(new["ui_language"])
        # 本地模型只看引擎和模型名；识别语言、提示词每次识别时才传，不用重新加载
        engine = lambda c: (c["asr_engine"], c["model"] if c["asr_engine"] == "local" else None)
        if engine(new) != engine(old):
            self._reload_model()
        self._set_state(self.state)  # 刷新托盘：界面语言、模型加载中
        log.info("[设置] 已生效")

    def _start_hotkeys(self, hotkeys):
        """开一个线程注册全局热键，等它注册完；返回注册失败的键，成功返回 None。"""
        result = queue.Queue()
        self.hotkey_thread = threading.Thread(target=hotkey_loop, args=(self.events, hotkeys, result),
                                              name="hotkey", daemon=True)
        self.hotkey_thread.start()
        return result.get(timeout=5)

    def _stop_hotkeys(self):
        th = self.hotkey_thread
        if th is not None and th.is_alive():
            user32.PostThreadMessageW(th.native_id, WM_QUIT, 0, 0)  # 线程退出前会注销自己的热键
            th.join(timeout=2)

    def _reload_model(self):
        self.model_gen += 1
        self.model = None  # 加载完之前按热键会提示稍等；旧模型没人引用了就释放
        threading.Thread(target=self._load_model, args=(self.model_gen, self.cfg), name="model", daemon=True).start()

    def _bind_popup_keys(self, old=None):
        """弹窗内快捷键：取消绑在整个窗口上，其余绑在文本框上。换键时先解绑旧键。"""
        actions = {
            "newline": (self.text, lambda e: self.text.insert("insert", "\n") or "break"),
            "commit": (self.text, lambda e: self.send() or "break"),
            "llm": (self.text, lambda e: self.run_llm() or "break"),
            "cancel": (self.root, lambda e: self.cancel()),
        }
        if old:
            for name, (widget, _) in actions.items():
                widget.unbind(parse_key(old[name])[2])
        for name, (widget, handler) in actions.items():
            widget.bind(parse_key(self.keys[name])[2], handler)

    def _apply_font_size(self):
        """换字号后按新的行高重新算弹窗高度，底边位置不动。"""
        w, h, x, y = map(int, re.match(r"(\d+)x(\d+)\+(-?\d+)\+(-?\d+)", self.root.geometry()).groups())
        self.text.config(font=(UI_FONT, self.cfg["font_size"]))
        self.root.update_idletasks()
        nh = self.root.winfo_reqheight()
        self.root.geometry(f"{w}x{nh}+{x}+{y + h - nh}")

    def _build_ui(self):
        """无边框深色面板：顶部拖拽区 + 文本区 + 底部状态栏（动态状态图标 / ✦ LLM）+ 最底部状态色带。界面上不放文字。"""
        c = COLORS
        self.root.overrideredirect(True)  # 去掉系统标题栏
        self.root.configure(bg=c["border"])
        scale = self.root.winfo_fpixels("1i") / 96

        panel = tk.Frame(self.root, bg=c["bg"])
        panel.pack(fill="both", expand=True, padx=1, pady=1)  # 外面一圈 1px 边框色

        accent_h, pad = max(2, round(3 * scale)), round(14 * scale)
        # 顶部拖拽区：高度 = 原来的色带 + 文本框上内边距，光标离顶部的距离不变
        drag_bar = tk.Frame(panel, bg=c["bg"], height=accent_h + pad, cursor="fleur")
        drag_bar.pack(fill="x", side="top")

        self.accent = tk.Frame(panel, bg=ACCENTS["loading"], height=accent_h)  # 状态色带放在最底部
        self.accent.pack(fill="x", side="bottom")

        bar = tk.Frame(panel, bg=c["bar"])
        bar.pack(fill="x", side="bottom")
        self.meter = tk.Canvas(bar, bg=c["bar"], highlightthickness=0, width=round(46 * scale), height=round(18 * scale))
        self.meter.pack(side="left", padx=(round(18 * scale), 0), pady=round(7 * scale))  # 左边和文字对齐
        self.llm_btn = tk.Label(bar, text="✦", bg=c["llm_bg"], fg=c["llm_fg"], font=(UI_FONT, 11, "bold"),
                                padx=round(9 * scale), pady=round(2 * scale), cursor="hand2")
        self.llm_btn.pack(side="right", padx=round(10 * scale), pady=round(6 * scale))
        self.llm_btn.bind("<Button-1>", lambda e: self.run_llm())
        self.llm_btn.bind("<Enter>", lambda e: self.llm_btn.config(bg=c["llm_hover"]))
        self.llm_btn.bind("<Leave>", lambda e: self.llm_btn.config(bg=c["llm_bg"]))
        # ⚙ 设置：在 ✦ 左边
        self.gear_img = ImageTk.PhotoImage(make_gear(round(14 * scale), c["llm_fg"]))
        # 图片按钮不认 padx/pady，直接用和 ✦ 一样的像素尺寸，底色块才对齐
        edge = 2 * (int(self.llm_btn["borderwidth"]) + int(self.llm_btn["highlightthickness"]))
        self.gear_btn = tk.Label(bar, image=self.gear_img, bg=c["llm_bg"], cursor="hand2",
                                 width=self.llm_btn.winfo_reqwidth() - edge, height=self.llm_btn.winfo_reqheight() - edge)
        self.gear_btn.pack(side="right", padx=(0, round(2 * scale)))
        self.gear_btn.bind("<Button-1>", lambda e: self.open_settings())
        self.gear_btn.bind("<Enter>", lambda e: self.gear_btn.config(bg=c["llm_hover"]))
        self.gear_btn.bind("<Leave>", lambda e: self.gear_btn.config(bg=c["llm_bg"]))

        self.text = tk.Text(panel, font=(UI_FONT, self.cfg["font_size"]), wrap="word", width=1, height=4, undo=True,
                            bg=c["bg"], fg=c["fg"], insertbackground=c["fg"], selectbackground="#3d4455",
                            relief="flat", borderwidth=0, highlightthickness=0,
                            padx=round(18 * scale), pady=0, spacing2=round(4 * scale))
        tk.Frame(panel, bg=c["bg"], height=pad).pack(fill="x", side="bottom")  # 文本区下方留白，和原来一样
        self.text.pack(fill="both", expand=True)

        self._bind_popup_keys()

        # 没有标题栏，按住顶部拖拽区 / 状态栏拖动窗口
        for w in (drag_bar, self.accent, bar, self.meter):
            w.bind("<ButtonPress-1>", self._drag_start)
            w.bind("<B1-Motion>", self._drag_move)

        # 放到屏幕下方居中
        self.root.update_idletasks()
        w, h = round(720 * scale), self.root.winfo_reqheight()
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        self.root.geometry(f"{w}x{h}+{(sw - w) // 2}+{sh - h - sh // 8}")
        self._round_corners()
        self._animate()

    def _round_corners(self):
        """Win11 圆角 + 系统阴影；旧系统上调用失败就保持直角。"""
        try:
            hwnd = wintypes.HWND(int(self.root.wm_frame(), 16))
            pref = ctypes.c_int(2)  # DWMWCP_ROUND
            ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 33, ctypes.byref(pref), ctypes.sizeof(pref))
        except Exception:
            pass

    def _drag_start(self, e):
        self._drag = (e.x_root - self.root.winfo_x(), e.y_root - self.root.winfo_y())

    def _drag_move(self, e):
        dx, dy = self._drag
        self.root.geometry(f"+{e.x_root - dx}+{e.y_root - dy}")

    def _animate(self):
        """状态图标：录音=跳动音量条，识别=流动小块，编辑=实心点；短暂提示见 _notify。"""
        m = self.meter
        m.delete("all")
        w, h = int(m["width"]), int(m["height"])
        n, gap = 5, max(2, w // 20)
        bw = (w - gap * (n - 1)) / n
        now = time.time()
        if self.state == "recording":
            level = min(1.0, self.recorder.level * 12)
            for i in range(n):
                wobble = 0.55 + 0.45 * abs(np.sin(now * 9 + i * 1.3))
                bh = max(3, h * min(1.0, 0.15 + level * wobble))
                x = i * (bw + gap)
                m.create_rectangle(x, (h - bh) / 2, x + bw, (h + bh) / 2, fill=ACCENTS["recording"], width=0)
        elif self.state in ("transcribing", "optimizing"):
            on_color, off_color = (ACCENTS["transcribing"], "#4a4130") if self.state == "transcribing" else (ACCENTS["optimizing"], "#3a3350")
            for i in range(n):
                on = int(now * 6) % n == i
                x = i * (bw + gap)
                m.create_rectangle(x, h / 2 - 2, x + bw, h / 2 + 2, fill=on_color if on else off_color, width=0)
        elif self.notice and now < self.notice[1]:
            kind = self.notice[0]
            if kind == "wait":  # 模型还在加载：灰点闪烁
                if int(now * 4) % 2:
                    m.create_oval(3, h / 2 - 4, 11, h / 2 + 4, fill=COLORS["muted"], width=0)
            else:  # empty=灰色空心圈（没内容），error=红色空心圈（出错）
                color = ACCENTS["recording"] if kind == "error" else COLORS["muted"]
                m.create_oval(1, h / 2 - 6, 13, h / 2 + 6, outline=color, width=2)
        else:
            # 圆点靠左画（和空心圈同一个圆心），不要居中在音量条的宽度里
            m.create_oval(3, h / 2 - 4, 11, h / 2 + 4, fill=ACCENTS.get(self.state, ACCENTS["idle"]), width=0)
        self.root.after(60, self._animate)

    def run_llm(self, start="1.0", end="end-1c"):
        """✦：把 start~end 这段（默认整个文本框）交给大模型整理成提示词，结果替换这段（Ctrl+Z 可以撤回原文）。
        识别后自动优化时只传新说的那一段，前面已经整理过的内容不会被反复改写。"""
        text = self.text.get(start, end).strip()
        if self.state != "editing" or not text:
            return
        # 用 mark 记住范围：优化期间用户改了别处的字，范围也跟着移动
        self.text.mark_set("llm_start", start)
        self.text.mark_gravity("llm_start", "left")
        self.text.mark_set("llm_end", end)
        self.text.mark_gravity("llm_end", "right")
        self.llm_btn.config(bg=COLORS["llm_fg"], fg=COLORS["llm_bg"])  # 按钮反色闪一下
        self.root.after(250, lambda: self.llm_btn.config(bg=COLORS["llm_bg"], fg=COLORS["llm_fg"]))
        self.llm_seq += 1
        self._set_state("optimizing")
        log.info(f"[LLM] 开始优化（{describe_llm(self.cfg['llm'])}）")
        threading.Thread(target=self._call_llm, args=(self.llm_seq, text), name="llm", daemon=True).start()
        self.text.focus_force()

    def _call_llm(self, seq, text):
        c = self.cfg["llm"]
        t0 = time.time()
        try:
            result = llm_complete(c, c["system_prompt"], text)
            log.info(f"[LLM] 完成，用时 {time.time() - t0:.1f}s：{result!r}")
            self.events.put(("llm_result", (seq, result)))
        except Exception as e:
            log.error(f"[LLM] 失败：{e}")
            self.events.put(("llm_result", (seq, None)))

    def on_llm_result(self, seq, result):
        if self.state != "optimizing" or seq != self.llm_seq:  # 已经按 Esc 放弃了这次优化
            return
        self._set_state("editing")
        if not result:
            self._notify("error", 2.5)
            return
        if self.cfg["normalize_punctuation"]:
            result = normalize_punctuation(result)
        # 删除 + 插入合成一步撤销（Tk 默认会在两者之间自动插分隔点，Ctrl+Z 就只撤回一半）
        self.text.edit_separator()
        self.text.config(autoseparators=False)
        self.text.delete("llm_start", "llm_end")
        self.text.insert("llm_start", result)
        self.text.mark_set("insert", f"llm_start + {len(result)}c")
        self.text.edit_separator()
        self.text.config(autoseparators=True)
        self.text.focus_force()

    def _notify(self, kind, seconds=1.5):
        self.notice = (kind, time.time() + seconds)

    # ---------- 后台线程 ----------
    def _load_model(self, gen, cfg):
        """gen：第几次加载。结果带着它发回去，设置里又换了模型的话旧结果作废。cfg 是发起加载时的配置。"""
        if cfg["asr_engine"] == "cloud":  # 云端识别不需要本地模型，秒开
            log.info(f"[识别] 使用云端 {cfg['cloud_asr']['model']}（{cfg['cloud_asr']['api_style']}）")
            self.events.put(("model", (gen, "cloud")))
            return
        name = cfg["model"]
        log.info(f"[模型] 加载 {name} ...")
        t0 = time.time()
        try:
            model, device = load_model(name, cfg["language"])
            self.events.put(("model", (gen, model)))
            log.info(f"[模型] 就绪：{device}，用时 {time.time() - t0:.1f}s。按 {self.keys['start_record']} 开始说话。")
        except Exception as e:
            log.error(f"[模型] {e}")
            self.events.put(("model_failed", (gen, t("model_failed", err=e, path=LOG_FILE))))

    def _transcribe(self, audio):
        language = self.cfg["language"]
        t0 = time.time()
        try:
            if self.cfg["asr_engine"] == "cloud":
                text = cloud_transcribe(self.cfg["cloud_asr"], audio, language)
                log.info(f"[识别] 云端用时 {time.time() - t0:.1f}s")
            else:
                segments, _ = self.model.transcribe(
                    audio, language=language, initial_prompt=self.cfg["initial_prompt"], vad_filter=True, beam_size=5
                )
                sep = "" if language == "zh" else " "
                text = sep.join(s.text.strip() for s in segments).strip()
            if self.cfg["normalize_punctuation"]:
                text = normalize_punctuation(text)
        except Exception as e:
            log.error(f"[识别] 出错：{e}")
            text = None  # None = 出错（红圈），"" = 没识别到内容（灰圈）
        self.events.put(("result", text))

    # ---------- 主线程事件循环 ----------
    def _poll(self):
        try:
            while True:
                kind, payload = self.events.get_nowait()
                if kind == "hotkey":
                    self.on_hotkey(payload)
                elif kind in ("model", "model_failed"):
                    gen, value = payload
                    if gen != self.model_gen:  # 加载期间设置里又换了模型，这次的结果作废
                        continue
                    if kind == "model_failed":
                        self.events.put(("fatal", value))
                        continue
                    self.model = value
                    self._set_state("idle" if self.state == "loading" else self.state)
                elif kind == "settings":
                    self.open_settings()
                elif kind == "llm_result":
                    self.on_llm_result(*payload)
                elif kind == "result":
                    self.on_result(payload)
                elif kind in ("quit", "restart", "fatal"):
                    log.info(f"[{'重启' if kind == 'restart' else '退出'}] {payload or ''}")
                    self.restart = kind == "restart"
                    if self.recorder.stream is not None:
                        self.recorder.stop()
                    self.tray.stop()
                    self.root.destroy()
                    if kind == "fatal":
                        message_box(payload)
                    return
        except queue.Empty:
            pass
        self.root.after(50, self._poll)

    def _tray_text(self):
        # 模型没好时，idle/editing 也显示为加载中
        if self.model is None:
            return t("st_loading")
        return t("st_" + self.state, key=self.keys["start_record"]) if self.state == "idle" else t("st_" + self.state)

    def _set_state(self, state):
        self.state = state
        self.accent.config(bg=ACCENTS["loading" if self.model is None else state])
        self.tray.icon = make_icon(TRAY_COLORS["loading" if self.model is None else state])
        self.tray.title = f"{t('app_name')}: " + self._tray_text()
        self.tray.update_menu()

    def open_settings(self):
        if self.settings is not None and self.settings.alive():
            self.settings.focus()
        else:
            self.settings = SettingsDialog(self)

    def on_hotkey(self, action):
        """action: toggle（开始/结束同一个键）/ start / stop / quit。"""
        if self.settings is not None and self.settings.alive() and self.settings.capturing is not None:
            # 设置里正在录入快捷键：已注册的全局热键被系统截走了，转交给输入框
            spec = {"toggle": "start_record", "start": "start_record", "stop": "stop_record", "quit": "quit"}[action]
            self.settings.capture_spec(self.keys[spec])
            return
        if action == "quit":
            self.events.put(("quit", None))
            return
        log.info(f"[热键] {action}，当前状态 {self.state}")
        if self.state == "recording":
            if action in ("toggle", "stop"):
                self.stop_recording()
        elif action in ("toggle", "start"):
            if self.state in ("idle", "loading"):
                self.target_hwnd = user32.GetForegroundWindow()
                log.info(f"[目标] {window_title(self.target_hwnd)!r}")
                self.text.delete("1.0", "end")
                self.start_recording()
            elif self.state == "editing":
                self.start_recording()  # 追加录音，插到光标处

    def start_recording(self):
        k = self.keys
        if self.model is None:
            self._set_state("editing")
            self._notify("wait", 2.5)
            self.show(f"模型还在加载，稍等几秒再按 {k['start_record']}")
            return
        try:
            self.recorder.start()
        except Exception as e:
            self._set_state("editing")
            self._notify("error", 2.5)
            self.show(f"麦克风打开失败：{e}")
            return
        self._set_state("recording")
        self.show("录音中")

    def stop_recording(self):
        audio = self.recorder.stop()
        if len(audio) < SAMPLE_RATE * 0.3:
            self._set_state("editing")
            self._notify("empty")
            self.show("录音太短，已忽略")
            return
        self._set_state("transcribing")
        log.info(f"[录音] 结束，{len(audio) / SAMPLE_RATE:.1f}s，开始识别")
        self.show("识别中…")
        threading.Thread(target=self._transcribe, args=(audio,), daemon=True).start()

    def on_result(self, text):
        log.info(f"[识别] {text!r}")
        self._set_state("editing")
        if not text:
            self._notify("error" if text is None else "empty", 2.5 if text is None else 1.5)
            self.show("识别出错" if text is None else "没识别到内容")
            return
        start = self.text.index("insert")
        self.text.insert("insert", text)
        end = self.text.index("insert")
        self.show("识别完成")
        if self.cfg["auto_llm"] and len(text) >= AUTO_LLM_MIN_CHARS and llm_configured(self.cfg["llm"]):
            self.run_llm(start, end)  # 只优化这次新说的一段

    def show(self, status):
        """显示弹窗；status 只写日志，界面上用图标表示。"""
        self.root.deiconify()
        self.root.lift()
        focus_window(int(self.root.wm_frame(), 16))
        self.text.focus_force()
        log.info(f"[弹窗] {status} | 前台={window_title(user32.GetForegroundWindow())!r}")

    def _get_text(self):
        return self.text.get("1.0", "end-1c").strip()

    def _set_clipboard(self, text):
        self.root.clipboard_clear()
        self.root.clipboard_append(text)

    def _return_to_target(self):
        """必须在隐藏弹窗之前切：此时本程序还在前台，有权限把前台交给别的窗口。"""
        ok = focus_window(self.target_hwnd)
        self._set_state("idle")
        self.root.withdraw()
        if ok:
            log.info(f"[切回] 成功 {window_title(self.target_hwnd)!r}")
        else:
            log.warning(f"[切回] 失败，目标 {window_title(self.target_hwnd)!r}，当前前台 {window_title(user32.GetForegroundWindow())!r}")
        return ok

    def send(self):
        if self.state != "editing":
            return
        text = self._get_text()
        if not text:
            return
        self._set_clipboard(text)
        if not self._return_to_target():
            log.warning("[粘贴] 文字已在剪贴板，请手动 Ctrl+V。")
            return

        def paste():
            if user32.GetForegroundWindow() != self.target_hwnd and not focus_window(self.target_hwnd):
                log.warning("[粘贴] 目标窗口失去焦点，文字已在剪贴板，请手动 Ctrl+V。")
                return
            send_keys(VK_CONTROL, VK_V)
            log.info(f"[上屏] {text!r}")

        self.root.after(PASTE_DELAY_MS, paste)

    def cancel(self):
        if self.state == "transcribing":
            return
        if self.state == "optimizing":  # 第一次 Esc 只放弃优化，保留原文
            log.info("[LLM] 已放弃")
            self._set_state("editing")
            return
        if self.state == "recording":
            self.recorder.stop()
        self._return_to_target()

    def run(self):
        # 让 Ctrl+C 能退出：tk 主循环里定时回到 Python 以处理信号
        signal.signal(signal.SIGINT, lambda *a: self.root.after(0, self.root.destroy))

        def tick():
            self.root.after(200, tick)
        tick()
        self.root.mainloop()


def main():
    if "--after" in sys.argv:  # 由「重启」拉起：等旧进程退出，释放热键和单实例锁
        wait_for_process_exit(int(sys.argv[sys.argv.index("--after") + 1]))
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)  # 高分屏下字体清晰
    except Exception:
        pass
    instance_lock = acquire_single_instance()
    if instance_lock is None:
        message_box(t("already_running", app=t("app_name")))
        return
    try:
        cfg = load_config()
    except Exception as e:
        log.error(f"[配置] 出错：{e}")
        message_box(t("config_error", err=e, path=CONFIG_FILE))
        subprocess.Popen(["notepad.exe", CONFIG_FILE])
        return
    apply_log_level(cfg["log_level"])
    set_ui_language(cfg["ui_language"])
    app = App(cfg)
    app.run()
    if app.restart:
        argv = [sys.executable] if FROZEN else [sys.executable, os.path.abspath(__file__)]
        subprocess.Popen(argv + ["--after", str(os.getpid())], cwd=APP_DIR)


if __name__ == "__main__":
    main()
