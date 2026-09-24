import sys, os, time
import tempfile
S = tempfile.mkdtemp(prefix="local_asr_input_test_")  # 测试用的配置、截图都放临时目录
CFG = os.path.join(S, "llm_config.json")
if os.path.exists(CFG): os.remove(CFG)
os.environ["LOCAL_ASR_INPUT_CONFIG"] = CFG
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import local_asr_input as a

RAW = "搞成单立的﹐只能运行一个,或者是夹一个系统托盘,然后点右键退出"
class Seg: text = RAW
class FakeModel:
    def transcribe(self, audio, **kw): return iter([Seg()]), None
a.hotkey_loop = lambda events, hotkeys, result: result.put(None)
a.load_model = lambda name, lang: (FakeModel(), "fake")
a.Recorder.start = lambda self: None
a.Recorder.stop = lambda self: a.np.zeros(a.SAMPLE_RATE, a.np.float32)
a.focus_window = lambda hwnd: True
a.send_keys = lambda *vks: None

cfg0 = a.load_config(); cfg0["auto_llm"] = False  # 这个测试只测手动 ✦
app = a.App(cfg0)
r = app.root
raw_text = lambda: app.text.get("1.0", "end-1c")
steps = {}
def wait_state(state, then, timeout=40):
    t0 = time.time()
    def poll():
        if app.state == state: then()
        elif time.time() - t0 > timeout: steps["timeout " + state] = app.state; finish()
        else: r.after(100, poll)
    poll()
def finish(): app.tray.stop(); r.destroy()

def s1():  # 录音 -> 识别 -> 标点整理
    app.on_hotkey("toggle"); app.on_hotkey("toggle")
    wait_state("editing", s2)
def s2():
    steps["transcribed"] = raw_text()
    app.text.event_generate("<Control-Key-l>", when="tail")      # Ctrl+L
    r.after(150, lambda: steps.__setitem__("state after ctrl+L", app.state))
    r.after(200, lambda: wait_state("editing", s3))
def s3():
    steps["optimized"] = raw_text()
    app.text.edit_undo()
    steps["after undo"] = raw_text()
    app.run_llm()                                                  # 再优化一次，马上 Esc 放弃
    r.after(100, lambda: (steps.__setitem__("state before esc", app.state), app.text.event_generate("<Key-Escape>", when="tail")))
    r.after(300, lambda: steps.__setitem__("state after esc", app.state))
    for ms in (120, 350, 1000, 3000, 6000):
        r.after(ms, lambda ms=ms: print(f"   t+{ms}ms state={app.state} text={raw_text()!r}", flush=True))
    r.after(8000, s4)                                              # 等旧结果回来，应被丢弃
def s4():
    steps["text after late result"] = raw_text()
    app.cfg["llm"]["openai"]["api_key_env"] = "NO_SUCH_ENV_VAR_XYZ"         # 模拟 key 没设置
    app.run_llm()
    r.after(1500, lambda: (steps.__setitem__("error case", (app.state, app.notice and app.notice[0], raw_text())), finish()))
r.after(500, s1)
r.mainloop()

for k, v in steps.items(): print(f"{k}: {v!r}")
normalized = a.normalize_punctuation(RAW)
checks = [
 ("识别结果已整理标点", steps.get("transcribed") == normalized and "﹐" not in normalized and "," not in normalized),
 ("Ctrl+L 进入优化中", steps.get("state after ctrl+L") == "optimizing"),
 ("优化结果替换了文本", steps.get("optimized") not in (None, "", normalized)),
 ("Ctrl+Z 撤回原文", steps.get("after undo") == normalized),
 ("Esc 放弃优化回到编辑", steps.get("state before esc") == "optimizing" and steps.get("state after esc") == "editing"),
 ("放弃后迟到的结果被丢弃", steps.get("text after late result") == normalized),
 ("key 缺失：红圈提示且原文不变", steps.get("error case") == ("editing", "error", normalized)),
]
for name, ok in checks: print(("PASS " if ok else "FAIL ") + name)
print("ALL PASS" if all(ok for _, ok in checks) else "SOME FAIL")
