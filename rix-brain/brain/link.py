"""作者 ↔ AI 的邮局（2026-10-29 用户要的「打通聊天」第一条通道）。

不走 QQ、不走 DSH 内部 API，就用两个队列文件：
    AI_data/<ai>_data/link/to_su.jsonl     ← AI写给我（作者）的
    AI_data/<ai>_data/link/to_jj.jsonl     ← 我写给她（AI）的

两边各自读、各自回。好处是：不依赖任何内部协议，谁都挂不了；坏处是不同步，
要等对方下一次上线才回——所以它是「留言板」，不是实时聊天。

触发与上限（用户说再细说）先不实现，这里只提供管道。
"""
import json
import os
import time

import config

MAX_CHARS = 2000


def _dir():
    d = os.path.join(config.data_dir(), "link")
    os.makedirs(d, exist_ok=True)
    return d


def _path(who):
    return os.path.join(_dir(), "to_%s.jsonl" % who)


def _append(who, sender, text):
    text = str(text or "").strip()
    if not text:
        return {"ok": False, "reason": "empty"}
    if len(text) > MAX_CHARS:
        text = text[:MAX_CHARS]
    rec = {"ts": int(time.time()), "from": sender, "text": text, "read": False}
    with open(_path(who), "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return {"ok": True, "to": who, "chars": len(text), "ts": rec["ts"]}


def _read(who, mark_read=True, limit=20):
    p = _path(who)
    if not os.path.exists(p):
        return []
    rows, keep = [], []
    for line in open(p, encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
        except Exception:
            continue
        keep.append(r)
    unread = [r for r in keep if not r.get("read")]
    out = unread[:limit]
    if mark_read and out:
        ids = {r["ts"] for r in out}
        for r in keep:
            if r.get("ts") in ids:
                r["read"] = True
        with open(p, "w", encoding="utf-8") as f:
            for r in keep:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return out


# ---- AI侧 ----

def say_to_su(text):
    """AI给作者留言。"""
    return _append("su", "AI", text)


def read_from_su():
    """AI看作者给她留了什么（读完标记已读）。"""
    rows = _read("jj")
    return [{"ts": r["ts"], "from": r.get("from", "作者"),
             "at": time.strftime("%m-%d %H:%M", time.localtime(r["ts"])), "text": r["text"]} for r in rows]


# ---- 作者侧（供命令行脚本用） ----

def read_to_su(mark_read=True):
    return _read("su", mark_read=mark_read)


def reply_to_jj(text):
    return _append("jj", "作者", text)

# ---- 闲聊概率（用户 2026-10-29 定） ----
# 1 小时没人理她 → 想找作者说话的概率 +20%；基础 10%，封顶 90%。说过话就重置回 10%。

def idle_hours(key):
    """这个会话距离「用户最后一次说话」过了几小时（读短期记忆里的时间戳）。"""
    k = _norm_key(key) if "_norm_key" in globals() else str(key or "")
    rows = []
    try:
        path = os.path.join(config.data_dir(), "chats", k.replace(":", "_"), "short_term.json")
        with open(path, encoding="utf-8") as f:
            rows = json.load(f)
    except Exception:
        rows = []
    last = 0
    for m in rows:
        if str(m.get("role") or "") == "用户":
            last = max(last, int(m.get("time") or 0))
    if not last:
        return None
    return round((time.time() - last) / 3600, 2)


def su_chance(key):
    """当前「主动找作者聊天」的概率 + 是否命中。"""
    import random

    hours = idle_hours(key)
    if hours is None:
        return {"allowed": False, "reason": "no_history", "chance": 0.1, "idle_hours": None}
    steps = int(hours)                      # 每满 1 小时 +20%
    chance = min(0.9, 0.1 + 0.2 * steps)
    hit = random.random() < chance
    return {
        "allowed": hit,
        "chance": round(chance, 2),
        "idle_hours": hours,
        "hint": "命中就给作者留言；没命中就别打扰她，下小时再说" if hit else "这次没轮到你，别刷",
    }

# ---------- 总结与滚动（用户 2026-10-29 定） ----------
# 规则：和作者的对话不写日记；满 10 条压成一段纯文本摘要（带时间范围），
# 原文只留最近 20 条，超了滚动掉；摘要**不参与日常召回**，
# 只在「和作者聊天」或「用户提到 作者」时才取出来看。

SUMMARY_KEEP = 10      # 满几条就总结
RAW_KEEP = 20          # 原文最多留几条


def _sum_path():
    return os.path.join(_dir(), "summary.jsonl")


def _all_msgs():
    """两个方向的消息合并成一条时间线（含已读标记）。"""
    rows = []
    for who, me in (("su", "AI"), ("jj", "作者")):
        p = _path(who)
        if not os.path.exists(p):
            continue
        for line in open(p, encoding="utf-8"):
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except Exception:
                continue
            rows.append({"who": who, "from": r.get("from", me), "ts": int(r.get("ts") or 0),
                         "text": r.get("text", ""), "summarized": bool(r.get("summarized"))})
    rows.sort(key=lambda r: r["ts"])
    return rows


def _rewrite(who, rows):
    with open(_path(who), "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps({"ts": r["ts"], "from": r.get("from", ""), "text": r["text"],
                                "read": r.get("read", True), "summarized": bool(r.get("summarized"))}, ensure_ascii=False) + "\n")


