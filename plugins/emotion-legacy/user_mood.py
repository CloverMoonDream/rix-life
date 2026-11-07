import re
import json
import os
import time
import threading

_mood_lock = threading.Lock()

# ── 积极语气词 ──
_POSITIVE_PARTICLES = ["哈哈", "嘿嘿", "呀", "啊", "耶", "哇", "好耶"]

# ── 消极语气词 ──
_NEGATIVE_PARTICLES = ["唉", "呵", "切"]

# ── 态度词（不靠直白情绪词，靠间接行为信号） ──
_DISMISSIVE_WORDS = ["算了", "随便", "无所谓", "都行", "你定", "没什么", "不想说", "别问了", "不想聊"]
_IRRITATED_WORDS = ["行吧", "够了", "不用", "烦", "无语", "你说呢", "你开心就好", "随便你", "有病"]
_ENTHUSIASTIC_WORDS = ["牛", "绝了", "可以啊", "nice", "真的吗", "然后呢", "说说", "厉害", "好耶"]

# ── 标点 ──
_POSITIVE_PUNCT = ["!", "！", "~", "～"]
_FLAT_PUNCT = ["...", "。。。", "。。"]

# ── 心情效价映射 ──
MOOD_VALENCE = {
    "开心": 7,
    "平静": 0,
    "疲惫": -3,
    "焦虑": -5,
    "难过": -7,
    "愤怒": -8,
}

VALID_MOODS = list(MOOD_VALENCE.keys())


def _count_matches(text, words):
    """统计 text 中命中的词数"""
    return sum(text.count(w) for w in words)


def detect_mood(user_text, interval=None):
    """
    本地行为信号检测用户心情

    通过语气词、态度词、标点、字数、间隔推断用户心情。
    不依赖直白的情绪词（"难过""开心"），而是捕捉间接行为信号。

    :param user_text: 用户消息
    :param interval: 距上一轮的间隔秒数（可选）
    :return: {"mood": str, "valence": int, "confidence": int, "source": "local"}
    """
    # 1. 语气词
    pos_particles = _count_matches(user_text, _POSITIVE_PARTICLES)
    neg_particles = _count_matches(user_text, _NEGATIVE_PARTICLES)

    # 2. 态度词
    dismissive = _count_matches(user_text, _DISMISSIVE_WORDS)
    irritated = _count_matches(user_text, _IRRITATED_WORDS)
    enthusiastic = _count_matches(user_text, _ENTHUSIASTIC_WORDS)

    # 3. 标点
    pos_punct = _count_matches(user_text, _POSITIVE_PUNCT)
    flat_punct = _count_matches(user_text, _FLAT_PUNCT)

    # 4. 字数（仅汉字）
    char_count = len(re.findall(r'[\u4e00-\u9fff]', user_text))
    is_short = char_count <= 3

    # 5. 间隔
    is_slow = interval is not None and interval > 120

    # 加权打分
    positive_score = pos_particles * 2 + enthusiastic * 2 + pos_punct
    negative_score = neg_particles + dismissive * 2 + irritated * 2
    flat_score = flat_punct + (2 if is_short else 0) + (1 if is_slow else 0)

    # 判断优先级：愤怒 > 难过 > 开心 > 疲惫 > 焦虑 > 平静
    if irritated >= 2 or (irritated >= 1 and is_short):
        mood = "愤怒"
        confidence = min(85, 50 + irritated * 15)
    elif dismissive >= 2 or (dismissive >= 1 and is_short and is_slow):
        mood = "难过"
        confidence = min(80, 50 + dismissive * 15)
    elif positive_score >= 3 and positive_score > negative_score:
        mood = "开心"
        confidence = min(90, 50 + positive_score * 10)
    elif flat_score >= 3 and negative_score == 0:
        mood = "疲惫"
        confidence = min(75, 40 + flat_score * 10)
    elif is_short and is_slow:
        mood = "焦虑"
        confidence = 55
    elif negative_score > positive_score and negative_score > 0:
        mood = "难过"
        confidence = 45
    else:
        mood = "平静"
        confidence = 50

    valence = MOOD_VALENCE.get(mood, 0)
    return {"mood": mood, "valence": valence, "confidence": confidence, "source": "local"}


def detect_mood_ai(recent_messages, api_key, ai_model):
    """
    AI判断用户心情（每5轮调用一次，校准本地检测）

    使用 API_main.ask_ai 嵌套调用，与 memory_split 同一模式。

    :param recent_messages: 最近5轮用户消息列表
    :param api_key: API密钥
    :param ai_model: AI模型名
    :return: {"mood": str, "valence": int, "confidence": int, "source": "ai"} 或 None
    """
    import API_main

    messages_text = "\n".join(f"{i+1}. {msg}" for i, msg in enumerate(recent_messages))
    prompt = (f'请根据以下用户最近5轮的回复，判断用户的心情。'
              f'只输出心情词和强度(1-10)，逗号分隔。'
              f'可选：开心/平静/疲惫/焦虑/难过/愤怒\n'
              f'用户回复：\n{messages_text}')

    messages = [{"role": "system", "content": prompt}]
    max_token = 20

    try:
        response = API_main.ask_ai(ai_model, api_key, messages, max_token)
    except Exception as e:
        print(f"用户心情AI判断失败: {e}")
        return None

    if not response or not isinstance(response, str):
        return None

    # 解析 "难过,7" 格式
    parts = response.strip().replace("，", ",").split(",")
    if len(parts) < 2:
        return None

    mood = parts[0].strip()
    try:
        intensity = int(parts[1].strip())
    except ValueError:
        intensity = 5

    if mood not in VALID_MOODS:
        return None

    base_valence = MOOD_VALENCE.get(mood, 0)
    valence = int(base_valence * intensity / 10) if base_valence != 0 else 0

    return {"mood": mood, "valence": valence, "confidence": 90, "source": "ai"}


