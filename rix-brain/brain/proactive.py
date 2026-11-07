"""冷暴力惩罚 + 主动概率硬闸门（用户 2026-10-29 定，仅私聊）。

规则（写死在代码里，不交给 AI 判断）：
  · AI**主动**开口后，对方在 5 分钟内没回 → 好感 -1
  · 20 分钟没回 → -3（补到 3）
  · 60 分钟没回 → -5（补到 5）
  · 超过 1 小时按 1 小时算，不再加码
  · 被这样晾过一次之后，**她对该用户主动说话的概率钉死在 10%**，
    直到"该用户好感满 100"或"期间好感累计 +5"才解除

状态文件：AI_data/<ai>_data/proactive.json
  { "private:123": {"sent_ts":..., "penalty_ts":..., "applied": 3,
                    "cap_active": true, "cap_base_like": 80, "cap_base_ts": ...} }

桥接侧只要读这个文件里的 cap_active 决定是否把概率压到 0.1，
本模块负责判定与扣分。
"""
import json
import os
import time

import config

TIERS = [(60 * 60, 5), (20 * 60, 3), (5 * 60, 1)]   # (秒, 累计扣分)


def _enabled():
    """冷暴力惩罚总开关（2026-11-03 AI提出、用户转达批准关掉）。

    她要的不是「等待没有代价」，是「代价不该由系统替她扣」——
    「等不等、值不值得等，我自己判断」。关掉后：不扣分、不封 10% 概率。
    想恢复：config.json 里 emotion.proactive_penalty 设回 true。
    """
    try:
        cfg = config.load_config()
        return bool(cfg.get("emotion", {}).get("proactive_penalty", False))
    except Exception:
        return False
CAP_PROBABILITY = 0.1
QUIET_START, QUIET_END = 0, 8   # 免罚时段（本地时间，左闭右开）


def _path():
    d = config.data_dir()
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, "proactive.json")


