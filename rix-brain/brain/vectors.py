"""向量召回（2026-10-30 用户定：把按顺序调用的 50% 换成向量检索）。

依赖本机 ollama 的 bge-m3（1024 维，不联网、不花钱）：
    POST http://127.0.0.1:11434/api/embed  {"model":"bge-m3","input":[...]}

缓存：`AI_data/<ai>_data/vecdb.json`
    {"<session>::<first_time>": {"h": "<内容哈希>", "v": [1024 个数...]}}
内容变了才重算；新条目按批补（一批 16 条）。
"""
import hashlib
import json
import math
import os
import urllib.request

import config

OLLAMA = "http://127.0.0.1:11434/api/embed"
MODEL = "bge-m3"
DIM = 1024
_BATCH = 16


def _path():
    return os.path.join(config.data_dir(), "vecdb.json")


def _load():
    try:
        with open(_path(), encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _save(db):
    with open(_path(), "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False)


def embed(texts):
    """批量取向量；失败返回 []。"""
    texts = [str(t)[:2000] for t in texts if str(t or "").strip()]
    if not texts:
        return []
    try:
        body = json.dumps({"model": MODEL, "input": texts}).encode()
        req = urllib.request.Request(OLLAMA, data=body, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=120) as r:
            d = json.loads(r.read())
        return d.get("embeddings") or []
    except Exception:
        return []


def _hash(text):
    return hashlib.md5(str(text or "").encode("utf-8")).hexdigest()[:16]


def _cos(a, b):
    if not a or not b:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def _entry_id(mem):
    return "%s::%s" % (mem.get("_src") or mem.get("key") or "", mem.get("first_time") or 0)


def top_k(query, memories, k=3):
    """返回 [(index, score)]，按相似度降序。缓存缺失的会就地补齐。"""
    if not memories or not str(query or "").strip():
        return []
    db = _load()
    pending = []
    for i, mem in enumerate(memories):
        text = str(mem.get("memory_content") or "")
        eid = _entry_id(mem)
        h = _hash(text)
        rec = db.get(eid)
        if not rec or rec.get("h") != h or not rec.get("v"):
            pending.append((i, eid, h, text))

    if pending:
        for start in range(0, len(pending), _BATCH):
            chunk = pending[start:start + _BATCH]
            vecs = embed([c[3] for c in chunk])
            if not vecs or len(vecs) != len(chunk):
                continue
            for (i, eid, h, _), v in zip(chunk, vecs):
                db[eid] = {"h": h, "v": v}
        try:
            _save(db)
        except Exception:
            pass

    qv = embed([query])
    if not qv:
        return []
    qv = qv[0]
    scored = []
    for i, mem in enumerate(memories):
        rec = db.get(_entry_id(mem))
        if rec and rec.get("v"):
            scored.append((i, _cos(qv, rec["v"])))
    scored.sort(key=lambda x: -x[1])
    return scored[:max(1, int(k))]
