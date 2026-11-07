"""用 trace 的 .cover 和源码算出真实行覆盖率。

trace 只把执行过的行写进 .cover，所以文件里的 miss 恒为 0，
不能直接拿它的数字。这里以 AST 统计源文件里的可执行行（去掉空行、
注释、文档字符串），再看其中有多少行在 .cover 里有计数。
"""
import ast
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
COV = ROOT / ".coverage"
MODS = ["memory", "vectors", "attributes", "profiles", "notebook", "emotion_memory", "config"]


def executable(path):
    src = path.read_text(encoding="utf-8")
    tree = ast.parse(src)
    doc = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            body = node.body[0] if node.body else None
            if (isinstance(body, ast.Expr)
                    and isinstance(getattr(body, "value", None), ast.Constant)
                    and isinstance(body.value.value, str)):
                for n in range(body.lineno, (body.end_lineno or body.lineno) + 1):
                    doc.add(n)
    text = src.splitlines()
    keep = set()
    for node in ast.walk(tree):
        start = getattr(node, "lineno", 0) or 0
        end = getattr(node, "end_lineno", 0) or 0
        for n in range(start, end + 1):
            if not n or n in doc or n > len(text):
                continue
            s = text[n - 1].strip()
            if s and not s.startswith("#"):
                keep.add(n)
    return keep


def main():
    total_exe = total_hit = 0
    for name in MODS:
        exe = executable(ROOT / "code" / (name + ".py"))
        # .cover 的格式是 "    <计数>: <源码>"，行号就是它自己的行号。
        # 计数为空的行没有被执行。
        hit = set()
        for n, line in enumerate((COV / (name + ".cover")).read_text(encoding="utf-8").splitlines(), 1):
            m = re.match(r"\s*(\d+):", line)
            if m and int(m.group(1)) > 0:
                hit.add(n)
        covered = len(exe & hit)
        total_exe += len(exe)
        total_hit += covered
        print("%-16s %5d/%-5d %6.1f%%" % (name, covered, len(exe), 100 * covered / len(exe)))
    print("%-16s %5d/%-5d %6.1f%%" % ("TOTAL", total_hit, total_exe, 100 * total_hit / total_exe))


if __name__ == "__main__":
    main()
