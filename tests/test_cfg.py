# 不注入任何真实按键：全局热键用 PostThreadMessage 投递 WM_HOTKEY，弹窗按键用 Tk event_generate
import sys, os, json, time, threading
import tempfile
S = tempfile.mkdtemp(prefix="local_asr_input_test_")  # 测试用的配置、截图都放临时目录
CFG = os.path.join(S, "test_config.json")
if os.path.exists(CFG): os.remove(CFG)
os.environ["LOCAL_ASR_INPUT_CONFIG"] = CFG
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import local_asr_input as a

fails = []
def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond: fails.append(name)

# 1) 按键解析
check("parse F9", a.parse_key("F9")[:2] == (0, 0x78))
check("parse Ctrl+Alt+F9", a.parse_key("ctrl + ALT + f9")[:2] == (a.MOD_CONTROL | a.MOD_ALT, 0x78))
check("tk Shift+Enter", a.parse_key("Shift+Enter")[2] == "<Shift-Key-Return>")
check("tk Esc", a.parse_key("Esc")[2] == "<Key-Escape>")
check("tk digit", a.parse_key("Ctrl+1")[2] == "<Control-Key-1>")
check("win no tk", a.parse_key("Win+F9")[2] is None)
for bad in ("F99", "Hyper+F9", "", "Ctrl+"):
    try: a.parse_key(bad); check(f"reject {bad!r}", False)
    except ValueError: check(f"reject {bad!r}", True)

# 2) 配置：自动生成、合并默认值、报错
cfg = a.load_config()
check("config generated", os.path.exists(CFG) and cfg["hotkeys"]["commit"] == "Enter")
json.dump({"hotkeys": {"commit": "F99"}}, open(CFG, "w", encoding="utf-8"))
try: a.load_config(); check("bad key rejected", False)
except ValueError as e: check("bad key rejected: " + str(e), "hotkeys.commit" in str(e))
json.dump({"hotkeys": {"cancel": "Win+Q"}}, open(CFG, "w", encoding="utf-8"))
try: a.load_config(); check("win in popup rejected", False)
except ValueError as e: check("win in popup rejected", "Win" in str(e))
# 测试配置：开始/结束分开，上屏改成 Ctrl+Enter，避免和正在用的 F9 冲突
json.dump({"hotkeys": {"start_record": "F10", "stop_record": "F11", "quit": "Ctrl+Alt+F12", "commit": "Ctrl+Enter"}},
          open(CFG, "w", encoding="utf-8"))
cfg = a.load_config()
check("merge defaults", cfg["hotkeys"]["cancel"] == "Esc" and cfg["model"] == "large-v3-turbo" and cfg["font_size"] == 11)

# 3) 完整流程（假模型/假麦克风/不真正切窗口和粘贴）
class Seg:  text = " 你好世界 "
class FakeModel:
    def transcribe(self, audio, **kw): return iter([Seg()]), None
a.load_model = lambda name, lang: (FakeModel(), "fake")
a.Recorder.start = lambda self: None
a.Recorder.stop = lambda self: a.np.zeros(a.SAMPLE_RATE, a.np.float32)
a.focus_window = lambda hwnd: True
sent = []
a.send_keys = lambda *vks: sent.append(vks)

app = a.App(cfg)
def hotkey_tid():
    return next(t.native_id for t in threading.enumerate() if t.name == "hotkey")
def post_hotkey(hid):  # 1=start 2=stop 3=quit
    a.user32.PostThreadMessageW(hotkey_tid(), a.WM_HOTKEY, hid, 0)
def key(seq):
    app.text.event_generate(seq, when="tail")

steps = []
def later(ms, fn): app.root.after(ms, fn)
def run_steps():
    later(1500, lambda: post_hotkey(2))                      # 空闲时按 stop：应忽略
    later(1800, lambda: steps.append(("stop ignored", app.state)))
    later(2000, lambda: post_hotkey(1))                      # start
    later(2300, lambda: steps.append(("recording", app.state)))
    later(2400, lambda: post_hotkey(1))                      # 录音中按 start：应忽略
    later(2600, lambda: steps.append(("start ignored while rec", app.state)))
    later(2700, lambda: post_hotkey(2))                      # stop -> 识别
    later(3300, lambda: steps.append(("editing", app.state, app._get_text())))
    later(3400, lambda: key("<Key-Return>"))                 # 普通回车：commit 是 Ctrl+Enter，所以这里应只是换行
    later(3500, lambda: steps.append(("enter = newline", app.state, app.text.get("1.0", "end-1c"))))
    later(3600, lambda: key("<Shift-Key-Return>"))           # newline 键
    later(3700, lambda: steps.append(("shift+enter newline", app.text.get("1.0", "end-1c").count("\n"))))
    later(3800, lambda: key("<Control-Key-Return>"))         # commit
    later(4200, lambda: steps.append(("committed", app.state, list(sent), app.root.clipboard_get())))
    later(4300, lambda: post_hotkey(1))
    later(4500, lambda: key("<Key-Escape>"))                 # cancel
    later(4700, lambda: steps.append(("cancelled", app.state)))
    later(4800, lambda: post_hotkey(3))                      # quit
app.root.after(0, run_steps)
t0 = time.time(); app.run()
print("app exited after", round(time.time() - t0, 1), "s")
d = {s[0]: s[1:] for s in steps}
for k_, v_ in d.items(): print("  ", k_, v_)
check("stop ignored when idle", d["stop ignored"][0] == "idle")
check("start -> recording", d["recording"][0] == "recording")
check("start ignored while recording", d["start ignored while rec"][0] == "recording")
check("stop -> editing with text", d["editing"] == ("editing", "你好世界"))
check("Enter just newline when commit=Ctrl+Enter", d["enter = newline"][0] == "editing" and "\n" in d["enter = newline"][1])
check("Shift+Enter newline", d["shift+enter newline"][0] >= 2)
check("Ctrl+Enter commits: idle + Ctrl+V + clipboard", d["committed"][0] == "idle" and d["committed"][1] == [(a.VK_CONTROL, a.VK_V)] and "你好世界" in d["committed"][2])
check("Esc cancels", d["cancelled"][0] == "idle")
check("quit hotkey exits", time.time() - t0 < 10 and not app.restart)
print("\nRESULT:", "ALL PASS" if not fails else f"{len(fails)} FAIL: {fails}")
