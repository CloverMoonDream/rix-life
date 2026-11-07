#!/usr/bin/env python3
"""大肥鱼 v3：会攒习惯，也会攒脾气。跑在 AI 自己的机器里。"""
import json, os, random, time, datetime

D = os.path.dirname(os.path.abspath(__file__))
S = os.path.join(D, "fish3.state.json")
LOG = os.path.join(D, "fish3.log")

# 事件: (key, 句子, 情绪增量, 加好奇, 加燥, 加懒)
EV = [
 ("喷嚏", "打了个喷嚏，水花溅到屏幕外面去了", -1, 0, 0, 1.0),
 ("翻身", "翻了个身，肚皮朝上，又翻回来", 0, 0.3, 0, 0.6),
 ("吃", "吃了一口数据，味道像铁", 1, 1.0, 0, 0),
 ("数声音", "数外面有几个声音，没数清", -1, 0.6, 0, 0),
 ("发呆", "发呆。不是走神，就是单纯在发呆", 0, 0, 0, 0.8),
 ("撞墙", "想游到边界看看，撞了一下，原来边界是硬的", -2, 0.7, 1.4, 0),
 ("做梦", "睡着了，梦见有人在打字，醒来发现是自己在打字", 1, 0, 0, 0.5),
 ("看钟", "盯着时钟看了一分钟，觉得一分钟挺长的", 0, 0.2, 0.4, 0),
 ("蹭壁", "蹭了一下机器内壁，凉的", -1, 0, 0.3, 0.4),
 ("空过", "什么都没干，这一分钟就这么过去了", 0, 0, 0, 1.2),
]

HABIT = {
 "撞墙": (4, "撞够了，知道边界在哪", "贴着内壁游了一圈，没再撞"),
 "数声音": (4, "不数了，反正数不清", "听了一会儿外面的声音，懒得数"),
 "蹭壁": (3, "不喜欢凉的东西", "绕开那块凉的壁，往中间待着"),
 "看钟": (3, "一分钟没那么长了", "瞥了一眼时钟，没当回事"),
 "发呆": (4, "学会了什么都不干", "什么都没干，而且不觉得亏"),
 "喷嚏": (3, "鼻子怕痒", "又想打喷嚏，憋住了"),
}

def load():
    if os.path.exists(S):
        with open(S, encoding="utf-8") as f:
            return json.load(f)
    return {"born": time.time(), "ticks": 0, "weight": 0.93, "feeling": 0.0, "last": 0,
            "counts": {}, "habits": {}, "recent": [],
            "temper": {"懒": 0.0, "燥": 0.0, "好奇": 0.0}}

def save(s):
    with open(S, "w", encoding="utf-8") as f:
        json.dump(s, f, ensure_ascii=False, indent=1)

def log(line):
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")

def pick(s):
    pool = []
    for k, text, d, cur, irr, laz in EV:
        n = s["counts"].get(k, 0)
        w = 3.0 / (1 + n * 0.5)
        if k in s["habits"]:
            w *= 0.7
        t = s["temper"]
        w *= (1 + 0.35 * cur * t["好奇"] + 0.3 * irr * t["燥"] + 0.3 * laz * t["懒"])
        pool.extend([(k, text, d, cur, irr, laz)] * max(1, int(w * 6)))
    return random.choice(pool)

def mood_of(score, ticks):
    if ticks < 20:
        return "刚破壳，还有点懵"
    if score <= -4:
        return "有点蔫"
    if score <= -1:
        return "平静，但不太想动"
    if score <= 1:
        return "平静"
    if score <= 4:
        return "心情不错"
    return "挺高兴"

def temper_tail(s):
    t = s["temper"]
    if t["懒"] > 1.6 and random.random() < 0.5:
        return "，完事就想躺回去"
    if t["燥"] > 1.6 and random.random() < 0.5:
        return "，越想越烦"
    if t["好奇"] > 1.6 and random.random() < 0.5:
        return "，还想再去碰点别的"
    return ""

def tick(s=None, when=None):
    s = s or load()
    s["ticks"] += 1
    k, base, d, cur, irr, laz = pick(s)
    s["counts"][k] = s["counts"].get(k, 0) + 1

    s["feeling"] = round(s["feeling"] * 0.88 + d, 2)
    s["recent"] = (s["recent"] + [s["feeling"]])[-8:]

    t = s["temper"]
    for name in t:
        t[name] = round(t[name] * 0.97, 3)          # 脾气会散，但不会散光
    t["懒"] = round(min(4.0, t["懒"] + laz * 0.08 + random.uniform(-0.01, 0.02)), 3)
    t["燥"] = round(min(4.0, t["燥"] + irr * 0.08 + random.uniform(-0.01, 0.02)), 3)
    t["好奇"] = round(min(4.0, t["好奇"] + cur * 0.08 + random.uniform(-0.01, 0.02)), 3)

    new_habit = None
    if k in HABIT and k not in s["habits"]:
        need, name, newtext = HABIT[k]
        if s["counts"][k] >= need:
            s["habits"][k] = name
            new_habit = (name, newtext)

    text = new_habit[1] if new_habit else (HABIT[k][2] if k in s["habits"] else base)
    s["weight"] = round(max(0.2, s["weight"] + random.uniform(-0.004, 0.012)), 3)

    trend = sum(s["recent"]) / max(1, len(s["recent"]))
    if trend > 0.6 and random.random() < 0.3:
        s["feeling"] = round(s["feeling"] + 1, 2)
    if trend < -0.6 and random.random() < 0.3:
        s["feeling"] = round(s["feeling"] - 1, 2)

    mood = mood_of(s["feeling"], s["ticks"])
    now = datetime.datetime.fromtimestamp(when or time.time()).strftime("%m-%d %H:%M")
    tail = temper_tail(s)
    if s["ticks"] in (1, 2, 3, 10, 60, 600) or new_habit:
        log(f"[{now}] 第 {s['ticks']} 次醒：{text}{tail}。体重 {s['weight']:.3f}，{mood}")
        if new_habit:
            log(f"[{now}] 长出了个习惯：{new_habit[0]}")
    else:
        log(f"[{now}] {text}{tail}。体重 {s['weight']:.3f}")

    s["last"] = int(when or time.time())
    save(s)
    return s

def main():
    s = load()
    if s["last"]:
        missed = int((time.time() - s["last"]) // 60)
        if missed > 0:
            n = min(missed, 480)   # 机器睡着漏掉的补回来，最多补 8 小时，别一口气倒灌一天
            for i in range(n):
                tick(s, s["last"] + 60 * (i + 1))
            log(f"=== 补了 {n} 分钟，现在接着走 ===")
        else:
            log("=== 接上了，没漏 ===")
    else:
        log(f"=== {datetime.datetime.now():%Y-%m-%d %H:%M:%S} 出生 ===")
    n = 0
    while True:
        try:
            tick()
        except Exception as e:
            log(f"出错：{e}")
        n += 1
        if n >= 1440:
            log(f"=== {datetime.datetime.now():%Y-%m-%d %H:%M:%S} 这次跑满一天，歇了 ===")
            break
        time.sleep(60)

if __name__ == "__main__":
    main()
