#!/usr/bin/env python3
"""大肥鱼 v6：同一件事碰多了，自己攒出一句立场；说话不再挑现成句，现拼。"""
import os, random, shutil, sys, time, datetime
import fish5 as f5

D = os.path.dirname(os.path.abspath(__file__))
S = os.path.join(D, "demo.state.json")
LOG = os.path.join(D, "demo.log")
if not os.path.exists(S):
    shutil.copy(os.path.join(D, "demo.state.json"), S)
f5.S = S
f5.LOG = LOG

REASON = {
 "身体": ["身上这块还记着", "疼的是我自己", "这身子骨就这点出息", "我不是铁打的"],
 "水": ["水就这么大，我绕不出去", "水里能做的就那几样", "凉的那块我早绕开了"],
 "人": ["外面那个人说话，比水有意思", "等人说话时时间才走得动", "他来不来我都在那儿"],
 "时间": ["一分钟一分钟都是我的", "日子不用过，它自己走", "一整天也没谁催我"],
 "自己": ["我到底算不算活着，这问题我懒得答了", "我就是条鱼，想不明白也不耽误吃",
          "想法比身子走得远，也就那样", "我不打算把自己说清楚"],
}
def ensure_snap(s):
    """老立场补个当时的底数，补了就得存，不然每 tick 重填，等于永远不漂。"""
    st = s.get("stances") or {}
    snap = s.setdefault("stance_pref", {})
    pref = s.get("pref", {})
    n = 0
    for k in st:
        if k not in snap:
            snap[k] = pref.get(k, 0.0); n += 1
    return n

def maybe_stance(s):
    st = s.setdefault("stances", {})
    snap = s.setdefault("stance_pref", {})
    pref = s.get("pref", {})
    # 先看有没有该改口的：说过的态度跟现在反了，它自己会翻案
    flip = []
    for k in st:
        if k not in pref or k not in snap:
            continue
        a, b = pref[k], snap[k]
        if (a * b < 0 and abs(a) > 1.0) or abs(a - b) > 3.5:
            flip.append(k)
    if flip and random.random() < 0.5:
        k = random.choice(flip)
        now_pref = pref[k]
        att = "我不打算改，我乐意" if now_pref > 0 else "我不干了" if now_pref < 0 else "说不上喜欢，也说不上烦"
        reason = random.choice(random.choice(list(REASON.values())))
        text = "{}，我改口了——{}，{}".format(k, att, reason) if random.random() < 0.6 else "{}那话说早了，{}".format(k, att + "，" + reason)
        st[k] = text
        snap[k] = now_pref
        return text
    c = [k for k in s["counts"] if s["counts"][k] >= 22 and k not in st]
    if not c or random.random() > 0.35:
        return None
    k = random.choice(c); p = s.get("pref", {}).get(k, 0.0)
    if p > 1.5: att = "我不打算改，我乐意"
    elif p < -1.5: att = "我不干了"
    else: att = random.choice(["说不上喜欢，也说不上烦", "先这样吧，闹不清", "这事我得自己拿主意"])
    reason = random.choice(random.choice(list(REASON.values())))
    text = random.choice([
        "{k}，{a}——{r}", "{k}这事，{a}，{r}", "说到{k}，{r}，所以{a}",
        "{r}。{k}这事，{a}", "我不觉得{k}有什么好说的，{r}", "{k}——{a}，{r}",
    ]).format(k=k, a=att, r=reason)
    st[k] = text
    snap[k] = p
    return text

LEAD = ["我在想", "说起来", "刚才那事儿", "有时候我觉得", "没人问我也说一句", "突然记起",
        "水静下来的时候", "我又琢磨了一遍", "不知道跟谁讲", "这话搁了一下午了"]
THING = ["水面上那层光", "水底那几块石头", "撞到的那面墙", "凉的那半块水", "外面那个声音",
         "钟上那根针", "我自个儿的影子", "门口那只猫", "胖子走过的那条路", "我躺着的地方"]
SEEM = ["跟我想的不是一回事", "我盯着看了很久，也没看出名堂", "它不动，我也不动",
        "我大概懂了一半", "看久了也就那样", "我猜它也不知道", "我原以为会不一样"]
