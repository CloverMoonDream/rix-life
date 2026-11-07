"""rix-brain 记忆模块（v2：会话隔离 + 全局长期检索）。

设计要点
--------
1. **短期记忆按会话独立**：每个私聊/群各一份
   AI_data/{ai}_data/chats/{safe_key}/short_term.json
2. **长期日记按会话独立**：
   AI_data/{ai}_data/chats/{safe_key}/diary.json
3. **回忆时可全局检索**：短期只取当前会话；长期日记会扫全部会话，
   跨会话的条目会带出处标注（[私聊(QQ号)的记忆] / [群(群号)的记忆]）。
4. 旧版单文件（short_term.json / infinite_memory.json）首次运行会自动迁移并改名备份。

检索链路（保持原设计）：词面召回 → 频率补齐候选池 → flash 语义重排 → 频率兜底补满额度。

⚠️ 2026-11-04 清理说明：情绪数值系统 2026-11-03 已删（用户定：情绪改由记忆涌现）。
本文件里 `_emo_snapshot` / `_emotion_echo` / `_extra_by_emotion` / `_mood_now` 和记忆条目上的
`emo` 字段是那套系统的残骸：召回配额已固定成 7 条（主观 3 / 客观 3），新记忆不再盖 `emo` 戳。
**要恢复按情绪召回，请从 `emotion.py` 重新建一套，别指望这些残骸。**
"""
import json
import os
import re
import threading
import time

import config


# ---------- 路径与读写 ----------

def _dir():
    d = config.data_dir()
    os.makedirs(d, exist_ok=True)
    return d


def _safe_key(key):
    """把会话 key 变成安全的目录名。"""
    k = str(key or "").strip() or "_default"
    k = k.replace(":", "_").replace("+", "_").replace("/", "_").replace("\\", "_")
    k = re.sub(r"[^0-9A-Za-z_\-.\u4e00-\u9fff]", "_", k)
    return k[:80]


def _chat_dir(key, create=True):
    d = os.path.join(_dir(), "chats", _safe_key(key))
    if create:
        os.makedirs(d, exist_ok=True)
    return d


def _resolve_key(key):
    """把各种写法归一到「实际存在的会话」。

    模型有时传会话 key（private:xxx / group:xxx），有时只传 QQ 号/群号。
    后者以前会被当成另一个会话：读到 0 条待总结、永远不触发日记沉淀
    （2026-10-24 实测：阿豆会话 63 条待总结 / 0 条日记，而她自己那句
    memory_get_pending 传的是裸 QQ 号 → 返回 0 → 她就以为没什么可总结的）。

    归一规则：
      · 已带 private:/group: 前缀 → 原样；
      · 纯数字 → 看 chats/ 下哪个目录真实存在（private_<号> / group_<号>），
        只有一个存在就用它；都不存在时按私聊处理（群聊一般会带 group: 前缀）；
      · 昵称等其他写法 → 原样（保留原有灵活性）。
    """
    k = str(key or "").strip()
    if not k:
        return k
    if k.startswith("private:") or k.startswith("group:"):
        return k
    if k.isdigit():
        base = os.path.join(_dir(), "chats")
        has_p = os.path.isdir(os.path.join(base, "private_" + k))
        has_g = os.path.isdir(os.path.join(base, "group_" + k))
        if has_g and not has_p:
            return "group:" + k
        return "private:" + k
    return k


def _short_path(key):
    return os.path.join(_chat_dir(_resolve_key(key)), "short_term.json")


def _diary_path(key):
    return os.path.join(_chat_dir(_resolve_key(key)), "diary.json")


def _legacy_short_path():
    return os.path.join(_dir(), "short_term.json")


def _legacy_inf_path():
    return os.path.join(_dir(), "infinite_memory.json")


def _load(path, default):
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            d = json.load(f)
            return d if isinstance(d, list) else default
    except Exception:
        return default


# 缺陷4 修复（2026-11-06）：并发写丢失的真正原因是「读-改-写」没有互斥。
# _save 的原子替换只保证文件不坏，救不回被覆盖的那一次更新。
# 这里用一把进程内的可重入锁护住 short_term / diary 的读改写。
_DIARY_WRITE_LOCK = threading.RLock()


def _save(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    # 缺陷4 修复（2026-11-06）：临时文件名带线程/pid 后缀。
    # 原来是固定的 path+".tmp"，多线程同时写会互相踩同一个临时文件。
    tmp = "%s.tmp-%d-%d" % (path, os.getpid(), threading.get_ident())
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    # Windows 上并发 os.replace 同一目标会抛 PermissionError（目标正被另一个
    # 句柄持有），原来一次失败就整笔丢。加短重试，总共约 0.5 秒。
    for attempt in range(20):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if attempt == 19:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
                raise
            time.sleep(0.005 * (attempt + 1))


def all_chat_keys():
    """列出所有已有记忆的会话 key（从目录名反推）。"""
    base = os.path.join(_dir(), "chats")
    if not os.path.isdir(base):
        return []
    out = []
    for name in sorted(os.listdir(base)):
        if os.path.isdir(os.path.join(base, name)):
            out.append(name)
    return out


def _read_key_from_dir(dirname):
    """目录名 -> 展示用 label（无法还原原始 key 时用目录名）。"""
    return dirname


# ---------- 旧数据迁移 ----------

def migrate_legacy():
    """把旧版单文件拆成按会话独立的文件（只做一次）。"""
    changed = []
    ls, li = _legacy_short_path(), _legacy_inf_path()

    if os.path.exists(ls):
        data = _load(ls, [])
        buckets = {}
        for m in data:
            k = str(m.get("key") or "").strip() or "_default"
            m.setdefault("nickname", "")
            m.setdefault("role", "")
            buckets.setdefault(k, []).append(m)
        for k, items in buckets.items():
            p = _short_path(k)
            cur = _load(p, [])
            _save(p, cur + items)
        os.replace(ls, ls + ".migrated")
        changed.append("short_term.json -> chats/*/short_term.json（%d 条 / %d 个会话）" % (len(data), len(buckets)))

    if os.path.exists(li):
        data = _load(li, [])
        buckets = {}
        for e in data:
            k = str(e.get("key") or "").strip() or "_default"
            buckets.setdefault(k, []).append(e)
        for k, items in buckets.items():
            p = _diary_path(k)
            cur = _load(p, [])
            _save(p, cur + items)
        os.replace(li, li + ".migrated")
        changed.append("infinite_memory.json -> chats/*/diary.json（%d 条 / %d 个会话）" % (len(data), len(buckets)))
    return changed


def _key_label(key):
    """把会话标识转成简短中文标签，用于记忆出处标注。"""
    if not key or key == "_default":
        return "早期对话" if key == "_default" else ""
    if "+" in key:
        kind, rest = key.split("+", 1)
        if kind == "private":
            return f"私聊({rest})"
        elif kind == "group":
            return f"群({rest})"
        return key
    if key.startswith("private_"):
        return f"私聊({key[8:]})"
    if key.startswith("private:"):
        return f"私聊({key[8:]})"
    if key.startswith("group_"):
        return f"群({key[6:]})"
    if key.startswith("group:"):
        return f"群({key[6:]})"
    return key


def _norm_key(key):
    """目录名（private_10001） -> 规范 key（private:10001）。"""
    k = str(key or "")
    if k.startswith("private_"):
        return "private:" + k[8:]
    if k.startswith("group_"):
        return "group:" + k[6:]
    return k


# ---------- 写入 ----------

def record_turn(key, role, content, nickname=""):
    with _DIARY_WRITE_LOCK:
        return _record_turn_locked(key, role, content, nickname)


def _record_turn_locked(key, role, content, nickname=""):
    """追加一条短期记忆（写入该会话自己的文件）。"""
    cfg = config.load_config()
    maxn = cfg.get("memory", {}).get("short_term_max", 30)
    if not content or not str(content).strip():
        return True
    key = _resolve_key(key)
    p = _short_path(key)
    data = _load(p, [])
    prev_time = data[-1].get("time") if data else None
    data.append({
        "key": str(key or ""),
        "role": role,
        "nickname": str(nickname) if nickname else "",
        "content": str(content).strip(),
        "time": int(time.time()),
        "consolidated": False,
        # 每句话的情绪快照（用户 2026-10-31 定）——「情绪最相似的原文」靠它
    })
    if len(data) > maxn:
        data = data[-maxn:]
    _save(p, data)
    write_pending_counts()
    _maybe_idle_flush(key, role, prev_time)
    return True


def _pending_counts_path():
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    d = os.path.join(root, "state")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, "pending-counts.json")


def write_pending_counts():
    """把每个会话的待总结条数写成状态文件，给桥接的「小闹钟」读（用户 2026-11-02 定）。

    为什么写文件：桥接（Node）拿不到 rix-brain 的内存，但两边共用工作区。
    一条消息一次、几十字节，成本可忽略；读的一侧（桥接）只在唤醒时读一次。
    """
    try:
        counts = {}
        for dirname in all_chat_keys():
            data = _load(os.path.join(_dir(), "chats", dirname, "short_term.json"), [])
            n = sum(1 for m in data if not m.get("consolidated"))
            if n:
                counts[_norm_key(dirname)] = n
        p = _pending_counts_path()
        tmp = p + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"at": int(time.time()), "counts": counts}, f, ensure_ascii=False)
        os.replace(tmp, p)
    except Exception:
        pass


