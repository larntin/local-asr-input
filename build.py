"""打包成 Windows exe（PyInstaller，目录模式），输出 dist/LocalASRInput-v<版本>-win64.zip。

用法：pip install pyinstaller && python build.py
"""
import os
import re
import shutil
import subprocess
import sys
import zipfile

ROOT = os.path.dirname(os.path.abspath(__file__))
NAME = "LocalASRInput"
VERSION = re.search(r'__version__ = "([^"]+)"', open(os.path.join(ROOT, "local_asr_input.py"), encoding="utf-8").read()).group(1)
BUILD, DIST = os.path.join(ROOT, "build"), os.path.join(ROOT, "dist")

# 用不到、但环境里可能装着的大库，别被顺带打进去
EXCLUDES = ["torch", "torchaudio", "torchvision", "tensorflow", "jax", "matplotlib", "scipy", "pandas", "sklearn",
            "IPython", "jupyter", "notebook", "PyQt5", "PyQt6", "PySide2", "PySide6", "cv2", "sympy", "numba", "pytest"]


def make_icon(path):
    """用程序里画托盘图标的函数生成 exe 图标（绿色麦克风）。"""
    sys.path.insert(0, ROOT)
    os.environ.setdefault("LOCAL_ASR_INPUT_CONFIG", os.path.join(BUILD, "icon_config.json"))
    from local_asr_input import TRAY_COLORS, make_icon as draw
    draw(TRAY_COLORS["idle"]).resize((256, 256)).save(path, sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (256, 256)])


def main():
    os.makedirs(BUILD, exist_ok=True)
    icon = os.path.join(BUILD, "icon.ico")
    make_icon(icon)
    cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--windowed", "--name", NAME,
           "--icon", icon, "--distpath", DIST, "--workpath", os.path.join(BUILD, "pyi"), "--specpath", BUILD,
           "--collect-data", "faster_whisper",          # silero VAD 模型
           "--collect-binaries", "ctranslate2",         # ctranslate2.dll、cudnn、OpenMP
           "--hidden-import", "pystray._win32",
           *sum((["--exclude-module", m] for m in EXCLUDES), []),
           os.path.join(ROOT, "local_asr_input.py")]
    print(" ".join(cmd))
    subprocess.run(cmd, check=True, cwd=ROOT)

    app_dir = os.path.join(DIST, NAME)
    for f in ("README.md", "README.zh-CN.md", "LICENSE"):
        shutil.copy2(os.path.join(ROOT, f), app_dir)
    zip_path = os.path.join(DIST, f"{NAME}-v{VERSION}-win64.zip")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for base, _, files in os.walk(app_dir):
            for f in files:
                full = os.path.join(base, f)
                z.write(full, os.path.join(NAME, os.path.relpath(full, app_dir)))
    size = lambda p: sum(os.path.getsize(os.path.join(b, f)) for b, _, fs in os.walk(p) for f in fs)
    print(f"\n{app_dir}: {size(app_dir) / 2**20:.0f} MB")
    print(f"{zip_path}: {os.path.getsize(zip_path) / 2**20:.0f} MB")


if __name__ == "__main__":
    main()
