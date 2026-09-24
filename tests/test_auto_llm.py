import sys, os, time, glob, logging, logging.handlers
import tempfile
S = tempfile.mkdtemp(prefix="local_asr_input_test_")  # 测试用的配置、截图都放临时目录
CFG = os.path.join(S, "auto_config.json")
if os.path.exists(CFG): os.remove(CFG)
os.environ["LOCAL_ASR_INPUT_CONFIG"] = CFG
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import local_asr_input as a

SEGS = ["搞成单立的，只能运行一个，或者是夹一个系统托盘", "然后嗯点右键退出，嗯就这样吧", "好的", "这一段没有配置大模型", "另外呢那个图标也换一下颜色"]
class Seg:
    def __init__(self, t): self.text = t
class FakeModel:
    def __init__(self): self.i = 0
    def transcribe(self, audio, **kw):
        t = SEGS[self.i]; self.i += 1; return iter([Seg(t)]), None
a.hotkey_loop = lambda events, hotkeys, result: result.put(None)
a.load_model = lambda name, lang: (FakeModel(), "fake")
a.Recorder.start = lambda self: None
a.Recorder.stop = lambda self: a.np.zeros(a.SAMPLE_RATE, a.np.float32)
a.focus_window = lambda hwnd: True
a.send_keys = lambda *vks: None

cfg = a.load_config()
check_default = cfg["auto_llm"] is True and cfg["log_level"] == "info"
app = a.App(cfg); r = app.root
raw = lambda: app.text.get("1.0", "end-1c")
res = {}
def wait(state, then, timeout=40):
    t0 = time.time()
    def poll():
        if app.state == state: then()
        elif time.time() - t0 > timeout: res["timeout"] = (state, app.state); done()
        else: r.after(100, poll)
    r.after(100, poll)
def done(): app.tray.stop(); r.destroy()
def say(then_state, then):
    app.on_hotkey("toggle"); app.on_hotkey("toggle"); wait(then_state, then)

def s1():  # 第一段：自动进入优化
    say("optimizing", lambda: wait("editing", s2))
def s2():
    res["seg1 optimized"] = raw()
    app.text.mark_set("insert", "end-1c")
    say("optimizing", lambda: wait("editing", s3))  # 第二段：接着说
def s3():
    res["after seg2"] = raw()
    app.text.edit_undo()
    res["after undo"] = raw()
    app.text.edit_redo()
    app.text.mark_set("insert", "end-1c")
    before = raw()
    app.on_hotkey("toggle"); app.on_hotkey("toggle")   # 第三段「好的」太短
    r.after(1500, lambda: s4(before))
def s4(before):
    res["short"] = (app.state, raw()[len(before):])
    app.cfg["llm"]["openai"]["api_key_env"] = "NO_SUCH_KEY_VAR"   # LLM 没配置：自动优化应静默跳过
    app.text.mark_set("insert", "end-1c")
    before1 = raw()
    app.on_hotkey("toggle"); app.on_hotkey("toggle")
    r.after(1500, lambda: s5(before1))
def s5(before1):
    res["not configured"] = (app.state, raw()[len(before1):], app.notice and app.notice[0])
    app.cfg["llm"]["openai"]["api_key_env"] = "BAILIAN_API_KEY"
    app.cfg["auto_llm"] = False                        # 关掉开关
    app.text.mark_set("insert", "end-1c")
    before2 = raw()
    app.on_hotkey("toggle"); app.on_hotkey("toggle")
    r.after(1500, lambda: (res.__setitem__("auto off", (app.state, raw()[len(before2):])), done()))
r.after(500, s1)
r.mainloop()
for k, v in res.items(): print(f"{k}: {v!r}")

seg1_opt = res.get("seg1 optimized", "")
checks = [
 ("默认开启自动优化、日志为详细", check_default),
 ("第一段自动优化（单立→单例）", "单例" in seg1_opt and "单立" not in seg1_opt),
 ("第二段只优化新段，前面不动", res.get("after seg2", "").startswith(seg1_opt) and "嗯" not in res.get("after seg2", "")[len(seg1_opt):]),
 ("Ctrl+Z 只撤回第二段的优化", res.get("after undo") == seg1_opt + SEGS[1]),
 ("太短不自动优化", res.get("short") == ("editing", "好的")),
 ("LLM 没配置时静默跳过、不报错", res.get("not configured") == ("editing", SEGS[3], None)),
 ("关闭开关后不自动优化", res.get("auto off") == ("editing", SEGS[4])),
]

# 日志级别：error 档不记 info，记 warning
LOGT = os.path.join(S, "lvl_test.log")
h = logging.FileHandler(LOGT, mode="w", encoding="utf-8"); logging.getLogger().addHandler(h)
a.apply_log_level("error"); a.log.info("INFO-LINE"); a.log.warning("WARN-LINE")
a.apply_log_level("info"); a.log.info("INFO-AGAIN"); h.close(); logging.getLogger().removeHandler(h)
txt = open(LOGT, encoding="utf-8").read()
checks.append(("仅错误档：不记普通信息、记警告", "INFO-LINE" not in txt and "WARN-LINE" in txt and "INFO-AGAIN" in txt))

# 日志轮转：和程序同样的参数，造 10 个旧文件，轮转后只剩 7 个
d = os.path.join(S, "rot"); os.makedirs(d, exist_ok=True)
for f in glob.glob(os.path.join(d, "*")): os.remove(f)
base = os.path.join(d, "asr_input.log")
for day in range(1, 11): open(f"{base}.2026-09-{day:02d}", "w").close()
rh = logging.handlers.TimedRotatingFileHandler(base, when="midnight", backupCount=7, encoding="utf-8")
rh.emit(logging.makeLogRecord({"msg": "x"})); rh.doRollover(); rh.close()
left = sorted(os.path.basename(f) for f in glob.glob(base + ".*"))
print("rotation left:", left)
checks.append(("日志只保留最近 7 个", len(left) == 7 and "asr_input.log.2026-09-01" not in left))
main_handler = logging.getLogger().handlers[0]
checks.append(("程序用的是按天轮转、保留 7 天", isinstance(main_handler, logging.handlers.TimedRotatingFileHandler)
               and main_handler.when == "MIDNIGHT" and main_handler.backupCount == 7))

for n, ok in checks: print(("PASS " if ok else "FAIL ") + n)
print("ALL PASS" if all(ok for _, ok in checks) else "SOME FAIL")
