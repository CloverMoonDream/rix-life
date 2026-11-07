"""AI的小抽屉：一个只放 txt 的文件夹，她自己写、自己翻（2026-10-29 用户要的）。

和「记忆」的区别：
  · 记忆（rix-brain）是**自动沉淀 + 检索**的，她不能直接改结构；
  · 抽屉是**她主动整理**的地方——想写什么写什么，按文件名找回来。

硬规矩（用户定）：**文件名必须一眼看懂里面是什么**，例如
  `2026-10-29-用户的高数与风扇.txt`、`关于作者和我的关系.txt`
不合法（如 `1.txt`、`笔记.txt`、`新文件.txt`）会被工具拒绝。

存储：D:\\AI\\笔记\\   （UTF-8 纯文本，只收 .txt）
"""
import os
import re
import time

ROOT = os.path.join("D:\\", "AI", "笔记")
MAX_WRITE = 200_000      # 单文件上限（字符）
MAX_READ = 6000          # 单次读回上限（字符）

_BAD_NAMES = {"笔记", "txt", "文本", "新文件", "新建文本文档", "untitled", "note", "notes", "todo", "memo", "abc"}
_BAD_CHARS = re.compile(r'[\\/:*?"<>|\r\n\t]')


def _dir():
    os.makedirs(ROOT, exist_ok=True)
    return ROOT


def _clean_name(name):
    raw = str(name or "").strip()
    raw = _BAD_CHARS.sub("_", raw)
    if not raw.lower().endswith(".txt"):
        raw += ".txt"
    return raw


def _check_name(filename):
    base = os.path.splitext(filename)[0]
    core = re.sub(r"[\d\-_ .年月日]", "", base)
    if len(core) < 4:
        return "文件名太短，看不出内容。要写成能一眼看懂的一句话，比如「2026-10-29-用户的高数与风扇.txt」"
    if base.strip().lower() in _BAD_NAMES:
        return "这个名字太泛（%s），换个能看出内容的" % base
    return ""


def write_note(name, content, mode="append"):
    """写一条 txt。mode=append 追加（同一主题继续写）；overwrite 覆盖。"""
    fname = _clean_name(name)
    err = _check_name(fname)
    if err:
        return {"ok": False, "reason": "bad_name", "hint": err, "name": fname}
    text = str(content or "").strip()
    if not text:
        return {"ok": False, "reason": "empty", "name": fname}
    if len(text) > MAX_WRITE:
        return {"ok": False, "reason": "too_long", "limit": MAX_WRITE, "chars": len(text)}

    path = os.path.join(_dir(), fname)
    mode = "overwrite" if str(mode).lower().startswith("over") else "append"
    try:
        if mode == "overwrite" or not os.path.exists(path):
            with open(path, "w", encoding="utf-8") as f:
                f.write(text + "\n")
            created = True
        else:
            with open(path, "a", encoding="utf-8") as f:
                f.write("\n---\n" + time.strftime("%Y-%m-%d %H:%M") + "\n" + text + "\n")
            created = False
        return {"ok": True, "name": fname, "mode": mode, "created": created,
                "chars": len(text), "path": path}
    except Exception as e:
        return {"ok": False, "reason": "write_error", "error": str(e)[:120]}


def list_notes(limit=50):
    """列出她自己写的东西：文件名 + 大小 + 修改时间 + 开头 40 字（方便挑）。"""
    d = _dir()
    rows = []
    for fn in os.listdir(d):
        if not fn.lower().endswith(".txt"):
            continue
        p = os.path.join(d, fn)
        try:
            st = os.stat(p)
            with open(p, encoding="utf-8", errors="ignore") as f:
                head = f.read(200).replace("\n", " ").strip()
        except Exception:
            continue
        rows.append({
            "name": fn,
            "kb": round(st.st_size / 1024, 1),
            "updated": time.strftime("%m-%d %H:%M", time.localtime(st.st_mtime)),
            "preview": head[:40],
        })
    rows.sort(key=lambda r: r["updated"], reverse=True)
    return rows[: max(1, int(limit))]


def read_note(name):
    """按文件名读回来（超长只回前 6000 字，并说明被截断）。"""
    fname = _clean_name(name)
    path = os.path.join(_dir(), fname)
    if not os.path.exists(path):
        return {"ok": False, "reason": "not_found", "name": fname, "hint": "用 note_list 看看有哪些"}
    try:
        with open(path, encoding="utf-8", errors="ignore") as f:
            text = f.read(MAX_READ + 1)
    except Exception as e:
        return {"ok": False, "reason": "read_error", "error": str(e)[:120]}
    truncated = len(text) > MAX_READ
    return {"ok": True, "name": fname, "content": text[:MAX_READ], "truncated": truncated,
            "chars": len(text[:MAX_READ])}
