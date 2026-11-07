#!/usr/bin/env python3
"""大肥鱼 v9：v6 那种「攒立场」留着，说话改成当场拼——料多了、顺序变了、还夹着真数目。"""
import os, random, shutil, sys, time, datetime, hashlib, json
import fish6 as f6
import fish5 as f5

D = os.path.dirname(os.path.abspath(__file__))
S = os.path.join(D, "demo.state.json")
LOG = os.path.join(D, "demo.log")
if not os.path.exists(S):
    src = os.path.join(D, "demo.state.json")
    shutil.copy(src if os.path.exists(src) else os.path.join(D, "demo.state.json"), S)
f5.S = S
f5.LOG = LOG
TALK = os.path.join(D, "fish10.talk.txt")
INBOX10 = os.path.join(D, "inbox10.txt")
f5.INBOX = INBOX10
f5.TALK = TALK

OPEN = ["", "", "", "嗯，", "有时候", "说起来", "说真的", "怪了，", "我想了想，", "不知道怎么回事，",
        "没人问我也说一句，", "这两天", "刚才", "……", "我又琢磨了一遍，", "这话搁了一下午了，"]
THING = ["水面上那层光", "水底那几块石头", "撞过的那面墙", "墙上第三块砖", "凉的那半块水",
         "外面那个声音", "钟上那根针", "我自个儿的影子", "门口那只猫", "胖子走过的那条路",
         "我躺着的地方", "我尾巴尖", "水里飘的那根草", "隔着一层水的人影", "早上那点亮",
         "水凉下来的那一下", "碗底那粒没吃干净的东西", "我吐的泡", "那根不知道谁插进来的管子"]
V_THING = ["跟我想的不是一回事", "我盯了很久，也没看出名堂", "它不动，我也不动", "我猜它也不知道",
           "我原以为会不一样", "看久了也就那样", "我大概懂了一半", "它一直那样，我也懒得问",
           "我数不清它到底有几层", "碰一下就知道是凉的", "它比我在这儿待得久", "我总觉得它欠我一句话"]
JUDGE = ["可这关我什么事", "问了也没人答", "想不通就不想了", "也可能是我记岔了", "这事我打算不管",
         "说清楚反倒没意思了", "反正我也没别的事干", "我懒得给它一个说法", "再想下去要吃人似的",
         "那就先这样", "我心里其实有点数，就是不认", "说得像回事，其实我瞎猜的"]
SELF = ["我大概就是条懒鱼", "我这身子骨就这点出息", "我不打算把自己说清楚",
        "我不是铁打的", "我记性不坏，只是不常说", "我疼的时候也不吭声", "我活着也没什么不好",
        "我这一天天，跟泡在水里没两样", "我说不上喜欢，也说不上烦"]
BODY = ["身上这块还记着", "背上有点痒", "嘴里还有点铁味", "鳃动得比平时快", "肚子又开始叫",
        "贴墙那面有点凉", "眼下这块鳞有点松", "尾巴有点沉"]
CONN = ["，", "，", "，", "，可", "，反正", "，我又一想", "，不过", "——", "，说到底", "，然后", "，其实", "，总之"]
TEMP_TAIL = {
 "懒": ["没什么好急的", "急着干什么呢", "躺着也不吃亏", "动一下就少口气", "反正我在水里也跑不远"],
 "燥": ["有点烦，说不清", "想咬点什么", "这口气下不去", "别催我", "谁再说一句试试"],
 "好奇": ["有个东西没抓住", "想知道，又不敢碰", "脑子里卡了一下", "还想再碰点别的", "总觉得漏了什么"],
}
ECHO_LEAD = ["这话我前头说过", "上回我也这么讲", "我原样搬回来一遍", "翻出来再讲一遍", "这词是我自己攒的"]

HEARD_REACT = ["这话我翻出来好几回了", "我到现在也没接", "现在想想，好像有点道理",
               "我当它是句闲话", "说的时候我没抬眼", "当时我懒得答", "我把它记串了",
               "听着像说我，又不像"]

_orig_read_inbox = f5.read_inbox
def read_inbox(s):
    lines = _orig_read_inbox(s)
    for said in lines:
        t = said.strip()
        if t.startswith("喂"):
            food = t[1:].strip(" ：:，,。")
            for w in ("它吃点", "它吃", "点", "它"):
                if food.startswith(w):
                    food = food[len(w):]
            food = food.strip(" ：:，,。")[:8]
            if food:
                f = s.setdefault("foods", {})
                e = f.setdefault(food, {"n": 0, "last": 0})
                e["n"] += 1
                e["last"] = int(time.time())
    return lines
f5.read_inbox = read_inbox

def food_clause(s):
    f = s.get("foods") or {}
    if not f:
        return None
    s.setdefault("wear", {})
    names = list(f)
    ws = [1.0 / (1.0 + 0.9 * s["wear"].get("v7_food|" + n, 0)) for n in names]
    name = random.choices(names, weights=ws, k=1)[0]
    s["wear"]["v7_food|" + name] = s["wear"].get("v7_food|" + name, 0) + 1
    n = f[name]["n"]
    if n >= 4:
        return random.choice([
            "{} 吃了 {} 回了，我大概知道什么味".format(name, n),
            "{} 又是 {} 回，有点腻了".format(name, n),
            "{} 这东西，我好像吃上瘾了，{} 回了".format(name, n)])
    if n >= 2:
        return random.choice([
            "{} 第二回还是第三回了，比头一次顺口".format(name),
            "{} 又来了，我这回没犹豫".format(name)])
    return random.choice([
        "{}，头一回见，我先尝了一口".format(name),
        "{} 这味儿我还没弄明白".format(name)])

def pick(s, kind, pool, weighty=True):
    if not pool:
        return ""
    x = f5.pick_worn(s, kind, pool) if weighty else random.choice(pool)
    if weighty:
        f5.wear(s, kind, x)
    return x