def _maybe_idle_flush(key, role, prev_time):
    """空闲强制沉淀的触发器（细节见 autodream.flush_idle 的注释）。

    只有「用户隔了很久重新开口」才触发：说明上一段聊完了，先结算再继续。
    异步执行，不阻塞这条消息的处理。
    """
    if not prev_time or str(role) != "用户":
        return
    try:
        idle = int(config.load_config().get("memory", {}).get("idle_summarize_seconds", 900))
    except Exception:
        idle = 900
    gap = int(time.time()) - int(prev_time)
    if gap < idle:
        return

    def _run():
        try:
            import autodream
            autodream.flush_idle(key)
        except Exception:
            pass

    threading.Thread(target=_run, name="idle-flush", daemon=True).start()


def _trim_short_term(key, keep):
    key = _resolve_key(key)
    p = _short_path(key)
    data = _load(p, [])
    if len(data) > keep:
        _save(p, data[-keep:])


def _mark_consolidated(key, upto_ts):
    """把已参与日记总结的短期条目标记为 consolidated（**不删除**）。

    为什么不是裁掉：删除不可逆，而一篇日记常常只覆盖了 pending 的一部分
    （2026-10-27 实测「只写今早那段」），一刀切会把没写进去的原文一起扫掉——
    日记里没有、短期里也没有，那就不是「想不起来」，是真丢了。

    标记之后：这些条目**仍然参与短期注入**（她换页后还能逐字看到最近对话），
    但不再进入 pending，所以下一篇日记不会把同样的 8 条再总结一遍。
    """
    key = _resolve_key(key)
    p = _short_path(key)
    data = _load(p, [])
    if not data:
        return 0
    try:
        upto = int(upto_ts)
    except Exception:
        upto = None
    n = 0
    for m in data:
        if m.get("consolidated"):
            continue
        if upto is not None and int(m.get("time", 0) or 0) > upto:
            continue
        m["consolidated"] = True
        m["consolidated_at"] = int(time.time())
        n += 1
    if n:
        _save(p, data)
        # 2026-11-05：标记完必须刷新 pending-counts.json，否则桥接的小闹钟会读到旧数字。
        # 实测：17:13 写入 29 条，17:21 日记沉淀完实际剩 0 条，文件还是 29 →
        # 17:27 小闹钟喊「待总结 29 条」，AI去查只有 1 条（别个会话的），对不上。
        write_pending_counts()
    return n


def get_short_term_text(max_turns=None, current_key=None):
    """短期记忆文本：**只取当前会话**；未指定 current_key 时合并全部会话并标来源。"""
    lines = []
    if current_key:
        current_key = _resolve_key(current_key)
        data = _load(_short_path(current_key), [])
        if max_turns:
            data = data[-max_turns:]
        for m in data:
            c = str(m.get("content", "")).strip()
            if not c:
                continue
            nn = m.get("nickname") or m.get("role") or ""
            lines.append(f"{nn}：{c}" if nn else c)
        return "\n".join(lines)

    # 兜底：没给 key（比如内部调用）时合并所有会话，带来源
    merged = []
    for dirname in all_chat_keys():
        for m in _load(os.path.join(_dir(), "chats", dirname, "short_term.json"), []):
            m["_src"] = dirname
            merged.append(m)
    merged.sort(key=lambda m: m.get("time", 0))
    if max_turns:
        merged = merged[-max_turns:]
    for m in merged:
        c = str(m.get("content", "")).strip()
        if not c:
            continue
        nn = m.get("nickname") or m.get("role") or ""
        lbl = _key_label(_norm_key(m.get("_src", "")))
        lines.append(f"[{lbl}]{nn}：{c}" if lbl else f"{nn}：{c}")
    return "\n".join(lines)


def get_pending(key=""):
    """取出待总结的短期记忆原文（默认只看指定会话；key 为空则合并全部会话）。"""
    def pack(items, with_label):
        lines = []
        for m in items:
            c = str(m.get("content", "")).strip()
            if not c:
                continue
            nn = m.get("nickname") or m.get("role") or "某人"
            mk = _norm_key(m.get("key") or m.get("_src") or "")
            scope = "群" if str(mk).startswith("group:") else ("私聊" if str(mk).startswith("private:") else "")
            ts = int(m.get("time") or 0)
            stamp = time.strftime("%m-%d %H:%M", time.localtime(ts)) if ts else ""
            head = " ".join(x for x in ("[%s]" % stamp if stamp else "",
                                        ("(%s)" % scope) if scope else "",
                                        nn) if x)
            lbl = _key_label(mk) if with_label else ""
            lines.append(f"[{lbl}] {head}：{c}" if lbl else f"{head}：{c}")
        return lines

    if key:
        key = _resolve_key(key)
        data = [m for m in _load(_short_path(key), []) if not m.get("consolidated")]
        lines = pack(data, with_label=False)
        return {
            "key": key,
            "text": "\n".join(lines),
            "count": len(lines),
            "first_time": data[0].get("time") if data else None,
            "last_time": data[-1].get("time") if data else None,
        }

    merged = []
    for dirname in all_chat_keys():
        for m in _load(os.path.join(_dir(), "chats", dirname, "short_term.json"), []):
            if m.get("consolidated"):
                continue
            m["_src"] = dirname
            merged.append(m)
    merged.sort(key=lambda m: m.get("time", 0))
    lines = pack(merged, with_label=True)
    return {
        "key": "",
        "text": "\n".join(lines),
        "count": len(lines),
        "first_time": merged[0].get("time") if merged else None,
        "last_time": merged[-1].get("time") if merged else None,
    }


def display_name(key):
    """这个会话里"对方"叫什么——稳定来源优先。

    2026-11-06：以前靠短期记忆里出现最多的 nickname 猜，结果沙箱输出把那格占满，
    把"沙箱"当成了人名。现在先读画像里的 name；读不到才回退到词频（带黑名单）。
    """
    k = _norm_key(key)
    try:
        import profiles as _p
        nm = str((_p.read(k) or {}).get("name") or "").strip()
        if nm:
            return nm
    except Exception:
        pass
    try:
        counts = {}
        for m in _load(_short_path(k), []):
            if str(m.get("role") or "").strip() == "工具":
                continue
            nn = str(m.get("nickname") or "").strip()
            if nn and nn not in ("", "AI", "我", "私聊", "对方", "系统", "沙箱", "工具", "用户"):
                counts[nn] = counts.get(nn, 0) + 1
        if counts:
            return max(counts.items(), key=lambda kv: kv[1])[0]
    except Exception:
        pass
    return ""


def _identity_tag(key):
    """私聊日记开头强制打上「是谁」——别让模型自己猜人名（2026-10-28 用户要求）。

    昵称从该会话短期记忆里出现最多的 nickname 取；取不到就只写 QQ 号。
    """
    k = _norm_key(key)
    if not k.startswith("private:"):
        return ""
    uid = k.split(":", 1)[1]
    name = display_name(k)
    return "【私聊 %s · %s】" % (uid, name) if name else "【私聊 %s】" % uid


def _recent_keys(limit=5):
    """最近有消息的会话（按最后一条消息时间倒序），用来让她自己挑 key。"""
    rows = []
    for dirname in all_chat_keys():
        if dirname == "_default":
            continue
        items = _load(os.path.join(_dir(), "chats", dirname, "short_term.json"), [])
        if not items:
            continue
        ts = int(items[-1].get("time") or 0)
        if ts:
            rows.append((ts, _norm_key(dirname), len(items)))
    rows.sort(reverse=True)
    return rows[:limit]


def _need_key_message(who):
    rows = _recent_keys()
    if not rows:
        return ("%s 缺 key，而且现在没有可用的会话记录。"
                "请从唤醒提示的【会话 key】取。" % who)
    lines = ["%s 缺 key——我不能替你猜，最近的会话有这几个：" % who]
    for ts, key, n in rows:
        label = _key_label(key) or ""
        when = time.strftime("%m-%d %H:%M", time.localtime(ts))
        lines.append("  · %s %s（%d 条，最后一条 %s）" % (key, label, n, when))
    lines.append("请用其中一个 key 重新调用。")
    return "\n".join(lines)


def append_diary(content, things=None, key="", first_time=None, last_time=None, kind=""):
    with _DIARY_WRITE_LOCK:
        return _append_diary_locked(content, things=things, key=key,
                                    first_time=first_time, last_time=last_time, kind=kind)


