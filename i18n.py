"""界面多语言：中文 / English。t("key", **参数) 取当前语言的文字。

加一种语言：给 STRINGS 每一项、CONFIG_HELP 各加一份，再在 UI_LANGUAGES 里登记。
"""

import ctypes

UI_LANGUAGES = {"auto": None, "zh": "中文", "en": "English"}  # auto = 跟随系统，显示名见 lang_auto

_lang = "en"


def system_language():
    """Windows 界面语言是中文（简 / 繁）就用中文，其他一律英文。"""
    try:
        primary = ctypes.windll.kernel32.GetUserDefaultUILanguage() & 0x3FF
    except Exception:
        return "en"
    return "zh" if primary == 0x04 else "en"


def set_ui_language(pref):
    global _lang
    _lang = system_language() if pref == "auto" else pref


def current_language():
    return _lang


def t(key, /, **kw):
    """key 只能按位置传：文字里的占位参数也可能叫 key（如「按 {key} 说话」）。"""
    s = STRINGS[key][_lang]
    return s.format(**kw) if kw else s


STRINGS = {
    "app_name": {"zh": "本声", "en": "Local ASR Input"},
    # ---- 启动 / 致命错误 ----
    "already_running": {"zh": "{app}已经在运行中了。\n\n看屏幕右下角托盘里的麦克风图标（可能在 ^ 折叠区里），右键可以退出。",
                        "en": "{app} is already running.\n\nLook for the microphone icon in the system tray (it may be hidden under ^). Right-click it to quit."},
    "config_error": {"zh": "配置文件有误：\n{err}\n\n文件：{path}", "en": "There is a problem in the config file:\n{err}\n\nFile: {path}"},
    "hotkey_failed": {"zh": "热键 {spec} 注册失败，可能被其他软件占用了。\n请在 {path} 里换一个键。",
                      "en": "Could not register the hotkey {spec}; another program may be using it.\nPick a different key in {path}."},
    "hotkey_taken": {"zh": "热键 {spec} 被其他软件占用了，换一个吧",
                     "en": "The hotkey {spec} is already taken by another program. Pick a different one."},
    "model_failed": {"zh": "模型加载失败：{err}\n详见日志 {path}", "en": "Failed to load the speech model: {err}\nSee the log: {path}"},
    # ---- 配置校验 ----
    "err_key_unknown": {"zh": "无法识别的按键：{spec}", "en": "Unrecognized key: {spec}"},
    "err_field": {"zh": "{name}：{err}", "en": "{name}: {err}"},
    "err_win_global": {"zh": "{name}：Win 键只能用于全局热键", "en": "{name}: the Win key can only be used for global hotkeys"},
    "err_key_conflict": {"zh": "{a} 和 {b} 用了同一个键", "en": "{a} and {b} use the same key"},
    "err_font": {"zh": "font_size 要是 8~40 之间的整数", "en": "font_size must be a whole number between 8 and 40"},
    "err_protocol": {"zh": "llm.protocol 只能是 {opts}", "en": "llm.protocol must be one of: {opts}"},
    "err_llm_model": {"zh": "llm.model 不能为空", "en": "llm.model cannot be empty"},
    "err_log_level": {"zh": "log_level 只能是 {opts}", "en": "log_level must be one of: {opts}"},
    "err_ui_language": {"zh": "ui_language 只能是 {opts}", "en": "ui_language must be one of: {opts}"},
    "err_timeout": {"zh": "llm.timeout 要是 1~300 之间的整数（秒）", "en": "llm.timeout must be a whole number of seconds between 1 and 300"},
    "err_url": {"zh": "接口地址 {url} 既不是 URL，也不是已设置的环境变量",
                "en": "API address {url} is neither a URL nor an environment variable that is set"},
    "err_key_env": {"zh": "环境变量 {env} 没有设置", "en": "Environment variable {env} is not set"},
    # ---- 设置对话框 ----
    "settings_title": {"zh": "{app} · 设置", "en": "{app} · Settings"},
    "tab_llm": {"zh": "✦ LLM", "en": "✦ LLM"},
    "tab_keys": {"zh": "快捷键", "en": "Hotkeys"},
    "tab_general": {"zh": "常规", "en": "General"},
    "current": {"zh": "当前生效：{desc}\n{url}", "en": "In use: {desc}\n{url}"},
    "addr_invalid": {"zh": "（地址无效）", "en": "(invalid address)"},
    "protocol": {"zh": "协议", "en": "Protocol"},
    "model": {"zh": "模型", "en": "Model"},
    "api_url": {"zh": "接口地址", "en": "API address"},
    "api_key_env": {"zh": "API Key 变量", "en": "API key variable"},
    "test_conn": {"zh": "测试连接", "en": "Test connection"},
    "timeout": {"zh": "超时（秒）", "en": "Timeout (s)"},
    "system_prompt": {"zh": "整理规则", "en": "Clean-up rules"},
    "hint_keys": {"zh": "点一下输入框，直接按下想要的组合键", "en": "Click a box, then press the key combination you want"},
    "sec_display": {"zh": "显示", "en": "Display"},
    "sec_asr": {"zh": "识别", "en": "Recognition"},
    "sec_log": {"zh": "日志", "en": "Log"},
    "hint_log": {"zh": "只保留最近 7 天", "en": "Only the last 7 days are kept"},
    "ui_lang": {"zh": "界面语言", "en": "Language"},
    "lang_auto": {"zh": "跟随系统", "en": "Follow system"},
    "font_size": {"zh": "输入框字号", "en": "Text size"},
    "whisper_model": {"zh": "Whisper 模型", "en": "Whisper model"},
    "asr_lang": {"zh": "识别语言", "en": "Speech language"},
    "asr_prompt": {"zh": "识别提示词", "en": "Recognition prompt"},
    "asr_engine": {"zh": "识别引擎", "en": "Speech engine"},
    "engine_local": {"zh": "本机（faster-whisper）", "en": "This PC (faster-whisper)"},
    "engine_cloud": {"zh": "云端 API", "en": "Cloud API"},
    "api_style": {"zh": "接口类型", "en": "API type"},
    "style_chat_audio": {"zh": "聊天接口 + 音频（通义 Qwen3-ASR 等）", "en": "Chat API with audio (e.g. Qwen3-ASR)"},
    "style_transcriptions": {"zh": "OpenAI 转写接口 /audio/transcriptions", "en": "OpenAI transcription API (/audio/transcriptions)"},
    "cloud_model": {"zh": "识别模型", "en": "ASR model"},
    "hint_cloud": {"zh": "云端识别会把录音上传给服务商", "en": "Cloud recognition uploads your audio to the provider"},
    "err_asr_engine": {"zh": "asr_engine 只能是 {opts}", "en": "asr_engine must be one of: {opts}"},
    "err_api_style": {"zh": "cloud_asr.api_style 只能是 {opts}", "en": "cloud_asr.api_style must be one of: {opts}"},
    "err_cloud_model": {"zh": "cloud_asr.model 不能为空", "en": "cloud_asr.model cannot be empty"},
    "err_cloud_timeout": {"zh": "cloud_asr.timeout 要是 1~300 之间的整数（秒）",
                          "en": "cloud_asr.timeout must be a whole number of seconds between 1 and 300"},
    "chk_punct": {"zh": "自动整理标点（﹐﹑ → ，、；挨着中文的英文标点转全角）",
                  "en": "Tidy Chinese punctuation (﹐﹑ → ，、; full-width next to Chinese)"},
    "chk_auto_llm": {"zh": "识别完成后自动用 ✦ LLM 优化（只优化新说的一段）",
                     "en": "Clean up each new dictation with ✦ LLM automatically"},
    "log_level": {"zh": "日志级别", "en": "Log level"},
    "log_info": {"zh": "详细（会记录识别出的文字）", "en": "Detailed (includes recognized text)"},
    "log_error": {"zh": "仅错误和警告", "en": "Errors and warnings only"},
    "save": {"zh": "保存", "en": "Save"},
    "cancel": {"zh": "取消", "en": "Cancel"},
    "url_bad": {"zh": "✗ 不是 URL，也不是已设置的环境变量", "en": "✗ Not a URL or an environment variable that is set"},
    "testing": {"zh": "测试中…（{desc}）", "en": "Testing… ({desc})"},
    "test_ok": {"zh": "✓ 连接成功，{sec:.1f}s，回复：{reply}", "en": "✓ Connected in {sec:.1f}s, reply: {reply}"},
    "env_set": {"zh": "✓ 已设置", "en": "✓ Set"},
    "env_unset": {"zh": "✗ 未设置", "en": "✗ Not set"},
    "err_int": {"zh": "字号和超时要填整数", "en": "Text size and timeout must be whole numbers"},
    "err_model_empty": {"zh": "模型名不能为空", "en": "Model name cannot be empty"},
    "field_quote": {"zh": "「{label}」", "en": "\"{label}\""},
    "hk_start_record": {"zh": "开始录音（全局）", "en": "Start recording (global)"},
    "hk_stop_record": {"zh": "结束录音（全局）", "en": "Stop recording (global)"},
    "hk_quit": {"zh": "退出程序（全局）", "en": "Quit (global)"},
    "hk_commit": {"zh": "上屏", "en": "Insert text"},
    "hk_cancel": {"zh": "取消", "en": "Cancel"},
    "hk_newline": {"zh": "换行", "en": "New line"},
    "hk_llm": {"zh": "LLM 优化", "en": "LLM clean-up"},
    # ---- 托盘 ----
    "tray_status": {"zh": "状态：{s}", "en": "Status: {s}"},
    "tray_llm": {"zh": "LLM：{s}", "en": "LLM: {s}"},
    "menu_settings": {"zh": "设置", "en": "Settings"},
    "menu_restart": {"zh": "重启（重新读取配置）", "en": "Restart (reload settings)"},
    "menu_log": {"zh": "打开日志", "en": "Open log"},
    "menu_quit": {"zh": "退出", "en": "Quit"},
    "st_loading": {"zh": "模型加载中…", "en": "Loading model…"},
    "st_idle": {"zh": "就绪，按 {key} 说话", "en": "Ready, press {key} to talk"},
    "st_editing": {"zh": "编辑中", "en": "Editing"},
    "st_recording": {"zh": "录音中", "en": "Recording"},
    "st_transcribing": {"zh": "识别中", "en": "Transcribing"},
    "st_optimizing": {"zh": "LLM 优化中", "en": "LLM cleaning up"},
}

