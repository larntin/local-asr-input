"""标点整理：小号标点转常规，挨着中文的英文标点转全角，英文 / 代码里的标点不动。"""
import os
import sys
import tempfile

os.environ["LOCAL_ASR_INPUT_CONFIG"] = os.path.join(tempfile.mkdtemp(prefix="local_asr_input_test_"), "config.json")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from local_asr_input import normalize_punctuation as n

CASES = [
    ("是不是有后台程序正在运行﹐我双击Start﹐然后它自己的CMD就退出了。", "是不是有后台程序正在运行，我双击Start，然后它自己的CMD就退出了。"),
    ("把当前的任务状态﹑后续计划﹑写一段提示词", "把当前的任务状态、后续计划、写一段提示词"),
    ("请帮我检查一下这个函数为什么会报错,然后修复它。", "请帮我检查一下这个函数为什么会报错，然后修复它。"),
    ("这个图标是你怎么弄来的?", "这个图标是你怎么弄来的？"),
    ("把 useState, useEffect 都删掉", "把 useState, useEffect 都删掉"),
    ("打开 file.py 看一下", "打开 file.py 看一下"),
    ("版本是 v1.2.3 吧.", "版本是 v1.2.3 吧。"),
    ("注意: 不要改配置", "注意：不要改配置"),
    ("Hello, world!", "Hello, world!"),
    ("第一步,安装;第二步,运行!", "第一步，安装；第二步，运行！"),
]

fails = 0
for src, want in CASES:
    got = n(src)
    ok = got == want
    fails += not ok
    print(("PASS " if ok else "FAIL ") + (src if ok else f"{src!r} -> {got!r}，期望 {want!r}"))
print("ALL PASS" if not fails else f"{fails} FAIL")
