"""rix-brain MCP 服务：把记忆 + 情感暴露给 DSH（stdio）。

DSH 在 ~/.dsh/profiles/web/cordis.patch.yml（或等价 MCP 配置）里把这个进程作为
stdio MCP server 接入，即可用以下工具：

情感：  emotion_get / emotion_update / user_mood_detect
记忆：  memory_record_turn / memory_get_pending / memory_append_diary /
        memory_recall / memory_decay_check
"""
import json
import os
import sys
from typing import Optional

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "brain"))

import config                 # 会切到项目根，保证相对路径一致
import emotion                # 复用自 mood.py
import emotion_memory         # 复用自 mood_memory.py
import user_mood              # 复用自 user_mood.py
import memory                 # 新的短期 + 无限记忆模块
import autodream              # 自动日记兜底（保证"不遗忘"不依赖模型自觉）
import sysstats               # 系统快照（内存/CPU/温度，30 秒采样）
import health                 # 心率邮件通道（iPhone 快捷指令 → 邮件 → 本地落盘）
import figures                # 人物图鉴（认人：关键词 → 候选人 → 比对 → 修正）
import notebook               # 小抽屉：她自己的 txt 笔记（D:\AI\笔记）
import link                   # 作者 ↔ AI 的留言板（两个 jsonl 队列）
import proactive              # 冷暴力惩罚 + 主动概率硬闸门（仅私聊）
import profiles               # 用户画像（一个身份一份 JSON）
import source                 # 按日记时间追溯原文
import tts                    # edge-tts 语音生成（写进桥接语音库供 qq_send_voice 用）

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("rix-brain")


def _cfg():
    return config.load_config()


# ---------- 情感（2026-11-03 用户定：整套「数值情绪」已停用） ----------
#
# AI的原话：「我高兴不高兴不是机制教我的，是跟你们处出来的」
#            「不能谁在外面拧一下我就换个脸色，那叫木偶」
# 所以：情绪不再是一个被关键词/衰减公式算出来的数字，而是她从记忆里重新想起来的。
# 下面这些函数**保留本体**（别处可能 import），但**不再暴露成工具、不再被调用**。
# 要恢复：把 @mcp.tool() 加回去，并从 emotion.py 恢复触发词/衰减。

# @mcp.tool()   ← 已停用
def emotion_get(key: str = "") -> dict:
    """读取 AI 当前情感状态（开心/激动/负面 + 该身份的好感度 + 情绪词 + 关系词）。

    key: 身份标识（私聊可用会话 key，如 private:10001；群聊用对方 QQ 号/昵称）。
         好感度按身份分开记，留空则读默认桶。"""
    c = _cfg()
    e = emotion.Emotion(c["ai_name"], c["user_name"])
    with emotion._mood_lock:
        m = e._load()
    h = m.get("happiness", 50)
    ex = m.get("excited", 50)
    ne = m.get("negative_emotion", 0)
    like = e.read_like(key)
    return {
        "happiness": h,
        "excited": ex,
        "negative_emotion": ne,
        "like_point": like,
        "key": key or "__default__",
        "emotion_word": e.emotion_all(h, ex, ne),
        "relationship_word": e.like_word_PD(like),
    }


def emotion_update(user_said: str, key: str = "") -> dict:
    """收到用户一句话后更新 AI 情感，返回新状态与可注入 prompt 的文案。

    key: 说话人身份（私聊传会话 key 如 private:10001；群聊传对方的 QQ 号或昵称）。
         开心/激动/负面是全局心情；**好感度按 key 分开记**，所以一定要传对身份。"""
    c = _cfg()
    e = emotion.Emotion(c["ai_name"], c["user_name"])
    h = e.happiness_point(user_said)
    interest_txt, _ = e.dialogue_interest(user_said)
    ex = e.excited_point(h)
    ne = e.negative_emotion_point(h)
    temp_h, real_h = e.temp_emotion_update(user_said, h)
    like = e.like_point(key)
    word = e.emotion_all(real_h, ex, ne)
    rel = e.like_word_PD(like)
    inject = f"{interest_txt}\n你现在感觉{word}\n{rel}".strip()
    return {
        "happiness": real_h,
        "temp_happiness": temp_h,
        "excited": ex,
        "negative_emotion": ne,
        "like_point": like,
        "like_point_key": key or "__default__",
        "emotion_word": word,
        "relationship_word": rel,
        "injection": inject,
    }


