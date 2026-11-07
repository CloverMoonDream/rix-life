"""自动日记兜底（不遗忘的代码级保险）。

设计背景
--------
「不遗忘」链条：每轮 record_turn 写短期原文 → 达到阈值后沉淀成日记（无限记忆）
→ 回忆时全局检索。其中「沉淀」这一步原本只靠模型按人设自觉调用，
实测曾 19 小时 0 次，短期一旦滚出上限就是真失忆。

因此这里加一层兜底：任何会话的待总结短期条数超过 auto_at（默认 60）时，
由本模块用 DeepSeek 直接生成一篇第一人称日记并落盘，再裁剪短期。
平时（阈值 16~60 之间）仍由模型自己写，保持日记的"她本人语气"。

启动：mcp_server.main() 里 autodream.start()
审计：AI_data/{ai}_data/auto_dream.log
"""
import json
import os
import threading
import time

import config
import memory

_DEFAULT_AUTO_AT = 60          # 超过多少条待总结就自动兜底
_DEFAULT_INTERVAL = 600        # 检查间隔（秒）
_DEFAULT_COOLDOWN = 1800       # 同一会话两次自动总结的最小间隔（秒）

_lock = threading.Lock()
_last_run = {}                 # key -> 上次自动总结时间


_nightly_done = {}


def _nightly_state_path():
    import os as _os
    return _os.path.join(config.data_dir(), "nightly.state.json")


def _nightly_load():
    import json as _json
    import os as _os
    try:
        p = _nightly_state_path()
        if _os.path.exists(p):
            return _json.load(open(p, encoding="utf-8"))
    except Exception:
        pass
    return {}


def _nightly_save(d):
    import json as _json
    try:
        _json.dump(d, open(_nightly_state_path(), "w", encoding="utf-8"))
    except Exception:
        pass


def _cfg():
    c = config.load_config().get("memory", {})
    return (
        int(c.get("auto_summarize_at") or _DEFAULT_AUTO_AT),
        int(c.get("auto_summarize_interval") or _DEFAULT_INTERVAL),
        int(c.get("auto_summarize_cooldown") or _DEFAULT_COOLDOWN),
    )


