# 保存设置后直接生效、不重启。不注入真实按键：全局热键用 PostThreadMessage 投递 WM_HOTKEY，
# 注册情况用「测试自己能不能注册同一个键」来判断；热键选 Ctrl+Alt+Shift+F21~F24，不会和平时用的键冲突
import sys, os, json, time, threading, logging, ctypes
import tkinter.font
import tempfile
S = tempfile.mkdtemp(prefix="local_asr_input_test_")
CFG = os.path.join(S, "hot_reload_config.json")
os.environ["LOCAL_ASR_INPUT_CONFIG"] = CFG
ctypes.windll.shcore.SetProcessDpiAwareness(1)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import local_asr_input as a

K1, K2, K3, K4 = (f"Ctrl+Alt+Shift+F{i}" for i in (21, 22, 23, 24))
json.dump({"ui_language": "zh", "font_size": 11, "log_level": "info", "asr_engine": "local", "model": "small",
           "language": "zh", "hotkeys": {"start_record": K1, "stop_record": K1, "quit": K2, "commit": "Enter"}},
          open(CFG, "w", encoding="utf-8"))

loads = []
class FakeModel:
    def __init__(self, name): self.name = name
    def transcribe(self, audio, **kw):
        class Seg: text = "你好"
        return iter([Seg()]), None
def fake_load(name, lang):
    loads.append(name)
    if name == "slow":
        time.sleep(1.0)
    return FakeModel(name), "fake"
a.load_model = fake_load
a.Recorder.start = lambda self: None
a.Recorder.stop = lambda self: a.np.zeros(a.SAMPLE_RATE, a.np.float32)
a.focus_window = lambda hwnd: True
a.send_keys = lambda *vks: None

app = a.App(a.load_config())
r = app.root
res = {}


def key_free(spec):
    """测试线程能注册上 = 程序没占着这个键。"""
    mods, vk, _ = a.parse_key(spec)
    ok = a.user32.RegisterHotKey(None, 0xBFF0, mods | a.MOD_NOREPEAT, vk)
    if ok:
        a.user32.UnregisterHotKey(None, 0xBFF0)
    return bool(ok)


def hotkey_threads():
    return [t for t in threading.enumerate() if t.name == "hotkey" and t.is_alive()]


def cfg_with(**changes):
    new = json.loads(json.dumps(app.cfg))
    for k, v in changes.items():
        if k == "hotkeys":
            new["hotkeys"].update(v)
        else:
            new[k] = v
    return new


def wait(cond, then, timeout=10):
    t0 = time.time()
    def poll():
        if cond() or time.time() - t0 > timeout:
            then()
        else:
            r.after(50, poll)
    r.after(50, poll)


def geometry():
    w, h, x, y = map(int, r.geometry().replace("x", "+").split("+"))
    return w, h, x, y


def s1():
    res["startup load"] = list(loads)
    res["startup key taken"] = not key_free(K1)
    got = []
    real_put = app.events.put
    app.events.put = lambda ev: (got.append(ev), real_put(ev))
    # 全局热键：换成 K3
    app.apply_config(cfg_with(hotkeys={"start_record": K3, "stop_record": K3}))
    res["global rebound"] = (key_free(K1), not key_free(K3), len(hotkey_threads()), app.keys["start_record"])
    a.user32.PostThreadMessageW(hotkey_threads()[0].native_id, a.WM_HOTKEY, 1, 0)
    wait(lambda: app.state == "recording", lambda: s2(got))


def s2(got):
    res["new hotkey works"] = app.state
    a.user32.PostThreadMessageW(hotkey_threads()[0].native_id, a.WM_HOTKEY, 1, 0)
    wait(lambda: app.state == "editing", lambda: s3(got))


def s3(got):
    res["transcribed"] = app.text.get("1.0", "end-1c")
    # 弹窗内快捷键：上屏换成 Ctrl+Enter
    app.apply_config(cfg_with(hotkeys={"commit": "Ctrl+Enter"}))
    binds = app.text.bind()
    res["popup rebound"] = ("<Control-Key-Return>" in binds, "<Key-Return>" in binds)
    # 字号：变大后弹窗变高，底边位置不动
    w0, h0, x0, y0 = geometry()
    app.apply_config(cfg_with(font_size=20))
    r.update_idletasks()
    w1, h1, x1, y1 = geometry()
    res["font"] = (tkinter.font.Font(font=app.text.cget("font")).actual("size"), h1 > h0, (w1, x1, y1 + h1) == (w0, x0, y0 + h0))
    # 日志级别、界面语言
    app.apply_config(cfg_with(log_level="error", ui_language="en"))
    res["log level"] = logging.getLogger().level
    res["language"] = (a.current_language(), app.tray.menu.items[2].text, app.tray.title)
    # 上屏用新键
    app.text.event_generate("<Control-Key-Return>", when="tail")
    r.update()
    res["commit with new key"] = app.state
    res["no restart"] = not any(k in ("restart", "quit", "fatal") for k, _ in got)
    # 换本地模型：先变成加载中，加载完用新模型
    app.apply_config(cfg_with(model="medium"))
    res["reloading"] = (app.model is None, app.tray.title)
    wait(lambda: app.model is not None, s4)


