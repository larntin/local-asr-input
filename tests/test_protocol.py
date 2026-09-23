import sys, os, json, time, ctypes
import tempfile
S = tempfile.mkdtemp(prefix="local_asr_input_test_")  # 测试用的配置、截图都放临时目录
CFG = os.path.join(S, "proto_config.json")
os.environ["LOCAL_ASR_INPUT_CONFIG"] = CFG
# 1) 旧版配置格式（llm 下平铺 base_url_env / api_key_env / model），加载时要迁移到 openai 那一套
user = {"llm": {"base_url_env": "OPENAI_COMPAT_BASE_URL", "api_key_env": "BAILIAN_API_KEY", "model": "deepseek-v4-flash"}}
json.dump(user, open(CFG, "w", encoding="utf-8"), ensure_ascii=False)
ctypes.windll.shcore.SetProcessDpiAwareness(1)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import local_asr_input as a
from PIL import ImageGrab
checks = []
cfg = a.load_config()
old = user["llm"]
checks.append(("旧配置迁移到 openai 那一套", cfg["llm"]["protocol"] == "openai" and cfg["llm"]["openai"] ==
               {"base_url": old["base_url_env"], "api_key_env": old["api_key_env"], "model": old["model"]}
               and "base_url_env" not in cfg["llm"]))
# 地址解析
checks.append(("地址：URL 原样", a.resolve_base_url(" https://x.y/v1 ") == "https://x.y/v1"))
checks.append(("地址：环境变量名取值", a.resolve_base_url("OPENAI_COMPAT_BASE_URL") == os.environ["OPENAI_COMPAT_BASE_URL"]))
checks.append(("地址：无效为空", a.resolve_base_url("NO_SUCH_VAR") == ""))
# 2) 两种协议真实调用
TEXT = "搞成单立的，只能运行一个，或者是夹一个系统托盘"
for proto in ("openai", "anthropic"):
    llm = json.loads(json.dumps(cfg["llm"])); llm["protocol"] = proto
    t = time.time()
    try:
        out = a.llm_complete(llm, llm["system_prompt"], TEXT)
        print(f"{proto}: {time.time()-t:.1f}s {out!r}")
        checks.append((f"{proto} 协议调用成功", "单例" in out))
    except Exception as e:
        print(f"{proto}: ERROR {e}"); checks.append((f"{proto} 协议调用成功", False))
# Anthropic 地址写到 /v1 也行
llm = json.loads(json.dumps(cfg["llm"])); llm["protocol"] = "anthropic"
llm["anthropic"]["base_url"] = "https://dashscope.aliyuncs.com/apps/anthropic/v1"
try: checks.append(("Anthropic 地址带 /v1 也能用", bool(a.llm_complete(llm, "只回复 OK", "ping", max_tokens=16))))
except Exception as e: print("v1:", e); checks.append(("Anthropic 地址带 /v1 也能用", False))
# key 缺失给出明确错误
llm["anthropic"]["api_key_env"] = "NO_SUCH_KEY_VAR"
try: a.llm_complete(llm, "x", "y"); checks.append(("key 缺失报错", False))
except RuntimeError as e: checks.append(("key 缺失报错", "NO_SUCH_KEY_VAR" in str(e)))

# 3) 设置对话框
a.hotkey_loop = lambda events, hotkeys: None
a.load_model = lambda name, lang: (object(), "fake")
app = a.App(cfg); r = app.root
res = {}
def grab(win, name):
    win.update(); x, y, w, h = win.winfo_rootx(), win.winfo_rooty(), win.winfo_width(), win.winfo_height()
    ImageGrab.grab((x - 10, y - 40, x + w + 10, y + h + 10), all_screens=True).save(os.path.join(S, name))
def wait_test(then, timeout=40):
    t0 = time.time()
    def poll():
        txt = d.test_label.cget("text")
        if txt.startswith(("✓", "✗")) or time.time() - t0 > timeout: then(txt)
        else: r.after(200, poll)
    poll()
def s1():
    global d
    app.open_settings(); d = app.settings; d.win.update()
    res["visible openai"] = d.proto_frames["openai"].winfo_ismapped() and not d.proto_frames["anthropic"].winfo_ismapped()
    d._test_llm(); wait_test(s2)
def s2(txt):
    res["test openai"] = txt; grab(d.win, "v7_openai.png")
    d._select_proto("anthropic"); d.win.update()
    res["visible anthropic"] = d.proto_frames["anthropic"].winfo_ismapped() and not d.proto_frames["openai"].winfo_ismapped()
    res["openai kept"] = d.proto_vars["openai"]["model"].get() == old["model"]
    d._test_llm(); wait_test(s3)
def s3(txt):
    res["test anthropic"] = txt; grab(d.win, "v7_anthropic.png")
    d.proto_vars["anthropic"]["base_url"].set("NO_SUCH_VAR"); d.win.update()
    res["stale cleared"] = d.test_label.cget("text") == ""
    grab(d.win, "v7_badurl.png")
    d.proto_vars["anthropic"]["base_url"].set("https://dashscope.aliyuncs.com/apps/anthropic")
    got = []; app.events.put = lambda ev: got.append(ev)
    d.save()
    saved = json.load(open(CFG, encoding="utf-8"))
    res["saved"] = (saved["llm"]["protocol"], saved["llm"]["openai"]["model"], "base_url_env" in saved["llm"], ("restart", None) in got)
    app.tray.stop(); r.destroy()
r.after(800, s1)
r.mainloop()
for k, v in res.items(): print(f"{k}: {v!r}")
checks += [
 ("对话框默认显示 OpenAI 那一套", res.get("visible openai")),
 ("OpenAI 测试连接成功", res.get("test openai", "").startswith("✓")),
 ("切到 Anthropic 显示另一套", res.get("visible anthropic")),
 ("切换不影响 OpenAI 那一套的值", res.get("openai kept")),
 ("Anthropic 测试连接成功且有回复", res.get("test anthropic", "").startswith("✓") and not res.get("test anthropic", "").endswith("回复：")),
 ("改了地址后清掉旧测试结果", res.get("stale cleared")),
 ("保存为 anthropic，旧字段不再出现", res.get("saved") == ("anthropic", old["model"], False, True)),
]
for n, ok in checks: print(("PASS " if ok else "FAIL ") + n)
print("ALL PASS" if all(ok for _, ok in checks) else "SOME FAIL")
