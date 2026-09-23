"""云端识别：两种接口的请求格式（本地模拟服务器）、真实百炼调用、程序流程、设置界面。"""
import ctypes
import http.server
import io
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import wave

S = tempfile.mkdtemp(prefix="local_asr_input_test_")
CFG = os.path.join(S, "config.json")
os.environ["LOCAL_ASR_INPUT_CONFIG"] = CFG
ctypes.windll.shcore.SetProcessDpiAwareness(1)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import local_asr_input as a

checks = []
np = a.np

# ---------------- 本地模拟服务器 ----------------
REQS = []
MODE = {"fail": False}


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        body = self.rfile.read(int(self.headers["Content-Length"]))
        REQS.append({"path": self.path, "auth": self.headers.get("Authorization"),
                     "ctype": self.headers.get("Content-Type"), "body": body})
        if MODE["fail"]:
            self.send_response(500)
            self.end_headers()
            self.wfile.write(b'{"error":"boom"}')
            return
        if self.path.endswith("/audio/transcriptions"):
            out = {"text": " 你好，模拟转写。 "}
        else:
            out = {"choices": [{"message": {"content": [{"type": "text", "text": "你好，模拟聊天识别。"}]}}]}
        data = json.dumps(out, ensure_ascii=False).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(data)


srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
threading.Thread(target=srv.serve_forever, daemon=True).start()
MOCK = f"http://127.0.0.1:{srv.server_port}/v1"
os.environ["MOCK_ASR_KEY"] = "test-key-123"
os.environ["NO_PROXY"] = "127.0.0.1,localhost"
audio = (0.1 * np.sin(np.linspace(0, 2000, a.SAMPLE_RATE))).astype(np.float32)

# 1) WAV 编码
w = wave.open(io.BytesIO(a.wav_bytes(audio)))
checks.append(("WAV：16k 单声道 16 位", (w.getframerate(), w.getnchannels(), w.getsampwidth(), w.getnframes()) == (16000, 1, 2, 16000)))

# 2) transcriptions 接口
c = {"api_style": "transcriptions", "base_url": MOCK, "api_key_env": "MOCK_ASR_KEY", "model": "whisper-1", "timeout": 10}
out = a.cloud_transcribe(c, audio, "zh")
req = REQS[-1]
checks.append(("转写接口：地址 / 认证 / multipart", req["path"] == "/v1/audio/transcriptions" and req["auth"] == "Bearer test-key-123"
               and req["ctype"].startswith("multipart/form-data")))
checks.append(("转写接口：带模型、语言和 WAV 文件", b'name="model"' in req["body"] and b"whisper-1" in req["body"]
               and b'name="language"' in req["body"] and b"RIFF" in req["body"]))
checks.append(("转写接口：解析 text", out == "你好，模拟转写。"))

# 3) chat_audio 接口
c = {**c, "api_style": "chat_audio", "model": "qwen3-asr-flash"}
out = a.cloud_transcribe(c, audio, "zh")
req = REQS[-1]
body = json.loads(req["body"])
part = body["messages"][0]["content"][0]
checks.append(("聊天接口：地址和音频格式", req["path"] == "/v1/chat/completions" and part["type"] == "input_audio"
               and part["input_audio"]["data"].startswith("data:audio/wav;base64,")))
checks.append(("聊天接口：非百炼地址不带 asr_options", "asr_options" not in body))
checks.append(("聊天接口：解析分段内容", out == "你好，模拟聊天识别。"))

# 4) 出错
MODE["fail"] = True
try:
    a.cloud_transcribe(c, audio, "zh")
    checks.append(("HTTP 出错抛异常", False))
except RuntimeError as e:
    checks.append(("HTTP 出错抛异常", "HTTP 500" in str(e)))
MODE["fail"] = False
try:
    a.cloud_transcribe({**c, "api_key_env": "NO_SUCH_KEY_VAR"}, audio, "zh")
    checks.append(("key 缺失报错", False))
except RuntimeError as e:
    checks.append(("key 缺失报错", "NO_SUCH_KEY_VAR" in str(e)))

# 5) 真实百炼（有环境变量才测）：现场用 Windows 语音合成一段中文
if os.environ.get("BAILIAN_API_KEY"):
    wav_path = os.path.join(S, "tts.wav")
    ps = (f"Add-Type -AssemblyName System.Speech; $s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
          f"$v = $s.GetInstalledVoices() | Where-Object {{ $_.VoiceInfo.Culture.Name -like 'zh*' }} | Select-Object -First 1; "
          f"if ($v) {{ $s.SelectVoice($v.VoiceInfo.Name) }}; "
          f"$s.SetOutputToWaveFile('{wav_path}', (New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo 16000, "
          f"([System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen), ([System.Speech.AudioFormat.AudioChannel]::Mono))); "
          f"$s.Speak('请帮我检查一下这个函数为什么会报错'); $s.Dispose()")
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], check=True)
    ww = wave.open(wav_path)
    speech = np.frombuffer(ww.readframes(ww.getnframes()), np.int16).astype(np.float32) / 32768
    real = a.default_config()["cloud_asr"]
    t0 = time.time()
    text = a.cloud_transcribe(real, speech, "zh")
    print(f"百炼 qwen3-asr-flash：{time.time() - t0:.1f}s {text!r}")
    checks.append(("真实百炼识别正确", "函数" in text and "报错" in text))

