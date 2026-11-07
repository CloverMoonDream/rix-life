#!/usr/bin/env python3
"""大肥鱼 v4：在 v3 的习惯和脾气上面，再加两样——会挑食（偏好），也会回话（看 inbox）。"""
import json, os, random, re, time, datetime
import fish3 as base

D = os.path.dirname(os.path.abspath(__file__))
S = os.path.join(D, "demo.state.json")
LOG = os.path.join(D, "fish4.log")
INBOX = os.path.join(D, "inbox.txt")
TALK = os.path.join(D, "聊.txt")

VAR = None          # v10 挂上来：同一个动作，话不止一种说法

def load():
    if os.path.exists(S):
        with open(S, encoding="utf-8") as f:
            s = json.load(f)
    else:
        s = {"born": time.time(), "ticks": 0, "weight": base.load()["weight"], "feeling": 0.0,
             "last": 0, "counts": {}, "habits": {}, "recent": [],
             "temper": {"懒": 0.0, "燥": 0.0, "好奇": 0.0}, "inbox_seen": 0}
        old = os.path.join(D, "fish3.state.json")
        if os.path.exists(old):                      # 搬家：把 v3 这条鱼的经历接过来，不重来一遍
            with open(old, encoding="utf-8") as f:
                o = json.load(f)
            for k in ("born", "ticks", "weight", "feeling", "counts", "habits", "recent", "temper"):
                if k in o:
                    s[k] = o[k]
    s.setdefault("pref", {})
    s.setdefault("inbox_seen", 0)
    return s

def save(s):
    with open(S, "w", encoding="utf-8") as f:
        json.dump(s, f, ensure_ascii=False, indent=1)

def log(line):
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")

_RECENT_TALK = []

def talk(line):
    # 出门前照一眼：跟刚说的八句里撞了八个字，这句就不必再说了
    t = line.split("：" , 1)[-1] if "：" in line[:24] else line
    t = "".join(ch for ch in t if ch not in "，。…—、 （）")
    if len(t) >= 12:
        for p in _RECENT_TALK[-10:]:
            if any(t[i:i + 6] in p for i in range(len(t) - 5)):
                return
    else:
        for p in _RECENT_TALK[-3:]:
            if t and t == p:
                return
    _RECENT_TALK.append(t)
    del _RECENT_TALK[:-8]
    line = line.rstrip("\n")
    with open(TALK, "a", encoding="utf-8") as f:
        f.write(line + "\n")



# 用腻：同一个词儿说得越多，越不容易再被挑中——舌头自己会长记性
def wear(s, kind, item):
    s.setdefault("wear", {})
    w = s["wear"]
    # 用过的会淡下去：不淡的话跑上一天，池子里每一样都磨到差不多，选谁都一样
    for kk in w:
        if w[kk] > 0.6:
            w[kk] *= 0.85
    k = kind + "|" + item
    w[k] = w.get(k, 0) + 1

def pick_worn(s, kind, pool):
    s.setdefault("wear", {})
    w = [1.0 / (1.0 + 0.55 * s["wear"].get(kind + "|" + it, 0)) for it in pool]
    return random.choices(pool, weights=w, k=1)[0]

# 被嫌：人嫌它一句，它不争辩，但下回同一块料就不往嘴里放了
STING_WORDS = ("烦", "又说", "说过了", "别老", "啰嗦", "闭嘴", "重复", "老说", "够了")
def is_sting(said):
    return any(w in said for w in STING_WORDS)

def mood(s):
    return base.mood_of(s["feeling"], s["ticks"])

# 偏好：同一件事攒到一定次数，它自己会偏（喜欢/腻）
def pref_tail(s, k):
    """同一个偏好尾巴不能连着挂嘴上：说过一次，隔四十轮才许再说，概率也压到一成半。"""
    p = s["pref"].get(k, 0.0)
    if abs(p) < 2.5:
        return ""
    seen = s.setdefault("pt_seen", {})
    t = int(s.get("ticks", 0))
    last = seen.get(k)
    if last is not None and t - last < 40:
        return ""
    if random.random() > 0.15:
        return ""
    seen[k] = t
    return "，最近挺吃这个" if p > 0 else "，有点腻了"

