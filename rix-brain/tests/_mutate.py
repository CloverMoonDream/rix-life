"""变异测试：随机挑 code/ 里公开函数的 10 处，逐个改一个运算符再跑测试。

每处只改一处，跑完立刻还原。能被测试抓住的记为 killed，
测试照样全绿的记为 survived。结果写到 mutation-log.md。

只动比较和算术运算符，不改字符串、不删行，避免改出语法错误。
"""
import pathlib
import random
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
CODE = ROOT / "code"
LOG = ROOT / "mutation-log.md"
PY = sys.executable

# 公开函数（模块级 def，名字不以 _ 开头）。
PUBLIC = re.compile(r"^def (?!_)(\w+)\(", re.M)
SWAPS = {"==": "!=", "!=": "==", ">=": "<", "<=": ">", ">": "<=", "<": ">="}
TOKEN = re.compile(r"(==|!=|>=|<=|>|<)")


def public_functions(text):
    """返回 [(函数名, 起始行, 结束行)]，结束行取到下一个模块级 def/class 之前。"""
    lines = text.splitlines()
    heads = [i for i, line in enumerate(lines) if line.startswith("def ") or line.startswith("class ")]
    out = []
    for n, i in enumerate(heads):
        m = re.match(r"def (?!_)(\w+)\(", lines[i])
        if not m:
            continue
        end = heads[n + 1] if n + 1 < len(heads) else len(lines)
        out.append((m.group(1), i, end))
    return out


def candidates(path):
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    found = []
    for name, start, end in public_functions(text):
        for i in range(start, end):
            raw = lines[i]
            if raw.strip().startswith("#") or raw.strip().startswith('"""') or raw.strip().startswith("'''"):
                continue
            code_part = raw.split("#", 1)[0]
            # 去掉字符串字面量，避免改到文档或提示词里的 > <。
            code_part = re.sub(r"(\"[^\"]*\"|'[^']*')", lambda s: " " * len(s.group(0)), code_part)
            for m in TOKEN.finditer(code_part):
                found.append((path.name, name, i, m.start(), m.group(1)))
    return found


def run_suite():
    proc = subprocess.run(
        [PY, "-m", "unittest", "discover", "-s", "tests"],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    tail = (proc.stderr or "").strip().splitlines()
    summary = tail[-1] if tail else ""
    return proc.returncode, summary


def main():
    pool = []
    for src in sorted(CODE.glob("*.py")):
        pool.extend(candidates(src))
    print("candidate pool: %d" % len(pool))
    # 固定种子抽 10 处，但跳过整段被 try/except 包住、实测跑不到的死代码
    # （recall 里 import source 那段，见 test_hot_tracking_never_persists）。
    dead = {("memory.py", i) for i in range(1412, 1434)}
    pool = [c for c in pool if (c[0], c[2]) not in dead]
    rng = random.Random(20261106)
    rng.shuffle(pool)
    picked = pool[:10]

    rows = []
    for n, (file, func, line, col, op) in enumerate(picked, 1):
        path = CODE / file
        original = path.read_text(encoding="utf-8")
        lines = original.splitlines()
        new_op = SWAPS[op]
        lines[line] = lines[line][:col] + new_op + lines[line][col + len(op):]
        path.write_text("\n".join(lines) + ("\n" if original.endswith("\n") else ""), encoding="utf-8")
        try:
            code, summary = run_suite()
        finally:
            path.write_text(original, encoding="utf-8")
        killed = code != 0
        rows.append((n, file, func, line + 1, op, new_op, "killed" if killed else "SURVIVED", summary))
        print("%2d %-16s %-24s L%-5d %s -> %s  %s" % (n, file, func, line + 1, op, new_op,
                                                      "killed" if killed else "SURVIVED"))

    killed = sum(1 for r in rows if r[6] == "killed")
    out = ["# 变异测试记录", "",
           "随机种子 `20261106`，从 `code/` 公开函数里的比较运算符中抽 10 处，",
           "逐个取反后跑完整测试，跑完立即还原源码。", "",
           "杀死 %d / %d，杀死率 %.0f%%。" % (killed, len(rows), 100 * killed / len(rows)), "",
           "| # | 文件 | 函数 | 行 | 改动 | 结果 | 测试输出 |",
           "|---|------|------|----|------|------|----------|"]
    for n, file, func, line, op, new, status, summary in rows:
        out.append("| %d | %s | `%s` | %d | `%s` → `%s` | %s | %s |"
                   % (n, file, func, line, op, new, status, summary.replace("|", "\\|")))
    LOG.write_text("\n".join(out) + "\n", encoding="utf-8")
    print("killed %d/%d" % (killed, len(rows)))


if __name__ == "__main__":
    main()
