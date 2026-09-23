"""依次运行 tests/ 下所有测试并汇总。

需要 Windows 桌面会话（测试会短暂弹出窗口，但不会模拟真实按键）。
test_llm / test_auto_llm / test_protocol 会真实调用 LLM，需要环境变量
OPENAI_COMPAT_BASE_URL 和 BAILIAN_API_KEY（阿里百炼）；没设置时这几项会跳过。
"""
import glob
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
NEEDS_LLM = {"test_llm.py", "test_auto_llm.py", "test_protocol.py"}
has_llm = all(os.environ.get(k) for k in ("OPENAI_COMPAT_BASE_URL", "BAILIAN_API_KEY"))

results = []
for path in sorted(glob.glob(os.path.join(HERE, "test_*.py"))):
    name = os.path.basename(path)
    if name in NEEDS_LLM and not has_llm:
        results.append((name, "SKIP（没有 LLM 环境变量）"))
        continue
    try:
        out = subprocess.run([sys.executable, "-X", "utf8", path], capture_output=True, text=True,
                             encoding="utf-8", errors="replace", timeout=300).stdout
    except subprocess.TimeoutExpired:
        results.append((name, "TIMEOUT"))
        continue
    fails = [line for line in out.splitlines() if line.startswith("FAIL")]
    passed = "ALL PASS" in out
    results.append((name, "PASS" if passed and not fails else "FAIL"))
    for line in fails:
        print(f"  {name}: {line}")

width = max(len(n) for n, _ in results)
for name, status in results:
    print(f"{name:<{width}}  {status}")
sys.exit(0 if all(s in ("PASS",) or s.startswith("SKIP") for _, s in results) else 1)
