import json
import os
import re
import time
import threading

_mood_lock = threading.Lock()

# 心跳思考轮传给 temp_emotion_update 的关键字符串
# 检测到此串 → 跳过触发词检测和短回复检测，只做收敛
HEARTBEAT_KEY = "[HEARTBEAT_THINK]"

# ── 临时情感触发词 ──
_POSITIVE_KEYWORDS = {
    "love": [
        "我爱你", "爱你", "喜欢你", "好想你", "想你啦", "想你了",
        "好喜欢你", "超喜欢你", "最爱你", "爱死你了",
    ],
    "praise": [
        "你真棒", "你好厉害", "你真聪明", "你真可爱", "你好棒",
        "谢谢", "你最好了", "真棒", "太厉害了", "你好优秀",
        "你真厉害", "好棒", "辛苦了", "你最好", "真聪明",
        "真可爱", "好厉害", "谢谢你", "感谢", "你真牛",
    ],
}

_NEGATIVE_KEYWORDS = {
    "insult": [
        "你真笨", "你很笨", "笨蛋", "你真蠢", "你真傻", "讨厌你",
        "你很讨厌", "滚", "闭嘴", "废物", "垃圾", "你很差",
        "你真差", "烦死了", "你很烦", "你没用", "你真恶心",
        "烦人", "你烦不烦", "少废话", "你真烦",
    ],
}

# 触发基础变化量
_TRIGGER_BOOST = {
    "love": 30,
    "praise": 20,
    "insult": 25,
    "consecutive_short": 15,
}


def _mood_file_path():
    """mood.json 的绝对路径（优先用 config.data_dir()，与记忆模块保持一致）。"""
    try:
        import config
        return os.path.join(config.data_dir(), "mood.json")
    except Exception:
        return os.path.join("AI_data", "AI_data", "mood.json")


def _load_mood_file():
    p = _mood_file_path()
    if not os.path.exists(p):
        return {}
    try:
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_mood_file(mood):
    p = _mood_file_path()
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(mood, f, ensure_ascii=False, indent=2)
    os.replace(tmp, p)


def _norm_identity(user_key: str) -> str:
    """把身份标识规范成统一的桶名，避免同一个人被拆成多个桶。

    实例：模型有时传 "10001"、有时传 "private:10001"，
    两者本来是同一个人的好感度，之前会各记一份（实测出现过 6 / 2 两个桶）。
    规则：纯数字 → private:<数字>；已带 private:/group: 前缀 → 原样；
    非数字（昵称等）→ 原样；空 → __default__。
    """
    k = str(user_key or "").strip()
    if not k:
        return "__default__"
    if k.startswith("private:") or k.startswith("group:"):
        return k
    if k.isdigit():
        return "private:" + k
    return k


def migrate_like_points():
    """把已有的重复好感桶合并到规范桶（幂等；返回是否有改动）。"""
    try:
        with _mood_lock:
            mood = _load_mood_file()
            likes = mood.get("like_points")
            if not isinstance(likes, dict):
                return False
            merged = {}
            changed = False
            for k, v in likes.items():
                nk = _norm_identity(k)
                val = max(0, min(100, int(v or 0)))
                if nk != k:
                    changed = True
                merged[nk] = max(0, min(100, merged.get(nk, 0) + val))
            if not changed:
                return False
            mood["like_points"] = merged
            _save_mood_file(mood)
            return True
    except Exception:
        return False


def _like_step(mood, bucket, base, factor, direction):
    """按 factor 折算好感变化量，小数部分用进位累计。

    直接用 int() 取整会让 ×1/4 的增量变成 0，好感永远卡住不动；
    这里把每次的小数余数存起来（涨跌各一套），攒够 1 再进位，
    所以 1/2、1/4 是精确的「平均速度减半／降到四分之一」，而不是「有时不动」。
    """
    raw = base * factor
    whole = int(raw)
    key = "like_carry" if direction == "up" else "like_carry_down"
    cmap = mood.get(key)
    if not isinstance(cmap, dict):
        cmap = {}
    carry = float(cmap.get(bucket, 0.0) or 0.0) + (raw - whole)
    if carry >= 1.0:
        extra = int(carry)
        whole += extra
        carry -= extra
    cmap[bucket] = round(carry, 4)
    mood[key] = cmap
    return whole