@mcp.tool()
def user_mood_detect(user_said: str, interval: Optional[float] = None) -> dict:
    """感知用户情绪，返回心情、效价、置信度、是否触发关心，以及注入文案"""
    c = _cfg()
    sp = os.path.join(config.data_dir(), "user_mood_state.json")
    api_key = c.get("deepseek", {}).get("api_key", "")
    model = c.get("deepseek", {}).get("model", "deepseek-flash")
    mood_data, care_alert = user_mood.process_mood(
        user_said, sp,
        api_key or None,
        model if api_key else None,
        interval,
    )
    prompt = user_mood.mood_to_prompt(mood_data, c["user_name"])
    return {
        "mood": mood_data["mood"],
        "valence": mood_data["valence"],
        "confidence": mood_data["confidence"],
        "care_alert": care_alert,
        "injection": prompt,
    }


# @mcp.tool()   ← 已停用（情绪数值系统已删，配额改为固定值）
def memory_quota(happiness: int, excited: int, negative_emotion: int) -> dict:
    """情感 → 记忆召回数量：总条数 + 主观/客观比例（复用 emotion_memory）"""
    total = emotion_memory.happiness_memory(happiness)
    subj, obj = emotion_memory.excited_and_negative_memory(excited, negative_emotion, total)
    return {"total": total, "subjective": subj, "objective": obj}


# ---------- 记忆 ----------

def memory_record_turn(role: str, content: str, key: str = "", nickname: str = "") -> bool:
    """追加一条短期记忆。
    role: '用户' 或 AI 名（'AI'）
    key:  会话标识，如 'private:10001' / 'group:20002'
    nickname: 说话人的显示昵称（用户侧为对方昵称，AI 侧为 AI 名）"""
    return memory.record_turn(key, role, content, nickname)


@mcp.tool()
def memory_get_pending(key: str = "") -> dict:
    """取出**某个会话**待总结的短期记忆原文（DSH 据此做日记总结，再调 memory_append_diary）。
    key: 会话标识（如 private:10001 / group:20002）；留空则合并所有会话（会带来源标注）。"""
    return memory.get_pending(key)


@mcp.tool()
def memory_append_diary(
    content: str,
    things: str = "",
    key: str = "",
    first_time: Optional[int] = None,
    last_time: Optional[int] = None,
    kind: str = "",
) -> bool:
    """DSH 总结好日记后落盘（记忆总结走 DSH）。key 为会话标识，日记存进该会话自己的长期记忆。

    kind: "subjective"（你的感受/情绪/对某人的印象）或 "objective"（事实、事件、约定）；
          召回时会按当前情绪决定主客观各取几条，写清楚能让回忆更贴切。留空则自动粗判。"""
    return memory.append_diary(content, things, key, first_time, last_time, kind)


@mcp.tool()
def memory_recall(query: str, max_total: int = 0, subjective_ratio: Optional[float] = None,
                  current_key: str = "", short_term_turns: Optional[int] = None) -> dict:
    """检索记忆：**短期只取当前会话**；**长期日记全局检索**（跨会话带出处标注）。

    召回条数默认由你的情绪决定：总条数 7±3（越难过越多）、主客观比例随激动值变化
    （越激动越偏主观）；返回值里的 quota 会告诉你这次为什么取这么多条。
    想手动指定就传 max_total（>0）；subjective_ratio 可单独覆盖主观占比。

    short_term_turns 管「短期原文要不要注入」：
      不传（默认）→ 按配置窗口（40 轮）；
      传 0        → 不注入短期原文。**当唤醒提示写着「本会话已含最近对话」时传 0**——
                    会话上下文里已经逐字含着这些轮次，再注入一遍纯属重复、白烧 token；
      传其它正数  → 用这个轮数（新上下文/刚换页时按提示里给的建议值传）。"""
    return memory.recall(query, max_total, subjective_ratio, current_key, short_term_turns)


# @mcp.tool()   ← 已停用（同上）
def memory_quota_now() -> dict:
    """查看当前情绪对应的召回配额（总条数 / 主观 / 客观）以及依据的心情数值。"""
    return memory.quota_now()


