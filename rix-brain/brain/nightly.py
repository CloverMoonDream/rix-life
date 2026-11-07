"""夜间记忆结算（2026-10-30，借「四个柜子」思路）。

两件事，都是脚本自动跑，不经模型决定：
  ① 冷热分层结算：命中过的上浮，到期的下沉；**永不删除**
  ② 提炼「长期 = 我变了什么」：读当天日记，写 1~2 条人格层面的变化到 long_term.jsonl

由 autodream 每天 22:05 之后自动调用一次；也可以手动 `python tools/memory-nightly.py`。
"""
import json
import os
import shutil
import time

import config
import memory

DAY = 86400
PROMOTE_DAYS = 7
DEMOTE_DAYS = {1: 7, 2: 30, 3: 3650}
LONG_TERM = "long_term.jsonl"


def _today0():
    t = time.localtime()
    return int(time.mktime((t.tm_year, t.tm_mon, t.tm_mday, 0, 0, 0, 0, 0, -1)))


def settle_layers(dry=False):
    now = int(time.time())
    today0 = _today0()
    stats = {"promoted": 0, "demoted": 0, "kept": 0}
    base = os.path.join(config.data_dir(), "chats")
    for dirname in os.listdir(base):
        p = os.path.join(base, dirname, "diary.json")
        if not os.path.exists(p):
            continue
        try:
            data = json.load(open(p, encoding="utf-8"))
        except Exception:
            continue
        changed = False
        for e in data:
            layer = int(e.get("layer") or 1)
            due = int(e.get("next_due") or 0)
            called = int(e.get("last_called") or 0)
            hit_today = called >= today0
            if hit_today:
                if layer > 1:
                    layer -= 1
                    stats["promoted"] += 1
                e["last_hit"] = now
                e["next_due"] = now + PROMOTE_DAYS * DAY
                changed = True
            elif due and due <= now:
                if layer < 3:
                    layer += 1
                    stats["demoted"] += 1
                e["next_due"] = now + DEMOTE_DAYS[layer] * DAY
                changed = True
            else:
                stats["kept"] += 1
            e["layer"] = layer
        if changed and not dry:
            try:
                shutil.copyfile(p, p + ".bak-nightly-" + time.strftime("%Y%m%d-%H%M%S"))
            except Exception:
                pass
            json.dump(data, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return stats


def extract_long_term(dry=False):
    today = time.strftime("%Y-%m-%d")
    today0 = _today0()
    texts = [str(e.get("memory_content") or "")[:300]
             for e in memory._load_all_diaries()
             if int(e.get("first_time") or 0) >= today0]
    if not texts:
        return {"ok": False, "reason": "今天没有日记"}

    prompt = (
        "下面是AI今天写的一批日记。请提炼 **1~2 条「她今天发生了什么样的改变」**——"
        "不是事件，是人格/认知/关系上的变化，例如「以前怕被忘，现在接受重来」。\n"
        "每条 30 字以内，第一人称，从「我」出发；只输出 JSON 数组：[\"…\", \"…\"]\n\n"
        + "\n---\n".join(texts[:12])
    )
    try:
        raw = config.deepseek_complete([{"role": "user", "content": prompt}], max_tokens=300) or ""
        import re as _re
        m = _re.search(r"\[.*\]", raw, _re.S)
        items = json.loads(m.group(0)) if m else []
    except Exception as e:
        return {"ok": False, "reason": str(e)[:100]}
    items = [str(x).strip() for x in items if str(x).strip()][:2]
    if not items:
        return {"ok": False, "reason": "没提炼出内容"}

    if not dry:
        with open(os.path.join(config.data_dir(), LONG_TERM), "a", encoding="utf-8") as f:
            for t in items:
                f.write(json.dumps({"date": today, "text": t, "ts": int(time.time())},
                                   ensure_ascii=False) + "\n")
    return {"ok": True, "date": today, "items": items}


def run(dry=False):
    s = settle_layers(dry)
    r = extract_long_term(dry)
    return {"layers": s, "long_term": r}