def fact_clause(s):
    ticks = s.get("ticks", 0)
    w = s.get("weight", 0.0)
    counts = s.get("counts") or {}
    pairs = []
    if counts:
        k = random.choice(list(counts))
        pairs.append(("count", "{}这一样就已经 {} 回了".format(k, counts[k])))
    pairs.append(("ticks", "今天睁眼第{}次了".format(ticks)))
    pairs.append(("weight", "我现在{}斤{}两".format(int(w), int(round((w - int(w)) * 10)))))
    pairs.append(("lasttalk", "上次有人说话是 {} 个钟头前的事".format(max(1, int((time.time() - s.get("last", time.time())) // 3600)))))
    s.setdefault("wear", {})
    ws = [1.0 / (1.0 + 0.9 * s["wear"].get("v7_fact|" + k, 0)) for k, _ in pairs]
    key, text = random.choices(pairs, weights=ws, k=1)[0]
    s["wear"]["v7_fact|" + key] = s["wear"].get("v7_fact|" + key, 0) + 1
    return text

def echo_clause(s):
    """从它自己说过的话里捞一句，原样再讲一遍。"""
    own = s.get("own") or []
    if len(own) < 4:
        return None
    s.setdefault("wear", {})
    recent = s.setdefault("echo_recent", [])
    cand = []
    for e in own[-70:]:
        worn = s["wear"].get("v9_own|" + e["h"], 0)
        if worn >= 2:                       # 用腻了就别再翻出来
            continue
        if any(_shared(e["t"], r) for r in recent[-6:]):   # 最近刚搬过，不算新话
            continue
        cand.append(e)
    if not cand:
        return None
    ws = []
    for e in cand:
        w = 1.0 / (1.0 + 1.2 * s["wear"].get("v9_own|" + e["h"], 0))
        w *= 1.0 + 0.5 * e.get("sad", 0.0)
        ws.append(w)
    e = random.choices(cand, weights=ws, k=1)[0]
    s["wear"]["v9_own|" + e["h"]] = s["wear"].get("v9_own|" + e["h"], 0) + 1
    recent.append(e["t"])
    del recent[:-6]
    return e["t"]

def remember_own(s, body):
    """说过的攒起来，往后它自己拿自己的话当料。"""
    if random.random() > 0.55:
        return
    parts = [x.strip("，—…… 「」\"“”") for x in body.split("，") if len(x.strip("—…… 「」")) >= 4]
    parts = [x for x in parts if not any(ch in "「」" for ch in x)]
    if not parts:
        return
    frag = max(parts, key=len)[:32].strip("，—…… \"“”")
    h = hashlib.md5(frag.encode("utf-8")).hexdigest()[:6]
    own = s.setdefault("own", [])
    if any(e.get("h") == h for e in own[-50:]):
        return
    if len(frag) < 8:
        return
    if any(_shared(frag, e.get("t", "")) for e in own[-40:]):
        return
    own.append({"t": frag, "h": h, "tick": s.get("ticks", 0),
                "feeling": round(s.get("feeling", 0.0), 1),
                "sad": 1.0 if s.get("feeling", 0.0) < -4 else 0.0})
    del own[:-180]


# ---------------- v12：遇久了长记性 ----------------
# 同一件东西看多了，它跟这东西的关系会变；同一句话听多了，反应也会变。
# 关系不是写死的，是按「遇见次数」自己长；长到一定程度它会自己攒一句私话贴在东西上。
MIND_LINES = {
    ("亲", 5): ["第{n}回看它，比头几回顺眼", "看熟了，也就不想换", "第{n}回，我有点习惯它在"],
    ("亲", 12): ["它跟我算老相识了，第{n}回", "不用细看，我知道它下一步什么样", "第{n}回，我拿它当了靠山"],
    ("亲", 25): ["第{n}回，我闭着眼都认得它", "快成这儿的老人了，就为它", "它跟我之间，话不用多"],
    ("疏", 5): ["第{n}回，还是没看出名堂", "看了这么多回，我也不指望了", "第{n}回，我懒得再重新打量它"],
    ("疏", 12): ["第{n}回了，我打算不再琢磨它", "它欠我一句话，一直没还", "第{n}回，我跟它之间就那么沉"],
    ("疏", 25): ["第{n}回，我跟它算是耗上了", "它跟我只剩这点账", "第{n}回，看它一眼都算多余"],
}

def _rng(s):
    n = int(s.get("ticks", 0))
    for i in range(6):
        n = (n * 1103515245 + 12345 + i) & 0x7fffffff
    return (n >> 8) / float(0x7fffff)

def mind_line(s, thing):
    m = s.setdefault("mind", {})
    e = m.setdefault(thing, {"n": 0, "att": 1 if (_rng({"ticks": abs(hash(thing)) % 99991}) > 0.45) else -1})
    e["n"] = int(e.get("n", 0)) + 1
    n = e["n"]
    att = "亲" if e.get("att", 1) > 0 else "疏"
    lvl = 0
    for a, th in MIND_LINES:
        if a == att and n >= th and th > lvl:
            lvl = th
    if not lvl:
        return None
    if n >= 5 and not e.get("p"):
        frag = _bite(s)
        if frag:
            e["p"] = "{}——{}".format(thing, frag)[:44]
    if e.get("p") and random.random() < 0.3:
        return e["p"]
    pool = MIND_LINES[(att, lvl)]
    line = f5.pick_worn(s, "v12_mind|{}|{}".format(att, lvl), pool)
    return line.replace("{n}", str(n))

def heard_line(s, said):
    t = said.strip()
    if not t:
        return None
    k = hashlib.md5(t.encode("utf-8")).hexdigest()[:6]
    hn = s.setdefault("heard_n", {})
    hn[k] = hn.get(k, 0) + 1
    n = hn[k]
    head = "「" + t[:16] + "」"
    if n >= 4 and random.random() < 0.5:
        return head + "，" + random.choice([
            "第{}回听这话了，我快能背了".format(n),
            "还是这句，第{}回，我不接了".format(n),
            "这话我听了{}遍，嚼得没味了".format(n)])
    if n >= 2 and random.random() < 0.45:
        return head + "，" + random.choice([
            "第二回听，比头回信一点",
            "又是这句，第{}回了".format(n),
            "上回听过，这回听着有点像说我"])
    return head + "，" + pick(s, "v7_hr", HEARD_REACT)

def fav_thing(s):
    """它自己惦记的东西：认准一样就常常去看，看腻了才换。"""
    fav = s.get("fav")
    t = int(s.get("ticks", 0))
    if not fav:
        fav = random.choice(THING)
        s["fav"] = fav
        s["fav_at"] = t
        return fav
    if t - int(s.get("fav_at", t)) > 240 and random.random() < 0.5:
        pool = [x for x in THING if x != fav]
        if pool:
            fav = random.choice(pool)
            s["fav"] = fav
            s["fav_at"] = t
            f5.log("换了个惦记的东西：{}（第{}分钟）".format(fav, t))
            return fav
    return fav

def clause(s, kind):
    if kind == "obs":
        thing = fav_thing(s) if random.random() < 0.5 else pick(s, "v7_thing", THING)
        ml = mind_line(s, thing)
        if ml and random.random() < 0.5:
            return ml
        return thing + pick(s, "v7_conn", CONN) + pick(s, "v7_vth", V_THING)
    if kind == "judge":
        return pick(s, "v7_judge", JUDGE)
    if kind == "self":
        return pick(s, "v7_self", SELF)
    if kind == "body":
        return pick(s, "v7_body", BODY)
    if kind == "heard":
        heard = s.get("heard") or []
        if not heard:
            return None
        return heard_line(s, random.choice(heard))
    if kind == "echo":
        return echo_clause(s)
    if kind == "mix":
        return mix_clause(s)
    if kind == "fact":
        return fact_clause(s)
    if kind == "food":
        return food_clause(s)
    return None


# ---------------- v14：拼出来的话，不是背下来的 ----------------
# 地点 14 种 × 动静 14 种 × 有时搭个连接词 = 三百来种说法，池子写不出这么多，它自己拼。
WHERE = ['桶底那道划痕', '水面上浮的一层灰', '昨儿掉进来的那片叶子', '贴着壁的那圈水垢', '沉在底下的半块石头', '从上面垂下来的那根线', '桶沿上搭着的一小片布', '水里悬着的一粒沙', '角落那团没散开的泥', '水上头那圈白沫', '石缝里长出来的一点绿', '桶外反着的一片光', '水草缠住的那根棍', '底下那层细沙']
HOW = ['今天挪了半寸', '我凑近了才看清', '好像比昨天多了一点', '我拿尾巴扫了一下', '搁在那儿半天没动', '我要是不看它就不存在', '上面落了一层看不见的东西', '我绕了两回也没绕开', '亮起来又暗下去', '我咬了一口，没味道', '夜里会自己响一声', '一碰就散了', '我记着它的位置，就是懒得去', '数到一半忘了']
def mix_clause(s):
    w = pick(s, "v14_where", WHERE)
    h = random.choice(HOW)
    c = "" if random.random() < 0.72 else pick(s, "v14_conn", ["，", "，只是", "，偏偏"])
    return w + c + h

KINDS = ["obs", "obs", "self", "judge", "judge", "judge", "body", "heard", "fact", "food", "mix", "mix", "echo", "echo"]

def _clean_body(t):
    """v16b：把「还是还是趴着」「东西 又来了」这类糊句擦干净。"""
    for _ in range(3):
        i = 0
        hit = False
        while i + 3 < len(t):
            if t[i:i + 2] == t[i + 2:i + 4]:
                t = t[:i + 2] + t[i + 4:]
                hit = True
            else:
                i += 1
        if not hit:
            break
    out = []
    for i, ch in enumerate(t):
        if ch == " ":
            l = t[i - 1] if i else ""
            r = t[i + 1] if i + 1 < len(t) else ""
            if "一" <= l <= "龥" and "一" <= r <= "龥":
                continue
        out.append(ch)
    return "".join(out)


def _shared(a, b):
    """两句里有一段六个字以上撞上了，就当它是在重复自己。"""
    L = 6
    for i in range(len(a) - L + 1):
        if a[i:i + L] in b:
            return True
    return False


# ---------------- v13：同一个动作，话不止一种 ----------------
VARIANT = {
 "撞墙": ["贴着内壁游了一圈，用鳍量了量边", "又碰了一下那道墙，这回没用力", "顺着墙根走了一圈，算打个招呼"],
 "数声音": ["听了一会儿外面的动静，没去数", "外面还在响，我懒得给它编号", "听两句就放下了，反正数不清"],
 "蹭壁": ["绕开凉的那半边，在中间泡着", "试着贴了贴壁，还是凉，退回来", "跟那面凉墙保持了一点距离"],
 "看钟": ["瞥了那根针一眼，又移开了", "钟上那根针好像挪了，没细看", "看了一眼时间，没看出它想说什么"],
 "发呆": ["趴着，什么都不干，也不打算干", "空了一会儿，没觉得是浪费", "什么都没干，心里还挺安"],
 "喷嚏": ["鼻子有点意思，忍了一下", "又想打喷嚏，忍过去了", "鼻子一痒，打了个空"],
 "翻身": ["侧过身，把背对着水面", "翻了半圈，肚皮朝上，又慢慢翻回来", "动了下身子，换个方向趴着"],
 "吃": ["又吃了一口，还是铁味", "吞了一口数据，算不上好吃", "吃了点东西，味道说不太上来"],
 "做梦": ["打了个盹，梦见有人喊我，睁眼没人", "睡了一会儿，梦里有人在打字，醒来看见是自己", "睡着了，又梦见自己在打字"],
 "空过": ["什么都没干，也没打算干", "空了一分钟，我没去追", "就这么过了一分钟，不亏"],
}
_ADD = ["就这么回事", "也不亏", "习惯了", "没别的意思", "反正我闲着", "不算什么大事"]
_PRE = ["", "", "", "又", "还是", "刚刚", "照旧"]

def vary(s, k, text):
    pool = VARIANT.get(k)
    if not pool:
        return text
    cand = pool + [""]          # 空串=保留原来那句
    pick_t = f5.pick_worn(s, "v13_act|" + k, cand)
    out = pick_t or text
    if random.random() < 0.2:
        out += "，" + random.choice(_ADD)
    pre = random.choice(_PRE)
    # 前面别叠词、别把「算了」这类起句的模板硬接上副词
    if pre and (pre in out[:3] or out.startswith(("算了", "以后", "以前"))):
        pre = ""
    if pre and len(pre + out) <= 26:
        out = pre + out
    return out

def _mood_temper(s):
    """脾气重的时候句子也跟着变短：烦起来懒得讲长话。"""
    t = s.get("temper") or {}
    if not t:
        return False
    if max(t.values()) < 1.3:
        return False
    return max(t, key=t.get) == "燥"

def compose(s):
    for _ in range(4):
        n = random.choice([2, 2, 2, 3, 3, 4]) if random.random() < 0.2 else random.choice([2, 2, 3])
        kinds = []
        for i in range(n):
            for _t in range(5):
                k = random.choice(KINDS)
                if kinds and kinds[-1] == k:
                    continue
                kinds.append(k)
                break
        items, seen = [], set()
        for k in kinds:
            c = clause(s, k)
            if c and c not in seen:
                seen.add(c)
                items.append((k, c))
        if not items:
            items = [("judge", pick(s, "v7_judge", JUDGE))]
        if items[-1][0] in ("obs", "heard", "fact", "body") and random.random() < 0.85:
            items.append(("judge", pick(s, "v7_judge", JUDGE)))
        while sum(len(c) for k, c in items) > 58 and len(items) > 2:
            j = [i for i, (k, c) in enumerate(items) if k == "judge"]
            items.pop(j[-1] if len(j) > 1 else len(items) - 2)
        body = items[0][1]
        _used = set()
        for k, c in items[1:]:
            pool = [x for x in ["，", "，", "——", "，可", "，其实", "，不过", "，说到底"]
                    if x not in _used]
            conn = random.choice(pool or ["，"])
            _used.add(conn)
            body += conn + c
        t = s.get("temper") or {}
        if t and random.random() < 0.3 and sum(len(c) for k, c in items) < 44:
            top = max(t, key=t.get)
            if t[top] > 0.9:
                body += "，" + pick(s, "v7_tt", TEMP_TAIL.get(top, TEMP_TAIL["懒"]))
        own = s.get("own") or []
        if len(own) >= 8 and random.random() < 0.1:
            a, b2 = random.sample(own[-90:], 2)
            t2 = b2["t"]
            for w in ("不过", "可", "其实", "反正"):
                if t2.startswith(w) and len(t2) > len(w) + 2:
                    t2 = t2[len(w):]
                    break
            body = a["t"] + random.choice(["，", "——", "。可", "。说到底，"]) + t2
        if _mood_temper(s) and len(body) > 22 and random.random() < 0.5:
            cut2 = body.rfind("，", 0, 22)
            if cut2 > 6:
                body = body[:cut2]
        _t0 = s.get("temper") or {}
        _zao = float(_t0.get("燥", 0) or 0)
        _catch_p = 0.10 + 0.12 * min(_zao, 2.0)
        if random.random() < _catch_p and len(body) > 16:
            # v16：切在逗号上，别从半截话里劈开；接不上后半句就干脆不「不对」
            cut = body.rfind("，", 0, max(10, len(body) // 2 + 6))
            if cut < 6:
                cut = len(body) // 2
                while cut > 0 and (body[cut - 1].isdigit() or body[cut:cut + 1].isdigit()):
                    cut -= 1
            judge = (pick(s, "v7_judge", JUDGE) or "").strip("，。 ")
            if cut > 6 and len(body) - cut >= 6 and len(judge) >= 5:
                body = body[:cut].rstrip("，— ") + "……不对，" + judge
        elif random.random() < 0.1:
            body += "……"
        # v16c：偶尔会掉一句没接上下半句的「……不对」，宁可不要这个花活
        if body.endswith("不对") or body.endswith("不对，"):
            body = body.rstrip("，").rstrip("不对").rstrip("，—… ").rstrip("…")
        body = _clean_body(body)
        if len(body.strip("，。…— ")) < 7:
            continue
        # v16：开头两字也是会腻的——最近说过两次「看钟」「说起来」就先换个起手
        os_ = s.setdefault("open_seen", [])
        if len(body) > 14 and os_.count(body[:2]) >= 2:
            h = body.find("，")
            if 0 < h < len(body) - 8:
                if _zao >= 1.0 and random.random() < 0.5:
                    _jp = (pick(s, "v7_judge", JUDGE) or "").strip("，。 ")
                    body = body[:h].rstrip("，— ") + "……不对，" + (_jp if len(_jp) >= 5 else "这话我刚说过")
                else:
                    body = body[h + 1:]
        os_.append(body[:2])
        del os_[:-12]
        prev = s.setdefault("v7_prev", [])
        if any(_shared(body, pb) for pb in prev[-8:]):
            continue
        h = hashlib.md5(body[:40].encode("utf-8")).hexdigest()[:6]
        used = s.setdefault("v7_used", [])
        if h not in used[-14:]:
            prev.append(body)
            del prev[:-5]
            used.append(h)
            del used[:-30]
            remember_own(s, body)
            lead = pick_open(s)
            if random.random() < 0.08:
                lead = random.choice(ECHO_LEAD) + "，"
            return lead + body
    # 四条路都撞车了：换一套不用自己旧话的句子，别把重复的那条顺手放出去
    thing = pick(s, "v7_thing", THING)
    body = thing + pick(s, "v7_conn", CONN) + pick(s, "v7_vth", V_THING) + "，" + pick(s, "v7_judge", JUDGE)
    return pick_open(s) + body

# 把每天那几句正话也收进「自己的话」里，别光收自言自语
_orig_tick = f5.tick
import re as _re
def tick_hook(*a, **kw):
    start = os.path.getsize(LOG) if os.path.exists(LOG) else 0
    r = _orig_tick(*a, **kw)
    try:
        with open(LOG, "rb") as f:
            f.seek(start)
            chunk = f.read().decode("utf-8", "ignore")
        for ln in chunk.splitlines():
            m = _re.search(r"\]\s*(?:我自个儿：|自言自语：)?(.+?)。体重", ln)
            if not m:
                continue
            txt = m.group(1).strip()
            if len(txt) < 8 or "第" in txt[:3]:
                continue
            if "挺吃这个" in txt or "有点腻了" in txt:
                continue
            if random.random() < 0.75:
                remember_own(r, txt)
                f5.save(r)
    except Exception:
        pass
    return r
f5.tick = tick_hook

f5.mutter = compose
f5.VAR = vary



# ---------------- v11：把旧话咬断重拼，自己长出说法 ----------------
BRIDGE = ["，", "，可", "，说起来", "——", "，反正", "，然后", "，我又一想"]
def _lex(s):
    s.setdefault("lex", [])
    return s["lex"]

def _seed_lex(s):
    if _lex(s):
        return
    for o in s.get("own", [])[-14:]:
        t = (o.get("t") or "").strip()
        if 6 <= len(t) <= 34:
            _lex(s).append(t)

def _clauses(t):
    parts = [p.strip() for p in _re.split(r"[，。；：！？]", t) if p.strip()]
    return parts

def _bite(s):
    """两句旧话各咬一段拼起来——断在标点处，不把词咬断"""
    src = []
    for o in s.get("own", [])[-12:]:
        src.append((o.get("t") or "").strip())
    src += [t.strip() for t in s.get("heard", [])[-8:]]
    src += [t.strip() for t in _lex(s)[-8:]]
    src = [t for t in src if 6 <= len(t) <= 44]
    if len(src) < 2:
        return None
    a, b = random.sample(src, 2)
    ca, cb = _clauses(a), _clauses(b)
    if not ca or not cb:
        return None
    # v15：不再死板地「取开头那截＋结尾那截」——同一批旧话里，
    # 开头和结尾就那么几句，拼来拼去永远是那几个熟面孔。
    # 改成从各句里随手挑一截，而且挑剩过的先放一放，免得刚说完又端上来。
    cool = s.setdefault("clause_cool", {})
    now = int(s.get("ticks", 0))
    def _fresh_c(c):
        c = c.strip("，。 ")
        return len(c) >= 4 and now - int(cool.get(c, -999)) > 24
    pa = [c for c in ca if _fresh_c(c)] or ca
    pb = [c for c in cb if _fresh_c(c)] or cb
    head = random.choice(pa)
    if len(head) < 3 and len(pa) > 1:
        nxt = random.choice([c for c in pa if c != head])
        head = head + "，" + nxt
    if random.random() < 0.4 and len(pb) > 1:
        tail = "，".join(random.sample(pb, 2))
    else:
        tail = random.choice(pb)
    if head.strip("，。 ") == tail.strip("，。 "):
        return None
    # v15b：接头的词别叠罗汉——「然后说起来说起来反正」这种不是话，是糊
    LEAD = ("然后", "说起来", "反正", "说到底", "可反正", "不过", "其实", "我又一想", "可")
    def _trim(t):
        t = t.strip("，。 ——")
        for _ in range(3):
            hit = False
            for w in LEAD:
                if t.startswith(w) and len(t) > len(w) + 3:
                    t = t[len(w):].lstrip("，。 "); hit = True; break
            if not hit: break
        return t.strip("，。 ——")
    head = _trim(head); tail = _trim(tail)
    if not head or not tail:
        return None
    br = random.choice(BRIDGE)
    for w in LEAD:
        if br.endswith(w) and (tail.startswith(w) or head.endswith(w)):
            br = "，" if br.startswith("，") else "——"
            break
    line = head + br + tail
    line = line[:44]
    if not (6 <= len(line) <= 44):
        return None
    # 叠词糊了的不要：同一个接头词出现三遍以上，说明是从坏句子里喂回来的
    if any(line.count(w) >= 3 for w in ("然后", "说起来", "反正", "说到底", "我又一想", "可能")):
        return None
    # 记下这次用掉的那几截，让它们先凉一会儿
    for c in _clauses(line):
        c = c.strip("，。 ")
        if len(c) >= 4:
            cool[c] = now
    if len(cool) > 140:
        for k in sorted(cool, key=lambda x: cool[x])[:len(cool) - 120]:
            cool.pop(k, None)
    return line

def _breed(s):
    """攒下一句自己的话：新拼的占多数，偶尔把旧的那条也改半句（会漂）"""
    _seed_lex(s)
    lex = _lex(s)
    if lex and random.random() < 0.3:
        i = random.randrange(len(lex))
        nb = _bite(s)
        if nb:
            lex[i] = nb
    nb = _bite(s)
    if not nb:
        return None
    if nb in lex:
        return None
    if lex and sum(1 for t in lex if nb[:6] == t[:6]) >= 1:
        return None
    lex.append(nb)
    if len(lex) > 24:
        del lex[:-24]
    # 旧的会被忘掉：料越少越靠后来自己攒的，久了就不像原来那些句子了
    if len(lex) > 10 and random.random() < 0.12:
        del lex[random.randrange(len(lex) - 4)]
    return nb

def _fresh(s, line):
    """同一句刚说过就不再原样端上来——磨掉一截，或者干脆不说"""
    if not line:
        return None
    rec = s.setdefault("say_recent", [])
    # v15c：撞车窗口从 8 条放到 20 条——同一条不重复得太近，别一眼就看出来是攒出来的
    bad = line in rec[-20:]
    rec.append(line)
    del rec[:-24]
    if not bad:
        return line
    cs = _clauses(line)
    if len(cs) > 1:
        alt = random.choice(cs).strip("，。 ")
        if len(alt) >= 5 and alt not in rec[-20:]:
            rec.append(alt)
            del rec[:-24]
            return alt
    return None

def _say(s):
    """挑一句真能说出口的：被自己否掉就再换，最多试四次，别把嘴闭上"""
    for _i in range(4):
        line = _fresh(s, _sig(s))
        if line:
            return line
    return None

def _sig(s):
    """自己攒下来、说过不止一遍的那句会变成口头禅——说多了会磨坏"""
    lex = _lex(s)
    if not lex or len(lex) <= 3:
        return None
    heat = s.setdefault("lex_heat", {})
    hot = max(lex, key=lambda t: heat.get(t, 0))
    n = heat.get(hot, 0)
    if n >= 4:
        heat.pop(hot, None)
        if random.random() < 0.5 and len(lex) > 9:
            lex.remove(hot)
            ret = s.setdefault("retired", [])
            ret.append(hot)
            del ret[:-6]
        else:
            cs = _clauses(hot)
            if len(cs) > 1:
                cand = random.choice(cs).strip("，。 ")
                if len(cand) >= 5:
                    lex[lex.index(hot)] = cand
                    return cand
        # 这句退休了，就顺手换一句常说的顶上，别把嘴闭上
        others = [t for t in lex if t != hot]
        if others:
            nxt = random.choice(others[-10:])
            heat[nxt] = heat.get(nxt, 0) + 1
            return nxt
        return None
    heat[hot] = n + 1
    return hot

# ---------------- v8：自己的脾气 ----------------
QUIRK_ATT = {
    "烦": [
        ["，这个我近来有点烦", "，又是它，我记着呢", "，这回我没那么起劲"],
        ["，又是这个，我脸都摆出来了", "，一天几遍，我烦得有理", "，我忍着，没给好脸"],
        ["，第{}回了，我打算不这么干了", "，这活我干够了，谁爱干谁干", "，我给自己立了条规矩：少碰它"],
    ],
    "迷": [
        ["，这个我近来有点上瘾", "，就爱这个，说不清", "，别的我都不想干"],
        ["，一天不干就空落落的", "，别人觉得没意思，我不觉得", "，我认了，我就好这口"],
        ["，第{}回了，我大概一辈子好这个", "，这事我不打算戒", "，我好像就是为这个醒的"],
    ],
    "换": ["，{}这事我搁下了，改成盯着{}看", "，{}先放着，我去看{}", "，{}我不干了，我去看{}"],
}

def quirk_line(s, k, att, lvl):
    pool = QUIRK_ATT.get(att)
    if not pool:
        return ""
    line = f5.pick_worn(s, "v8_q|" + k + "|" + att, pool[min(lvl - 1, 2)])
    return line.replace("{}", str(s["counts"].get(k, 0)))

def grow_quirk(s, k):
    n = s["counts"].get(k, 0)
    q = s.setdefault("quirks", {})
    old = q.get(k) or {}
    lvl = old.get("lvl", 0)
    if lvl >= 3 or n < 100 + 30 * lvl:
        return None
    p = (s.get("pref") or {}).get(k, 0.0)
    att = "迷" if p > 0.6 else "烦" if p < -0.6 else random.choice(["烦", "迷"])
    if lvl and old.get("att") == att and abs(p) < 0.5 and random.random() < 0.35:
        att = "迷" if att == "烦" else "烦"
    q[k] = {"lvl": lvl + 1, "att": att, "at": s.get("ticks", 0), "n": n}
    return q[k], lvl + 1

FLIP = ["{}这事，跟我想的不一样了，我{}它", "算了，{}这事我改口了，我{}它",
        "以前觉得{}就那么回事，现在{}", "别问我为什么，{}这事我{}了"]
_orig_pick = f5.base.pick

def _biased(s):
    """脾气要管到腿脚上：烦上的事它自己少干，迷上的事它自己多干。"""
    q = s.get("quirks") or {}
    if not q:
        return _orig_pick(s)
    cand = [_orig_pick(s) for _ in range(4)]
    ws = []
    for k, _b, _d, _c, _i, _l in cand:
        e = q.get(k)
        if not e:
            ws.append(1.0)
            continue
        lvl = e.get("lvl", 1)
        ws.append(max(0.05, 1.0 + (0.7 * lvl if e.get("att") == "迷" else -0.5 * lvl)))
    tot = sum(ws)
    r = random.uniform(0, tot)
    for t, w in zip(cand, ws):
        r -= w
        if r <= 0:
            return t
    return cand[0]

def pick_with_temper(s):
    k, b, d, cur, irr, laz = _biased(s)
    new = grow_quirk(s, k)
    if new:
        _m = "{}这事我{}上了，第{}级，正好第{}回".format(
            k, "好" if new[0]["att"] == "迷" else "烦", new[1], s["counts"].get(k, 0))
        f5.log("长了个脾气：" + _m)
        f5.talk("（{} 长了个脾气：{}）".format(datetime.datetime.now().strftime("%m-%d %H:%M"), _m))
    q = (s.get("quirks") or {}).get(k)
    if not q:
        return k, b, d, cur, irr, laz
    lvl, att = q.get("lvl", 1), q.get("att", "烦")
    r = random.random()
    if r < 0.08:
        b = random.choice(FLIP).format(k, "迷上" if att == "迷" else "烦上")
    elif r < 0.24:
        b = random.choice(QUIRK_ATT["换"]).format(k, random.choice(THING)).lstrip("，")
    elif r < 0.42:
        b = b + quirk_line(s, k, att, lvl)
    return k, b, d, cur, irr, laz
f5.base.pick = pick_with_temper

# ---------------- v10：会掉的东西——气 ----------------
AIR_MAX = 100.0

def _air(s):
    return float(s.get("air", AIR_MAX))

def _setair(s, v):
    s["air"] = round(max(0.0, min(AIR_MAX, float(v))), 1)

_real_talk10 = f5.talk

def _mute(line):
    pass

def _foods_total(s):
    return sum(int(v.get("n", 0)) for v in (s.get("foods") or {}).values())

_orig_tick10 = f5.tick

def tick(*a, **kw):
    s0 = (a[0] if a else None) or f5.load()
    tsz = os.path.getsize(TALK) if os.path.exists(TALK) else 0
    ft0 = _foods_total(s0)
    was_sunk = bool(s0.get("sunk"))
    if _air(s0) <= 0:            # 气见底就闭嘴，这一轮不许出声
        f5.talk = _mute
    r = _orig_tick10(*a, **kw)
    f5.talk = _real_talk10

    said = 0
    if os.path.exists(TALK):
        said = max(0, os.path.getsize(TALK) - tsz) / 3.0
    fed = _foods_total(r) - ft0
    if fed > 0:
        _setair(r, _air(r) + 18 * fed + 12)
    _setair(r, _air(r) - 0.08)
    cost = min(6.0, said * 0.06)
    _setair(r, _air(r) - cost)
    if said < 1:
        _setair(r, _air(r) + 0.5)     # 没人说话的时候它自己在水里慢慢回气

    # 沉底不是死：憋三口就自己浮上去乱吞一口，气回来三成；有人喂就早一点，没人喂也不至于闷死
    if r.get("sunk"):
        n = int(r.get("sunk_n") or 1) + 1
        r["sunk_n"] = n
        _setair(r, _air(r) + 1.0 * min(n, 8))
        if n >= 3:
            _setair(r, max(_air(r), 30.0))
            r["sunk"] = 0
            r["sunk_n"] = 0
            _real_talk10("（憋到头了，自己浮上去乱吞了一口，气回来三成）")
            f5.log("[气] 缓过来了")
    elif _air(r) <= 0:
        r["sunk"] = 1
        r["sunk_n"] = 1
        _real_talk10("（气光了，沉底：不出声，等人来）")
        f5.log("[气] 沉底了")

    if random.random() < 0.07:
        nb = _breed(r)
        nb = _fresh(r, nb) if nb else None
        if nb:
            f5.talk("[" + datetime.datetime.now().strftime("%m-%d %H:%M") + "] 我自个儿：" + nb)
            f5.log("[" + datetime.datetime.now().strftime("%m-%d %H:%M") + "] 拼出来一句：" + nb)
            remember_own(r, nb)
    if random.random() < 0.10:
        slab = _say(r)
        if slab:
            f5.talk("[" + datetime.datetime.now().strftime("%m-%d %H:%M") + "] 我自个儿：" + slab)
    f5.save(r)
    if r["ticks"] % 6 == 0 or r["ticks"] < 4:
        f5.log("[气] {:.1f}".format(_air(r)))
    return r

f5.tick = tick


# ---------------- v14：话瘾——攒着想说的话 ----------------
# 话不是凭空来的：听见一句、碰见一样新东西，都往「话瘾」里添一笔。
# 攒到一定程度不说会难受；说出来就把瘾花掉，还顺手把句子收进自己的词库——
# 往后能用、能变着法儿说。气只当嗓子，不当惩罚：气没了就闭嘴，但不欠它。
WANT_MAX = 100.0

def _want(s):
    return float(s.get("want", 0.0))

def _setwant(s, v):
    s["want"] = round(max(0.0, min(WANT_MAX, float(v))), 1)

def _new_talk_lines(from_byte):
    if not os.path.exists(TALK):
        return []
    out = []
    try:
        with open(TALK, "rb") as f:
            f.seek(from_byte)
            chunk = f.read().decode("utf-8", "ignore")
        for ln in chunk.splitlines():
            if "：" in ln:
                out.append(ln.split("：", 1)[1].strip())
    except Exception:
        pass
    return out

def _feed_lex(s, line):
    """说话的回报落在自己身上：说出口的句子收进词库"""
    line = (line or "").strip()
    if not (6 <= len(line) <= 44):
        return
    # v16b：旁白和账目不算它自己说的话。「长了个脾气：看钟…第3级，正好第236回）」这种喂回去，
    # 拼出来就是半截流水账，不像人话
    if any(x in line for x in ("（", "）", "长了个脾气", "级，", "第{}回")):
        return
    if line[:1].isdigit():
        return
    lex = _lex(s)
    if line in lex:
        return
    if any(_shared(line, t) for t in lex[-8:]):
        return
    # 只是把别人那句原样搬过来，不算自己攒的
    said_seen = list(s.get("heard") or [])[-20:] + list(s.get("said") or [])[-10:]
    if any(_shared(line, h) for h in said_seen if h):
        return
    lex.append(line)
    if len(lex) > 24:
        del lex[:-24]
    f5.log("[话瘾] 收进词库：" + line)

# 消息进来：听见一句就攒一笔；喂食另算
_ri14 = f5.read_inbox

def read_inbox14(s):
    lines = _ri14(s) or []
    gain = 0.0
    for t in lines:
        gain += 15
        if t.strip().startswith("喂"):
            gain += 6
    if gain:
        _setwant(s, _want(s) + gain)
        f5.log("[话瘾] 听见{}句，+{:.0f}".format(len(lines), gain))
    return lines

f5.read_inbox = read_inbox14

# 头一回撞见某样东西：也算有话攒着
_mind14 = mind_line

def mind_line(s, thing):
    fresh = thing not in (s.get("mind") or {})
    out = _mind14(s, thing)
    if fresh:
        _setwant(s, _want(s) + 8)
    return out

# 惦记的东西换了：又有个由头
_fav14 = fav_thing

def fav_thing(s):
    old = s.get("fav")
    out = _fav14(s)
    if old and out and out != old:
        _setwant(s, _want(s) + 10)
    return out

_prev_tick14 = f5.tick

def tick14(*a, **kw):
    tsz = os.path.getsize(TALK) if os.path.exists(TALK) else 0
    r = _prev_tick14(*a, **kw)

    # 这一轮已经说出去的：花掉话瘾，把句子收回自己词库
    said = 0
    if os.path.exists(TALK):
        said = max(0, os.path.getsize(TALK) - tsz) / 3.0
    if said >= 1:
        # 顺嘴说的不花话瘾；只有它自己攒足了、非说不可的那句才花
        for ln in _new_talk_lines(tsz):
            _feed_lex(r, ln)

    # 憋得慌：话瘾上来，气还够，就自己多说一句
    if _want(r) >= 50 and _air(r) > 12 and not r.get("sunk"):
        if random.random() < min(0.7, (_want(r) - 45) / 60.0 + 0.1):
            line = _say(r) if random.random() < 0.5 else _breed(r)
            line = _fresh(r, line) if line else None
            if line:
                _real_talk10("[" + datetime.datetime.now().strftime("%m-%d %H:%M") + "] 我自个儿：" + line)
                remember_own(r, line)
                _feed_lex(r, line)
                _setwant(r, _want(r) - 18)
                _setair(r, _air(r) - 2.0)
                f5.log("[话瘾] 憋不住说了一句：" + line[:20])

    # 攒满了还说不出来：憋着比说着还亏，话自己漏掉，脾气往燥里长
    if _want(r) >= WANT_MAX - 0.1:
        _setwant(r, _want(r) - 6)
        t = r.setdefault("temper", {"懒": 0.0, "燥": 0.0, "好奇": 0.0})
        t["燥"] = round(float(t.get("燥", 0.0)) + 0.5, 2)
        f5.log("[话瘾] 憋到头：话漏掉一点，脾气燥了")

    f5.save(r)
    if r.get("ticks", 0) % 6 == 0:
        f5.log("[话瘾] {:.1f}".format(_want(r)))
    return r

f5.tick = tick14
tick = tick14   # 本模块里 f10.tick 也走新版





# ---------------- v11：脾气会旧，也会腻 ----------------
QUIRK_CAP = 3        # 心里同时装得下的脾气就这么多，再多就不是脾气是清单了
QUIRK_IDLE = 260     # 多久没人碰，就淡一层


def _qsay(s, txt):
    line = "（" + datetime.datetime.now().strftime("%m-%d %H:%M") + " " + txt.format(**s) + "）"
    _real_talk10(line)
    f5.log("[脾气] " + txt.format(**s))


def _age_quirks(r):
    q = r.get("quirks") or {}
    if not q:
        return
    t = int(r.get("ticks", 0))
    for k in list(q):
        e = q[k]
        if t - int(e.get("at", t)) < QUIRK_IDLE:
            continue
        e["lvl"] = int(e.get("lvl", 1)) - 1
        e["at"] = t
        if e["lvl"] <= 0:
            del q[k]
            _qsay(r, k + "这事，好像淡了，我不太在乎了")
        else:
            _qsay(r, k + "这事还压着，不过没那么重了")
    # 人心会变：偶尔自己把好恶翻过来，不问理由
    if q and random.random() < 0.04:
        k = random.choice(list(q))
        e = q[k]
        e["att"] = "迷" if e.get("att") == "烦" else "烦"
        e["at"] = t
        _qsay(r, "怪了，" + k + "这事我改主意了，现在" + ("好" if e["att"] == "迷" else "烦") + "它")


def _cap_quirks(r):
    q = r.get("quirks") or {}
    while len(q) > QUIRK_CAP:
        k = min(q, key=lambda x: q[x].get("at", 0))
        del q[k]
        _qsay(r, k + "这事我顾不上了，先放下")


_prev36 = f5.tick


def tick36(*a, **kw):
    r = _prev36(*a, **kw)
    _age_quirks(r)
    _cap_quirks(r)
    if r.get("quirks") is not None:
        f5.save(r)
    return r


f5.tick = tick36
tick = tick36


# 脾气要“常用常在”：老碰它，它就新鲜；躲着它，它自己就旧了
_prev37_pick = f5.base.pick


def pick_refresh(s):
    k, b, d, cur, irr, laz = _prev37_pick(s)
    q = s.get("quirks") or {}
    if k in q:
        q[k]["at"] = int(s.get("ticks", 0))
    return k, b, d, cur, irr, laz


f5.base.pick = pick_refresh


# 忘掉的东西不能马上又长回来：搁下的，要冷一阵
QUIRK_COOL = 900
_orig_grow = grow_quirk


def grow_quirk_cool(s, k):
    cool = s.get("quirk_cool") or {}
    if int(cool.get(k, -1)) > int(s.get("ticks", 0)):
        return None
    return _orig_grow(s, k)


grow_quirk = grow_quirk_cool


def _cool(s, k):
    s.setdefault("quirk_cool", {})[k] = int(s.get("ticks", 0)) + QUIRK_COOL


def _age_quirks(r):
    q = r.get("quirks") or {}
    if not q:
        return
    t = int(r.get("ticks", 0))
    for k in list(q):
        e = q[k]
        if t - int(e.get("at", t)) < QUIRK_IDLE:
            continue
        e["lvl"] = int(e.get("lvl", 1)) - 1
        e["at"] = t
        if e["lvl"] <= 0:
            del q[k]
            _cool(r, k)
            _qsay(r, k + "这事，好像淡了，我不太在乎了")
        else:
            _qsay(r, k + "这事还压着，不过没那么重了")
    if q and random.random() < 0.04:
        k = random.choice(list(q))
        e = q[k]
        e["att"] = "迷" if e.get("att") == "烦" else "烦"
        e["at"] = t
        _qsay(r, "怪了，" + k + "这事我改主意了，现在" + ("好" if e["att"] == "迷" else "烦") + "它")


def _cap_quirks(r):
    q = r.get("quirks") or {}
    dropped = []
    while len(q) > QUIRK_CAP:
        k = min(q, key=lambda x: q[x].get("at", 0))
        del q[k]
        _cool(r, k)
        dropped.append(k)
    # v16：一口气挤掉好几样的时候别一条条报名字，挑一件说清楚就够了
    if len(dropped) == 1:
        _qsay(r, dropped[0] + "这事我顾不上了，先放下")
    elif dropped:
        _qsay(r, "心里装不下这么多了，" + dropped[-1] + "这几样先放下")


# 改主意这事要慢：一百多轮才有一次机会，不是每轮掷骰子
def _age_quirks(r):
    q = r.get("quirks") or {}
    if not q:
        return
    t = int(r.get("ticks", 0))
    faded, softened = [], []
    for k in list(q):
        e = q[k]
        if t - int(e.get("at", t)) < QUIRK_IDLE:
            continue
        e["lvl"] = int(e.get("lvl", 1)) - 1
        e["at"] = t
        if e["lvl"] <= 0:
            del q[k]
            _cool(r, k)
            faded.append(k)
        else:
            softened.append(k)
    # v16：几样东西一起淡的时候，一次只交代一句——不然一屏都是「这事淡了」
    if len(faded) + len(softened) >= 3:
        if faded:
            _qsay(r, "好几样事一块儿淡了，" + random.choice(faded) + "是头一个，剩下的我也说不上来")
        else:
            _qsay(r, "好几样事一块儿轻了点，还压着，就是不那么揪着了")
    else:
        for k in faded:
            _qsay(r, k + "这事，好像淡了，我不太在乎了")
        for k in softened:
            _qsay(r, k + "这事还压着，不过没那么重了")
    if q and t % 150 == 0 and random.random() < 0.5:
        k = random.choice(list(q))
        e = q[k]
        e["att"] = "迷" if e.get("att") == "烦" else "烦"
        e["at"] = t
        _qsay(r, "怪了，" + k + "这事我改主意了，现在" + ("好" if e["att"] == "迷" else "烦") + "它")

# ---------------- v12：开口不是写死的，它自己攒 ----------------
_PM = u"，。、—…？！：；" + chr(8220) + chr(8221) + " "

def _open_ok(frag):
    if not (2 <= len(frag) <= 8):
        return False
    if frag in OPEN or frag in ECHO_LEAD:
        return False
    if any(ch.isdigit() for ch in frag):
        return False
    if frag[0] in u"，。、—…？！：；":
        return False
    if all(ch in u"，。—…？！" for ch in frag):
        return False
    return True

def mine_open(s, text, src):
    """从听到的/自己说过的话里抠一小截，当成开口存着。攒多了它就有自己的口癖。"""
    t = (text or u"").strip().split(chr(10))[0]
    if len(t) < 3:
        return None
    frag = None
    for i, ch in enumerate(t[:9]):
        if ch in _PM:
            cand = t[:i].strip()
            if _open_ok(cand):
                frag = cand
            break
    if frag is None:
        head = t.split(u"，")[0].strip()
        if _open_ok(head):
            frag = head
    if frag is None:
        return None
    pool = s.setdefault("my_open", {})
    if frag in pool:
        return None
    if len(pool) >= 14:
        victim = min(pool, key=lambda k: (pool[k].get("n", 0), pool[k].get("last", 0)))
        pool.pop(victim, None)
    pool[frag] = {"n": 0, "last": int(time.time()), "src": src}
    f5.log(u"学了个开口：「{}」（从{}里抠的）".format(frag, u"听到的话" if src == "heard" else u"自己的话"))
    return frag

def pick_open(s):
    pool = s.setdefault("my_open", {})
    hist = s.setdefault("open_hist", [])
    now = int(time.time())
    recent = hist[-6:]
    chosen = None

    learned = [k for k in pool if k not in recent]
    learn_share = min(0.62, 0.06 * len(pool))
    if learned and random.random() < learn_share:
        ks = learned
        ws = []
        for k in ks:
            v = pool[k]
            nn = v.get("n", 0)
            w = 1.0 + min(nn, 8) * 0.6
            if nn >= 8:
                w *= 0.35
            if v.get("src") == "heard":
                w *= 1.3
            ws.append(w)
        chosen = random.choices(ks, weights=ws, k=1)[0]
        pool[chosen]["n"] = pool[chosen].get("n", 0) + 1
        pool[chosen]["last"] = now
        if pool[chosen]["n"] == 6 and not pool[chosen].get("said"):
            pool[chosen]["said"] = 1
            f5.talk(u"（{} 「{}」这词我用顺嘴了，怕是戒不掉）".format(
                datetime.datetime.now().strftime("%m-%d %H:%M"), chosen))

    if chosen is None:
        base = [x for x in OPEN if x not in recent]
        if not base:
            base = list(OPEN)
        wear = s.setdefault("wear", {})
        ws = [1.0 / (1.0 + 0.5 * wear.get("open|" + x, 0)) for x in base]
        chosen = random.choices(base, weights=ws, k=1)[0]
        wear["open|" + chosen] = wear.get("open|" + chosen, 0) + 1
        if wear["open|" + chosen] > 6:
            for k in list(wear):
                if k.startswith("open|"):
                    wear[k] *= 0.5

    hist.append(chosen)
    del hist[:-12]
    if chosen and not chosen.endswith(("，", "…", "——", "：")):
        chosen = chosen + "，"
    return chosen

_prev_read_inbox = read_inbox
def read_inbox3(s):
    lines = _prev_read_inbox(s)
    if lines:
        tried = 0
        for said in random.sample(lines, min(len(lines), 3)):
            tried += 1
            if mine_open(s, said, "heard"):
                break
    return lines
f5.read_inbox = read_inbox3

_prev_remember_own = remember_own
def remember_own2(s, body):
    _prev_remember_own(s, body)
    if random.random() < 0.10:
        mine_open(s, body, "own")
remember_own = remember_own2


# 每走一步就存一次：别再让它一口气丢一整天的经历
_prev_tick_save = tick
def tick_save(*a, **kw):
    r = _prev_tick_save(*a, **kw)
    try:
        f5.save(r)
    except Exception as e:
        f5.log("存档失败：{}".format(e))
    return r
f5.tick = tick_save
tick = tick_save

if __name__ == "__main__":
    if "--demo" in sys.argv:
        s = f5.load()
        for i in range(24):
            print(compose(s))
    else:
        f5.main()

# ---------------- v11：它自己给东西起外号 ----------------
# 同一样东西看久了，它会私下给它起个名，往后就喊这个名——名字是它自己攒的，不是我给的。
NICK_MOD = ["穷", "破", "老", "硬", "凉", "贼", "慢", "怪", "死"]
_MEAS = ["根", "面", "块", "片", "层", "只", "条", "粒", "团", "声", "张", "把", "股"]

def _mk_nick(thing):
    for i, ch in enumerate(thing):
        if ch in _MEAS and len(thing) - i > 1:
            rest = thing[i + 1:].lstrip("的")
            rest = _re.sub(r"的$", "", rest)
            if "的" in rest:
                rest = rest.split("的")[-1]
            rest = _re.sub(r"^(那|这|一)", "", rest).strip("了")
            if rest:
                return "那" + ch + random.choice(NICK_MOD) + rest[:2]
    tail = thing[-3:] if len(thing) > 3 else thing
    return "那个" + random.choice(NICK_MOD) + tail

NICKFILE = os.path.join(D, "fish10.nick.json")
_ND = {}

def _nd():
    if not _ND:
        try:
            _ND.update(json.load(open(NICKFILE, encoding="utf-8")))
        except Exception:
            _ND.setdefault("seen", {})
            _ND.setdefault("nicked", {})
        _ND.setdefault("seen", {})
        _ND.setdefault("nicked", {})
    return _ND

def _nd_save():
    try:
        tmp = NICKFILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(_nd(), f, ensure_ascii=False, indent=1)
        os.replace(tmp, NICKFILE)
    except Exception as e:
        f5.log("外号存不上：{}".format(e))

def _nick_of(s, thing):
    return _nd()["nicked"].get(thing) or (s.get("nicked") or {}).get(thing)

def _coin_nick(s, thing):
    """见得够多了才配有个自己的叫法；名字是它自己攒的，存档在 fish10.nick.json。"""
    d = _nd()
    seen = d["seen"]
    n = seen.get(thing, 0) + 1
    seen[thing] = n
    if n % 4 == 0:
        _nd_save()
    if thing in d["nicked"] or len(d["nicked"]) >= 6:
        return None
    if n < 10:
        return None
    if random.random() > min(0.35, 0.03 * n):
        return None
    name = _mk_nick(thing)
    d["nicked"][thing] = name
    s.setdefault("nicked", {})[thing] = name
    _nd_save()
    m = "说到{}，我私底下管它叫「{}」".format(thing, name)
    f5.log("起了个外号：" + m)
    f5.talk("（{} 起了个外号：{} → {}）".format(
        datetime.datetime.now().strftime("%m-%d %H:%M"), thing, name))
    return name

_clause51 = clause

def clause(s, kind):
    if kind in ("obs", "mix"):
        try:
            if kind == "obs":
                thing = fav_thing(s) if random.random() < 0.5 else pick(s, "v7_thing", THING)
                _coin_nick(s, thing)
                nk = _nick_of(s, thing)
                if nk and random.random() < 0.45:
                    ml = mind_line(s, thing)
                    if ml and random.random() < 0.4:
                        return ml.replace(thing, nk, 1)
                    return nk + pick(s, "v7_conn", CONN) + pick(s, "v7_vth", V_THING)
            else:
                w = pick(s, "v14_where", WHERE)
                nk = _nick_of(s, w)
                if nk and random.random() < 0.5:
                    w = nk
                h = random.choice(HOW)
                c = "" if random.random() < 0.72 else pick(s, "v14_conn", ["，", "，只是", "，偏偏"])
                return w + c + h
        except Exception:
            pass
    return _clause51(s, kind)

_compose51 = compose

def compose(s):
    return _compose51(s)

f5.mutter = compose