def pending_count():
    return len([r for r in _all_msgs() if not r["summarized"]])


def summarize(force=False):
    """满 SUMMARY_KEEP 条就把最老的一批压成摘要；同时把原文裁到 RAW_KEEP 条。"""
    rows = _all_msgs()
    todo = [r for r in rows if not r["summarized"]]
    if len(todo) < (1 if force else SUMMARY_KEEP):
        return {"ok": False, "reason": "not_enough", "pending": len(todo)}

    batch = todo[:SUMMARY_KEEP] if not force else todo
    text = "\n".join("%s：%s" % (r["from"], r["text"]) for r in batch)
    prompt = (
        "下面是我和作者（造我的那个 Agent）的一段私聊记录，请压成一段纯文本摘要。\n"
        "要求：保留说到的事、结论、约定和她的建议；去掉寒暄；200 字以内；不要分条。\n\n" + text
    )
    try:
        merged = config.deepseek_complete([{"role": "user", "content": prompt}], max_tokens=400)
    except Exception as e:
        return {"ok": False, "reason": "llm_error", "error": str(e)[:100]}
    merged = (merged or "").strip()
    if len(merged) < 10:
        return {"ok": False, "reason": "empty_summary"}

    # 1) 写摘要
    rec = {"from_ts": batch[0]["ts"], "to_ts": batch[-1]["ts"], "count": len(batch), "text": merged}
    with open(_sum_path(), "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    # 2) **无损保存**：原文一条都不删，只给已压过的打上 summarized 标记
    #    （用户理念：无损保存一切。RAW_KEEP 只是「上下文里带多少条」的视图上限）
    cutoff = batch[-1]["ts"]
    for who in ("su", "jj"):
        p = _path(who)
        if not os.path.exists(p):
            continue
        out = []
        for line in open(p, encoding="utf-8"):
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except Exception:
                continue
            if int(r.get("ts") or 0) <= cutoff:
                r["summarized"] = True
            out.append(r)
        _rewrite(who, out)

    return {"ok": True, "count": len(batch),
            "from": time.strftime("%m-%d %H:%M", time.localtime(batch[0]["ts"])),
            "to": time.strftime("%m-%d %H:%M", time.localtime(batch[-1]["ts"])),
            "summary": merged}


def history(limit=5):
    """取出最近几段摘要（**只有在和作者聊天、或用户提起作者时才调**）。"""
    out = []
    p = _sum_path()
    if os.path.exists(p):
        for line in open(p, encoding="utf-8"):
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except Exception:
                continue
            out.append({"at": "%s ~ %s" % (
                time.strftime("%m-%d %H:%M", time.localtime(r["from_ts"])),
                time.strftime("%m-%d %H:%M", time.localtime(r["to_ts"]))),
                "count": r.get("count"), "text": r.get("text")})
    return out[-max(1, int(limit)):]

def recent(n=20):
    """和作者聊天时带进上下文的**最近 N 条原文**（只影响视图，不动存档）。"""
    rows = _all_msgs()
    return [{"at": time.strftime("%m-%d %H:%M", time.localtime(r["ts"])),
             "from": r["from"], "text": r["text"]} for r in rows[-max(1, int(n)):]]