# 6) 程序流程：云端引擎不加载本地模型
a.hotkey_loop = lambda events, hotkeys: None
a.load_model = lambda *args: (_ for _ in ()).throw(AssertionError("云端模式不应加载本地模型"))
a.Recorder.start = lambda self: None
a.Recorder.stop = lambda self: audio
a.focus_window = lambda hwnd: True
cfg = a.load_config()
cfg["asr_engine"], cfg["auto_llm"] = "cloud", False
cfg["cloud_asr"] = {"api_style": "chat_audio", "base_url": MOCK, "api_key_env": "MOCK_ASR_KEY", "model": "qwen3-asr-flash", "timeout": 10}
app = a.App(cfg)
r = app.root
res = {}


def wait(cond, then, timeout=15):
    t0 = time.time()

    def poll():
        if cond() or time.time() - t0 > timeout:
            then()
        else:
            r.after(100, poll)
    r.after(100, poll)


def s1():
    res["model ready (cloud)"] = app.model == "cloud" and app.state == "idle"
    app.on_hotkey("toggle")
    app.on_hotkey("toggle")
    wait(lambda: app.state == "editing", s2)


def s2():
    res["text"] = app.text.get("1.0", "end-1c")
    MODE["fail"] = True
    app.text.mark_set("insert", "end-1c")
    app.on_hotkey("toggle")
    app.on_hotkey("toggle")
    wait(lambda: app.state == "editing" and app.notice, s3)


def s3():
    res["error notice"] = app.notice and app.notice[0]
    MODE["fail"] = False
    app.open_settings()
    d = app.settings
    d.select_tab(d.tab_general)
    d.win.update()
    res["cloud frame shown"] = d.engine_frames["cloud"].winfo_ismapped() and not d.engine_frames["local"].winfo_ismapped()
    size1 = (d.win.winfo_width(), d.win.winfo_height())
    d.engine_var.set(d.engine_names["local"])
    d._select_engine("local")
    d.win.update()
    res["local frame shown"] = d.engine_frames["local"].winfo_ismapped() and not d.engine_frames["cloud"].winfo_ismapped()
    res["size fixed"] = size1 == (d.win.winfo_width(), d.win.winfo_height())
    d.engine_var.set(d.engine_names["cloud"])
    d._select_engine("cloud")
    d._test_asr()
    wait(lambda: d.asr_test_label.cget("text").startswith(("✓", "✗")), s4)


def s4():
    d = app.settings
    res["test button"] = d.asr_test_label.cget("text")
    d.style_var.set(d.style_names["transcriptions"])
    d.cloud_vars["model"].set("whisper-1")
    got = []
    app.events.put = lambda ev: got.append(ev)
    d.save()
    saved = json.load(open(CFG, encoding="utf-8"))
    res["saved"] = (saved["asr_engine"], saved["cloud_asr"]["api_style"], saved["cloud_asr"]["model"], ("restart", None) in got)
    app.tray.stop()
    r.destroy()


def guard(fn):
    def run():
        try:
            fn()
        except Exception:
            import traceback
            traceback.print_exc()
            app.tray.stop()
            r.destroy()
    return run


s1, s2, s3, s4 = map(guard, (s1, s2, s3, s4))
r.after(800, s1)
r.mainloop()
srv.shutdown()
for k, v in res.items():
    print(f"{k}: {v!r}")
checks += [
    ("云端模式不加载本地模型、立即就绪", res.get("model ready (cloud)")),
    ("云端识别结果进入弹窗", res.get("text") == "你好，模拟聊天识别。"),
    ("云端出错显示红圈", res.get("error notice") == "error"),
    ("设置：云端引擎显示云端配置", res.get("cloud frame shown")),
    ("设置：切到本机显示本机配置", res.get("local frame shown")),
    ("设置：切换引擎对话框大小不变", res.get("size fixed")),
    ("设置：测试连接成功", str(res.get("test button", "")).startswith("✓")),
    ("设置：保存引擎和云端配置", res.get("saved") == ("cloud", "transcriptions", "whisper-1", True)),
]
for n, ok in checks:
    print(("PASS " if ok else "FAIL ") + n)
print("ALL PASS" if all(ok for _, ok in checks) else "SOME FAIL")