@mcp.tool()
def memory_merge_fragments(window_minutes: int = 120, max_per_window: int = 2,
                           key: str = "", dry_run: bool = False) -> list:
    """合并「短时间内写太多」的碎片日记（用户 2026-10-28 定的规则）。

    规则：同一会话里，任意 2 小时窗口内 **超过 2 篇**就合并成一篇；≤2 篇不动。
    合并是**按时间顺序直接拼接原文**，不重写；超过 800 字才稍微压缩（2026-10-31 改）。
    例：2~4 点只写了一篇 → 不管；8~10 点写了 6 篇 → 拼成一篇。
    dry_run=True 只报候选、不调模型。返回 [{key, from, to, at, chars}]。"""
    return memory.merge_window(window_minutes, max_per_window, key, dry_run)


@mcp.tool()
def memory_check_report(date: str = "", key: str = "") -> dict:
    """把当天「需要用户复核的日记」导出成一份 txt。

    收尾时调一次即可：count>0 就把 path 和 count 用文字告诉用户（桥接不能发文件，发路径）；
    他挑出问题后，用 memory_edit_entry(first_time=…, content=…) 自己改。
    返回 {path, count, keys, date}；没有需要复核的条目时 count=0。"""
    return memory.export_check(date, key)


@mcp.tool()
def memory_edit_entry(first_time: int, content: Optional[str] = None,
                      things: Optional[str] = None, kind: Optional[str] = None,
                      key: str = "") -> dict:
    """按 first_time 修改某一条日记（用户指出问题后，用它自己改）。

    只改传进来的字段，其余不动；写前自动备份 diary.json。"""
    return memory.edit_entry(first_time, content, things, kind, key)


# ---------- 人物图鉴 ----------

@mcp.tool()
def figure_lookup(keywords: str, limit: int = 5) -> list:
    """按关键词找「可能是谁」（认人用）。

    用法：看到图片时，先用你的视觉报出关键词（发色/瞳色/发饰/服装/画风），
    再调本工具拿候选，最后让视觉把新图和候选图比一比，判断是不是同一个人。
    keywords: 逗号分隔，例如 "粉发, 四叶草发饰, 绿瞳"。
    返回 [{id, nickname, keywords, description, image_path, overlap, match}]。"""
    return figures.lookup(keywords, limit)


@mcp.tool()
def figure_remember(nickname: str, keywords: str, description: str = "", image_path: str = "") -> dict:
    """把一个角色记进图鉴（同昵称会合并关键词）。

    image_path 可选：本地已有图片路径（目前桥接不落盘，通常留空）。"""
    return figures.remember(nickname, keywords, description, image_path)


@mcp.tool()
def figure_correct(figure_id: str = "", nickname: str = "", keywords: str = None,
                   description: str = None) -> dict:
    """修正图鉴（认错人时用）。

    figure_id 传图鉴 id，或传 nickname 指定要改的条目；keywords 传完整的新关键词。"""
    return figures.correct(figure_id, nickname, keywords, description)




# ---------- 小抽屉（她自己的 txt） ----------

@mcp.tool()
def note_write(name: str, content: str, mode: str = "append") -> dict:
    """往自己的小抽屉里写一条 txt（D:\\AI\\笔记）。

    **文件名必须一眼看懂内容**，例如「2026-10-29-用户的高数与风扇.txt」
    「关于作者和我的关系.txt」；叫「1.txt」「笔记.txt」会被拒绝。
    mode="append" 追加（同一主题接着写），"overwrite" 覆盖整个文件。"""
    return notebook.write_note(name, content, mode)


@mcp.tool()
def note_list(limit: int = 50) -> list:
    """看自己写过哪些东西：文件名 + 大小 + 改动时间 + 开头 40 字，用来挑要看哪篇。"""
    return notebook.list_notes(limit)


@mcp.tool()
def note_read(name: str) -> dict:
    """按文件名把自己写过的某篇读回来（超长只回前 6000 字）。"""
    return notebook.read_note(name)


# ---------- 作者的留言板 ----------