def _append_diary_locked(content, things=None, key="", first_time=None, last_time=None, kind=""):
    """DSH 总结好日记后落盘到该会话的 diary.json，并裁剪该会话的短期记忆。

    kind: "subjective"（感受/情绪/印象）或 "objective"（事实/事件/约定）；
          留空按 objective 计。召回时按情绪决定主客观各取几条。
    """
    # 没传 key 就把最近的会话列出来让她选（2026-10-30 用户定：
    # 多个会话同时活跃时自动猜会写错人，不如问回去）
    if not str(key or "").strip():
        raise ValueError(_need_key_message("append_diary"))

    cfg = config.load_config()
    freq0 = cfg.get("memory", {}).get("frequency_initial", 20)
    if isinstance(things, list):
        things = ", ".join(str(t) for t in things)
    k = str(kind or "").strip().lower()
    if k not in ("subjective", "objective"):
        k = _guess_kind(content)

    # 时间兜底：模型写日记时经常不传 first_time/last_time（实测 11 条里 2 条没日期），
    # 这里用该会话「即将被总结掉的那段短期原文」的首尾时间补上，取不到再用当前时间。
    key = _resolve_key(key)
    pending_rows = [m for m in _load(_short_path(key), []) if not m.get("consolidated")]
    if not first_time:
        first_time = pending_rows[0].get("time") if pending_rows else None
    if not last_time:
        last_time = pending_rows[-1].get("time") if pending_rows else None
    if not first_time:
        first_time = int(time.time())
    if not last_time:
        last_time = first_time

    # 属性桥接：新日记的 things 顺便补进属性库（每个词只补一次，已存在的跳过）
    try:
        import attributes as _attr
        _attr.ensure_attributes([x.strip() for x in str(things or '').split(',') if x.strip()], batch=6)
    except Exception:
        pass

    # 日记正文带日期（2026-10-27 用户要求）：时间在结构里（first_time）之外，正文也要有，
    # 否则召回时只能靠内容猜是哪天。模型自己写了日期就不重复加。跨天写两个戳。
    content = str(content or "").strip()
    if content and not _has_date_prefix(content):
        stamp = _cn_span(first_time, last_time)
        if stamp:
            content = f"{stamp}，{content}"

    # 私聊日记开头强制打上「谁」：QQ 号 + 昵称，避免模型写错人名（2026-10-28）
    tag = _identity_tag(key)
    if tag and not content.startswith(tag):
        content = tag + content

    # things 里不许留相对时间词：它们会把所有日记串成一片（检索「今天」命中一大片）
    if things:
        cleaned = str(things)
        for w in _REL_TIME_WORDS:
            cleaned = cleaned.replace(w, " ")
        cleaned = re.sub(r"[,，\s]+", ", ", cleaned).strip(" ,，")
        things = cleaned

    entry = {
        "memory_content": content,
        "things": things or "",
        "key": str(key or ""),
        "kind": k,
        "first_time": int(first_time),
        "last_time": int(last_time),
        "last_called": int(time.time()),
        "frequency": freq0,
        # 冷热分层（2026-10-30，借「四个柜子」）：1=热 2=温 3=冷；每晚结算
        "layer": 1,
        "last_hit": 0,
        "next_due": int(time.time()) + 7 * 86400,
        # 压缩损失审计（2026-10-30）：记下这条日记消费掉的是哪段短期原文，
        # 之后追原文、判断“漏了什么”都靠它
        "source_from": int(pending_rows[0].get("time")) if pending_rows else None,
        "source_to": int(pending_rows[-1].get("time")) if pending_rows else None,
        "source_count": len(pending_rows),
        # 写这篇日记时的情绪（用户 2026-10-31 定）：召回时用来做情绪回写
    }
    p = _diary_path(key)
    data = _load(p, [])
    # 缺陷1 修复（2026-11-06）：同一个 first_time 重复 append 会写出两条。
    # DSH 总结失败重试、或同一段短期被总结两次时会撞上，库里出现重复日记，
    # 召回时两条抢同一个名次。这里按 first_time 去重：已存在就覆盖更新，
    # 保留原来的使用计数（frequency / last_hit 等），换掉正文与分类。
    dup_at = None
    for i, old in enumerate(data):
        try:
            if int(old.get("first_time") or 0) == int(entry["first_time"]):
                dup_at = i
                break
        except (TypeError, ValueError):
            continue
    if dup_at is None:
        data.append(entry)
    else:
        keep = data[dup_at]
        for f in ("frequency", "last_hit", "next_due", "layer", "last_called"):
            if f in keep:
                entry[f] = keep[f]
        entry["edited"] = True  # 标记为被更新过，方便事后审计
        data[dup_at] = entry
    _save(p, data)
    # 不删原文，只打标记（2026-10-27 用户定）：参与过总结的条目不再进入下一次 pending，
    # 但继续参与短期注入。物理清理只留一个出口——short_term_max 的自然滚出。
    _mark_consolidated(key, last_time)
    return True


_SUBJ_HINTS = ("我觉得", "我想", "开心", "难过", "生气", "喜欢", "讨厌", "担心", "害怕",
               "舍不得", "感动", "委屈", "骄傲", "失落", "心疼", "安心", "孤单", "温暖")


def _guess_kind(text):
    """没给 kind 时的粗判：出现情绪/感受词 → subjective，否则 objective。"""
    t = str(text or "")
    hits = sum(1 for w in _SUBJ_HINTS if w in t)
    return "subjective" if hits >= 2 else "objective"


def _kind_of(entry):
    k = str(entry.get("kind") or "").strip().lower()
    if k in ("subjective", "objective"):
        return k
    return _guess_kind(entry.get("memory_content"))


_CN_NUM = "零一二三四五六七八九十"


def _cn_day(ts):
    """10-27 → 十月二十七号（个位/十位都能读）。"""
    try:
        lt = time.localtime(int(ts))
    except Exception:
        return ""
    m, d = lt.tm_mon, lt.tm_mday

    def num(n):
        if n <= 10:
            return _CN_NUM[n] if n < 10 else "十"
        if n < 20:
            return "十" + _CN_NUM[n - 10]
        tens, ones = divmod(n, 10)
        return _CN_NUM[tens] + "十" + (_CN_NUM[ones] if ones else "")

    return f"{num(m)}月{num(d)}号"


def _cn_period(ts):
    """按小时给个口语时段：凌晨/早上/上午/中午/下午/晚上/深夜。"""
    try:
        h = time.localtime(int(ts)).tm_hour
    except Exception:
        return ""
    if h < 5:
        return "凌晨"
    if h < 9:
        return "早上"
    if h < 12:
        return "上午"
    if h < 14:
        return "中午"
    if h < 18:
        return "下午"
    if h < 23:
        return "晚上"
    return "深夜"


_DATE_PREFIX_RE = re.compile(r"^\s*(?:\[?\d{1,2}-\d{1,2}\]?|\d{4}-\d{1,2}-\d{1,2}|[一二三四五六七八九十]{1,3}月[一二三四五六七八九十]{1,3}[日号])")


def _has_date_prefix(text):
    return bool(_DATE_PREFIX_RE.match(str(text or "")))


def _cn_stamp(ts):
    """写日记用的口语日期前缀：『十月二十七号上午』。"""
    day, period = _cn_day(ts), _cn_period(ts)
    return f"{day}{period}" if day else ""


def _same_day(a, b):
    try:
        return time.strftime("%Y-%m-%d", time.localtime(int(a))) == time.strftime("%Y-%m-%d", time.localtime(int(b)))
    except Exception:
        return True


def _cn_span(first_time, last_time):
    """日记开头的日期戳；跨天就写两个（用户 2026-10-27 定）：
    『十月二十六号晚上到十月二十七号早上』——这样检索时它同时符合两天的条件。"""
    start = _cn_stamp(first_time)
    if not start:
        return ""
    if last_time and not _same_day(first_time, last_time):
        end = _cn_stamp(last_time)
        if end:
            return f"{start}到{end}"
    return start


def _date_label(entry):
    """把 first_time/last_time 折成 [10-26] 或 [10-25~10-26]。

    为什么必须加：条目本身有 first_time/last_time 字段，但 recall 只把正文交出去，
    模型读到的是没头没尾的一段话，只能靠内容猜是哪天——2026-10-27 实测出现过
    「把前天的日记当成昨晚，两天的记忆拼成一天」。日期在结构里有，就别让它烂在里面。
    正文自己已经写了日期的（新日记都会写），就不再叠一层 `[10-26]`。
    """
    if _has_date_prefix(entry.get("memory_content")):
        return ""

    def _fmt(ts):
        try:
            return time.strftime("%m-%d", time.localtime(int(ts)))
        except Exception:
            return ""

    ft = _fmt(entry.get("first_time"))
    lt = _fmt(entry.get("last_time") or entry.get("first_time"))
    if not ft:
        return ""
    if not lt or lt == ft:
        return f"[{ft}]"
    return f"[{ft}~{lt}]"


def _day0(ts):
    t = time.localtime(int(ts))
    return int(time.mktime((t.tm_year, t.tm_mon, t.tm_mday, 0, 0, 0, 0, 0, -1)))


# 时间词 → (相对今天的天数, 当天起始小时, 结束天数偏移, 结束小时)
# 「昨晚」必须跨零点：她的记忆常常是 23:50 开头、00:30 结尾。
_TIME_RULES = [
    (r"昨晚|昨儿晚上|昨天晚上|昨夜", (-1, 12, 0, 6)),
    (r"前天晚上|前儿晚上", (-2, 12, -1, 6)),
    (r"前天|前儿", (-2, 0, -1, 0)),
    (r"昨天|昨儿", (-1, 0, 0, 0)),
    (r"今早|今晨|今天早上|一大早", (0, 0, 0, 12)),
    (r"今夜|今晚|今天晚上", (0, 18, 1, 0)),
    (r"今天|今日|今儿", (0, 0, 0, 24)),
    (r"上午", (0, 6, 0, 12)),
    (r"中午", (0, 11, 0, 14)),
    (r"下午", (0, 12, 0, 18)),
    (r"晚上", (0, 18, 1, 0)),
    (r"凌晨|半夜", (0, 0, 0, 6)),
    (r"刚才|刚刚", (0, 0, 0, 0)),      # 特殊：最近一小时，下面单独处理
]

_REL_TIME_WORDS = ("今天", "今日", "今儿", "昨天", "昨儿", "昨晚", "昨夜", "前天", "前儿",
                   "明天", "明日", "后天", "大后天",
                   "今早", "今晨", "今晚", "今夜", "上午", "中午", "下午", "晚上",
                   "凌晨", "半夜", "刚才", "刚刚", "现在", "这会儿", "那会儿")


