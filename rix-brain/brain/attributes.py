"""联想库（原「属性桥接」的仿生版）—— 2026-10-30 用户改的口径。

原版只做「换说法的兜底」：属性 ∩ 用户这句话。用户要的不是"合适"，是**仿生**：
人想到「苹果」，会同时想起 iPhone 和能吃的那种苹果——**一个词会点亮一串概念**。

所以每个词存两层：
  a（属性）：红的、甜的、圆的…属于"换说法"时的锚点
  s（联想）：同名的另一个意思、同类、常见搭配、相关事物（苹果 → iPhone、牛顿、水果）

召回时三个信号叠加：
  · 直接命中（things 词出现在 query）→ 词面召回已覆盖，这里跳过
  · 属性命中（a ∩ query）
  · 联想命中（记忆的 things 出现在「query 词的联想集」里）—— 这就是仿生的那一步
"""
import json
import os
import re

import config

_LOCK = __import__("threading").Lock()
_MAX_ATTRS = 8
_MAX_ASSOC = 8


def _path():
    return os.path.join(config.data_dir(), "attributes.json")


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


def _entry(data, word):
    """取一条，兼容旧格式（纯列表＝只有属性）。"""
    v = data.get(word)
    if isinstance(v, list):
        return {"a": v, "s": []}
    if isinstance(v, dict):
        return {"a": list(v.get("a") or []), "s": list(v.get("s") or [])}
    return {"a": [], "s": []}


def attributes_of(word):
    return _entry(_load(), str(word or "").strip())["a"]


def assoc_of(word):
    return _entry(_load(), str(word or "").strip())["s"]


def ensure_attributes(words, batch=6):
    """给一批词补齐「属性 + 联想」（缺的才调模型）。返回补了几个。"""
    words = [str(w).strip() for w in words if str(w).strip()]
    if not words:
        return 0
    data = _load()
    missing = [w for w in dict.fromkeys(words) if (w not in data) or not isinstance(data.get(w), dict)][:batch]
    if not missing:
        return 0
    prompt = (
        "给下面每个词写两组词条，模仿人脑的联想方式。\n"
        "1) a：5~8 个可见/可感知的属性（颜色、形状、味道、材质、用途、位置），用于「换个说法也能认出来」\n"
        "2) s：5~8 个**联想到的东西**——包括同名的另一个意思、同类事物、常见搭配、相关人物或场景"
        "（例：苹果 → iPhone、乔布斯、牛顿、水果）\n"
        "不要写身份评价或标签化的称呼。\n"
        "只输出 JSON，格式：[[\"词\", {\"a\": [...], \"s\": [...]}], ...]\n\n"
        + "、".join(missing)
    )
    try:
        raw = config.deepseek_complete([{"role": "user", "content": prompt}], max_tokens=1200)
        text = (raw or "").strip()
        m = re.search(r"\[.*\]", text, re.S)
        pairs = json.loads(m.group(0)) if m else []
    except Exception:
        return 0
    added = 0
    with _LOCK:
        for pair in pairs:
            if not isinstance(pair, (list, tuple)) or len(pair) != 2:
                continue
            word, payload = str(pair[0]).strip(), pair[1]
            if not word or not isinstance(payload, dict):
                continue
            a = [str(x).strip() for x in (payload.get("a") or []) if str(x).strip()][:_MAX_ATTRS]
            s = [str(x).strip() for x in (payload.get("s") or []) if str(x).strip()][:_MAX_ASSOC]
            if a or s:
                data[word] = {"a": a, "s": s}
                added += 1
        if added:
            _save(data)
    return added


def _query_words(q):
    """从这句话里切出可能指向概念的词（中文 2~4 字 + 英文/数字）。"""
    out = set()
    for w in re.findall(r"[A-Za-z]{2,}|\d+", q):
        out.add(w.lower())
    for run in re.findall(r"[\u4e00-\u9fff]{2,}", q):
        for n in (2, 3, 4):
            for i in range(0, max(1, len(run) - n + 1)):
                out.add(run[i:i + n])
    return out


def bridge_scores(query, memories, exclude=(), max_hits=4):
    """联想式召回：返回 [(index, score)]，score 越大越相关。"""
    q = str(query or "")
    if not q:
        return []
    data = _load()
    if not data:
        return []
    exclude = set(exclude)
    qwords = _query_words(q)

    expanded = set()
    for w in list(qwords):
        e = _entry(data, w)
        expanded.update(str(a).lower() for a in e["a"])
        expanded.update(str(s).lower() for s in e["s"])
    expanded.discard("")

    scored = []
    for idx, mem in enumerate(memories):
        if idx in exclude:
            continue
        things = str(mem.get("things") or "")
        tokens = [t.strip() for t in re.split(r"[,，、]", things) if t.strip()]
        if not tokens:
            continue
        if any(t in q for t in tokens):
            continue                       # 词面已覆盖
        score = 0
        for t in tokens:
            e = _entry(data, t)
            score += sum(1 for a in e["a"] if a and str(a).lower() in q.lower())
            if t.lower() in expanded:      # 联想命中：这条的 things 被「query 的联想」点亮
                score += 2
        if score >= 1:
            scored.append((idx, score))
    scored.sort(key=lambda x: -x[1])
    return scored[:max_hits]


def missing_words(memories, limit=200):
    have = _load()
    out = []
    for mem in memories:
        for t in re.split(r"[,，、]", str(mem.get("things") or "")):
            t = t.strip()
            if t and t not in have and t not in out:
                out.append(t)
    return out[:limit]


def stats():
    data = _load()
    return {"words": len(data),
            "attrs": sum(len(_entry(data, w)["a"]) for w in data),
            "assoc": sum(len(_entry(data, w)["s"]) for w in data)}