def _log(line):
    try:
        p = os.path.join(config.data_dir(), "auto_dream.log")
        with open(p, "a", encoding="utf-8") as f:
            f.write("%s %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), line))
    except Exception:
        pass


def _summarize_prompt(pending_text, key, first_time=None, last_time=None):
    label = memory._key_label(memory._norm_key(key)) or key
    start = memory._cn_stamp(first_time) if first_time else ""
    end = memory._cn_stamp(last_time) if last_time else ""
    if start and end and start != end:
        when = f"{start} 到 {end}"
    else:
        when = start or end or ""
    when_line = f"这段对话发生在：{when}（北京时间）。\n" if when else ""
    return (
        "你在为一只名叫AI的 QQ 聊天机器人整理长期记忆（第一人称日记）。\n"
        "结尾必须单独写一句「现在是___的心情」（用户 2026-10-31 定，强制）。\n"
        f"下面是它在「{label}」这个会话里最近的对话原文，每行格式为「昵称：内容」。\n\n"
        f"{pending_text}\n\n"
        f"{when_line}"
        "请输出 JSON（不要代码块、不要多余文字），格式：\n"
        '{"content": "第一人称日记，80~200字", "things": "关键词1, 关键词2, 关键词3", '
        '"kind": "subjective 或 objective"}\n'
        "要求：\n"
        "1. content 用第一人称（我/他），写清「谁在哪个会话说了什么、发生了什么」，"
        "保留具体细节（人名、数字、事件），不要空泛评价；\n"
        "2. **content 必须以日期开头**（用上面给出的年月日，例：「十月二十七号上午，……」），"
        "跨越两天的就写两个日期（例：「十月二十六号晚上到十月二十七号早上，……」）；"
        "不要写「今天」「昨晚」「昨天」这类相对时间——她日后翻记忆时不知道对标的是哪一天；\n"
        "3. 若有情绪变化、约定、承诺、喜好，必须写进去；\n"
        "4. things 是 3~8 个便于日后检索的关键词（人名、话题、地点、物品等）；\n"
        "5. kind：这条主要讲「我的感受/情绪/对某人的印象」就填 subjective，"
        "主要讲「发生了什么事/事实/约定」就填 objective；\n"
        "6. 不要编造原文里没有的内容。"
    )


def summarize_now(key, force=False):
    """对某个会话做一次总结。force=True 时忽略阈值与冷却（用于手动测试）。"""
    auto_at, _, cooldown = _cfg()
    pend = memory.get_pending(key)
    if pend["count"] == 0:
        return {"ok": False, "reason": "empty"}
    if not force:
        if pend["count"] < auto_at:
            return {"ok": False, "reason": "below_threshold", "count": pend["count"], "auto_at": auto_at}
        last = _last_run.get(key, 0)
        if time.time() - last < cooldown:
            return {"ok": False, "reason": "cooldown"}

    try:
        raw = config.deepseek_complete(
            [{"role": "user", "content": _summarize_prompt(pend["text"], key, pend.get("first_time"), pend.get("last_time"))}],
            max_tokens=700,
        )
    except Exception as e:
        _log("总结失败 %s：%s" % (key, str(e)[:120]))
        return {"ok": False, "reason": "llm_error", "error": str(e)[:150]}

    content, things, kind = "", "", ""
    try:
        s = raw.strip()
        if s.startswith("```"):
            s = s.split("```")[1]
            s = s[4:] if s.lower().startswith("json") else s
        obj = json.loads(s)
        if not isinstance(obj, dict):
            raise ValueError("not a dict")
        # 字段名容错：模型可能用中文键
        for k in ("content", "日记", "正文", "记忆", "diary", "memory_content", "text"):
            if obj.get(k):
                content = str(obj[k]).strip()
                break
        for k in ("things", "关键词", "关键字", "keywords", "tags"):
            if obj.get(k):
                v = obj[k]
                things = ", ".join(str(x) for x in v) if isinstance(v, list) else str(v)
                break
        for k in ("kind", "类型", "类别"):
            v = str(obj.get(k) or "").strip().lower()
            if v in ("subjective", "objective"):
                kind = v
                break
            if "subject" in v or "主观" in v or "感受" in v:
                kind = "subjective"
                break
            if "object" in v or "客观" in v or "事实" in v:
                kind = "objective"
                break
        if not content:
            # 兜底：把所有字符串值拼起来当日记
            vals = [str(v).strip() for v in obj.values() if isinstance(v, str) and len(str(v).strip()) > 10]
            content = max(vals, key=len) if vals else ""
    except Exception:
        content = raw.strip()[:800]      # 兜底：JSON 解析失败就把原文当日记
    if not content:
        return {"ok": False, "reason": "empty_summary"}

    memory.append_diary(content, things, key, pend.get("first_time"), pend.get("last_time"), kind)
    _last_run[key] = time.time()
    _log("自动总结 %s：%d 条 -> 日记 %d 字（kind=%s）" % (key, pend["count"], len(content), kind or "auto"))
    return {"ok": True, "key": key, "from": pend["count"], "kind": kind or "auto", "content": content[:80]}


def flush_idle(key, idle_seconds=None, min_entries=None):
    """空闲强制沉淀（沿用 Rix 原版机制，2026-10-27 补）。

    原版在收到新消息前先判断：距上一条 ≥900 秒就说明上一段聊完了，先结算再开口。
    对应到这里就是：一段聊天结束后（人离开了），把这段落成日记，
    别等它攒到 auto_at 条、更别等下次聊天把新内容混进来。

    实测事故（2026-10-27）：昨晚聊完就散，pending 没到 24/60 的兜底线，
    于是昨晚那段从没写进日记；今早问「昨晚聊了什么」，她只能拿前天的记忆顶，
    还把两天的内容拼成一天。
    """
    cfg = config.load_config().get("memory", {})
    if idle_seconds is None:
        idle_seconds = int(cfg.get("idle_summarize_seconds") or 900)
    if min_entries is None:
        min_entries = int(cfg.get("idle_summarize_min_entries") or 4)

    pend = memory.get_pending(key)
    if pend["count"] < min_entries:
        return {"ok": False, "reason": "too_few", "count": pend["count"]}
    last = pend.get("last_time") or 0
    gap = int(time.time()) - int(last) if last else 0
    if gap < idle_seconds:
        return {"ok": False, "reason": "not_idle", "gap": gap}

    with _lock:
        r = summarize_now(key, force=True)
    if r.get("ok"):
        _log("空闲强制沉淀 %s：间隔 %ds，%d 条" % (key, gap, pend["count"]))
    return r


def sweep(force=False):
    """扫描所有会话，达阈值的做自动总结。返回处理结果列表。"""
    out = []
    with _lock:
        for dirname in memory.all_chat_keys():
            key = memory._norm_key(dirname)
            if key == "_default":
                continue
            try:
                r = summarize_now(key, force=force)
                if r.get("ok") or r.get("reason") not in ("empty", "below_threshold", "cooldown"):
                    out.append((key, r))
            except Exception as e:
                out.append((key, {"ok": False, "reason": "exception", "error": str(e)[:120]}))
        # 情绪心跳（2026-10-31 补）：激动值随时间向 50 回落。
        # 2026-11-03 用户定：整套数值情绪已停用（情绪改由记忆涌现），这段心跳一并删掉。
        # 要恢复：从 git / .bak-emotiondelete-* 里取回原来的 try 块。
        pass

        # 自动合并已被用户喊停（2026-10-28）：默认关闭，只有手动调 memory_merge_days 才会合并
        if config.load_config().get("memory", {}).get("auto_merge_days") is True:
            try:
                merged = memory.merge_days(min_entries=2)
                for m in merged:
                    _log("合并碎片 %s %s：%d 篇 -> 1 篇（%d 字）" % (m["key"], m["day"], m["from"], m["chars"]))
            except Exception as e:
                _log("合并碎片失败：%s" % str(e)[:120])
    return out


def _loop():
    _, interval, _ = _cfg()
    while True:
        try:
            for key, r in sweep():
                if r.get("ok"):
                    print("[autodream] %s 已自动总结：%s" % (key, r.get("content", "")), flush=True)
        except Exception as e:
            print("[autodream] 扫描异常：%s" % str(e)[:120], flush=True)
        # 夜间结算（每天 22:05 之后跑一次）：冷热分层 + 提炼「我变了什么」
        try:
            now_t = time.localtime()
            stamp = time.strftime("%Y-%m-%d", now_t)
            if (now_t.tm_hour, now_t.tm_min) >= (22, 5) and _nightly_load().get("date") != stamp:
                import nightly
                r = nightly.run()
                _nightly_save({"date": stamp})
                print("[nightly] %s 分层：+%d/-%d；长期：%s" % (
                    stamp, r["layers"]["promoted"], r["layers"]["demoted"],
                    "、".join(r["long_term"].get("items") or []) or r["long_term"].get("reason")),
                    flush=True)
        except Exception as e:
            print("[nightly] 异常：%s" % str(e)[:100], flush=True)

        # 冷暴力巡检：主动开口后 5/20/60 分钟没回话就扣好感（硬规则，不经模型）
        try:
            import proactive
            for hit in proactive.sweep():
                print("[proactive] %s 被晾 %d 分钟，扣 %d 点（%d -> %d）" % (
                    hit["key"], hit.get("wait_min", 0), -int(hit.get("penalty", 0)),
                    hit.get("like_before", 0), hit.get("like_after", 0)), flush=True)
        except Exception as e:
            print("[proactive] 巡检异常：%s" % str(e)[:100], flush=True)
        time.sleep(max(60, interval))


def start():
    """后台线程：定期兜底总结。"""
    auto_at, interval, _ = _cfg()
    t = threading.Thread(target=_loop, name="autodream", daemon=True)
    t.start()
    print("[autodream] 已启动：每 %d 秒检查，某会话待总结 ≥%d 条时自动写日记" % (interval, auto_at), flush=True)
    return t