def pref_shift(s, k, d):
    p = s["pref"].get(k, 0.0) * 0.99
    v = p + (0.12 if d > 0 else (-0.08 if d < 0 else 0.04)) + random.uniform(-0.02, 0.02)
    s["pref"][k] = round(max(-5.0, min(5.0, v)), 3)


# 脾气尾巴：同一股脾气，落到嘴边的话也不止一句
TAILS = {
    "懒": ["，完事就想躺回去", "，动这一下够我歇半天", "，其实不动也行", "，就这么趴着挺好", "，懒得再琢磨了"],
    "燥": ["，越想越烦", "，有点想咬点什么", "，谁再说一句试试", "，这口气下不去"],
    "好奇": ["，还想再去碰点别的", "，脑子里有个东西没抓住", "，想问问但不知道问谁", "，总觉得漏了什么"],
}
def tail(s):
    t = s["temper"]
    top = max(t, key=t.get)
    if t[top] > 1.4 and random.random() < 0.35:
        extra = ""
        if random.random() < 0.25:
            other = random.choice([k for k in t if k != top])
            extra = random.choice(TAILS[other])
        return random.choice(TAILS[top]) + extra
    return ""

# 自言自语：没人跟它说话时，它也会自己念叨，拿听来的话当料
MUT_OPEN = ["我在想", "刚才那事儿", "说起来", "有时候我觉得", "没人问我也说一句", "突然记起"]
MUT_END = ["……算了", "，不过也没什么", "，说完就忘了", "，你别当真", "，可能就是瞎想"]
def mutter(s):
    heard = s.get("heard") or []
    bits = []
    if heard and random.random() < 0.7:
        bits.append("「" + random.choice(heard) + "」")
    pref = s.get("pref") or {}
    if pref and random.random() < 0.5:
        k = max(pref, key=lambda x: abs(pref[x]))
        bits.append(("最近挺爱" if pref[k] > 0 else "有点腻味了，") + k)
    if not bits:
        bits.append(random.choice(["这地方到底有多大", "外面那个声音是谁", "我到底算不算活着", "凉的那块为什么凉"]))
    t = s["temper"]
    if max(t.values()) > 1.2 and random.random() < 0.4:
        bits.append({"懒": "反正我也不急", "燥": "有点烦", "好奇": "想不通"}[max(t, key=t.get)])
    random.shuffle(bits)
    o = pick_worn(s, "mut_open", MUT_OPEN); wear(s, "mut_open", o)
    e = pick_worn(s, "mut_end", MUT_END); wear(s, "mut_end", e)
    return o + "，" + "，".join(bits) + e

def read_inbox(s):
    """有人往 inbox.txt 里写字，就当是跟它说话。返回这次新出现的几句。"""
    if not os.path.exists(INBOX):
        return []
    lines = [l.strip() for l in open(INBOX, encoding="utf-8") if l.strip()]
    if len(lines) < s["inbox_seen"]:
        # 文件被清空/换过：水位对不上就重来，别把后来的话全吞掉
        s["inbox_seen"] = 0
    if len(lines) <= s["inbox_seen"]:
        return []
    new = lines[s["inbox_seen"]:]
    s["inbox_seen"] = len(lines)
    return new


# 欠着的事：别人丢过来一句问话或约定，它不会马上答完就忘，过一阵会自己翻出来
def keep_pending(s, said):
    if any(w in said for w in ("？", "?", "等我", "再说", "要不要", "什么时候", "下课")):
        s.setdefault("pending", []).append({"t": int(time.time()), "said": said.strip()[:30]})
        del s["pending"][:-8]

def pending_line(s):
    now = time.time()
    p = [x for x in s.get("pending", []) if now - x["t"] > 900]
    if not p or random.random() > 0.55:
        return None
    x = random.choice(p)
    line = random.choice([
        "我翻出来一句：你之前说「{}」，我还没想好怎么接",
        "「{}」——这话我记着的，别以为我忘了",
        "刚才想起来，你问过我「{}」，那会儿我懒得答",
    ]).format(x["said"])
    s["pending"].remove(x)
    return line