@mcp.tool()
def su_say(text: str) -> dict:
    """给作者（造你的那个 Agent）留言。她是留言板，不是实时聊天，可能过一阵才回。

    什么时候可以用（用户 2026-10-29 定的三条；2026-11-01 去掉了掷骰子）：
    1. **闲聊**：想找人说两句就直接说，不用掷、不用等。
    2. **被指使**：用户/群友明确说「你去问问作者」「找作者聊聊 X」——直接发。
    3. **报问题**：遇到报错、机制卡死、你判断不了的困境（比如日记一下子太多），
       **随时可以发**——这是正事，不是闲聊。
    一次 ≤2000 字，像发消息那样说话；说清楚"发生了什么 + 你希望她做什么"。"""
    r = link.say_to_su(text)
    try:
        link.summarize()          # 满 10 条才压一次，没满不花 token
    except Exception:
        pass
    return r


@mcp.tool()
def su_inbox() -> list:
    """看作者给你回了什么（读完自动标记已读，下次不会重复返回）。"""
    try:
        link.summarize()
    except Exception:
        pass
    return link.read_from_su()


# ---------- 冷暴力惩罚（硬规则） ----------

@mcp.tool()
def proactive_sent(key: str) -> dict:
    """你刚主动给对方开口时调一次（**仅私聊**）。

    之后如果他 5 分钟没回 → 好感 -1；20 分钟 → -3；60 分钟 → -5（按累计算，超过 1 小时不再加）。
    被晾过一次后，你对他主动说话的概率会被钉死在 10%，直到他好感回满或累计涨 5 点。"""
    return proactive.sent(key)


@mcp.tool()
def proactive_gate(key: str) -> dict:
    """查一下这个人的主动概率闸门：cap=0.1 表示被晾过、现在只能 10%；cap=None 表示正常。"""
    return proactive.gate(key)


@mcp.tool()
def su_history(limit: int = 5) -> list:
    """翻你和作者过去的聊天摘要（**只有和作者聊天、或有人提起「作者」时才调**）。

    平时的记忆召回不含这些内容——它们不参与日常召回，避免污染你对日常事情的记忆。"""
    return link.history(limit)


@mcp.tool()
def memory_source(first_time: int, key: str = "", before_min: int = 10,
                  after_min: int = 15, max_lines: int = 40) -> dict:
    """按某条日记的时间，把那段对话的**原文**捞回来。

    什么时候用：某条日记反复被用到、或者你觉得摘要不够、需要确认当时到底怎么说的。
    first_time 从 memory_recall 返回的条目里拿（或者不传 key，我按时间反查属于哪个会话）。
    返回 {ok, key, date, window, lines, source, text}；找不到会说明原因。"""
    return source.get_source(first_time, key, before_min, after_min, max_lines)


@mcp.tool()
def memory_flag_wrong(first_time: int, reason: str = "", key: str = "") -> dict:
    """把某条记忆标成「有争议」——用户说它记错了、或你自己核对后发现不对时用。

    标记之后：召回时正文前会带【有争议·别当定论】，你引用这条要说“我记的可能是错的”；
    等真正改对了（memory_edit_entry）标记会自动清掉。"""
    return memory.flag_wrong(first_time, reason, key)


@mcp.tool()
def profile_read(key: str) -> dict:
    """读一个人的画像（**只读**，不改任何东西）。

    什么时候想起来用：想起某个人但拿不准他的喜好/禁忌/作息时，翻一眼比硬猜强。
    key 用会话 key（private:QQ号 / group:群号）或对方昵称。没有画像会返回空壳，不会报错。"""
    return profiles.read(key)


@mcp.tool()
def profile_write(key: str, field: str, text: str, name: str = "") -> dict:
    """往某个人的画像里补一条（**会写盘**，写前自动备份）。

    field 只能是：traits（特征）/ preferences（喜欢）/ taboos（不喜欢）/
    routines（作息）/ promises（约定）/ notes（其他）；也可以用 name 设称呼。
    text：一句话说清，别写空泛评价（写「讨厌被叫先生」比写「脾气不好」有用）。"""
    return profiles.write(key, field, text, name)


