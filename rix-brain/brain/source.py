"""按日记时间追溯原文（2026-10-29 用户定的思路：有日记时间就能追根作者源）。

查找顺序：
  1. 纯文本存档 `AI_data/<ai>_data/archive/<key>/<YYYY-MM-DD>.txt`
  2. 该会话的 short_term.json

时间**不必精确**：先按 ±10/15 分钟找，空就把窗口放大到 ±60/90 分钟、再放大到整天；
日期也会往前/后各试一天。这样"大概中午那条"也能捞到。
"""
import glob
import json
import os
import re
import time

import config


def _archive_root():
    return os.path.join(config.data_dir(), "archive")


def _key_folder(key):
    return key.replace(":", "_")


def _find_diary(first_time):
    """按时间反查属于哪个会话：找不到完全相等的，就取 ±6 小时内最近的一条。"""
    base = os.path.join(config.data_dir(), "chats")
    target = int(first_time)
    best_key, best_gap = "", None
    for p in glob.glob(os.path.join(base, "*", "diary.json")):
        try:
            for e in json.load(open(p, encoding="utf-8")):
                ft = int(e.get("first_time") or 0)
                if not ft:
                    continue
                gap = abs(ft - target)
                if gap == 0:
                    return os.path.basename(os.path.dirname(p)).replace("_", ":", 1)
                if gap <= 6 * 3600 and (best_gap is None or gap < best_gap):
                    best_key, best_gap = os.path.basename(os.path.dirname(p)).replace("_", ":", 1), gap
        except Exception:
            continue
    return best_key


def _read_day(key, day):
    """读某天存档，返回 [(ts, line)]。"""
    path = os.path.join(_archive_root(), _key_folder(key), day + ".txt")
    rows = []
    if not os.path.exists(path):
        return rows
    with open(path, encoding="utf-8", errors="ignore") as f:
        for line in f:
            m = re.match(r"\[(\d{2}):(\d{2}):(\d{2})\]", line)
            if not m:
                continue
            try:
                lt = time.mktime(time.strptime("%s %s:%s:%s" % (day, m.group(1), m.group(2), m.group(3)),
                                               "%Y-%m-%d %H:%M:%S"))
            except Exception:
                continue
            rows.append((lt, line.rstrip()))
    return rows


def _entry_range(key, ft):
    """从日记条目里读它记录的 source_from/source_to（压缩损失审计字段）。"""
    try:
        path = os.path.join(config.data_dir(), "chats", _key_folder(key), "diary.json")
        for e in json.load(open(path, encoding="utf-8")):
            if int(e.get("first_time") or 0) != int(ft):
                continue
            a, b = e.get("source_from"), e.get("source_to")
            if a and b:
                return int(a), int(b)
    except Exception:
        pass
    return None


def _gather(key, ft, before_min, after_min):
    """按逐级放大的窗口取原文，返回 (rows, source)。"""
    days = [time.strftime("%Y-%m-%d", time.localtime(ft + d)) for d in (-86400, 0, 86400)]
    rng = _entry_range(key, ft)
    windows = [(before_min, after_min), (60, 90), (12 * 60, 12 * 60)]
    if rng:   # 条目自己记着消费了哪段原文 → 最精确
        windows.insert(0, ((ft - rng[0]) / 60, (rng[1] - ft) / 60))
    for b, a in windows:
        start, end = ft - b * 60, ft + a * 60
        collected = []
        for day in days:
            collected += [r for r in _read_day(key, day) if start <= r[0] <= end]
        if collected:
            collected.sort(key=lambda x: x[0])
            return collected, "archive"
    try:
        st = os.path.join(config.data_dir(), "chats", _key_folder(key), "short_term.json")
        rows = []
        _b, _a = 3600, 90 * 60
        for m in json.load(open(st, encoding="utf-8")):
            t = int(m.get("time") or 0)
            if ft - _b <= t <= ft + _a:
                who = m.get("nickname") or m.get("role") or "?"
                text = str(m.get("content") or "").replace("\n", " ")
                rows.append((t, "[%s] %s：%s" % (time.strftime("%H:%M:%S", time.localtime(t)), who, text)))
        if rows:
            return rows, "short_term"
    except Exception:
        pass
    return [], ""


def get_source(first_time, key="", before_min=10, after_min=15, max_lines=40):
    """取某条日记对应时间段的对话原文（时间可以是个大概）。"""
    ft = int(first_time or 0)
    if not ft:
        return {"ok": False, "reason": "no_time"}
    if not key:
        key = _find_diary(ft)
    if not key:
        return {"ok": False, "reason": "key_not_found", "first_time": ft}

    rows, source = _gather(key, ft, before_min, after_min)
    if not rows:
        return {"ok": False, "reason": "no_source", "key": key,
                "date": time.strftime("%Y-%m-%d", time.localtime(ft)),
                "hint": "这天这个会话既没归档也没在短期记忆里"}
    clipped = rows[-max_lines:]
    return {
        "ok": True,
        "key": key,
        "date": time.strftime("%Y-%m-%d", time.localtime(clipped[0][0])),
        "window": "%s ~ %s" % (time.strftime("%m-%d %H:%M", time.localtime(clipped[0][0])),
                                time.strftime("%H:%M", time.localtime(clipped[-1][0]))),
        "lines": len(clipped),
        "source": source,
        "text": "\n".join(r[1] for r in clipped),
    }


def _query_terms(query):
    q = str(query or "")
    terms = set()
    for w in re.findall(r"[A-Za-z]{2,}|\d+", q):
        terms.add(w.lower())
    for run in re.findall(r"[\u4e00-\u9fff]{2,}", q):
        for n in (2, 3, 4):
            for i in range(0, max(1, len(run) - n + 1)):
                terms.add(run[i:i + n])
    return terms


def excerpt(first_time, key, query, max_lines=10, max_chars=600, before_min=10, after_min=15):
    """在原文里挑出与当前对话最贴合的连续几行。"""
    ft = int(first_time or 0)
    if not ft:
        return ""
    if not key:
        key = _find_diary(ft)
    if not key:
        return ""
    rows, _src = _gather(key, ft, before_min, after_min)
    if not rows:
        return ""
    terms = _query_terms(query)
    if not terms:
        return "\n".join(r[1] for r in rows[-max_lines:])[:max_chars]

    scores = [sum(1 for t in terms if t in line.lower()) for _, line in rows]
    best_i, best_score = 0, -1
    for i in range(len(rows)):
        sc = sum(scores[i:i + max_lines])
        if sc > best_score:
            best_score, best_i = sc, i
    window = rows[best_i:best_i + max_lines] if best_score > 0 else rows[-max_lines:]
    return "\n".join(r[1] for r in window)[:max_chars]
