"""状态图标：每种状态、每种提示都真的画一遍，画的时候不能报错（动画出错会让图标卡住不动）。"""
import os
import sys
import tempfile
import time

os.environ["LOCAL_ASR_INPUT_CONFIG"] = os.path.join(tempfile.mkdtemp(prefix="local_asr_input_test_"), "config.json")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import local_asr_input as a

a.hotkey_loop = lambda events, hotkeys: None
a.load_model = lambda name, lang: (object(), "fake")
app = a.App(a.load_config())
errors = []
app.root.report_callback_exception = lambda *exc: errors.append(exc[1])
results = []


def run():
    for state in ("loading", "idle", "recording", "transcribing", "optimizing", "editing"):
        for notice in (None, "empty", "error", "wait"):
            app.state = state
            app.recorder.level = 0.05
            app.notice = (notice, time.time() + 5) if notice else None
            try:
                app._animate()
                results.append((state, notice, len(app.meter.find_all()) >= 0))
            except Exception as e:
                errors.append(e)
                results.append((state, notice, False))
    app.root.after(300, finish)  # 再让排队的动画帧跑几轮


def finish():
    app.tray.stop()
    app.root.destroy()


app.root.after(500, run)
app.root.mainloop()
for e in errors:
    print("error:", repr(e))
checks = [("所有状态 × 提示组合都能画出来", len(results) == 24 and all(ok for *_, ok in results)),
          ("动画过程中没有异常", not errors)]
for n, ok in checks:
    print(("PASS " if ok else "FAIL ") + n)
print("ALL PASS" if all(ok for _, ok in checks) else "SOME FAIL")
