"""人物图鉴：给AI一个「认人」的档案库（2026-10-28 用户提的）。

流程（打算这么接）：
  1. 收到图片 → 视觉模型先报「关键词」（发色 / 瞳色 / 发饰 / 服装 / 画风）
  2. 用关键词查本图鉴 → 拿出候选人
  3. 让视觉模型把新图与候选人比对 → 判断是不是同一个人
  4. 认错时用 correct() 修正（和记忆修正走同一条路）

存储：
  AI_data/<ai>_data/figures/
    index.json          条目索引（昵称 / 关键词 / 描述 / 图片文件名 / 命中次数）
    <id>.jpg|png        有图就存图（桥接现在的临时目录会清空，需要另外落盘）

注意：桥接目前不把收到的图片落盘（临时目录用完即删），所以 image_path
暂时只能由手动/后续改动填；没有图时，图鉴条目靠「关键词 + 描述」工作。
"""
import json
import os
import shutil
import time
import uuid

import config

_LOCK = None


def _new_id():
    return "fig-" + uuid.uuid4().hex[:8]


def _dir():
    d = os.path.join(config.data_dir(), "figures")
    os.makedirs(d, exist_ok=True)
    return d


def _index_path():
    return os.path.join(_dir(), "index.json")


def _load():
    try:
        with open(_index_path(), encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _save(items):
    with open(_index_path(), "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=1)


def _norm_keywords(keywords):
    if isinstance(keywords, str):
        parts = keywords.replace("，", ",").replace("、", ",").split(",")
    else:
        parts = list(keywords or [])
    return [str(p).strip() for p in parts if str(p).strip()]


_FIGURE_MODE_TTL = 600      # 10 分钟内有效


def _figure_mode():
    """桥接写下的「认人场景」标记是否还新鲜（2026-10-30 用户定）。"""
    try:
        fp = os.path.join(config.data_dir(), "figure_mode.json")
        with open(fp, encoding="utf-8") as f:
            r = json.load(f)
        age = time.time() - float(r.get("at") or 0) / 1000.0
        return {"on": age <= _FIGURE_MODE_TTL, "key": r.get("key", ""), "age": int(age)}
    except Exception:
        return {"on": False, "key": "", "age": -1}


def remember(nickname, keywords, description="", image_path=""):
    _m = _figure_mode()
    if not _m["on"]:
        return {"ok": False, "reason": "not_figure_mode",
                "hint": "现在不是在认人：只有对方问「这是谁/认识吗/这个呢」这类问题时才查图鉴。"}
    """新增/更新一个图鉴条目。同一昵称重复添加就合并关键词。"""
    items = _load()
    kws = _norm_keywords(keywords)
    nick = str(nickname or "").strip() or "未知"
    existing = next((x for x in items if x.get("nickname") == nick), None)
    now = int(time.time())

    img_name = ""
    if image_path and os.path.exists(image_path):
        ext = os.path.splitext(image_path)[1].lower() or ".jpg"
        fid = existing["id"] if existing else _new_id()
        img_name = fid + ext
        try:
            shutil.copyfile(image_path, os.path.join(_dir(), img_name))
        except Exception:
            img_name = ""

    if existing:
        existing["keywords"] = sorted(set(existing.get("keywords", [])) | set(kws))
        if description:
            existing["description"] = str(description).strip()
        if img_name:
            existing["image"] = img_name
        existing["updated_at"] = now
        entry = existing
    else:
        entry = {
            "id": _new_id(),
            "nickname": nick,
            "keywords": kws,
            "description": str(description or "").strip(),
            "image": img_name,
            "added_at": now,
            "updated_at": now,
            "hits": 0,
        }
        items.append(entry)
    _save(items)
    return entry


def lookup(keywords, limit=5, min_overlap=1):
    _m = _figure_mode()
    if not _m["on"]:
        return {"ok": False, "reason": "not_figure_mode",
                "hint": "现在不是在认人：只有对方问「这是谁/认识吗/这个呢」这类问题时才查图鉴。"}
    """按关键词重合度找候选人（只返回**有重叠**的角色，绝不返回全量列表）。

    返回字段刻意压扁：昵称 / 关键词 / 重合数 / 描述（截断）/ 图（有就给路径）。
    没有重叠就返回空列表 + 提示，让调用方知道“可能是新角色”。
    """
    kws = set(_norm_keywords(keywords))
    items = _load()
    scored = []
    for it in items:
        have = set(it.get("keywords", []))
        if not have:
            continue
        overlap = len(kws & have)
        if overlap < max(1, int(min_overlap)):
            continue
        score = overlap / max(1, len(kws | have))
        scored.append((score, overlap, it))
    scored.sort(key=lambda x: (x[1], x[0]), reverse=True)
    out = []
    for score, overlap, it in scored[: max(1, int(limit))]:
        desc = str(it.get("description") or "").strip()
        row = {
            "id": it.get("id"),
            "nickname": it.get("nickname"),
            "keywords": it.get("keywords", []),
            "overlap": overlap,
            "match": round(score, 3),
            "description": (desc[:80] + "…") if len(desc) > 80 else desc,
        }
        if it.get("image"):
            row["image_path"] = os.path.join(_dir(), it["image"])
        out.append(row)
    # 命中计数写回（图鉴用得越多的条目，下次更容易被想到）
    if out:
        hit_ids = {r["id"] for r in out}
        for it in items:
            if it.get("id") in hit_ids:
                it["hits"] = int(it.get("hits", 0)) + 1
        _save(items)
    return out


def correct(figure_id="", nickname="", keywords=None, description=None):
    _m = _figure_mode()
    if not _m["on"]:
        return {"ok": False, "reason": "not_figure_mode",
                "hint": "现在不是在认人：只有对方问「这是谁/认识吗/这个呢」这类问题时才查图鉴。"}
    """修正图鉴：认错人时改昵称 / 关键词 / 描述。figure_id 可传 id，也可传现用昵称。"""
    items = _load()
    target = None
    fid = str(figure_id or "").strip()
    nick = str(nickname or "").strip()
    for it in items:
        if (fid and it.get("id") == fid) or (nick and it.get("nickname") == nick):
            target = it
            break
    if not target:
        return {"ok": False, "reason": "not_found", "figure_id": fid, "nickname": nick}

    if nickname and str(nickname).strip() != target.get("nickname"):
        target["nickname"] = str(nickname).strip()
    if keywords is not None:
        target["keywords"] = sorted(set(_norm_keywords(keywords)))
    if description is not None:
        target["description"] = str(description).strip()
    target["updated_at"] = int(time.time())
    target["corrected"] = int(target.get("corrected", 0)) + 1
    _save(items)
    return {"ok": True, "entry": target}


def listing(limit=50):
    items = _load()
    items.sort(key=lambda x: x.get("updated_at", 0), reverse=True)
    return items[:limit]