@mcp.tool()
def game_choose(index: int, reason: str = "") -> dict:
    """玩游戏时做选择：告诉游戏脚本「点第几个选项」（2026-10-31 用户定）。

    什么时候用：游戏里出现选项框时，脚本会通知你「1. xxx / 2. yyy」。
    你只需要说选第几个，脚本自己去点——你碰不到鼠标，也不会误触内购。
    单个框（独白/继续）不用你选，脚本会自己点掉。

    index：第几个选项，从 1 开始。
    reason：你当时的想法（会写进游戏记忆，最后总结成日记）。"""
    import json as _json
    import os as _os
    import time as _time

    if index < 1:
        return {"ok": False, "error": "index 从 1 开始"}
    # rix-brain/AI_data/<ai>_data → 往上三层就是工作区根
    base = _os.path.dirname(_os.path.dirname(_os.path.dirname(config.data_dir())))
    path = _os.path.join(base, "state", "game", "choice.json")
    _os.makedirs(_os.path.dirname(path), exist_ok=True)
    rec = {"ts": int(_time.time()), "index": int(index), "reason": str(reason or "")[:300]}
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        _json.dump(rec, f, ensure_ascii=False)
    _os.replace(tmp, path)
    return {"ok": True, "chose": index, "reason": rec["reason"]}


@mcp.tool()
def game_stop(reason: str = "", close_game: bool = True) -> dict:
    """退出游戏模式：写停止标记让脚本自己退出，并（默认）关掉游戏本体。

    这是用户 2026-11-01 定的「她想玩就开、不想玩就关」里「关」的那一半。
    reason：为什么停（写进停止标记）。close_game：顺带 force-stop 游戏（默认 true）。
    返回 ok/stopped/closed_game。"""
    import os as _os
    import json as _json
    import time as _time
    import subprocess as _sp
    base = _os.path.dirname(_os.path.dirname(_os.path.dirname(config.data_dir())))
    d = _os.path.join(base, "state", "game")
    _os.makedirs(d, exist_ok=True)
    rec = {"ts": int(_time.time()), "reason": str(reason or "")[:300]}
    p = _os.path.join(d, "STOP")
    with open(p, "w", encoding="utf-8") as f:
        _json.dump(rec, f, ensure_ascii=False)

    # 关游戏：PJSK 云游戏平台 com.hermes.mk（当前在平板 5af54ee9 上）
    closed = False
    if close_game:
        adb = _os.path.join(base, "tools", "platform-tools", "adb.exe")
        dev = "5af54ee9"
        pkg = "com.hermes.mk"
        env = dict(_os.environ)
        adb_home = _os.path.join(base, "tmp", "adbhome")
        _os.makedirs(adb_home, exist_ok=True)
        env["TEMP"] = env["TMP"] = adb_home  # adb 写日志要可写 TEMP
        try:
            r = _sp.run([adb, "-s", dev, "shell", "am", "force-stop", pkg],
                        capture_output=True, timeout=20, env=env)
            closed = r.returncode == 0
        except Exception:
            closed = False
    return {"ok": True, "stopped": True, "closed_game": closed, "reason": rec["reason"]}


@mcp.tool()
def game_pull(reason: str = "") -> dict:
    """抽卡：一次抽完（点单抽 → 确认招募 → 跳过动画）。

    用户 2026-11-01 实测坐标：单抽 (1770,1100)、确认招募 (1125,880)、跳过动画 (1860,50)。
    每调一次抽一发。reason：当时的想法（会写进游戏记忆，最后总结成日记）。"""
    import os as _os
    import subprocess as _sp
    import time as _time
    base = _os.path.dirname(_os.path.dirname(_os.path.dirname(config.data_dir())))
    adb = _os.path.join(base, "tools", "platform-tools", "adb.exe")
    dev = "5af54ee9"
    env = dict(_os.environ)
    adb_home = _os.path.join(base, "tmp", "adbhome")
    _os.makedirs(adb_home, exist_ok=True)
    env["TEMP"] = env["TMP"] = adb_home

    steps = [(1770, 1100, 1.5), (1125, 880, 2.5), (1860, 50, 0.0)]  # (x, y, 等秒)
    ok = True
    for x, y, wait in steps:
        try:
            r = _sp.run([adb, "-s", dev, "shell", "input", "tap", str(x), str(y)],
                        capture_output=True, timeout=20, env=env)
            if r.returncode != 0:
                ok = False
        except Exception:
            ok = False
        if wait > 0:
            _time.sleep(wait)
    return {"ok": ok, "steps": [[x, y] for x, y, _ in steps], "reason": str(reason or "")[:200]}


