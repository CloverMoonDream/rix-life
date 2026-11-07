"""列出 memory.py 里覆盖率最低的函数，方便决定补哪几条测试。"""
import ast
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
src_path = ROOT / "code" / "memory.py"
text = src_path.read_text(encoding="utf-8").splitlines()
cover = (ROOT / ".coverage" / "memory.cover").read_text(encoding="utf-8").splitlines()
hit = set()
for n, line in enumerate(cover, 1):
    m = re.match(r"\s*(\d+):", line)
    if m and int(m.group(1)) > 0:
        hit.add(n)

tree = ast.parse("\n".join(text))
rows = []
for node in ast.walk(tree):
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.col_offset == 0:
        body = range(node.body[0].lineno, (node.end_lineno or node.lineno) + 1)
        exe = [n for n in body if text[n - 1].strip() and not text[n - 1].strip().startswith("#")]
        got = sum(1 for n in exe if n in hit)
        rows.append((got / len(exe) if exe else 1, node.name, got, len(exe), node.lineno))
rows.sort()
for pct, name, got, total, line in rows[:25]:
    print("%5.0f%%  %-28s %4d/%-4d  L%d" % (100 * pct, name, got, total, line))