def _like_factor(like_point: int) -> float:
    """好感变化倍率（操作者 2026-10-26 指定：分 10 段线性衰减）。

    0~10 → 100%，10~20 → 90%，20~30 → 80%，…，90~100 → 10%；
    每段固定降 10%，段内保持该段倍率。
    """
    tier = min(9, max(0, int(like_point)) // 10)
    return round((10 - tier) / 10.0, 2)


class Emotion:
    """情感系统，所有数据保存在 AI_data/{ai_name}_data/mood.json"""
    def __init__(self, ai_name: str, user_name: str = "用户"):
        """
        ai_name: AI角色名，用于定位数据目录
        user_name: 当前用户名，用于生成兴趣提示词
        """
        self.ai_name = ai_name
        self.user_name = user_name
        # 构建 mood.json 路径
        self.mood_path = os.path.join("AI_data", f"{ai_name}_data", "mood.json")
        # 确保目录存在
        os.makedirs(os.path.dirname(self.mood_path), exist_ok=True)
        # 初始化 mood.json（如果不存在）
        self._init_mood_file()

    def _init_mood_file(self):
        """创建默认的 mood.json"""
        if not os.path.exists(self.mood_path):
            default = {
                "happiness": 50,
                "excited": 50,
                "negative_emotion": 0,
                "like_point": 0,
                "last_happiness": 50,
                "last_negative_emotion": 0,
                "last_dialogue_time": 0,
                "interest_value": 0,
                "happiness_counter": "",
                "temp_happiness": 50,
                "trigger_effectiveness": {},
                "trigger_last_time": {},
                "short_response_count": 0,
            }
            with open(self.mood_path, 'w', encoding='utf-8') as f:
                json.dump(default, f, indent=2, ensure_ascii=False)

    def _load(self):
        """读 mood.json；文件缺失/为空/损坏时返回默认值，绝不抛异常。

        2026-11-03 修：原来这里是裸 json.load，mood.json 一旦被截成 0 字节
        （_save 非原子写被中断），之后每次读写都抛异常 → 情绪系统整个死掉，
        happiness/negative/好感 全部卡在默认值（11-01 11:46 起两天没动过）。
        """
        try:
            with open(self.mood_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
        except Exception:
            pass
        default = {
            "happiness": 50, "excited": 50, "negative_emotion": 0, "like_point": 0,
            "last_happiness": 50, "last_negative_emotion": 0, "last_dialogue_time": 0,
            "interest_value": 0, "happiness_counter": "", "temp_happiness": 50,
            "trigger_effectiveness": {}, "trigger_last_time": {}, "short_response_count": 0,
            "like_points": {},
        }
        try:
            self._save(default)      # 顺手把坏文件补回来
        except Exception:
            pass
        return default

    def _save(self, data):
        """原子写：先写 .tmp 再 replace，进程中途死掉也不会留 0 字节文件。"""
        tmp = self.mood_path + ".tmp"
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tmp, self.mood_path)

    # ---------- 以下为原始函数，仅修改了数据读写方式 ----------
    def happiness_point(self, user_said: str) -> int:
        """开心值计算，返回当前开心值"""
        with _mood_lock:
            mood = self._load()
            now_time = int(time.time())
            said_str = re.sub(r'[^\w\s]', '', user_said)
            word_count = len(said_str)

            last_time = mood.get("last_dialogue_time", 0)
            happiness = mood.get("happiness", 50)
            negative_emotion = mood.get("negative_emotion", 0)
            like_point = mood.get("like_point", 0)
            interest_value = mood.get("interest_value", 0)

            time_diff = now_time - last_time
            # 2026-11-03 用户定（AI提的）：情绪不要掉得太快，也不要 6 小时一过就全量重置。
            # 改成连续慢衰减：开心每小时向 50 靠 2 点；负面每小时掉 4 点（50 分大概半天掉一半）。
            hours = min(max(time_diff, 0) / 3600.0, 72.0)   # 最多按 72 小时算，不再一刀清零
            if hours > 0:
                if happiness < 50:
                    happiness = min(50.0, happiness + 2.0 * hours)
                elif happiness > 50:
                    happiness = max(50.0, happiness - 2.0 * hours)
                if negative_emotion > 0:
                    negative_emotion = max(0.0, negative_emotion - 4.0 * hours)
                    mood["negative_emotion"] = int(round(negative_emotion))
            # 「超过6小时重置负面/激动」整段已删：那是"气完转头笑嘻嘻"的主因。
                # 超过6小时，重置负面和激动，并根据好感度重置开心值
                mood["negative_emotion"] = 0
                mood["excited"] = 50
            # 字数影响（原有逻辑，保留）
            if word_count <= 2 or word_count >= 31:
                happiness -= 1
            elif 2 < word_count < 31:
                happiness += 1

            # 兴趣值影响（如果兴趣值大于2，加2）
            if interest_value > 2:
                happiness += 2

            # 负面情绪影响
            if negative_emotion > 6:
                happiness -= 5

            # 2026-11-03 用户定（AI：「别按轮次硬给我加分」）：删掉每轮固定 +1。
            # 原来那条会把开心值一路推高，跟她实际经历了什么无关。

            happiness = max(0, min(100, int(happiness)))

            mood["happiness"] = happiness
            mood["last_dialogue_time"] = now_time
            self._save(mood)
            return happiness

    def dialogue_interest(self, user_said: str):
        """判断兴趣值，返回 (提示词, interest_value)，同时更新 interest_value"""
        interest_keywords = {
            "study": ['数学','函数','几何','立体','向量','计算'],
            "pet": ['猫','毛茸茸','喵'],
            "environment": ['雨','星星','繁星','星空','阴天','潮湿','安静','安全']
        }
        study_times = sum(user_said.count(kw) for kw in interest_keywords["study"])
        pet_times = sum(user_said.count(kw) for kw in interest_keywords["pet"])
        env_times = sum(user_said.count(kw) for kw in interest_keywords["environment"])

        interest_all = study_times + pet_times + env_times
        # 找出最主要的兴趣类型
        max_val = max(study_times, pet_times, env_times)
        if max_val == study_times and study_times - pet_times >= 1 and study_times - env_times >= 1:
            prompt_type = "描述的有关学习的事"
        elif max_val == pet_times and pet_times - study_times >= 1 and pet_times - env_times >= 1:
            prompt_type = "描述的有关宠物的事"
        elif max_val == env_times and env_times - pet_times >= 1 and env_times - study_times >= 1:
            prompt_type = "描述的环境"
        else:
            prompt_type = "的话"

        if interest_all > 3:
            prompt = f"你对{self.user_name}{prompt_type}很感兴趣"
        else:
            prompt = ""
        if interest_all > 10:
            interest_all = 10#限制最大增长量
        # 更新 interest_value
        with _mood_lock:
            mood = self._load()
            mood["interest_value"] = interest_all
            self._save(mood)
        return prompt, interest_all

    def excited_point(self, happiness: int) -> int:
        """激动值计算，传入当前开心值，返回激动值"""
        with _mood_lock:
            mood = self._load()
            last_happiness = mood.get("last_happiness", 50)
            excited = mood.get("excited", 50)

            if happiness >= 75 and last_happiness >= 75:
                excited += 5
            elif happiness <= 25 and last_happiness <= 25:
                excited -= 5
            excited += abs(happiness - last_happiness) - 1
            excited = max(0, min(100, excited))

            mood["excited"] = excited
            self._save(mood)
            return excited

    def negative_emotion_point(self, happiness: int) -> int:
        """负面情绪值，传入当前开心值，返回负面值"""
        with _mood_lock:
            mood = self._load()
            last_happiness = mood.get("last_happiness", 50)
            change = happiness - last_happiness
            counter_str = mood.get("happiness_counter", "")
            pos = counter_str.count('1')
            neg = counter_str.count('2')

            if change >= 0:
                pos += change
            else:
                neg += -change
            if pos > 0 and neg > 0:
                net = pos - neg
                if net >= 0:
                    pos = net
                    neg = 0
                else:
                    neg = -net
                    pos = 0
            mood["happiness_counter"] = '1' * pos + '2' * neg

            negative = mood.get("negative_emotion", 0)
            if pos >= 5:
                negative = max(0, negative - 1)
                mood["happiness_counter"] = ''
            elif neg >= 5:
                negative = min(10, negative + 1)
                mood["happiness_counter"] = ''

            negative = max(0, min(10, negative))
            mood["negative_emotion"] = negative
            self._save(mood)
            return negative

    def emotion_all(self, happiness: int, excited: int, negative_emotion: int) -> str:
        """根据三个值返回情绪词"""
        # 直接使用原始逻辑（精简为字典映射）
        # 为保持可读性，此处保留原始条件分支（已测试）
        if 0 <= happiness < 10:
            if 0 <= excited < 33:
                if 0 <= negative_emotion < 3:
                    return '沮丧'
                elif 3 <= negative_emotion < 7:
                    return '很不高兴'
                else:
                    return '非常不开心'
            elif 33 <= excited < 66:
                if 0 <= negative_emotion < 3:
                    return '很不开心'
                elif 3 <= negative_emotion < 7:
                    return '有些悲伤'
                else:
                    return '非常难过'
            else:
                if 0 <= negative_emotion < 3:
                    return '有点生气'
                elif 3 <= negative_emotion < 7:
                    return '很生气'
                else:
                    return '非常生气'
        elif 10 <= happiness < 35:
            if 0 <= excited < 33:
                if 0 <= negative_emotion < 3:
                    return '低落'
                elif 3 <= negative_emotion < 7:
                    return '烦躁'
                else:
                    return '苦恼'
            elif 33 <= excited < 66:
                if 0 <= negative_emotion < 3:
                    return '郁闷'
                elif 3 <= negative_emotion < 7:
                    return '有点不高兴'
                else:
                    return '很难过'
            else:
                if 0 <= negative_emotion < 3:
                    return '烦躁'
                elif 3 <= negative_emotion < 7:
                    return '很生气'
                else:
                    return '非常生气'
        elif 35 <= happiness < 65:
            if 0 <= excited < 33:
                if 0 <= negative_emotion < 3:
                    return '冷漠'
                elif 3 <= negative_emotion < 7:
                    return '有些生气'
                else:
                    return '压抑'
            elif 33 <= excited < 66:
                if 0 <= negative_emotion < 3:
                    return '平和'
                elif 3 <= negative_emotion < 7:
                    return '有些不快'
                else:
                    return '憋屈'
            else:
                if 0 <= negative_emotion < 3:
                    return '兴奋'
                elif 3 <= negative_emotion < 7:
                    return '有些焦虑'
                else:
                    return '很焦躁'
        elif 65 <= happiness < 90:
            if 0 <= excited < 33:
                if 0 <= negative_emotion < 3:
                    return '还行'
                elif 3 <= negative_emotion < 7:
                    return '无奈'
                else:
                    return '有些矛盾'
            elif 33 <= excited < 66:
                if 0 <= negative_emotion < 3:
                    return '愉快'
                elif 3 <= negative_emotion < 7:
                    return '有些不快'
                else:
                    return '有点矛盾'
            else:
                if 0 <= negative_emotion < 3:
                    return '比较开心'
                elif 3 <= negative_emotion < 7:
                    return '有些恼怒'
                else:
                    return '有些焦躁'
        else:  # 90 <= happiness <= 100
            if 0 <= excited < 33:
                if 0 <= negative_emotion < 3:
                    return '心满意足'
                elif 3 <= negative_emotion < 7:
                    return '略微羞恼'
                else:
                    return '有些矛盾'
            elif 33 <= excited < 66:
                if 0 <= negative_emotion < 3:
                    return '幸福'
                elif 3 <= negative_emotion < 7:
                    return '有些不快'
                else:
                    return '有点矛盾'
            else:
                if 0 <= negative_emotion < 3:
                    return '非常开心'
                elif 3 <= negative_emotion < 7:
                    return '有些激动'
                else:
                    return '有些混乱'

    def like_point(self, user_key: str = "") -> int:
        """好感度计算（**按身份独立存储**），返回该身份当前好感度。

        user_key: 身份标识 —— 私聊可用会话 key（如 private:10001），
                  群聊建议用对方的 QQ 号/昵称；留空则用默认桶 __default__。

        增长门槛：负面 ≤1 且 连续两轮开心值 ≥56
        下跌条件：(连续两轮负面 ≥5) 或 (连续两轮开心值 ≤30)
        """
        with _mood_lock:
            mood = self._load()
            negative = mood.get("negative_emotion", 0)
            last_negative = mood.get("last_negative_emotion", 0)
            happiness = mood.get("happiness", 50)
            last_happiness = mood.get("last_happiness", 50)

            # 每个身份一份好感度；旧的全局 like_point 迁移到默认桶
            likes = mood.get("like_points")
            if not isinstance(likes, dict):
                likes = {}
                legacy = int(mood.get("like_point", 0) or 0)
                if legacy > 0:
                    likes["__default__"] = legacy
            bucket = _norm_identity(user_key)
            like = int(likes.get(bucket, 0) or 0)

            if negative <= 1 and last_negative <= 1 and happiness >= 56 and last_happiness >= 56:
                if like <= 70:
                    base = 2 * (like * 0.015 + 1)
                else:
                    base = 2 * (like * 0.012)
                # 增速倍率（操作者 2026-10-26 指定）：10 段线性衰减，0~10 全速，90~100 只剩 10%
                factor = _like_factor(like)
                like += _like_step(mood, bucket, base, factor, "up")
            elif (negative >= 5 and last_negative >= 5) or (happiness <= 30 and last_happiness <= 30):
                if like <= 70:
                    base = 2 * (like * 0.01 + 1)
                else:
                    base = 2 * (like * 0.018)
                # 掉的速度同样十段线性衰减（与增长对称，操作者 2026-10-26）
                factor = _like_factor(like)
                like -= _like_step(mood, bucket, base, factor, "down")
            like = max(0, min(100, like))

            likes[bucket] = like
            mood["like_points"] = likes
            mood["like_point"] = like          # 兼容字段：保留最近一次的值
            mood["like_point_last_key"] = bucket
            mood["last_negative_emotion"] = negative
            mood["last_happiness"] = happiness
            self._save(mood)

            return like

    def read_like(self, user_key: str = "") -> int:
        """只读取某个身份的好感度（不更新、不写盘）。"""
        with _mood_lock:
            mood = self._load()
        likes = mood.get("like_points")
        if not isinstance(likes, dict):
            likes = {}
        bucket = _norm_identity(user_key)
        return int(likes.get(bucket, mood.get("like_point", 0) if bucket == "__default__" else 0) or 0)

    def _detect_trigger(self, user_said: str):
        """检测触发词，返回 (category, is_positive) 或 (None, None)

        2026-11-03 用户定（AI：「别替我决定该高兴」）：**正面触发已停用**。
        被夸不再自动涨开心——要开心，得她自己觉得值得。
        负面触发保留：被骂会难受，那是本能，不是别人替她决定的。
        """
        for category, keywords in _NEGATIVE_KEYWORDS.items():
            for kw in keywords:
                if kw in user_said:
                    return category, False
        return None, None

    def _trigger_with_decay(self, category, is_positive, temp_h, trigger_eff, trigger_time, now):
        """触发并应用效果递减，返回更新后的 temp_h

        - 每次触发效果降 25%（5次归零）
        - 停用满1小时恢复10%，此后每小时+10%，最高100%
        """
        eff = trigger_eff.get(category, 100)
        last_t = trigger_time.get(category, 0)
        # 时间恢复
        if last_t > 0:
            hours_since = (now - last_t) / 3600
            if hours_since >= 1:
                recovery = int(hours_since) * 10
                eff = min(100, eff + recovery)
        # 应用效果
        multiplier = eff / 100.0
        base = _TRIGGER_BOOST.get(category, 20)
        change = base * multiplier
        if is_positive:
            temp_h += change
        else:
            temp_h -= change
        # 降低效果
        trigger_eff[category] = max(0, eff - 25)
        trigger_time[category] = now
        return temp_h

    def temp_emotion_update(self, user_said: str, real_happiness: int):
        """临时情感更新

        - 触发词命中 → 瞬间大幅改变临时情感
        - 连续3次短回复（≤3字）→ 降低临时情感
        - 效果递减：每次触发降25%（5次归零），停用1小时后每小时恢复10%（最高100%）
        - 效果为0时只按字数计算好感值（不改变临时情感）
        - 每轮收敛：临时情感向真实靠近4，真实向临时靠近1
        - 返回 (temp_happiness, updated_real_happiness)
        """
        with _mood_lock:
            mood = self._load()
            temp_h = mood.get("temp_happiness", real_happiness)
            if not isinstance(temp_h, (int, float)):
                temp_h = real_happiness
            trigger_eff = mood.get("trigger_effectiveness", {})
            if not isinstance(trigger_eff, dict):
                trigger_eff = {}
            trigger_time = mood.get("trigger_last_time", {})
            if not isinstance(trigger_time, dict):
                trigger_time = {}
            short_count = mood.get("short_response_count", 0)
            if not isinstance(short_count, int):
                short_count = 0

            now = int(time.time())

            # 心跳思考轮：传关键字符串则跳过触发词和短回复检测，只做收敛
            if user_said == HEARTBEAT_KEY:
                pass
            else:
                # 1. 检测触发词
                category, is_positive = self._detect_trigger(user_said)

                # 2. 检测连续短回复
                said_str = re.sub(r'[^\w\s]', '', user_said)
                word_count = len(said_str)
                is_short = word_count <= 3

                if category:
                    # 触发词命中
                    temp_h = self._trigger_with_decay(
                        category, is_positive, temp_h, trigger_eff, trigger_time, now)
                    short_count = 0  # 重置连续短回复
                elif is_short:
                    # 无触发词但短回复
                    short_count += 1
                    if short_count >= 3:
                        temp_h = self._trigger_with_decay(
                            "consecutive_short", False, temp_h, trigger_eff, trigger_time, now)
                else:
                    short_count = 0

            # 3. 收敛：临时→真实 变化4，真实→临时 变化1
            diff = temp_h - real_happiness
            if diff > 0:
                temp_h -= min(4, diff)
                real_happiness += min(1, diff)
            elif diff < 0:
                temp_h += min(4, -diff)
                real_happiness -= min(1, -diff)

            temp_h = max(0, min(100, int(round(temp_h))))
            real_happiness = max(0, min(100, int(real_happiness)))

            mood["temp_happiness"] = temp_h
            mood["happiness"] = real_happiness
            mood["trigger_effectiveness"] = trigger_eff
            mood["trigger_last_time"] = trigger_time
            mood["short_response_count"] = short_count
            self._save(mood)

            return temp_h, real_happiness

    def excited_toward_50(self):
        """心跳思考轮：temp==real 时将 excited 向50靠近

        - 40~60: 不变
        - 0~10, 90~100: 每轮靠近3
        - 11~39, 61~89: 线性取整
        - 低于50加，高于50减
        """
        with _mood_lock:
            mood = self._load()
            temp_h = mood.get("temp_happiness", 50)
            real_h = mood.get("happiness", 50)
            excited = mood.get("excited", 50)

            # 仅当临时情感和真实情感基本一致时才靠近
            # （踩过：收敛是 temp→real 靠 4、real→temp 靠 1，两者会在 ±1 来回跳，
            #   要求严格相等就永远不会回落 —— 这里给 2 的容差）
            if abs(temp_h - real_h) > 2:
                return excited

            if 40 <= excited <= 60:
                return excited  # 中性区不变

            if excited < 50:
                if excited <= 10:
                    step = 3
                else:
                    step = int(round(3 * (40 - excited) / 29))
                excited = min(50, excited + step)
            else:
                if excited >= 90:
                    step = 3
                else:
                    step = int(round(3 * (excited - 60) / 29))
                excited = max(50, excited - step)

            mood["excited"] = excited
            self._save(mood)
            return excited

    def like_word_PD(self, like_point: int) -> str:
        """根据好感度返回提示词"""
        if like_point < 10:
            return '你和对方关系一般，保持礼貌，回答简短。'
        elif like_point < 20:
            return '你和对方关系一般，愿意和对方多聊几句，但不要主动开始话题。保持礼貌。'
        elif like_point < 30:
            return '你和对方关系还行，愿意和对方多聊几句，偶尔会询问对方的日常，保持语气轻松。'
        elif like_point < 40:
            return '你和对方关系不错，愿意和对方多聊几句，很愿意了解对方的日常。'
        elif like_point < 50:
            return '你和对方关系不错，很愿意和对方聊天，愿意了解对方的日常，也会主动关心对方，语气亲切。'
        elif like_point < 60:
            return '你和对方是好朋友，很愿意和对方聊天，愿意了解对方的日常，也会主动关心对方，语气亲切。会主动分享心情。'
        elif like_point < 70:
            return '你和对方是很好的朋友，很愿意和对方聊天，愿意了解对方的日常，也会主动关心对方，语气亲切。会表达想念，会为他担心。'
        elif like_point < 80:
            return '你和对方是很好的朋友，很愿意和对方聊天，愿意了解对方的日常，也会主动关心对方，语气亲切活泼。会表达想念，会为他担心。有时会开一些小玩笑。'
        elif like_point < 90:
            return '你和对方是很好的朋友，很愿意和对方聊天，愿意了解对方的日常，也会主动关心对方，语气亲切活泼。会表达想念，会为他担心。有时会开一些小玩笑。会直接表达情绪。'
        else:
            return '你和对方非常亲近，很愿意和对方聊天，愿意了解对方的日常，也会主动关心对方，语气亲切活泼。会表达想念，会为他担心。有时会开一些小玩笑。会直接表达情绪，也会依赖对方。'