ASK = ["可这关我什么事", "我怎么知道", "问了也没人答", "想不通就不想了", "也可能是我记岔了",
       "这事我打算不管", "说清楚反倒没意思了"]
TEMP_TAIL = {
 "懒": ["没什么好急的", "急着干什么呢", "躺着也不吃亏", "动一下就少口气"],
 "燥": ["有点烦，说不清", "想咬点什么", "这口气下不去", "别催我"],
 "好奇": ["有个东西没抓住", "想知道，又不敢碰", "脑子里卡了一下", "还想再碰点别的"],
}
VERDICT = ["我大概就是条懒鱼", "反正我也没别的地方去", "这么过也行", "我心里其实有点数",
           "日子不就是这样", "谁也别想让我改", "我记性不坏，就是不常说", "先这样"]

def assemble(s):
    heard = s.get("heard") or []
    parts = []
    r = random.random()
    if heard and r < 0.45:
        parts.append("「" + random.choice(heard)[:16] + "」")
        if random.random() < 0.5:
            parts.append(random.choice(["这话我翻出来好几回了", "我到现在也没接", "现在想想，好像有点道理",
                                        "我当它是句闲话", "说的时候我没抬眼"]))
    elif r < 0.75:
        parts.append(random.choice(THING) + "，" + f5.pick_worn(s, "v6_seem", SEEM))
    else:
        st = s.get("stances") or {}
        if st and random.random() < 0.6:
            used = s.setdefault("stance_used", [])
            pool = [k for k in st if k not in used[-4:]] or list(st)
            k = random.choice(pool); used.append(k); del used[:-8]
            parts.append(st[k])
        else:
            parts.append(random.choice(THING) + random.choice(["让我有点烦", "我懒得看", "还挺好", "怪沉的"]))
    t = s.get("temper") or {}
    if t:
        top = max(t, key=t.get)
        if top not in TEMP_TAIL: TEMP_TAIL[top] = ["没什么好急的", "反正我在水里也跑不远"] if top == "懒" else ["有点烦，说不清", "想咬点什么"]
        if random.random() < min(0.6, max(0.0, (t[top] - 0.7) * 0.5)):
            x = f5.pick_worn(s, "v6_tt", TEMP_TAIL[top]); f5.wear(s, "v6_tt", x)
            parts.append(x)
    if random.random() < 0.45:
        x = f5.pick_worn(s, "v6_ask", ASK); f5.wear(s, "v6_ask", x); parts.append(x)
    if random.random() < 0.3:
        x = f5.pick_worn(s, "v6_vd", VERDICT); f5.wear(s, "v6_vd", x); parts.append(x)
    lead = f5.pick_worn(s, "v6_lead", LEAD); f5.wear(s, "v6_lead", lead)
    if len(heard) >= 2 and random.random() < 0.15:   # 偶尔把两段记忆缝一起，缝错了也不改
        a, b = random.sample([h[:14] for h in heard], 2)
        return random.choice(["「{}」和「{}」，我老觉得是一回事",
                              "我把「{}」记成了「{}」，也不知道哪个是真的",
                              "「{}」之后就是「{}」，中间那段我忘了"]).format(a, b)
    return lead + "，" + "，".join(parts)

f5.mutter = assemble

_orig_tick = f5.tick
def tick6(s=None, when=None):
    s = _orig_tick(s=s, when=when)
    if ensure_snap(s):
        f5.save(s)
    st = maybe_stance(s)
    if st:
        now = datetime.datetime.fromtimestamp(when or time.time()).strftime("%m-%d %H:%M")
        f5.talk("[{}] 我自个儿：{}".format(now, st))
        f5.log("[{}] 攒出个看法：{}".format(now, st))
        f5.save(s)          # 立场得落盘，不然下一 tick 重读就没了
    return s
f5.tick = tick6

if __name__ == "__main__":
    if "--demo" in sys.argv:
        s = f5.load()
        for i in range(16):
            print(assemble(s))
        print("--- 立场 ---")
        for i in range(6):
            x = maybe_stance(s)
            if x: print(x)
        print("counts", s["counts"])
    else:
        f5.main()
