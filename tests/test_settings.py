# 不注入真实按键：录键用 Tk event_generate，全局热键转交直接调 on_hotkey
import sys, os, ctypes, json
import tempfile
import tkinter.font
S = tempfile.mkdtemp(prefix="local_asr_input_test_")  # 测试用的配置、截图都放临时目录
CFG = os.path.join(S, "settings_config.json")
if os.path.exists(CFG): os.remove(CFG)
os.environ["LOCAL_ASR_INPUT_CONFIG"] = CFG
ctypes.windll.shcore.SetProcessDpiAwareness(1)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import local_asr_input as a
from PIL import ImageGrab
a.hotkey_loop = lambda events, hotkeys, result: result.put(None)
a.load_model = lambda name, lang: (object(), "fake")
app = a.App(a.load_config()); r = app.root
res = {}
def grab(win, name):
    win.update()
    x, y, w, h = win.winfo_rootx(), win.winfo_rooty(), win.winfo_width(), win.winfo_height()
    ImageGrab.grab((x - 10, y - 40, x + w + 10, y + h + 10), all_screens=True).save(os.path.join(S, name))

def step1():
    app._set_state("editing"); app.show("test"); app.text.insert("1.0", "示例文字")
    r.after(300, lambda: (grab(r, "v4_popup.png"), step2()))
def step2():
    app.gear_btn.event_generate("<Button-1>")          # 点 ⚙
    r.after(600, step3)
def step3():
    d = app.settings; res["opened"] = d is not None and d.alive()
    res["first tab"] = d.current_tab()
    geo = set(); sizes = set()
    for i, name in enumerate(["llm", "keys", "general"]):
        d.select_tab(d.tab_list[i][1]); d.win.update(); grab(d.win, f"v6_tab_{name}.png")
        geo.add(tuple((lb.winfo_rooty(), lb.winfo_height(), lb.winfo_rootx()) for _, _, lb, _ in d.tab_list))
        sizes.add((d.win.winfo_width(), d.win.winfo_height()))
    res["tab labels fixed"] = len(geo) == 1
    xs = set()
    for _, f, _, _ in d.tab_list:
        d.select_tab(f); d.win.update()
        xs.add(min(ch.winfo_rootx() for ch in f.grid_slaves(column=1)))
    res["input x"] = xs
    res["dialog size fixed"] = len(sizes) == 1
    # 对话框按最高的页签定高；LLM 页签矮一截时，整理规则框往下撑满，不留大块空白
    d.select_tab(d.tab_llm); d.win.update()
    f, st = d.tab_llm, d.system_text
    res["prompt gap"] = (f.winfo_rooty() + f.winfo_height()) - (st.winfo_rooty() + st.winfo_height())
    res["gap limit"] = round(24 * d.scale)  # 页签下内边距 16 + 行距 3，再留点余量
    d.select_tab(d.tab_keys); d.win.update()  # 录键前先切到「快捷键」页签
    ents = {n: e for e, v in d.entry_vars.items() for n, vv in d.hotkey_vars.items() if vv is v}
    # 录入：在「上屏」框里按 Ctrl+Enter
    ents["commit"].focus_force(); d.win.update()
    ents["commit"].event_generate("<Control-Key-Return>", when="tail"); d.win.update()
    res["capture ctrl+enter"] = d.hotkey_vars["commit"].get()
    # 录入：在「退出」框里按 Esc（应被录成 Esc，而不是关掉对话框）
    ents["quit"].focus_force(); d.win.update()
    ents["quit"].event_generate("<Key-Escape>", when="tail"); d.win.update()
    res["capture esc"] = (d.hotkey_vars["quit"].get(), d.alive())
    # 全局热键被系统截走：在「开始录音」框按 F9 -> App 转交
    ents["start_record"].focus_force(); d.win.update()
    app.on_hotkey("toggle")
    res["global handoff"] = (d.hotkey_vars["start_record"].get(), app.state)
    # 只按修饰键不应改变
    ents["newline"].focus_force(); d.win.update()
    ents["newline"].event_generate("<Key-Control_L>", when="tail"); d.win.update()
    res["modifier only"] = d.hotkey_vars["newline"].get()
    d.select_tab(d.tab_general); d.win.update()  # 先离开快捷键页签，看报错时会不会切回来
    # 撞键：上屏和换行都设 Shift+Enter -> 报错不保存
    d.hotkey_vars["commit"].set("Shift+Enter"); d.hotkey_vars["quit"].set("Ctrl+Alt+F9")
    d.save(); d.win.update()
    res["dup error"] = d.error.cget("text")
    res["tab on error"] = d.current_tab()
    grab(d.win, "v4_settings_error.png")
    # 正常保存：上屏改 Ctrl+Enter，字号 12，LLM 模型 qwen3-max
    d.hotkey_vars["commit"].set("Ctrl+Enter"); d.font_var.set("12"); d.proto_vars["openai"]["model"].set("qwen3-max")
    got = []
    app.events.put = lambda ev: got.append(ev)
    d.save()
    saved = json.load(open(CFG, encoding="utf-8"))
    res["saved"] = (saved["hotkeys"]["commit"], saved["font_size"], saved["llm"]["openai"]["model"], "_说明" in saved)
    res["applied"] = (("restart", None) not in got and not d.alive() and app.keys["commit"] == "Ctrl+Enter"
                      and tkinter.font.Font(font=app.text.cget("font")).actual("size") == 12)
    app.tray.stop(); r.destroy()
def guard(fn):
    def run():
        try: fn()
        except Exception as e:
            import traceback; traceback.print_exc(); app.tray.stop(); r.destroy()
    return run
step3 = guard(step3)
r.after(800, step1)
r.mainloop()
for k, v in res.items(): print(f"{k}: {v!r}")
checks = [
 ("⚙ 打开对话框", res.get("opened")),
 ("默认第一个页签是 LLM", res.get("first tab") == "✦ LLM"),
 ("切换页签时文字位置不动", res.get("tab labels fixed")),
 ("切换页签时对话框大小不变", res.get("dialog size fixed")),
 ("各页签输入框左边对齐", len(res.get("input x", ())) == 1),
 ("整理规则框撑满 LLM 页签", res.get("prompt gap", 999) <= res.get("gap limit", 0)),
 ("撞键时自动切到快捷键页签", res.get("tab on error") == "快捷键"),
 ("录入 Ctrl+Enter", res.get("capture ctrl+enter") == "Ctrl+Enter"),
 ("录入 Esc 且不关对话框", res.get("capture esc") == ("Esc", True)),
 ("全局 F9 转交给录入框、不触发录音", res.get("global handoff") == ("F9", "editing")),
 ("只按修饰键不改变", res.get("modifier only") == "Shift+Enter"),
 ("撞键时报错（中文名）", "同一个键" in res.get("dup error", "") and "「换行」" in res.get("dup error", "")),
 ("保存写入配置", res.get("saved") == ("Ctrl+Enter", 12, "qwen3-max", True)),
 ("保存后关闭、立即生效、不重启", res.get("applied")),
]
for n, ok in checks: print(("PASS " if ok else "FAIL ") + n)
print("ALL PASS" if all(ok for _, ok in checks) else "SOME FAIL")