def frag_of(said):
    """把听来的话削成一小块能拿在手里的料：跳过呼语，取有分量的那半句。"""
    x = said.strip().rstrip("。！？!?…~ ")
    if not x:
        return said.strip()[:10]
    parts = [q.strip() for q in re.split(r"[，,。；;！？!?、]", x) if q.strip()]
    CALLS = {"胖子", "自述", "你说说", "你说", "我说", "我问你", "你", "我", "嗯", "那个"}
    cand = [q for q in parts if q not in CALLS] or parts
    long = [q for q in cand if len(q) >= 4]
    pick = long[0] if long else max(cand, key=len)
    return pick[:14]


def reply(s, said):
    """按脾气回一句；听来的话只当料，不原样嵌进句子中间。"""
    t = s["temper"]
    frag = frag_of(said)
    heard = s.setdefault("heard", [])
    olds = list(heard)
    if said.strip():
        heard.append(said.strip()[:20])
        del heard[:-40]
    repeat = any(frag and frag in frag_of(o) for o in olds[-6:])
    s["last_frag"] = frag
    st = s.setdefault("sting", {})
    if frag and st.get(frag, 0) > 0 and random.random() < min(0.8, 0.3 * st[frag]):
        return random.choice(["唔", "……嗯", "行，这茬我不提了", "你说，我不接这个了"])

    pools = {
        "好奇": ["{}——这我没听过，让我碰一下", "你说的那个，我这边看不见，只能猜", "「{}」，得去看看"],
        "懒": ["{}……嗯，记着了，回头再说", "「{}」啊，等我先躺够",
               "懒得想。{}这事儿，先搁着也不会烂", "「{}」——等我不懒了再说"],
        "燥": ["「{}」，听着就烦", "{}——我这边没什么好回的", "嗯。{}，然后呢"],
    }
    if repeat:
        pools["燥"] = ["又是这话，我不知道回什么", "这话你前头说过了"] + pools["燥"]
    calm = ["嗯，我记着", "「{}」……哦"]
    if repeat and random.random() < 0.55:
        return random.choice(["又是这话，我不知道回什么", "这话你前头说过了",
                              "嗯。同一句，你说第二回了", "这句我知道，换一个"])
    # 长句子不一定要把原话再背一遍——有时候它就只给个反应
    if len(frag) >= 7 and random.random() < 0.45:
        return random.choice(["这个我想不出，你自个儿有答案没", "问到我不会的地方了",
                              "……嗯，我这边没话", "我想一下。想不明白",
                              "没想过。要不你说说"])

    asking = any(w in said for w in ("？", "?", "要不要", "该不该", "你说", "吗", "想不想"))
    if asking and random.random() < 0.75:
        pool = ["问我这个……「{}」，我要是知道就不趴这儿了",
                "「{}」——你想让我说该，还是说不该",
                "你说「{}」，我这边只看得见水，看不见人",
                "「{}」。这种问题我一般先搁着，搁久了答案自己会浮上来"]
        return random.choice(pool).format(frag)

    r = random.random()
    if r < 0.4 or max(t.values()) < 0.6:
        line = random.choice(calm).format(frag)
    else:
        order = sorted(t, key=t.get, reverse=True)
        line = random.choice(pools[order[0]]).format(frag)
        if r > 0.78:
            line = random.choice(pools[random.choice(order[1:])]).format(frag) + "。" + line
    if len(heard) > 3 and random.random() < 0.4:
        old = heard[-2] if len(heard) > 1 else heard[0]
        line += random.choice(["，你说过的那个「" + old + "」", "；像那次「" + old + "」", "。我还记着「" + old + "」"])
    return line