def _load():
    try:
        with open(_path(), encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save(data):
    with open(_path(), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)


def _tier(seconds):
    """返回该等待时长对应的累计扣分（0 表示还没到 5 分钟）。"""
    for limit, points in TIERS:
        if seconds >= limit:
            return points
    return 0


def _like_kv(key):
    """直接读写 mood.json 里的 like_points（硬扣，不经模型）。"""
    import emotion

    c = config.load_config()
    e = emotion.Emotion(c["ai_name"], c["user_name"])
    with emotion._mood_lock:
        mood = e._load()
        likes = mood.get("like_points")
        if not isinstance(likes, dict):
            likes = {}
        bucket = emotion._norm_identity(key) if hasattr(emotion, "_norm_identity") else key
        cur = int(likes.get(bucket, 0) or 0)
        return e, mood, likes, bucket, cur


def _apply_like_delta(key, delta):
    import emotion

    c = config.load_config()
    e = emotion.Emotion(c["ai_name"], c["user_name"])
    with emotion._mood_lock:
        mood = e._load()
        likes = mood.get("like_points")
        if not isinstance(likes, dict):
            likes = {}
        bucket = emotion._norm_identity(key) if hasattr(emotion, "_norm_identity") else key
        old = int(likes.get(bucket, 0) or 0)
        new = max(0, min(100, old + int(delta)))
        likes[bucket] = new
        mood["like_points"] = likes
        mood["like_point"] = new
        mood["like_point_last_key"] = bucket
        e._save(mood)
    return old, new


# ---------- 对外 ----------

def sent(key):
    """AI刚刚主动开了一次口（仅私聊调用）。"""
    k = str(key or "")
    if not k.startswith("private:"):
        return {"ok": False, "reason": "private_only"}
    data = _load()
    rec = data.get(k, {})
    rec.update({"sent_ts": int(time.time()), "penalty_ts": None, "applied": 0})
    data[k] = rec
    _save(data)
    return {"ok": True, "key": k, "sent_ts": rec["sent_ts"]}


def settle(key, now_ts=None):
    """有人回话/后台巡检时调用：按等待时长扣分，必要时开启 10% 闸门。"""
    k = str(key or "")
    if not k.startswith("private:"):
        return {"ok": False, "reason": "private_only"}
    now = int(now_ts or time.time())
    data = _load()
    rec = data.get(k)
    if not rec or not rec.get("sent_ts"):
        return {"ok": False, "reason": "no_pending"}
    if not _enabled():
        # 惩罚已关：只清掉待结算状态，不扣好感、不封概率
        rec["penalty_ts"] = None
        rec["applied"] = 0
        data[k] = rec
        _save(data)
        return {"ok": True, "changed": False, "disabled": True,
                "wait_min": (now - int(rec["sent_ts"])) // 60}
    wait = now - int(rec["sent_ts"])
    target = _tier(wait)
    applied = int(rec.get("applied") or 0)
    if target <= applied:
        return {"ok": True, "changed": False, "wait_min": wait // 60, "applied": applied}

    delta = -(target - applied)
    old, new = _apply_like_delta(k, delta)
    rec["applied"] = target
    rec["penalty_ts"] = now
    if not rec.get("cap_active"):
        rec["cap_active"] = True
        rec["cap_base_like"] = new
        rec["cap_base_ts"] = now
    data[k] = rec
    _save(data)
    return {"ok": True, "changed": True, "wait_min": wait // 60,
            "penalty": delta, "like_before": old, "like_after": new,
            "cap_active": True}


def _in_quiet(ts):
    try:
        h = time.localtime(int(ts)).tm_hour
    except Exception:
        return False
    return QUIET_START <= h < QUIET_END


def answered(key, now_ts=None):
    """用户回话了。规则（用户 2026-10-29，第二版）：

    · 主动开口落在免罚时段（00:00–08:00）→ 全免，不扣不锁
    · 1 小时内回 → **照扣**，按等多久算：≥5 分钟 −1、≥20 分钟 −3、≥60 分钟 −5
    · 超过 1 小时才回 → **一律 −5**，并且绑定 10% 闸门
    """
    k = str(key or "")
    now = int(now_ts or time.time())
    data = _load()
    rec = data.get(k)
    if not rec or not rec.get("sent_ts"):
        return {"ok": False, "reason": "no_pending"}
    sent_ts = int(rec["sent_ts"])
    gap = now - sent_ts
    applied = int(rec.get("applied") or 0)
    rec["sent_ts"] = None
    rec["penalty_ts"] = None
    rec["applied"] = 0

    if _in_quiet(sent_ts):
        data[k] = rec
        _save(data)
        return {"ok": True, "exempt": "quiet_hours", "gap_min": gap // 60}

    target = _tier(gap) if gap <= 60 * 60 else 5
    delta = -(target - applied)
    old_like = new_like = None
    if delta:
        old_like, new_like = _apply_like_delta(k, delta)

    late = gap > 60 * 60
    if late and not rec.get("cap_active"):
        rec["cap_active"] = True
        rec["cap_base_like"] = new_like if new_like is not None else rec.get("cap_base_like")
        rec["cap_base_ts"] = now
        rec["cap_reason"] = "late_reply"

    data[k] = rec
    _save(data)
    return {"ok": True, "gap_min": gap // 60, "penalty": delta if delta else 0,
            "like_before": old_like, "like_after": new_like,
            "cap_active": bool(rec.get("cap_active"))}


def gate(key):
    """桥接侧问一句：这个人的主动概率要不要压到 10%？"""
    k = str(key or "")
    if not _enabled():
        return {"cap": None, "cap_active": False, "disabled": True}
    data = _load()
    rec = data.get(k) or {}
    if not rec.get("cap_active"):
        return {"cap": None, "cap_active": False}
    # 解除条件：好感满 100，或自设闸门起好感累计 +5
    try:
        _, _, _, _, cur = _like_kv(k)
    except Exception:
        cur = None
    base = rec.get("cap_base_like") if rec.get("cap_base_like") is not None else 0
    base_ts = int(rec.get("cap_base_ts") or 0)
    # 解除条件（任一）：好感比封闸时涨了 5 点；好感真涨回满（封闸时不满）；封闸满 24 小时自动解开
    grew = cur is not None and cur - int(base) >= 5
    refilled = cur is not None and cur >= 100 and int(base) < 100
    expired = base_ts and (time.time() - base_ts) >= 24 * 3600
    target = min(100, int(base) + 5)
    if grew or refilled or expired:
        rec["cap_active"] = False
        rec["cap_released_at"] = int(time.time())
        data[k] = rec
        _save(data)
        return {"cap": None, "cap_active": False, "released": True}
    return {"cap": CAP_PROBABILITY, "cap_active": True, "like": cur, "release_at": target}


def _replied_since(key, ts):
    """这个人有没有在 ts 之后回过话（读短期记忆，不依赖桥接通知）。"""
    try:
        path = os.path.join(config.data_dir(), "chats", key.replace(":", "_"), "short_term.json")
        with open(path, encoding="utf-8") as f:
            rows = json.load(f)
        for m in rows:
            if str(m.get("role") or "") == "用户" and int(m.get("time") or 0) > int(ts):
                return True
    except Exception:
        return False
    return False


def sweep():
    """后台巡检：等够 5/20/60 分钟就结算；对方其实回过的直接清掉，不扣分。"""
    data = _load()
    out = []
    for k, rec in list(data.items()):
        if not isinstance(rec, dict) or not rec.get("sent_ts"):
            continue
        sent_ts = int(rec["sent_ts"])
        if _replied_since(k, sent_ts):
            r = answered(k)
            if r.get("cap_active"):
                out.append({"key": k, **r})
            continue
        wait = int(time.time()) - sent_ts
        if _tier(wait) > int(rec.get("applied") or 0):
            r = settle(k)
            if r.get("changed"):
                out.append({"key": k, **r})
    return out
