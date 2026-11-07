"""心率邮件通道（2026-10-27）：iPhone 快捷指令 → 邮件 → 这里 IMAP 收 → 本地落盘。

为什么是邮件：用户先做了「收到 QQ 消息 → 发微信心率」，但微信 4.x 的消息存在
加密库里，程序读不了；他也不想让我截屏 OCR（隐私）。邮件是三选一里最干净的：
不暴露公网、不需要窗口亮着、锁屏也能收。

约定：
- 主题含 `HR` 或 `心率` 的邮件才算（其余一律忽略，别去碰私人邮件）
- 正文里第一个 30~220 的整数当心率；时间取邮件的 Date 头
- 落盘：AI_data/{ai}_data/health.jsonl（追加）+ health.latest.json（只留最新）
- 游标：health.mail_state.json 记 last_uid，不重复处理
"""
import email
import imaplib
import json
import os
import re
import threading
import time
from email.header import decode_header
from email.utils import parsedate_to_datetime

import config

_DEFAULT_POLL = 300
_SUBJECT_RE = re.compile(r"(\bHR\b|心率|heart\s*rate)", re.I)
_BPM_RE = re.compile(r"\b(\d{2,3})\b")

_lock = threading.Lock()


def _cfg():
    return config.load_config().get("health", {}) or {}


def _paths():
    d = config.data_dir()
    os.makedirs(d, exist_ok=True)
    return (
        os.path.join(d, "health.jsonl"),
        os.path.join(d, "health.latest.json"),
        os.path.join(d, "health.mail_state.json"),
        os.path.join(d, "health.log"),
    )


def _log(line):
    try:
        _, _, _, logp = _paths()
        with open(logp, "a", encoding="utf-8") as f:
            f.write("%s %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), line))
    except Exception:
        pass


def _decode_header(value):
    if not value:
        return ""
    out = []
    for part, enc in decode_header(str(value)):
        if isinstance(part, bytes):
            try:
                out.append(part.decode(enc or "utf-8", "ignore"))
            except Exception:
                out.append(part.decode("utf-8", "ignore"))
        else:
            out.append(part)
    return "".join(out)


def _text_body(msg):
    """取 text/plain 正文；没有就退回 HTML 去标签。"""
    texts, html = [], []
    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            if ctype not in ("text/plain", "text/html"):
                continue
            try:
                payload = part.get_payload(decode=True)
                charset = part.get_content_charset() or "utf-8"
                body = payload.decode(charset, "ignore") if payload else ""
            except Exception:
                continue
            (texts if ctype == "text/plain" else html).append(body)
    else:
        payload = msg.get_payload(decode=True)
        charset = msg.get_content_charset() or "utf-8"
        (texts if msg.get_content_type() == "text/plain" else html).append(
            payload.decode(charset, "ignore") if payload else ""
        )
    if texts:
        return "\n".join(texts)
    return re.sub(r"<[^>]+>", " ", "\n".join(html))


def _load_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)


def _parse_bpm(body):
    """优先取「整行只有一个数字」的那种（快捷指令发出来的就一行），
    再退回全文里第一个合理范围内的数字。"""
    for line in (body or "").splitlines():
        s = line.strip().strip("，,。.心率:：")
        if s.isdigit() and 30 <= int(s) <= 220:
            return int(s)
    for m in _BPM_RE.finditer(body or ""):
        v = int(m.group(1))
        if 30 <= v <= 220:
            return v
    return None