def s4():
    res["reloaded"] = (getattr(app.model, "name", None), list(loads))
    app.apply_config(cfg_with(language="en"))  # 只改识别语言不重新加载
    app.apply_config(cfg_with(asr_engine="cloud"))
    wait(lambda: app.model is not None, s5)


def s5():
    res["cloud"] = (app.model, list(loads))
    # 连着换两次：先换的 slow 加载得慢，它的结果要作废
    app.apply_config(cfg_with(asr_engine="local", model="slow"))
    app.apply_config(cfg_with(model="fast"))
    r.after(1500, s6)


def s6():
    res["latest wins"] = (getattr(app.model, "name", None), loads[-2:])
    # 设置框里保存：新键被别的程序占着 -> 报错、恢复旧键、不写配置
    mods, vk, _ = a.parse_key(K4)
    a.user32.RegisterHotKey(None, 0xBFF1, mods | a.MOD_NOREPEAT, vk)
    before = open(CFG, encoding="utf-8").read()
    app.open_settings()
    d = app.settings
    d.hotkey_vars["start_record"].set(K4)
    d.hotkey_vars["stop_record"].set(K4)
    d.select_tab(d.tab_general)
    d.save()
    r.update()
    res["taken error"] = (d.alive(), K4 in d.error.cget("text"), d.current_tab() == t_keys(d))
    res["taken restored"] = (app.keys["start_record"], not key_free(K3), len(hotkey_threads()))
    res["taken not saved"] = open(CFG, encoding="utf-8").read() == before
    a.user32.UnregisterHotKey(None, 0xBFF1)
    d.close()
    app.tray.stop()
    r.destroy()


def t_keys(d):
    return next(title for title, f, _, _ in d.tab_list if f is d.tab_keys)


def guard(fn):
    def run(*args):
        try:
            fn(*args)
        except Exception:
            import traceback
            traceback.print_exc()
            app.tray.stop()
            r.destroy()
    return run


for name in ("s1", "s2", "s3", "s4", "s5", "s6"):
    globals()[name] = guard(globals()[name])
wait(lambda: app.model is not None, s1)
r.mainloop()
for k, v in res.items():
    print(f"{k}: {v!r}")
checks = [
    ("启动时加载模型", res.get("startup load") == ["small"]),
    ("启动时注册全局热键", res.get("startup key taken")),
    ("全局热键换键：旧键释放、新键注册、只剩一个热键线程", res.get("global rebound") == (True, True, 1, K3)),
    ("新热键能开始录音", res.get("new hotkey works") == "recording"),
    ("新热键能结束录音并识别", res.get("transcribed") == "你好"),
    ("弹窗快捷键重绑：新键有、旧键无", res.get("popup rebound") == (True, False)),
    ("字号生效、弹窗变高、底边不动", res.get("font") == (20, True, True)),
    ("日志级别生效", res.get("log level") == logging.WARNING),
    ("界面语言生效（托盘菜单）", (res.get("language") or ("",))[0] == "en" and res["language"][1] == "Settings"
                               and res["language"][2].startswith("Local ASR Input")),
    ("新的上屏键能上屏", res.get("commit with new key") == "idle"),
    ("不重启、不退出", res.get("no restart")),
    ("换模型时进入加载中", (res.get("reloading") or (False,))[0]),
    ("换模型后加载新模型", res.get("reloaded") == ("medium", ["small", "medium"])),
    ("只改识别语言、切到云端都不加载本地模型", res.get("cloud") == ("cloud", ["small", "medium"])),
    ("连换两次模型，用最后一次的", res.get("latest wins") == ("fast", ["slow", "fast"])),
    ("新键被占用：对话框报错并切到快捷键页", res.get("taken error") == (True, True, True)),
    ("新键被占用：恢复旧键", res.get("taken restored") == (K3, True, 1)),
    ("新键被占用：不写配置", res.get("taken not saved")),
]
for n, ok in checks:
    print(("PASS " if ok else "FAIL ") + n)
print("ALL PASS" if all(ok for _, ok in checks) else "SOME FAIL")
