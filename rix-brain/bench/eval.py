"""召回评测基准（2026-10-30，P1 第一项）。

用法：
  python tools/recall-eval.py build --n 20     # 从日记里生成 20 条问题（冻结成基准）
  python tools/recall-eval.py run              # 跑一遍，输出 hit@1/3/5 与 MRR
  python tools/recall-eval.py run --save       # 跑完存结果，便于改前改后对比

基准文件：bench/queries.json（一旦生成就别随便改，它是标尺）
结果文件：bench/results-<时间>.json
"""
import argparse
import json
import os
import random
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "brain"))

import config  # noqa: E402
import memory  # noqa: E402

EVAL_DIR = os.path.dirname(os.path.abspath(__file__))
QUERIES = os.path.join(EVAL_DIR, "queries.json")


def _entries():
    out = []
    for e in memory._load_all_diaries():
        text = str(e.get("memory_content") or "").strip()
        if len(text) < 40:
            continue
        out.append(e)
    return out


def build(n=20):
    os.makedirs(EVAL_DIR, exist_ok=True)
    entries = _entries()
    random.seed(20261030)          # 固定种子：重建也一样，保证可比
    picked = random.sample(entries, min(n, len(entries)))
    rows = []
    for e in picked:
        content = str(e.get("memory_content") or "")[:220]
        prompt = (
            "下面是一段日记。请写一条**自然的提问**（第一人称、像真人随口问的那种），"
            "要求：看这段日记才能答出来，但**不要照抄里面的原词**（要换说法），20 字以内。\n"
            "只输出这一句提问，不要引号、不要解释。\n\n日记：" + content
        )
        try:
            q = (config.deepseek_complete([{"role": "user", "content": prompt}], max_tokens=60) or "").strip()
        except Exception:
            q = ""
        q = q.strip("\"'“”「」\n ")[:60]
        if not q:
            continue
        rows.append({
            "query": q,
            "expect_key": e.get("_src") or e.get("key") or "",
            "expect_first_time": int(e.get("first_time") or 0),
            "hint": content[:80],
        })
        print("  ", q)
    json.dump(rows, open(QUERIES, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("基准已生成：%d 条 → %s" % (len(rows), QUERIES))


def run(save=False):
    if not os.path.exists(QUERIES):
        print("先跑 build 生成基准")
        return
    rows = json.load(open(QUERIES, encoding="utf-8"))
    hits = {1: 0, 3: 0, 5: 0}
    rr = 0.0
    detail = []
    for r in rows:
        res = memory.recall(r["query"], max_total=5, current_key=r.get("expect_key") or "",
                            short_term_turns=0, with_ids=True)
        ids = res.get("ids") or []
        rank = None
        for i, item in enumerate(ids):
            if int(item.get("first_time") or 0) == int(r["expect_first_time"]):
                rank = i + 1
                break
        for k in hits:
            if rank and rank <= k:
                hits[k] += 1
        if rank:
            rr += 1.0 / rank
        detail.append({"query": r["query"], "expect": r["expect_first_time"], "rank": rank})
        print("  %s  rank=%s  %s" % ("✓" if rank else "✗", rank or "-", r["query"]))

    n = len(rows)
    print("\n结果（%d 条）：hit@1 %.0f%% | hit@3 %.0f%% | hit@5 %.0f%% | MRR %.3f" % (
        n, hits[1] * 100.0 / n, hits[3] * 100.0 / n, hits[5] * 100.0 / n, rr / n))
    if save:
        out = os.path.join(EVAL_DIR, "results-%s.json" % time.strftime("%Y%m%d-%H%M%S"))
        json.dump({"at": int(time.time()), "n": n, "hit@1": hits[1], "hit@3": hits[3],
                   "hit@5": hits[5], "mrr": rr / n, "detail": detail},
                  open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print("已保存：", out)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["build", "run"])
    ap.add_argument("--n", type=int, default=20)
    ap.add_argument("--save", action="store_true")
    a = ap.parse_args()
    if a.cmd == "build":
        build(a.n)
    else:
        run(a.save)