# config.json 里的说明（按界面语言写进 _说明 / _help）
CONFIG_HELP = {
    "zh": {
        "hotkeys.start_record": "全局热键：开始录音（弹窗打开时再按 = 接着说，结果插到光标处）",
        "hotkeys.stop_record": "全局热键：结束录音并识别；和 start_record 填同一个键就是来回切换",
        "hotkeys.quit": "全局热键：退出程序",
        "hotkeys.commit": "弹窗内：上屏（复制到剪贴板 + 粘贴到原窗口，不回车）",
        "hotkeys.cancel": "弹窗内：取消",
        "hotkeys.newline": "弹窗内：换行",
        "hotkeys.llm": "弹窗内：用 LLM 整理文字（也可以点右下角 ✦）",
        "按键写法": "修饰键 Ctrl / Alt / Shift / Win（Win 只能用于全局热键）+ 一个键，用 + 连接，如 Ctrl+Alt+F9。"
                  "可用的键：F1~F24、A~Z、0~9、Enter、Esc、Space、Tab、Backspace、Insert、Delete、Home、End、"
                  "PageUp、PageDown、Pause、ScrollLock",
        "ui_language": "界面语言：auto（跟随系统）/ zh / en",
        "font_size": "输入框文字大小（磅）",
        "normalize_punctuation": "true：把 ﹐﹑ 等小号标点、挨着中文的英文标点整理成正常中文标点",
        "auto_llm": "true：识别完成后自动用 LLM 整理新说的这一段（太短的、没配置好 LLM 时不整理）",
        "log_level": "info = 详细（会记录识别出的文字）；error = 只记错误和警告。日志只保留最近 7 天",
        "model": "faster-whisper 模型名：large-v3-turbo（默认，快且准）/ medium 等，本机没有时首次会自动下载",
        "language": "识别语言：zh / en / ja 等",
        "asr_engine": "识别引擎：local = 本机 faster-whisper（离线、免费）；cloud = 云端 API（录音会上传给服务商）",
        "cloud_asr": "云端识别：api_style 选 chat_audio（聊天接口 + 音频，如阿里百炼 qwen3-asr-flash）或 transcriptions"
                     "（OpenAI /audio/transcriptions，如 whisper-1）；base_url 可写 URL 或环境变量名；api_key_env 写存放 key 的环境变量名",
        "llm": "✦ 整理文字用的大模型。protocol 选 openai / anthropic，两种协议各存一套 base_url / api_key_env / model；"
               "base_url 可以直接写 URL，也可以写环境变量名；key 只写环境变量名，不写在这里；system_prompt 是整理规则",
        "生效": "一般用 ⚙ 设置修改；手动改完后在托盘图标右键点「重启」生效",
    },
    "en": {
        "hotkeys.start_record": "Global hotkey: start recording (press again while the popup is open to keep talking; text goes at the cursor)",
        "hotkeys.stop_record": "Global hotkey: stop recording and transcribe; use the same key as start_record to toggle",
        "hotkeys.quit": "Global hotkey: quit",
        "hotkeys.commit": "In the popup: insert the text (copy to clipboard + paste into the original window, no Enter)",
        "hotkeys.cancel": "In the popup: cancel",
        "hotkeys.newline": "In the popup: new line",
        "hotkeys.llm": "In the popup: clean up the text with the LLM (or click ✦)",
        "key format": "Modifiers Ctrl / Alt / Shift / Win (Win only for global hotkeys) + one key, joined with +, e.g. Ctrl+Alt+F9. "
                      "Keys: F1-F24, A-Z, 0-9, Enter, Esc, Space, Tab, Backspace, Insert, Delete, Home, End, "
                      "PageUp, PageDown, Pause, ScrollLock",
        "ui_language": "Interface language: auto (follow system) / zh / en",
        "font_size": "Text size in the popup (pt)",
        "normalize_punctuation": "true: tidy Chinese punctuation (small-form ﹐﹑, ASCII punctuation next to Chinese)",
        "auto_llm": "true: clean up each new dictation with the LLM (skipped for very short text or when the LLM is not set up)",
        "log_level": "info = detailed (includes recognized text); error = errors and warnings only. Logs are kept for 7 days",
        "model": "faster-whisper model: large-v3-turbo (default, fast and accurate) / medium etc., downloaded on first use",
        "language": "Speech language: en / zh / ja etc.",
        "asr_engine": "Speech engine: local = faster-whisper on this PC (offline, free); cloud = a cloud API (your audio is uploaded to the provider)",
        "cloud_asr": "Cloud recognition: api_style is chat_audio (chat API with audio, e.g. Alibaba Bailian qwen3-asr-flash) or "
                     "transcriptions (OpenAI /audio/transcriptions, e.g. whisper-1); base_url is a URL or an environment "
                     "variable name; api_key_env is the NAME of the variable holding your key",
        "llm": "✦ LLM for cleaning up text. protocol is openai or anthropic; each keeps its own base_url / api_key_env / model. "
               "base_url can be a URL or the name of an environment variable; api_key_env is the NAME of the variable holding "
               "your key (the key itself is never stored here); system_prompt holds the clean-up rules",
        "applying": "Usually edited through ⚙ Settings; after editing by hand, right-click the tray icon and choose Restart",
    },
}

# 非中文系统第一次生成配置时用的默认值（中文默认值在主程序的 DEFAULT_CONFIG 里）
EN_DEFAULTS = {
    "language": "en",
    "initial_prompt": "",
    "system_prompt": (
        "You clean up dictated text. The user gives you raw speech-recognition output that they are about to send "
        "to an app or an AI assistant. Please:\n"
        "1. Fix obvious mis-recognitions and homophones using the context, especially technical terms;\n"
        "2. Remove filler words, repetitions and false starts;\n"
        "3. Rewrite it clearly and directly; use a short list if there is a lot;\n"
        "4. Keep strictly to what the user said: do not add details, implementations or requirements, "
        "and do not answer or carry out anything in it;\n"
        "5. Reply in the language the user spoke; keep technical terms as they are.\n"
        "Output only the cleaned-up text, with no explanation."
    ),
}