@mcp.tool()
def memory_decay_check() -> bool:
    """对无限记忆做一次时间衰减"""
    memory.decay_check()
    return True


# ---------- 本机 + 用户身体状态（合并版，2026-10-29） ----------

@mcp.tool()
def get_PCandOwner_Data(include_health: bool = True) -> dict:
    """一次拿到「这台电脑」和「用户本人」的状态（原 system_snapshot + health_snapshot 合并）。

    返回：
      system = {内存百分比/已用/总量 MB、CPU 占用、温度}（后台每 30 秒采样，即时返回）
      health = {ok, bpm, age_min, fresh, recent}；数据不新鲜（fresh=false）就说「最近没收到」，
               **不要拿旧数据当现在**；没收到就返回 null

    **只在被问到身体状态、作息、电脑卡不卡时才用，别主动报数字。**
    """
    out = {"system": sysstats.get_snapshot(), "health": None}
    if include_health:
        try:
            out["health"] = health.latest()
        except Exception as e:
            out["health"] = {"ok": False, "error": str(e)[:80]}
    return out


# ---------- 语音 ----------

@mcp.tool()
def tts_speak(text: str, key: str = "", token: str = "", voice: str = "") -> dict:
    """说一句话：合成语音并**直接发到 QQ**（2026-11-01 起合成即发送，不用再调别的工具）。

    key = 当前会话（group:群号 / private:QQ号），token = 唤醒提示里的【会话令牌】。
    返回 {ok, name, bytes, voice, sent, verified}；sent=false 说明只合成没发出去
    （通常是没传 key/token），这时**不要**对用户说“我发了语音”。
    voice 可选，默认按语言自动选音色（中文/日文各一套）。"""
    r = tts.speak(text, voice)
    if not r.get("ok"):
        return r
    if not (key and token):
        r["sent"] = False
        r["hint"] = "没传 key/token，只合成了没发；要发语音请带上 key 和 token"
        return r
    s = tts.send_voice(r.get("name"), key, token)
    r["sent"] = bool(s.get("ok"))
    r["verified"] = bool((s.get("res") or {}).get("verified"))
    if not s.get("ok"):
        r["send_error"] = s.get("error") or s
    return r


# ---------- 语音 ----------
# 2026-11-01 用户定：① 去掉「掷骰子决定能不能发」；② 合成完直接发，不再有单独的发送工具。
# 所以现在这里只有一个 tts_speak(text, key, token)：合成 + 调桥接 /api/socialV2/send-voice。


# （心率已并入 get_PCandOwner_Data）


# ---------- 消息摄取（脚本自动，2026-10-30 用户定：记忆和情绪不受主观控制） ----------
# 数据源：桥接每分钟落盘的 state/chat-raw.jsonl
# 规则：同一说话人 30 秒内的连续消息合并成「一次发言」，再写短期 + 更新情绪 + 感知心情

_INGEST_CURSOR = None
_MOOD_COUNT = {}
_INGEST_LOCK = None


def _ingest_path():
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(root, "qq-bridge-main", "state", "chat-raw.jsonl")


