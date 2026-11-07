"""连续跑三遍测试，确认结果一致。

profiles.py 的 ResourceWarning 会把临时目录名和耗时嵌进输出，
所以比对前先把这两样抹掉，再看三次的输出是否逐字节相同。
"""
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
PY = sys.executable


def run():
    proc = subprocess.run(
        [PY, "-m", "unittest", "discover", "-s", "tests"],
        cwd=ROOT, capture_output=True, encoding="utf-8", errors="replace",
    )
    text = (proc.stderr or "") + (proc.stdout or "")
    return proc.returncode, text


def normalize(text):
    text = re.sub(r"memtest-[a-z0-9_]+", "memtest-X", text)
    text = re.sub(r"Ran \d+ tests in [\d.]+s", "Ran N tests in T.TTTs", text)
    return text


def main():
    codes, norms = [], []
    for i in range(3):
        code, text = run()
        codes.append(code)
        norms.append(normalize(text))
        print("run %d: exit=%d  lines=%d" % (i + 1, code, len(text.splitlines())))
    same = norms[0] == norms[1] == norms[2]
    print("identical after normalization: %s" % same)
    print("all green: %s" % all(c == 0 for c in codes))
    if not same:
        for i in range(3):
            (ROOT / ("run%d.txt" % (i + 1))).write_text(norms[i], encoding="utf-8")


if __name__ == "__main__":
    main()
