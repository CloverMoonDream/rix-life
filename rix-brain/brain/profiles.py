"""用户画像（2026-10-30 用户定，P1）。

一个身份一份 JSON，存在 `AI_data/<ai>_data/profiles/<key>.json`。
她的工具是「想起来才用」——不强制每轮，但想起一个人时能翻、能补。

字段（都是列表，写入时去重合并）：
  name        称呼（她怎么叫这个人）
  traits      性格/特征
  preferences 喜欢什么
  taboos      不喜欢/别碰的
  routines    作息/习惯
  promises    约定过的事
  notes       其他碎事
"""
import json
import os
import re
import time

import config

FIELDS = ("traits", "preferences", "taboos", "routines", "promises", "notes")
_MAX_PER_FIELD = 40


def _dir():
    d = os.path.join(config.data_dir(), "profiles")
    os.makedirs(d, exist_ok=True)
    return d


def _path(key):
    k = str(key or "").strip() or "unknown"
    safe = re.sub(r"[^0-9A-Za-z_:\u4e00-\u9fff-]", "_", k).replace(":", "_")
    return os.path.join(_dir(), safe + ".json")


def read(key):
    """读一个人的画像（没有就返回空壳，不报错）。"""
    k = str(key or "").strip()
    p = _path(k)
    data = {"key": k, "name": "", "updated_at": 0}
    for f in FIELDS:
        data[f] = []
    try:
        if os.path.exists(p):
            with open(p, encoding="utf-8") as f:  # 2026-11-06：原来不关句柄
                raw = json.load(f)
            if isinstance(raw, dict):
                data.update({x: raw.get(x, data[x]) for x in data})
    except Exception:
        pass
    return data


def write(key, field, text, name=""):
    """往画像里补一条（同一字段内去重）。field 见 FIELDS；也可传 name。"""
    k = str(key or "").strip()
    if not k or k == "unknown":
        return {"ok": False, "reason": "need_key",
                "hint": "要写进谁的画像？请传会话 key（如 private:10001）或对方昵称。"}
    text = str(text or "").strip()
    f = str(field or "").strip().lower()
    if f == "name":
        data = read(k)
        data["name"] = text
        data["updated_at"] = int(time.time())
        _save(k, data)
        return {"ok": True, "key": k, "field": "name", "value": text}
    if f not in FIELDS:
        return {"ok": False, "reason": "bad_field",
                "hint": "field 只能是 " + " / ".join(FIELDS) + " 或 name"}
    if not text:
        return {"ok": False, "reason": "empty"}
    data = read(k)
    items = [str(x) for x in data.get(f, [])]
    if text not in items:
        items.append(text)
    data[f] = items[-_MAX_PER_FIELD:]
    if name:
        data["name"] = str(name).strip()
    data["updated_at"] = int(time.time())
    _save(k, data)
    return {"ok": True, "key": k, "field": f, "value": text, "total": len(data[f])}


def _save(key, data):
    p = _path(key)
    try:
        if os.path.exists(p):      # 写前留一份，改坏了能退
            import shutil
            shutil.copyfile(p, p + ".bak")
    except Exception:
        pass
    with open(p, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=1)


def listing(limit=30):
    rows = []
    for fn in os.listdir(_dir()):
        if not fn.endswith(".json"):
            continue
        try:
            with open(os.path.join(_dir(), fn), encoding="utf-8") as f:  # 2026-11-06：原来不关句柄
                d = json.load(f)
        except Exception:
            continue
        rows.append({"key": d.get("key", ""), "name": d.get("name", ""),
                     "updated_at": d.get("updated_at", 0),
                     "items": sum(len(d.get(x) or []) for x in FIELDS)})
    rows.sort(key=lambda r: r["updated_at"], reverse=True)
    return rows[:limit]