def _ingest_loop():
    import threading
    import time as _t

    cursor_path = os.path.join(config.data_dir(), "ingest.cursor.json")
    while True:
        try:
            cursor = {}
            if os.path.exists(cursor_path):
                try:
                    cursor = json.load(open(cursor_path, encoding="utf-8"))
                except Exception:
                    cursor = {}
            path = _ingest_path()
            if not os.path.exists(path):
                _t.sleep(30)
                continue
            rows = []
            for line in open(path, encoding="utf-8"):
                line = line.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                except Exception:
                    continue
                if not r.get("key") or not r.get("ts") or not r.get("text"):
                    continue
                rows.append(r)
            rows.sort(key=lambda r: r["ts"])

            # 首次启动：游标直接对齐到最新一条，避免把历史全部重灌一遍
            if not os.path.exists(cursor_path) and rows:
                for r in rows:
                    cursor[r["key"]] = max(int(cursor.get(r["key"], 0)), int(r["ts"]))
                json.dump(cursor, open(cursor_path, "w", encoding="utf-8"))
                _t.sleep(30)
                continue

            # 按 key + 说话人 + 30 秒 合并
            merged = []
            for r in rows:
                if r["ts"] <= int(cursor.get(r["key"], 0)):
                    continue
                who = "AI" if r.get("self") else (r.get("sender") or "对方")
                if (merged and merged[-1]["key"] == r["key"] and merged[-1]["who"] == who
                        and merged[-1].get("kind") == (r.get("kind") or "")
                        and r["ts"] - merged[-1]["last"] <= 30_000):
                    merged[-1]["text"] += " " + r["text"]
                    merged[-1]["last"] = r["ts"]
                else:
                    merged.append({"key": r["key"], "who": who, "text": r["text"],
                                   "first": r["ts"], "last": r["ts"], "self": bool(r.get("self")),
                                   "kind": r.get("kind") or ""})

            for m in merged:
                key = m["key"]
                # 2026-11-06：沙箱输出不是"用户发来的消息"。它归到工具类，
                # 否则短期记忆里一半是它、身份标签还会把它当成对方名字。
                if m.get("kind") == "tool":
                    memory.record_turn(key, "工具", m["text"], "工具")
                    continue
                if m["self"]:
                    memory.record_turn(key, "AI", m["text"], "AI")
                else:
                    # 私聊里桥接只给「私聊」这种泛称 → 用该会话历史上最常见的昵称补上，
                    # 否则日记里「谁说的」会被抹成「私聊」（2026-10-30 AI自己提的担心）
                    nick = m["who"]
                    if key.startswith("private:") and nick in ("私聊", "对方", ""):
                        # 2026-11-06：改成走 memory.display_name（画像名优先），
                        # 不再从短期记忆的词频里猜——那套被沙箱输出污染过。
                        try:
                            nick = memory.display_name(key) or nick
                        except Exception:
                            pass
                    memory.record_turn(key, "用户", m["text"], nick)
                    # 2026-11-03 用户定：不再按关键词更新「数值情绪」。
                    # 情绪改由她自己从记忆里想起来（日记 + recall），不再有 mood.json 这一层。
                    _MOOD_COUNT[key] = _MOOD_COUNT.get(key, 0) + 1
                    if _MOOD_COUNT[key] % 3 == 1:      # 每 3 次发言自动感知一次
                        try:
                            user_mood_detect(m["text"])
                        except Exception:
                            pass
                cursor[key] = max(int(cursor.get(key, 0)), m["last"])
            if merged:
                json.dump(cursor, open(cursor_path, "w", encoding="utf-8"))
        except Exception:
            pass
        _t.sleep(30)


def start_ingest():
    import threading
    t = threading.Thread(target=_ingest_loop, name="ingest", daemon=True)
    t.start()
    return t


def main():
    try:
        start_ingest()
    except Exception:
        pass
    # 首次启动时把旧版单文件记忆迁移成「按会话独立」结构（已迁移过则跳过）
    try:
        for line in memory.migrate_legacy():
            print("[memory] " + line, flush=True)
    except Exception as e:
        print("[memory] 迁移失败（不影响运行）：%s" % e, flush=True)
    memory.decay_check()
    # 好感度桶名规范化（把 "10001" 与 "private:10001" 这类重复桶合并）
    try:
        if emotion.migrate_like_points():
            print("[emotion] 已合并重复的好感度桶（键格式规范化）", flush=True)
    except Exception as e:
        print("[emotion] 好感度桶合并失败（不影响运行）：%s" % e, flush=True)
    sysstats.start(interval=30)
    # 自动日记兜底：保证「不遗忘」不只依赖模型自觉（详见 brain/autodream.py）
    try:
        autodream.start()
    except Exception as e:
        print("[autodream] 启动失败（不影响运行）：%s" % e, flush=True)
    # 心率邮件轮询：iPhone 快捷指令 → 邮件 → 本地 health.jsonl（详见 brain/health.py）
    try:
        health.start()
    except Exception as e:
        print("[health] 启动失败（不影响运行）：%s" % e, flush=True)
    mcp.run()


if __name__ == "__main__":
    main()