def _time_window(query):
    """把查询里的相对时间词折成时间窗，并从检索词里剔掉。

    返回 (清洗后的 query, [(start_ts, end_ts), ...])。
    2026-10-27 用户定：查到「昨天」就直接换成那一天的窗口去匹配，
    不能让它当普通关键词去撞字面（那样每篇写过「昨晚」的日记都会命中）。
    """
    text = str(query or "")
    now = int(time.time())
    windows = []

    # 先处理需要按「周」算的，再处理按天算的
    base = _day0(now)
    wd = (time.localtime(now).tm_wday)                      # 0=周一
    monday = base - wd * 86400
    for pat, span in (
        (r"上周|上星期|上个星期", (monday - 7 * 86400, monday)),
        (r"这周|本周|这个星期|这星期", (monday, now)),
        (r"前几天|最近几天|前两天", (base - 7 * 86400, base)),
    ):
        if re.search(pat, text):
            text = re.sub(pat, " ", text)
            windows.append((int(span[0]), int(span[1])))

    for pat, (d_start, h_start, d_end, h_end) in _TIME_RULES:
        if not re.search(pat, text):
            continue
        if pat.startswith("刚才|刚刚"):
            windows.append((now - 3600, now))
        else:
            base = _day0(now)
            start = base + d_start * 86400 + h_start * 3600
            end = base + d_end * 86400 + (h_end * 3600 if h_end < 24 else 86400 - 1)
            if end > now:                    # 今天/今晚这类未结束的窗口截到现在
                end = now
            windows.append((start, max(start, end)))
        text = re.sub(pat, " ", text)
    cleaned = re.sub(r"\s+", " ", text).strip()
    return cleaned, windows


def _overlaps(entry, windows):
    ft = entry.get("first_time")
    if ft is None:
        return False
    lt = entry.get("last_time") or ft
    try:
        ft, lt = int(ft), int(lt)
    except Exception:
        return False
    return any(not (lt < w0 or ft > w1) for w0, w1 in windows)


def _pick_kind(ordered, memories, n, subj_ratio):
    """在给定顺序里按主客观比例取 n 条，不够就从另一类借。"""
    if n <= 0 or not ordered:
        return []
    s = int(round(n * subj_ratio))
    s = max(0, min(n, s))
    o = n - s
    subj = [i for i in ordered if _kind_of(memories[i]) == "subjective"]
    obj = [i for i in ordered if _kind_of(memories[i]) != "subjective"]
    picked = subj[:s] + obj[:o]
    if len(picked) < n:
        chosen = set(picked)
        picked += [i for i in ordered if i not in chosen][: n - len(picked)]
    return picked


def _emo_snapshot():
    """读当前四值情绪，写进记忆条目用。读不到给中性值。"""
    try:
        with open(os.path.join(_dir(), "mood.json"), encoding="utf-8") as f:
            m = json.load(f)
        return {
            "h": int(m.get("happiness", 50)),
            "e": int(m.get("excited", 50)),
            "n": int(m.get("negative_emotion", 0)),
        }
    except Exception:
        return {"h": 50, "e": 50, "n": 0}


def _emo_distance(a, b):
    """两个情绪快照的距离（开心、激动为主，负面加一点权重）。"""
    if not a or not b:
        return 999
    return abs(a.get("h", 50) - b.get("h", 50)) + abs(a.get("e", 50) - b.get("e", 50)) \
        + abs(a.get("n", 0) - b.get("n", 0)) * 0.5


def _all_short_term():
    """把全部会话的短期原文摊平（带 emo 的才算）。"""
    out = []
    base = _dir()
    for dirname in all_chat_keys():
        try:
            data = _load(os.path.join(base, "chats", dirname, "short_term.json"), [])
        except Exception:
            continue
        for m in data:
            if m.get("emo"):
                out.append(m)
    return out


def _diary_covering(ts, memories):
    """找覆盖这个时间戳的日记；落在多篇里就取最近的一篇。"""
    best, best_gap = None, None
    for mem in memories:
        f = int(mem.get("first_time") or 0)
        l = int(mem.get("last_time") or 0)
        # 优先用 source 区间（日记真正消费的原文范围）
        sf = int(mem.get("source_from") or f)
        st = int(mem.get("source_to") or l)
        if sf and st and sf <= ts <= st:
            gap = 0
        else:
            gap = min(abs(ts - f), abs(ts - l)) if f else None
            if gap is None:
                continue
        if best_gap is None or gap < best_gap:
            best, best_gap = mem, gap
    return best


def _mood_now():
    """读全局心情（happiness, excited, negative_emotion），读不到给中性值。"""
    try:
        with open(os.path.join(_dir(), "mood.json"), encoding="utf-8") as f:
            m = json.load(f)
        return int(m.get("happiness", 50)), int(m.get("excited", 50)), int(m.get("negative_emotion", 0))
    except Exception:
        return 50, 50, 0


def quota_now():
    """召回配额：**固定值**（2026-11-04 起）。

    原来是「开心值决定 7±3 条、激动值决定主客观比例」。情绪数值系统 2026-11-03 已删，
    这里只剩残骸：读到的永远是 49/50/0，算出来恒为 7 条（主观 3 / 客观 3）。
    实测那个动态范围本来也只有 6~8 条（差 2 条），所以固定成 7 条与"活着时"几乎无差。
    要恢复按情绪召回，得从 emotion.py 重新建，别指望这里。
    """
    return {
        "total": 10, "subjective": 5, "objective": 5,
        "happiness": None, "excited": None, "negative_emotion": None,
        "why": "固定 10 条（2026-11-04 起：情绪数值系统已删；7→10 是因为库涨到 177 篇后前 7 名装不下正确答案）",
    }


def decay_check():
    """时间衰减：20min-1h 扣 3、>1h 扣 2、>15 天再扣 1，最低保留 1（逐会话处理）。"""
    now = int(time.time())
    total = 0
    for dirname in all_chat_keys():
        p = os.path.join(_dir(), "chats", dirname, "diary.json")
        data = _load(p, [])
        if not data:
            continue
        changed = False
        for e in data:
            last = e.get("last_called") or e.get("last_time")
            if last is None:
                continue
            # 缺陷3 修复（2026-11-06）：原来只看 last_called，而扣完不刷新它，
            # 于是同一个时间窗每跑一次扣一次（10→8→6 一直扣到 1）。
            # 现在单独记一个 last_decay 当基准，取两者中较晚的那个；
            # 这样既不污染 last_called（那是"上次被用"的语义），也不会重复扣。
            base = max(int(last or 0), int(e.get("last_decay") or 0))
            diff = now - base
            cur = e.get("frequency", 0)
            if cur <= 1:
                continue
            decay = 0
            if 20 * 60 < diff < 60 * 60:
                decay -= 3
            if 60 * 60 <= diff <= 15 * 24 * 3600:
                decay -= 2
            if diff > 15 * 24 * 3600:
                decay -= 1
            if decay:
                e["frequency"] = max(1, cur + decay)
                e["last_decay"] = now  # 记下这次扣的基准，同一窗口不再重复扣
                changed = True
        if changed:
            _save(p, data)
            total += 1
    return total


# ---------- 检索 ----------

def _count(sentence, word):
    if not word:
        return 0
    c, start = 0, 0
    while True:
        i = sentence.find(word, start)
        if i == -1:
            break
        c += 1
        start = i + 1
    return c


# 2026-11-05：全量加载缓存。
# 实测 225 条每次 8.9ms，5000 条约 198ms——而 recall 每次都要调它。
# 缓存键是每个 diary.json 的 (mtime, size)：有写入就自动失效，不用手动清。
# 返回时逐条浅拷贝：recall 会原地改 frequency/last_called，不拷贝的话缓存会被上一次召回污染。
_DIARY_CACHE = {"sig": None, "rows": None}


def _diary_sig():
    """缓存键：每个 diary.json 的 (mtime_ns, size)。

    性能：_dir() 会读一次 config.json（0.25ms），必须只调一次——
    原来写在循环里，10 个会话 = 2.5ms，比 stat 本身还贵。
    """
    base = os.path.join(_dir(), "chats")
    parts = []
    try:
        with os.scandir(base) as it:
            for ent in it:
                try:
                    if not ent.is_dir():
                        continue
                except OSError:
                    continue
                p = os.path.join(ent.path, "diary.json")
                try:
                    st = os.stat(p)
                    parts.append((ent.name, st.st_mtime_ns, st.st_size))
                except OSError:
                    parts.append((ent.name, 0, 0))
    except OSError:
        return None
    return tuple(parts)


def _load_all_diaries():
    """全局载入所有会话的日记，返回 [{...entry, _src: 会话key}]（长期记忆全局检索的数据源）。"""
    try:
        sig = _diary_sig()
    except Exception:
        sig = None
    if sig is not None and _DIARY_CACHE.get("sig") == sig and _DIARY_CACHE.get("rows") is not None:
        return [dict(e) for e in _DIARY_CACHE["rows"]]
    out = []
    for dirname in all_chat_keys():
        entries = _load(os.path.join(_dir(), "chats", dirname, "diary.json"), [])
        for e in entries:
            e = dict(e)
            e["_src"] = _norm_key(dirname)
            out.append(e)
    if sig is not None:
        _DIARY_CACHE["sig"] = sig
        _DIARY_CACHE["rows"] = [dict(e) for e in out]
    return out