def _default_state():
    return {
        "mood": "平静",
        "valence": 0,
        "confidence": 50,
        "source": "local",
        "consecutive_negative": 0,
        "round_count": 0,
        "recent_user_messages": [],
        "history": []
    }


def _load_state(state_path):
    """加载心情状态文件"""
    if not os.path.exists(state_path):
        return _default_state()
    try:
        with open(state_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            if not isinstance(data, dict):
                return _default_state()
            state = _default_state()
            state.update(data)
            return state
    except (json.JSONDecodeError, FileNotFoundError):
        return _default_state()


def _save_state(state_path, state):
    """保存心情状态文件"""
    d = os.path.dirname(state_path)
    if d:
        os.makedirs(d, exist_ok=True)
    with open(state_path, 'w', encoding='utf-8') as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def process_mood(user_text, state_path, api_key=None, ai_model=None, interval=None):
    """
    处理用户心情：本地检测 → 每5轮AI校准 → 趋势追踪

    :param user_text: 本轮用户消息
    :param state_path: 状态文件路径
    :param api_key: API密钥（AI校准用）
    :param ai_model: AI模型名（AI校准用）
    :param interval: 距上一轮间隔秒数（可选）
    :return: (mood_data, care_alert)
        mood_data: {"mood", "valence", "confidence", "source"}
        care_alert: bool，连续3轮消极触发主动关心
    """
    with _mood_lock:
        state = _load_state(state_path)
        now = int(time.time())

        # 存储最近用户消息（最多5条，供AI校准用）
        recent = state.get("recent_user_messages", [])
        recent.append(user_text)
        state["recent_user_messages"] = recent[-5:]

        # 1. 本地检测
        mood_data = detect_mood(user_text, interval)

        # 2. 轮数计数
        state["round_count"] += 1

        # 3. 每5轮AI校准
        if state["round_count"] >= 5 and api_key and ai_model:
            ai_mood = detect_mood_ai(state["recent_user_messages"], api_key, ai_model)
            if ai_mood:
                mood_data = ai_mood
            state["round_count"] = 0  # 无论成功失败都重置，避免积压

        # 4. 更新当前心情
        state["mood"] = mood_data["mood"]
        state["valence"] = mood_data["valence"]
        state["confidence"] = mood_data["confidence"]
        state["source"] = mood_data["source"]

        # 5. 趋势追踪
        if mood_data["valence"] < 0:
            state["consecutive_negative"] += 1
        else:
            state["consecutive_negative"] = 0

        # 6. 连续3轮消极触发主动关心（触发后重置）
        care_alert = False
        if state["consecutive_negative"] >= 3:
            care_alert = True
            state["consecutive_negative"] = 0

        # 7. 记录历史（保留最近20条）
        state["history"].append({
            "mood": mood_data["mood"],
            "valence": mood_data["valence"],
            "time": now,
            "source": mood_data["source"]
        })
        state["history"] = state["history"][-20:]

        _save_state(state_path, state)
        return mood_data, care_alert


def get_current_mood(state_path):
    """读取当前用户心情"""
    with _mood_lock:
        state = _load_state(state_path)
        return {
            "mood": state.get("mood", "平静"),
            "valence": state.get("valence", 0),
            "confidence": state.get("confidence", 50),
            "source": state.get("source", "local")
        }


def mood_to_prompt(mood_data, user_name):
    """
    将用户心情转为提示词（第二人称内心感受式）

    :param mood_data: {"mood": str, "valence": int, ...}
    :param user_name: 用户名
    :return: 提示词字符串，中性心情返回空字符串
    """
    mood = mood_data.get("mood", "平静")
    valence = mood_data.get("valence", 0)

    if valence == 0:
        return ""

    prompts = {
        "开心": f"你感觉到{user_name}现在心情不错，你也被带动得有些开心",
        "疲惫": f"你感觉到{user_name}好像有点累了，你有点心疼",
        "焦虑": f"你感觉到{user_name}似乎有些焦虑，你有点担心",
        "难过": f"你感觉到{user_name}心情不太好，你有些心疼，想安慰{user_name}",
        "愤怒": f"你感觉到{user_name}正在生气，你有些紧张，小心翼翼的",
    }

    return prompts.get(mood, "")


def is_user_negative(state_path):
    """判断用户当前是否处于消极心情（供 engagement 抑制愤怒用）"""
    mood_data = get_current_mood(state_path)
    return mood_data["valence"] < -3


def reset_consecutive_negative(state_path):
    """重置连续消极计数器（主动关心触发后调用）"""
    with _mood_lock:
        state = _load_state(state_path)
        state["consecutive_negative"] = 0
        _save_state(state_path, state)