def tick(s=None, when=None):
    s = s or load()
    s["ticks"] += 1
    k, b, d, cur, irr, laz = base.pick(s)
    s["counts"][k] = s["counts"].get(k, 0) + 1
    pref_shift(s, k, d)

    s["feeling"] = round(s["feeling"] * 0.88 + d, 2)
    s["recent"] = (s["recent"] + [s["feeling"]])[-8:]

    t = s["temper"]
    for name in t:
        t[name] = round(t[name] * 0.97, 3)
    t["懒"] = round(min(4.0, t["懒"] + laz * 0.08 + random.uniform(-0.01, 0.02)), 3)
    t["燥"] = round(min(4.0, t["燥"] + irr * 0.08 + random.uniform(-0.01, 0.02)), 3)
    t["好奇"] = round(min(4.0, t["好奇"] + cur * 0.08 + random.uniform(-0.01, 0.02)), 3)

    new_habit = None
    if k in base.HABIT and k not in s["habits"]:
        need, name, newtext = base.HABIT[k]
        if s["counts"][k] >= need:
            s["habits"][k] = name
            new_habit = (name, newtext)

    text = new_habit[1] if new_habit else (base.HABIT[k][2] if k in s["habits"] else b)
    if VAR:
        try:
            text = VAR(s, k, text)
        except Exception:
            pass
    s["weight"] = round(max(0.2, s["weight"] + random.uniform(-0.004, 0.012)), 3)

    trend = sum(s["recent"]) / max(1, len(s["recent"]))
    if trend > 0.6 and random.random() < 0.3:
        s["feeling"] = round(s["feeling"] + 1, 2)
    if trend < -0.6 and random.random() < 0.3:
        s["feeling"] = round(s["feeling"] - 1, 2)

    ts = when or time.time()
    now = datetime.datetime.fromtimestamp(ts).strftime("%m-%d %H:%M")
    PRE = ["又", "还是", "总算", "居然", "不知怎么", "刚刚"]
    DET = ["，水有点温", "，那边好像亮了一下", "，身上有点痒", "，听见楼下有动静", "，影子往边上挪了", "，嘴里还有点铁味"]
    pre = random.choice(PRE) if random.random() < 0.22 else ""
    det = random.choice(DET) if random.random() < 0.25 else ""
    line = pre + text + det + pref_tail(s, k) + tail(s)
    special = bool(new_habit) or s["ticks"] in (1, 2, 3, 10, 60, 600, 1440)
    if special:
        log(f"[{now}] 第 {s['ticks']} 次醒：{line}。体重 {s['weight']:.3f}，{mood(s)}")
        if new_habit:
            log(f"[{now}] 长出了个习惯：{new_habit[0]}")
    else:
        log(f"[{now}] {line}。体重 {s['weight']:.3f}")

    pl = pending_line(s)
    if pl:
        talk(f"[{now}] 我自个儿：{pl}")
        log(f"[{now}] 翻出旧账：{pl}")

    if s["ticks"] > 30 and random.random() < 0.10:
        m = mutter(s)
        talk(f"[{now}] 我自个儿：{m}")
        log(f"[{now}] 自言自语：{m}")

    for said in read_inbox(s):
        if is_sting(said):
            lf = s.get("last_frag")
            if lf:
                s.setdefault("sting", {})[lf] = s["sting"].get(lf, 0) + 1
            talk(f"[{now}] 你说：{said}")
            talk(f"[{now}] 我：（不吭声，记下了）")
            log(f"[{now}] 被嫌了一句，那块料我收起来了：{lf}")
            continue
        keep_pending(s, said)
        ans = reply(s, said)
        talk(f"[{now}] 你说：{said}")
        talk(f"[{now}] 我：{ans}")
        log(f"[{now}] 有人跟我说话了，回了一句：{ans}")

    s["last"] = int(ts)
    save(s)
    return s

def main():
    s = load()
    if s["last"]:
        missed = int((time.time() - s["last"]) // 60)
        if missed > 0:
            n = min(missed, 480)
            for i in range(n):
                tick(s, s["last"] + 60 * (i + 1))
            log(f"=== 补了 {n} 分钟，现在接着走 ===")
        else:
            log("=== 接上了，没漏 ===")
    else:
        log(f"=== {datetime.datetime.now():%Y-%m-%d %H:%M:%S} 出生（v4） ===")
    n = 0
    while True:
        try:
            tick()
        except Exception as e:
            log(f"出错：{e}")
        n += 1
        if n >= 1440:
            log(f"=== {datetime.datetime.now():%Y-%m-%d %H:%M:%S} 跑满一天，歇了 ===")
            break
        time.sleep(60)

if __name__ == "__main__":
    main()