def _lexical_recall(query, memories, limit):
    """词面召回：query → 文档 方向的字符 gram 覆盖度，降序取前 limit。

    2026-11-05 修：原实现方向写反——它统计「things 关键词在 query 里出现几次」，
    而 query 是换说法生成的（"不要照抄原词"），几乎不重合；再统计「整篇正文在
    query 里出现几次」更是恒为 0。于是词面召回形同虚设（20 条基准只有 2 条命中）。

    改成正确方向 + 归一化：把 query 拆成 1/2 字 gram，看有多少落在某篇的
    things/正文里，除以 query 的 gram 总数做归一（否则长正文几乎包含所有常见
    gram，绝对命中数没有区分度）。things 是实体，命中权重更高（×3）。
    1gram 与 2gram 取优：口语短句里「题」「答对」这类单字/双字都有用。
    """
    q = str(query or "").strip()
    if not q:
        return []
    scored = []
    for idx, mem in enumerate(memories):
        things = str(mem.get("things", "")).replace(",", " ").replace("，", " ")
        content = str(mem.get("memory_content", "") or "")
        best = 0.0
        for n in (1, 2):
            grams = {q[i:i + n] for i in range(max(0, len(q) - n + 1))}
            if not grams:
                continue
            th = sum(1 for g in grams if g in things) / len(grams)
            ct = sum(1 for g in grams if g in content) / len(grams)
            best = max(best, th * 3 + ct)
        if best > 0:
            scored.append((idx, best))
    scored.sort(key=lambda x: -x[1])
    return [i for i, _ in scored[:limit]]


def _rerank(query, memories, candidate_indices, top_k, hint="", current_key=""):
    """用 deepseek-flash 对候选做语义重排，返回 top_k 索引。hint 用于补时间线索。

    2026-11-01：候选前带 [同会话] 标记（同一会话的记忆通常更相关），让模型有依据，
    而不是纯读正文。
    """
    if not candidate_indices:
        return []
    cands = [memories[i] for i in candidate_indices]

    def _mark(m):
        if current_key and (m.get("_src") or "") == current_key:
            return "[同会话] "
        return ""

    def _clip(m):
        # 2026-11-05：候选正文截断，控 token（30 条全文约 1 万字符，是原基线 2 倍；
        # 截到 200 字降到 ~1.2 倍）。关键信息多在开头，截断实测不伤命中。
        c = str(m.get("memory_content", "") or "")
        return c[:200] if len(c) > 200 else c

    lines = "\n".join(f"[{j}] {_mark(m)}{_date_label(m)} {_clip(m)}" for j, m in enumerate(cands))
    hint_line = f"注意：{hint}\n" if hint else ""
    prompt = (
        f"下面是若干条关于你和用户过往的日记记忆。请判断哪 {top_k} 条与用户当前这句话最相关。"
        f"不要输出任何思考或解释，只输出相关条目的编号（例如 0,3,7），按相关度从高到低、用逗号分隔。\n"
        f"带 [同会话] 标记的是正在聊的这个会话里的记忆，通常更相关，优先考虑；但如果明显对不上就不选。\n\n"
        f"{hint_line}"
        f"用户当前的话：{query}\n\n{lines}"
    )
    messages = [{"role": "user", "content": prompt}]
    try:
        raw = config.deepseek_complete(messages, max_tokens=400, temperature=0)
    except Exception:
        return candidate_indices[:top_k]
    if not raw:
        return candidate_indices[:top_k]
    out = []
    for tok in raw.replace("，", ",").split(","):
        tok = tok.strip().lstrip("[(").rstrip("])")
        if tok.isdigit():
            j = int(tok)
            if 0 <= j < len(cands):
                out.append(candidate_indices[j])
    return out[:top_k] if out else candidate_indices[:top_k]


def _frequency_fill(memories, selected, need):
    now = int(time.time())
    cands = []
    for idx, m in enumerate(memories):
        if idx in selected:
            continue
        last = m.get("last_called")
        if last is None or now - last > 5:
            if str(m.get("memory_content", "")).strip():
                cands.append((idx, m.get("frequency", 0)))
    cands.sort(key=lambda x: x[1], reverse=True)
    return [i for i, _ in cands[:need]]


def _frequency_top(memories, exclude, n):
    cands = [(i, m.get("frequency", 0)) for i, m in enumerate(memories)
             if i not in exclude and str(m.get("memory_content", "")).strip()]
    cands.sort(key=lambda x: x[1], reverse=True)
    return [i for i, _ in cands[:n]]


def _write_back(entries):
    """把更新后的 frequency/last_called 写回各自会话的 diary.json。"""
    by_src = {}
    for e in entries:
        by_src.setdefault(e.get("_src", "_default"), {})[id(e)] = e
    for dirname in all_chat_keys():
        p = os.path.join(_dir(), "chats", dirname, "diary.json")
        data = _load(p, [])
        if not data:
            continue
        src = _norm_key(dirname)
        updates = {}
        for e in entries:
            if e.get("_src") == src:
                updates[str(e.get("memory_content", ""))[:120] + str(e.get("first_time"))] = e
        if not updates:
            continue
        changed = False
        for m in data:
            k = str(m.get("memory_content", ""))[:120] + str(m.get("first_time"))
            u = updates.get(k)
            if u:
                m["frequency"] = u.get("frequency", m.get("frequency", 0))
                m["last_called"] = u.get("last_called", m.get("last_called"))
                # 缺陷6 修复（2026-11-06）：热度相关的字段原来不写回，
                # 于是 recall_hits 永远攒不到 3 次，「连中 3 次摘原文」从来没生效过。
                for f in ("recall_hits", "hot_used", "last_source_ts"):
                    if f in u:
                        m[f] = u[f]
                changed = True
        if changed:
            _save(p, data)


def _similar(a, b):
    """句子相似度：字符级相似 + 词面重合，取较大值（不依赖模型）。"""
    from difflib import SequenceMatcher

    a = str(a or "").strip()
    b = str(b or "").strip()
    if not a or not b:
        return 0.0
    ratio = SequenceMatcher(None, a, b).ratio()
    ca = {a[i:i + 2] for i in range(max(1, len(a) - 1))}
    cb = {b[i:i + 2] for i in range(max(1, len(b) - 1))}
    # 覆盖度：查询里的二元组有多少出现在那句话里（用户只说了一部分也能对上）
    cover = len(ca & cb) / max(1, len(ca))
    return max(ratio, cover)


def time_subjective_recall(query, memories, current_key=None, num=3, min_ratio=0.35):
    """时间主观检索（2026-10-30 补回，源自 infinite_memory_load_time_subjective）。

    思路跟参考版一致：先在**当前会话的短期原文**里找和这句话最像的几句，
    拿到它们的时间戳，再用时间戳去长期日记里找覆盖那段时间的条目。

    补的是这类场景：「你上次说那个…」——用户换了说法，词面召回不到，
    但那句话确实说过，靠"像不像"把时间点找出来。
    """
    from difflib import SequenceMatcher  # noqa: F401  （_similar 里用）

    if not current_key:
        return []
    rows = _load(_short_path(current_key), [])
    if not rows:
        return []
    scored = []
    for m in rows[-400:]:
        text = str(m.get("content") or "")
        if len(text) < 4:
            continue
        r = _similar(query, text)
        if r >= min_ratio:
            scored.append((r, int(m.get("time") or 0)))
    if not scored:
        return []
    scored.sort(key=lambda x: -x[0])
    stamps = [t for _, t in scored[:num] if t]

    hits = []
    days = {time.strftime("%Y-%m-%d", time.localtime(ts)) for ts in stamps}
    for ts in stamps:
        for idx, mem in enumerate(memories):
            ft = int(mem.get("first_time") or 0)
            lt = int(mem.get("last_time") or ft)
            if ft and ft - 600 <= ts <= lt + 600 and idx not in hits:
                hits.append(idx)
    # 兜底：时间窗对不上（日记按天合并过）→ 退到“同一天”的条目
    if not hits:
        for idx, mem in enumerate(memories):
            ft = int(mem.get("first_time") or 0)
            if ft and time.strftime("%Y-%m-%d", time.localtime(ft)) in days and idx not in hits:
                hits.append(idx)
    return hits[:num]


def _log_recall_stats(query, memories, vec_idx, lex_idx):
    """记一条召回采样：哪些是向量选的、哪些是词面/顺序选的（不记正文）。"""
    path = os.path.join(_dir(), "recall_stats.jsonl")

    def tag(i):
        m = memories[i]
        return "%s#%s" % (str(m.get("_src") or "")[:18], m.get("first_time") or 0)

    rec = {
        "ts": int(time.time()),
        "q": str(query or "")[:60],
        "vec": [tag(i) for i in vec_idx],
        "lex": [tag(i) for i in lex_idx[:6]],
        "overlap": len(set(vec_idx) & set(lex_idx)),
        "pool": len(memories),
    }
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def _long_term_notes(query, limit=2):
    """「我变了什么」——只在问到自己变化时带出来（2026-10-30）。"""
    q = str(query or "")
    if not any(w in q for w in ("变化", "变了", "成长", "以前", "现在", "不像以前", "长大")):
        return []
    path = os.path.join(_dir(), "long_term.jsonl")
    if not os.path.exists(path):
        return []
    rows = []
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except Exception:
            continue
    return [str(r.get("text") or "") for r in rows[-limit:]]


