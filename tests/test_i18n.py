"""多语言：所有文字中英文齐全、占位参数一致；英文界面能正常生成；非中文系统默认配置是英文。"""
import ctypes
import json
import os
import string
import sys
import tempfile

S = tempfile.mkdtemp(prefix="local_asr_input_test_")
CFG = os.path.join(S, "config.json")
os.environ["LOCAL_ASR_INPUT_CONFIG"] = CFG
ctypes.windll.shcore.SetProcessDpiAwareness(1)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import i18n
import local_asr_input as a

checks = []
fields = lambda s: {f for _, f, _, _ in string.Formatter().parse(s) if f}

# 1) 文字表完整
missing = [k for k, v in i18n.STRINGS.items() if set(v) != {"zh", "en"} or not all(v.values())]
checks.append(("每条文字都有中英文", not missing))
mismatch = [k for k, v in i18n.STRINGS.items() if fields(v["zh"]) != fields(v["en"])]
checks.append(("中英文占位参数一致", not mismatch))
checks.append(("配置说明中英文都有", set(i18n.CONFIG_HELP) == {"zh", "en"}))
if missing or mismatch:
    print("missing:", missing, "mismatch:", mismatch)

# 2) 非中文系统的默认配置
orig = a.system_language
a.system_language = lambda: "en"
d = a.default_config()
checks.append(("非中文系统：识别语言 en、整理规则英文",
               d["language"] == "en" and d["initial_prompt"] == "" and d["llm"]["system_prompt"].startswith("You clean up")))
a.system_language = lambda: "zh"
checks.append(("中文系统：默认值不变", a.default_config()["language"] == "zh"))
a.system_language = orig

# 3) 英文界面
i18n.set_ui_language("en")
a.save_config(a.default_config())
saved = json.load(open(CFG, encoding="utf-8"))
checks.append(("英文界面：配置说明写成 _help", "_help" in saved and "_说明" not in saved))
cfg = a.load_config()
cfg["hotkeys"]["commit"] = cfg["hotkeys"]["newline"] = "Shift+Enter"
try:
    a.validate_config(cfg)
    err = ""
except ValueError as e:
    err = str(e)
checks.append(("英文校验信息", err.endswith("use the same key")))
cfg = a.load_config()

a.hotkey_loop = lambda events, hotkeys: None
a.load_model = lambda name, lang: (object(), "fake")
app = a.App(cfg)
r = app.root
res = {}


def run():
    app.open_settings()
    dlg = app.settings
    dlg.win.update()
    res["title"] = dlg.win.title()
    res["tabs"] = [title for title, _, _, _ in dlg.tab_list]
    res["tray"] = app._tray_text()
    dlg.hotkey_vars["commit"].set("Shift+Enter")
    dlg.save()
    res["dlg error"] = dlg.error.cget("text")
    res["tab on error"] = dlg.current_tab()
    for i, name in enumerate(["llm", "keys", "general"]):
        dlg.select_tab(dlg.tab_list[i][1])
        dlg.win.update()
        # 标签列够宽：每个标签都完整显示（请求宽度 <= 实际宽度）
        for w in dlg.tab_list[i][1].grid_slaves(column=0):
            if isinstance(w, a.tk.Label) and w.winfo_reqwidth() > w.winfo_width() + 1:
                res.setdefault("clipped", []).append(w.cget("text"))
        from PIL import ImageGrab
        x, y, ww, hh = dlg.win.winfo_rootx(), dlg.win.winfo_rooty(), dlg.win.winfo_width(), dlg.win.winfo_height()
        ImageGrab.grab((x, y, x + ww, y + hh), all_screens=True).save(os.path.join(S, f"en_{name}.png"))
    dlg.close()
    app.tray.stop()
    r.destroy()


r.after(800, run)
r.mainloop()
print("screenshots:", S)
for k, v in res.items():
    print(f"{k}: {v!r}")
checks += [
    ("英文对话框标题", res.get("title") == "Local ASR Input · Settings"),
    ("英文页签", res.get("tabs") == ["✦ LLM", "Hotkeys", "General"]),
    ("英文托盘状态", res.get("tray", "").startswith("Ready")),
    ("英文报错用界面叫法", res.get("dlg error") == '"New line" and "Insert text" use the same key'),
    ("报错切到快捷键页签", res.get("tab on error") == "Hotkeys"),
    ("英文标签没有被截断", not res.get("clipped")),
]
for n, ok in checks:
    print(("PASS " if ok else "FAIL ") + n)
print("ALL PASS" if all(ok for _, ok in checks) else "SOME FAIL")