def _append(record):
    jsonl, latest, _, _ = _paths()
    with open(jsonl, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    _save_json(latest, record)


def fetch_new(limit=50):
    """拉一次新邮件，返回本次新增的心率记录列表。失败返回 []（不抛）。"""
    c = _cfg()
    mail = c.get("mail", {}) or {}
    user, pwd = str(mail.get("user") or ""), str(mail.get("pass") or "")
    if not (c.get("enabled", True) and user and pwd):
        return []
    host = mail.get("host", "imap.qq.com")
    port = int(mail.get("port", 993))
    folder = mail.get("folder", "INBOX")
    _, _, statep, _ = _paths()
    state = _load_json(statep, {})
    last_uid = int(state.get("last_uid", 0) or 0)

    new = []
    m = None
    try:
        m = imaplib.IMAP4_SSL(host, port)
        m.login(user, pwd)
        m.select(folder, readonly=True)
        typ, data = m.uid("SEARCH", None, "UID", "%d:*" % (last_uid + 1))
        if typ != "OK":
            return []
        uids = [int(x) for x in (data[0] or b"").split() if x.isdigit()]
        uids = [u for u in uids if u > last_uid][-limit:]
        for uid in uids:
            typ, d = m.uid("FETCH", str(uid), "(RFC822)")
            if typ != "OK" or not d or not isinstance(d[0], tuple):
                continue
            msg = email.message_from_bytes(d[0][1])
            subject = _decode_header(msg.get("Subject"))
            try:
                ts = int(parsedate_to_datetime(msg.get("Date")).timestamp())
            except Exception:
                ts = int(time.time())
            # 只认主题（2026-10-27 实测：正文里出现 "heart rate" 的营销邮件会误命中）
            if _SUBJECT_RE.search(subject or ""):
                bpm = _parse_bpm(_text_body(msg))
                if bpm:
                    rec = {"ts": ts, "bpm": bpm, "src": "mail", "subject": subject[:40]}
                    _append(rec)
                    new.append(rec)
                    _log("收到心率 %d（uid=%d）" % (bpm, uid))
            state["last_uid"] = max(int(state.get("last_uid", 0) or 0), uid)
        if uids:
            _save_json(statep, state)
    except Exception as e:
        _log("收信失败：%s" % str(e)[:160])
        return []
    finally:
        try:
            if m:
                m.logout()
        except Exception:
            pass
    return new


def latest(hours=12):
    """最近的心率记录 + 新鲜度。供 MCP 工具 health_snapshot 用。"""
    _, latestp, _, _ = _paths()
    now = int(time.time())
    rec = _load_json(latestp, None)
    recent = []
    try:
        jsonl, _, _, _ = _paths()
        if os.path.exists(jsonl):
            with open(jsonl, encoding="utf-8") as f:
                for line in f.readlines()[-200:]:
                    try:
                        r = json.loads(line)
                    except Exception:
                        continue
                    if now - int(r.get("ts", 0)) <= hours * 3600:
                        recent.append(r)
    except Exception:
        pass
    if not rec:
        return {"ok": False, "reason": "no_data", "recent": recent,
                "hint": "还没有收到过心率邮件——检查快捷指令是否已发过、主题是否含 HR"}
    age = now - int(rec.get("ts", 0))
    return {
        "ok": True,
        "bpm": rec.get("bpm"),
        "ts": rec.get("ts"),
        "age_min": round(age / 60, 1),
        "fresh": age <= hours * 3600,
        "recent": recent[-10:],
    }


def _loop():
    while True:
        try:
            fetch_new()
        except Exception as e:
            _log("轮询异常：%s" % str(e)[:160])
        time.sleep(max(60, int(_cfg().get("poll_seconds") or _DEFAULT_POLL)))


def start():
    """后台线程：定时收心率邮件。配置缺失时安静跳过。"""
    c = _cfg()
    if not c.get("enabled", True):
        print("[health] 未启用", flush=True)
        return None
    if not (c.get("mail", {}) or {}).get("user"):
        print("[health] 未配置邮箱，跳过", flush=True)
        return None
    t = threading.Thread(target=_loop, name="health-mail", daemon=True)
    t.start()
    print("[health] 心率邮件轮询已启动（每 %ss）" % (c.get("poll_seconds") or _DEFAULT_POLL), flush=True)
    return t