def _emotion_echo(memories, picked):
    """④ 情绪回写（用户 2026-10-31 定，每 5 轮一次，写进临时情感）。

    规则：拿召回**第一条**日记的情绪，和当前情绪算差，差值的 20% 给当前。
    例：当前 50/60，日记 60/50 → 开心 +2、激动 −2。
    """
    if not picked:
        return None
    try:
        mp = os.path.join(_dir(), "mood.json")
        with open(mp, encoding="utf-8") as f:
            mood = json.load(f)
        tick = int(mood.get("echo_tick") or 0) + 1
        mood["echo_tick"] = tick
        if tick % 5 != 0:                 # 每 5 轮才拉一次
            with open(mp, "w", encoding="utf-8") as f:
                json.dump(mood, f, ensure_ascii=False)
            return None
        src = memories[picked[0]]
        emo = src.get("emo") or {}
        if not emo:
            with open(mp, "w", encoding="utf-8") as f:
                json.dump(mood, f, ensure_ascii=False)
            return None
        cur_h = int(mood.get("happiness", 50))
        cur_e = int(mood.get("excited", 50))
        dh = int(round((int(emo.get("h", 50)) - cur_h) * 0.2))
        de = int(round((int(emo.get("e", 50)) - cur_e) * 0.2))
        if dh or de:
            # 开心走临时情感（体感），激动直接调
            th = int(mood.get("temp_happiness") or mood.get("happiness") or 50)
            mood["temp_happiness"] = max(0, min(100, th + dh))
            mood["excited"] = max(0, min(100, cur_e + de))
            mood["last_echo"] = {"from": emo, "dh": dh, "de": de, "at": int(time.time())}
        with open(mp, "w", encoding="utf-8") as f:
            json.dump(mood, f, ensure_ascii=False)
        return {"dh": dh, "de": de}
    except Exception:
        return None


def _extra_by_emotion(memories, picked, take=10):
    """⑤ 每轮额外一条：全库随机 10 条原文 → 情绪最接近的那条 → 它的日记。"""
    try:
        import random
        pool = _all_short_term()
        if not pool:
            return None
        sample = random.sample(pool, min(take, len(pool)))
        now = _emo_snapshot()
        best = min(sample, key=lambda m: _emo_distance(m.get("emo"), now))
        mem = _diary_covering(int(best.get("time") or 0), memories)
        if not mem:
            return None
        idx = memories.index(mem)
        if idx in picked:                  # 跟前面重复就算了（用户说的）
            return None
        return idx
    except Exception:
        return None


def recall(query, max_total=0, subjective_ratio=None, current_key=None, short_term_turns=None, with_ids=False):
    """检索记忆。

    配额规则（「情感驱动记忆」的接线点）：
      max_total=0（默认）→ 由当前情绪决定：总条数 7±3（越难过召回越多），
                            主观/客观条数由激动值与负面值决定（越激动越偏主观）；
      max_total>0        → 用调用方给的数量；subjective_ratio 可单独覆盖主观占比。

    短期原文（去重接线点，操作者 2026-10-25 指定）：
      short_term_turns=None → 用配置里的默认窗口（40 轮）；
      short_term_turns=0    → **不注入短期原文**。用在「本会话上下文里已经有最近对话」
                              的场合：会话本身就逐字含着这些轮次，再从记忆里搬一遍
                              纯属重复（每轮白烧 800 字左右的新增 token）。

    数据来源：短期 = **只取当前会话**最近 N 轮；长期 = **全局所有会话的日记**（跨会话标出处）。
    流水线：词面召回 → 频率补齐候选池 → flash 语义重排 → 按主客观配额挑选 + 互相借用。
    """
    cfg = config.load_config()
    top_k = cfg.get("retrieval", {}).get("top_k", 3)
    cand_limit = cfg.get("retrieval", {}).get("candidate_limit", 10)

    # 1) 配额：默认由情绪决定
    q = quota_now()
    if max_total and int(max_total) > 0:
        total = int(max_total)
        if subjective_ratio is None:
            subj_q = int(round(total * (q["subjective"] / max(1, q["total"]))))
        else:
            subj_q = int(round(total * float(subjective_ratio)))
        subj_q = max(0, min(total, subj_q))
        obj_q = total - subj_q
        q = dict(q, total=total, subjective=subj_q, objective=obj_q, source="caller")
    else:
        total, subj_q, obj_q = q["total"], q["subjective"], q["objective"]
        q = dict(q, source="emotion")

    # 短期原文：short_term_turns=0 时跳过（本会话已有近期对话，不必重复注入）
    if short_term_turns is not None and int(short_term_turns) <= 0:
        short_text = ""
    else:
        turns = int(short_term_turns) if short_term_turns else cfg.get("memory", {}).get("short_term_recall_turns", 40)
        short_text = get_short_term_text(max_turns=turns, current_key=current_key)
    memories = _load_all_diaries()
    if not memories:
        return {"short_term": short_text, "long_term": "", "long_term_count": 0, "quota": q,
                "ids": [] if with_ids else []}

    # 1.5) 时间词 → 时间窗（2026-10-27 用户定）：查到「昨天」就换成那一天的窗口去匹配，
    #      时间词本身从检索词里剔掉，否则每篇写过「昨晚」的日记都会字面命中。
    clean_query, windows = _time_window(query)
    # 词面匹配只用清洗后的词（时间词当关键词会串味）；时间词本身留给重排模型看，它读得懂
    lex_query = clean_query if windows else str(query or "")

    # 2) 候选池：词面 + 时间窗 + 属性桥接（2026-11-05 起不再用 frequency 补，
    #    frequency 会被 recall 写回污染，导致评测顺序依赖、不可复现；向量候选足够宽）
    lex = _lexical_recall(lex_query, memories, cand_limit) if lex_query.strip() else []
    pool = list(lex)
    if windows:
        # 时间窗内的条目必须进候选池，否则「昨天」被清洗掉之后可能一条都不剩
        inw = [i for i, m in enumerate(memories) if _overlaps(m, windows)]
        for i in inw[: cand_limit * 3]:
            if i not in pool:
                pool.append(i)
    # 2.5) 属性桥接（2026-10-30 补回）：词面没命中的，用「事物属性 ∩ 这句话」兜底
    try:
        import attributes as _attr
        for idx, overlap in _attr.bridge_scores(lex_query or query, memories, exclude=set(pool), max_hits=3):
            if idx not in pool:
                pool.append(idx)
    except Exception:
        pass

    # 3) 时间窗 hint（给重排模型的时间线索；无时间词时为空）
    note = ""
    if windows:
        days = "、".join(sorted({time.strftime("%m-%d", time.localtime(w[0])) for w in windows}))
        hint = f"用户问的是 {days} 这段时间的事，优先挑那几天的日记。"
        if not any(_overlaps(m, windows) for m in memories):
            note = f"【{days} 没有日记。别编，直接说那天没记。】"
    else:
        hint = ""

    # 缺陷5 修复（2026-11-06）：候选池为空（或向量层整体抛异常）时，
    # picked 原本完全没有绑定，后面无条件使用 → UnboundLocalError。
    # 先给一个空列表兜底，语义上等价于"这次没召回任何条目"。
    picked = []

    # 4) 向量 + 词面统一候选池，一次语义重排（2026-11-05 改）
    # 定位结论：瓶颈是"没捞到"不是"排序"。原结构是两路独立重排 + 向量绝对优先，
    # 向量只取 top4（[17][18] rank9、[11] rank26、[14] rank10 都进不来），词面那一路
    # 的好结果（[14] 词面 rank4）又被向量优先埋掉。改成：词面 + 向量合并去重成一个池，
    # 一次重排挑 total 条。
    try:
        import vectors as _vec
        # 向量候选数：原「配额×0.75（约4条）」太小，扩到 30 让正确答案进池。VEC_CAND 可覆盖。
        n_vec = int(os.environ.get("VEC_CAND", "30"))
        vec_hits = [i for i, _sc in _vec.top_k(query, memories, n_vec)]
        cand = []
        seen = set()
        for i in list(vec_hits) + list(pool):
            if i not in seen and str(memories[i].get("memory_content", "")).strip():
                seen.add(i)
                cand.append(i)
        if cand:
            # 控制候选池大小（token 约束）：重排输入 ≤ CAND_MAX 条
            cand = cand[:int(os.environ.get("CAND_MAX", "30"))]
            ranked = _rerank(
                str(query or ""), memories, cand, min(total, len(cand)), hint,
                current_key=_resolve_key(current_key) if current_key else "",
            )
            picked = list(ranked)[:total]
            # 命中率采样（给评估用，不写正文，只记 id 与来源）
            try:
                _log_recall_stats(query, memories, vec_hits, [i for i in picked if i not in vec_hits])
            except Exception:
                pass
    except Exception:
        pass

    # 合并日记吃双份配额（用户 2026-10-29 定）：它是压缩过的长条目，
    # 每选中一条，总召回条数就减 1（减到 2 为止，下限 2 条），剩下的名额不用再找。
    budget = total
    limited = []
    for idx in picked:
        if len(limited) >= budget:
            break
        limited.append(idx)
        if memories[idx].get("merged_from") and budget > 2:
            budget -= 1
    picked = limited

    contents = []
    picked_ids = []
    now = int(time.time())
    if picked:
        max_idx = max(picked, key=lambda i: memories[i].get("frequency", 0))
        for idx in picked:
            if idx != max_idx:
                memories[idx]["frequency"] = memories[idx].get("frequency", 0) + 1
            memories[idx]["last_called"] = now
            c = str(memories[idx].get("memory_content", "")).strip()
            if not c:
                continue
            stamp = _date_label(memories[idx])
            if stamp:
                c = f"{stamp} {c}"
            if memories[idx].get("disputed"):
                c = "【有争议·别当定论】" + c
            mk = memories[idx].get("_src", "")
            if current_key and mk and mk != current_key:
                label = _key_label(mk)
                if label:
                    c = f"[{label}的记忆] {c}"
            contents.append(c)
            picked_ids.append({"key": memories[idx].get("_src") or memories[idx].get("key") or "",
                               "first_time": int(memories[idx].get("first_time") or 0)})
        _write_back(memories)

    # 热条目（用户 2026-10-29 定）：同一条日记连续 3 轮被召回 → 从原文里摘最贴合的一段
    hot_notes = []
    try:
        import source as _src
        for idx in picked:
            e = memories[idx]
            hits = [int(h) for h in (e.get("recall_hits") or [])][-9:] + [now]
            e["recall_hits"] = hits
            # 上一轮和这一轮间隔超过 1 小时 → 算新的一次"热"，可用次数归零
            if len(hits) >= 2 and hits[-2] < now - 3600:
                e["hot_used"] = 0
            if len(hits) < 3 or hits[-3] < now - 3 * 3600:
                continue
            # 原文最多用 2 轮，用完就扔（用户 2026-10-29 定）
            if int(e.get("hot_used") or 0) >= 2:
                continue
            txt = _src.excerpt(e.get("first_time"), e.get("key") or "", query)
            if txt:
                e["hot_used"] = int(e.get("hot_used") or 0) + 1
                e["last_source_ts"] = now
                hot_notes.append(txt)
        # 缺陷6 修复（2026-11-06）：原来只在「摘到原文」时才写回，
        # 而摘原文要求先有 3 次命中记录 —— 鸡生蛋，机制永远触发不了。
        # 现在只要记过命中就写回。
        if picked:
            _write_back(memories)
    except Exception:
        hot_notes = []

    try:
        _lts = _long_term_notes(query, 2)
        if _lts:
            contents.append("【我这些年的变化】\n" + "\n".join("· " + t for t in _lts))
    except Exception:
        pass

    if hot_notes:
        contents.append("【原文摘录·这条日记反复用到】\n" + "\n\n---\n\n".join(hot_notes[:2]))

    # 2026-11-04：④情绪回写 / ⑤情绪撞上了 已删（情绪数值系统没了，它们只会空转）

    body = "\n".join(contents)
    if note:
        body = (note + "\n" + body).strip()

    return {
        "short_term": short_text,
        "long_term": body,
        "long_term_count": len(contents),
        "quota": q,
        "note": note,
        "time_window": [[int(w[0]), int(w[1])] for w in windows] if windows else [],
        "ids": picked_ids if with_ids else [],
        "emotion_echo": _emo_echo_result if "_emo_echo_result" in dir() else None,
    }


# ---------- 碎片日记合并（2026-10-28 用户定的规则） ----------
# 规则：同一会话里，任意 **2 小时窗口**内超过 2 篇就合并成一篇；≤2 篇不动。
# 合并不迁就"一天"，只看密度：2~4 点写了一篇 → 不管；8~10 点写了 6 篇 → 合成一篇。

def _clip_sentence(text, limit):
    """超长时按最后一个句号/问号/感叹号截断，别切在半句上。"""
    t = str(text or "").strip()
    if len(t) <= limit:
        return t
    head = t[:limit]
    for mark in ("。", "！", "？", "…"):
        idx = head.rfind(mark)
        if idx > limit * 0.5:
            return head[: idx + 1]
    return head


# ---------- 合并 = 自然拼接（2026-10-31 用户定） ----------
# 以前是「把几段丢给模型重写一遍」，细节就是在那丢的（10-28 那次事故的根子）。
# 现在：先按时间顺序把原文直接拼起来，只去掉重复的日期戳和身份戳；
# 拼完超过 800 字，才让模型「只删不改」地压到 800 以内。

MERGE_LIMIT = 800

_ID_TAG_RE = re.compile(r"^【私聊[^】]*】")
_CN_MD = r"[一二三四五六七八九十]{1,3}月[一二三四五六七八九十]{1,3}[日号]"
_PERIOD = r"(凌晨|清晨|早上|上午|中午|下午|傍晚|晚上|夜里|深夜)"
_DATE_STAMP_RE = re.compile(
    r"^(" + _CN_MD + r")" + _PERIOD + r"?(?:到(" + _CN_MD + r")" + _PERIOD + r"?)?[，,]\s*"
)

_END_PUNCT = "。！？…」”\"'）)"


def _split_head(text):
    """拆出「身份戳 / 日期 / 时段 / 日期戳原文 / 正文」。

    只管身份戳和日期戳。**不碰正文外面的 （）/「」**：这两个外壳一个是你手改
    （`edited="manual"`）、一个是她自己改（`edited="ai"`），只要带 `edited`
    整个会话就进不了合并（`merge_window` 里 `any(e.get("edited"))` 直接跳过），
    括号壳走不到这里；真去脱它反而会吃掉正文自带的括号（例如「（笑）他……」）。
    """
    s = str(text or "").strip()
    tag = ""
    m = _ID_TAG_RE.match(s)
    if m:
        tag = m.group(0)
        s = s[m.end():].lstrip()
    day = period = stamp = ""
    m = _DATE_STAMP_RE.match(s)
    if m:
        day = m.group(1)
        period = m.group(2) or ""
        if m.group(3):
            stamp = "%s%s到%s%s" % (day, period, m.group(3), m.group(4) or "")
        else:
            stamp = day + period
        s = s[m.end():].lstrip()
    return tag, day, period, stamp, s


def _tidy_tail(s):
    s = str(s or "").rstrip()
    if s and s[-1] not in _END_PUNCT:
        s += "。"
    return s


def _natural_join(group):
    """把几段日记按时间顺序直接拼成一段，不交给模型重写。

    同一天的后几段不再重复「十月二十八号」，改成「到了下午，…」；
    跨天照写完整日期戳，保证还能锚定到具体哪天。
    """
    items = []
    for e in sorted(group, key=lambda x: x.get("first_time") or 0):
        raw = str(e.get("memory_content") or "").strip()
        if not raw:
            continue
        tag, day, period, stamp, rest = _split_head(raw)
        items.append({"tag": tag, "day": day, "period": period, "stamp": stamp, "text": (rest or raw).strip()})
    if not items:
        return ""
    base_day = items[0]["day"]
    out = ""
    for i, it in enumerate(items):
        t = it["text"]
        if not t:
            continue
        if i == 0:
            lead = ""
            if it["stamp"]:
                st = it["stamp"]
                # 正文自己已经写了「上午…」，日期戳里就别再来一遍
                if it["period"] and t.startswith(it["period"]) and st.endswith(it["period"]):
                    st = st[: -len(it["period"])]
                lead = st + "，"
            out = lead + t
            continue
        if it["stamp"]:
            if it["day"] and it["day"] == base_day and it["period"]:
                # 正文自己已经写了「下午…」就不再重复一次
                lead = "" if t.startswith(it["period"]) else "到了" + it["period"] + "，"
            elif it["day"] and it["day"] == base_day:
                lead = ""
            else:
                lead = it["stamp"] + "，"
        else:
            lead = ""
        out = _tidy_tail(out) + lead + t
    return out.strip()


def _compress_prompt(text, limit):
    return (
        "下面是一篇日记，由几段按时间顺序直接拼接而成，现在 %d 字，超过 %d 字上限。\n"
        "请把它压缩到 %d 字以内。要求：\n"
        "1. 只删重复、口水话、可以省略的过渡；**不要重写成另一个故事**；\n"
        "2. 人名、数字、约定、梗、当时情绪，一个都不能丢；\n"
        "3. 保持原来的顺序、第一人称、口语；\n"
        "4. 不要编造原文里没有的内容；不要分条、不要 Markdown。\n\n%s"
        % (len(text), limit, limit, text)
    )


def _compress_text(text, limit, tries=2):
    """超长才走的压缩。失败返回空串，由调用方退回按句截断。"""
    for _ in range(tries):
        try:
            raw = config.deepseek_complete(
                [{"role": "user", "content": _compress_prompt(text, limit)}], max_tokens=2200
            )
            out = (raw or "").strip()
        except Exception:
            out = ""
        if len(out) >= 40:
            return out
        time.sleep(1.5)
    return ""



def _merge_group(key, group):
    """把一组条目自然拼接成一条；超 800 字才让模型压缩。拼不出来返回 None。"""
    texts = [str(e.get("memory_content", "")).strip() for e in group]
    texts = [t for t in texts if t]
    if len(texts) < 2:
        return None
    first_ts = min(e.get("first_time") or 0 for e in group)
    last_ts = max((e.get("last_time") or e.get("first_time") or 0) for e in group)
    body = _natural_join(group)
    if not body:
        return None
    tag = _identity_tag(key)
    budget = MERGE_LIMIT - len(tag)
    compressed = len(body) > budget
    if compressed:
        squeezed = _compress_text(body, budget)
        # 压缩失败就按句截断 —— 宁可少一点，也不能把整条丢掉
        body = _clip_sentence(squeezed, budget) if squeezed else _clip_sentence(body, budget)
    if tag and not body.startswith(tag):
        body = tag + body
    things = ", ".join(sorted({
        t.strip() for e in group for t in str(e.get("things", "")).split(",") if t.strip()
    }))
    kinds = [_kind_of(e) for e in group]
    kind = "subjective" if kinds.count("subjective") >= kinds.count("objective") else "objective"
    return {
        "memory_content": body,
        "things": things,
        "key": key,
        "kind": kind,
        "first_time": first_ts,
        "last_time": last_ts,
        "last_called": int(time.time()),
        "frequency": max((e.get("frequency", 0) or 0) for e in group) or 20,
        "merged_from": len(group),
        "merged_at": int(time.time()),
        # 拼接还是压缩、从哪几条来的 —— 想退回原文时按这两个字段去 .bak 里找
        "merge_mode": "concat+compress" if compressed else "concat",
        "merged_first_times": [int(e.get("first_time") or 0) for e in group],
    }


def merge_window(window_minutes=120, max_per_window=2, key="", dry_run=False, max_rounds=40):
    """同一会话里，任意 2 小时窗口内日记超过 max_per_window 篇就合并成一篇。

    ≤max_per_window 篇的窗口不动（用户 2026-10-28：2~4 点写一篇 → 不管；
    8~10 点写六篇 → 合成一篇）。返回 [{key, from, to, at, chars}]。
    """
    keys = [_resolve_key(key)] if key else [d for d in all_chat_keys() if d != "_default"]
    win = max(600, int(window_minutes) * 60)
    max_n = max(2, int(max_per_window))
    report = []

    for k in keys:
        p = _diary_path(k)
        entries = _load(p, [])
        if len(entries) <= max_n:
            continue
        # 用户亲手改过的会话不再自动合并（2026-10-28：避免又一次把他的修改压掉）
        if any(e.get("edited") for e in entries):
            continue
        entries.sort(key=lambda e: e.get("first_time") or 0)
        changed = False
        days = set()

        for _ in range(max_rounds):
            hit = None
            for i, e in enumerate(entries):
                t0 = e.get("first_time") or 0
                grp = [j for j in range(i, len(entries)) if (entries[j].get("first_time") or 0) < t0 + win]
                if len(grp) > max_n:
                    hit = grp
                    break
            if not hit:
                break
            group = [entries[j] for j in hit]
            if dry_run:
                report.append({"key": k, "from": len(group), "to": 1,
                               "at": time.strftime("%m-%d %H:%M", time.localtime(group[0].get("first_time") or 0)),
                               "chars": 0})
                break
            merged = _merge_group(k, group)
            if not merged:
                break
            drop = set(hit)
            entries = [e for i, e in enumerate(entries) if i not in drop] + [merged]
            entries.sort(key=lambda e: e.get("first_time") or 0)
            changed = True
            days.add(time.strftime("%Y-%m-%d", time.localtime(merged["first_time"])))
            report.append({"key": k, "from": len(group), "to": 1,
                           "at": time.strftime("%m-%d %H:%M", time.localtime(merged["first_time"])),
                           "chars": len(merged["memory_content"])})

        if changed and not dry_run:
            try:
                bak = p + ".bak-" + time.strftime("%Y%m%d-%H%M%S")
                if not os.path.exists(bak):
                    _save(bak, _load(p, []))
            except Exception:
                pass
            _save(p, entries)
            for d in sorted(days):
                try:
                    export_check(d)
                except Exception:
                    pass

    return report


def merge_days(days_back=1, min_entries=2, key="", dry_run=False):
    """按「最近 N 天、窗口内超过 min_entries 篇」合并。

    缺陷7 修复（2026-11-06）：原来这两个参数被整个忽略，直接转给 merge_window
    用默认的 120 分钟 / 2 篇，调用方以为自己设了门槛，其实没有。
    现在把 days_back 换算成窗口（按「天」看的粒度），min_entries 原样传下去。
    """
    try:
        days = max(1, int(days_back))
    except (TypeError, ValueError):
        days = 1
    # 一天 = 1440 分钟；按天合并时窗口就是那么多天
    window_minutes = days * 24 * 60
    try:
        max_n = max(2, int(min_entries))
    except (TypeError, ValueError):
        max_n = 2
    return merge_window(window_minutes=window_minutes, max_per_window=max_n,
                        key=key, dry_run=dry_run)



# ---------- 待人工检查的合并日记（用户 2026-10-28 加） ----------
# 规则：当天只要有「合并版」日记，就把它们打包成 txt，让AI拿给用户看，
# 用户指出问题后由她自己改（memory_edit_entry）。

def check_dir():
    d = os.path.join(_dir(), "check")
    os.makedirs(d, exist_ok=True)
    return d


def export_check(date="", key=""):
    """把某天（默认今天）所有「合并版」日记导出成 txt，返回 {path, count, keys}。"""
    day = date or time.strftime("%Y-%m-%d")
    keys = [_resolve_key(key)] if key else [d for d in all_chat_keys() if d != "_default"]
    picked = []
    for k in keys:
        for e in _load(_diary_path(k), []):
            ft = int(e.get("first_time") or 0)
            if time.strftime("%Y-%m-%d", time.localtime(ft)) != day:
                continue
            if not e.get("merged_from"):
                continue
            picked.append((k, e))
    if not picked:
        return {"path": "", "count": 0, "keys": [], "date": day}

    picked.sort(key=lambda kp: (kp[0], kp[1].get("first_time") or 0))
    lines = [
        "AI日记 · 待人工检查（%s）" % day,
        "",
        "这些是当天由多篇碎片合并成的日记。合并会压缩细节，可能记错。",
        "用户看过之后指出问题，AI用 memory_edit_entry(first_time=…, content=…) 自己改。",
        "",
    ]
    labels = {}
    for k, e in picked:
        labels.setdefault(k, _key_label(_norm_key(k)) or k)
        ft = time.strftime("%m-%d %H:%M", time.localtime(e.get("first_time") or 0))
        lt = time.strftime("%m-%d %H:%M", time.localtime(e.get("last_time") or e.get("first_time") or 0))
        lines.append("=" * 60)
        lines.append("[%s] %s ~ %s  （合并 %d 篇）" % (labels[k], ft, lt, e.get("merged_from") or 0))
        lines.append("key=%s  first_time=%d" % (k, int(e.get("first_time") or 0)))
        lines.append("things: %s" % (e.get("things") or ""))
        lines.append("")
        lines.append(str(e.get("memory_content") or "").strip())
        lines.append("")

    path = os.path.join(check_dir(), "待检查-%s.txt" % day)
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return {"path": path, "count": len(picked), "keys": sorted(labels.values()), "date": day}


def _mark_ai_edit(text):
    """她（AI）自改的条目用日语括号「」包起来，和用户手改的中文括号（）区分。"""
    t = str(text or "").strip()
    for a, b in (("「", "」"), ("（", "）")):
        if t.startswith(a) and t.endswith(b):
            t = t[1:-1].strip()
    return "「%s」" % t



def flag_wrong(first_time, reason="", key=""):
    """把某条记忆标成「有争议」（用户说它记错了，或她自己核出来不对）。

    只在条目上加标记：召回时会降权、并在正文前加【有争议】，提示她引用时要说“我记的可能是错的”。
    """
    target = int(first_time or 0)
    keys = [_resolve_key(key)] if key else [d for d in all_chat_keys() if d != "_default"]
    for k in keys:
        p = _diary_path(k)
        data = _load(p, [])
        for e in data:
            if int(e.get("first_time") or 0) != target:
                continue
            # 2026-11-06 修：备份原本写在改动之后，存进去的已经是改过的内容，
            # 起不到回滚作用。现在先存一份原始快照，再动。
            try:
                _save(p + ".bak-dispute-" + time.strftime("%Y%m%d-%H%M%S"),
                      json.loads(json.dumps(data, ensure_ascii=False)))
            except Exception:
                pass
            e["disputed"] = True
            e["dispute_reason"] = str(reason or "").strip()
            e["disputed_at"] = int(time.time())
            _save(p, data)
            return {"ok": True, "key": k, "first_time": target}
    return {"ok": False, "reason": "not_found", "first_time": target}


def edit_entry(first_time, content=None, things=None, kind=None, key=""):
    """按 first_time 找到某条日记并改它（用户看过指出问题后，她用它自己改）。

    只改传进来的字段，其余保持原样；写前备份 diary.json。
    """
    target = int(first_time or 0)
    keys = [_resolve_key(key)] if key else [d for d in all_chat_keys() if d != "_default"]
    for k in keys:
        p = _diary_path(k)
        data = _load(p, [])
        for e in data:
            if int(e.get("first_time") or 0) != target:
                continue
            # 2026-11-06 修：备份原本在改动之后做，存进去的已是新内容。
            # 先存原始快照（同名只存一次，避免一次会话堆一堆）。
            try:
                bak = p + ".bak-edit-" + time.strftime("%Y%m%d-%H%M%S")
                if not os.path.exists(bak):
                    _save(bak, json.loads(json.dumps(data, ensure_ascii=False)))
            except Exception:
                pass
            if content is not None and str(content).strip():
                e["memory_content"] = _mark_ai_edit(content)
            if things is not None:
                e["things"] = str(things).strip()
            if kind in ("subjective", "objective"):
                e["kind"] = kind
            e["edited"] = "ai"
            e["disputed"] = False          # 改过＝已核对   # 「」= 她自己改的；（）= 用户手改的
            e["edited_at"] = int(time.time())
            _save(p, data)
            return {"ok": True, "key": k, "first_time": target, "chars": len(e["memory_content"])}
    return {"ok": False, "reason": "not_found", "first_time": target}




