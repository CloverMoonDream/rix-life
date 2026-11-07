import API_main#必须使用这个程序里的函数
import json
import os
from datetime import datetime
import time
from difflib import SequenceMatcher
# ========== 超长常见属性列表（共200+个） ==========
EXTENDED_ATTRIBUTES = [
    # 物理属性
    "大", "小", "巨大", "微小", "中等", "宽敞", "狭窄", "重", "轻", "沉重", "轻盈", "圆", "方", "长", "扁",
    "不规则", "对称", "弯曲", "笔直", "红", "橙", "黄", "绿", "青", "蓝", "紫", "黑", "白", "灰", "粉", "棕",
    "透明", "彩色", "单色", "鲜艳", "暗淡", "热", "冷", "温暖", "凉爽", "冰凉", "滚烫", "常温", "软", "硬",
    "柔软", "坚硬", "粗糙", "光滑", "细腻", "毛茸茸", "黏稠", "干燥", "湿润", "响亮", "安静", "嘈杂", "悦耳",
    "刺耳", "低沉", "高亢", "清脆", "沙哑", "香", "臭", "芳香", "刺鼻", "清新", "霉味", "焦味", "甜香", "酸臭",
    "甜", "酸", "苦", "辣", "咸", "鲜", "清淡", "浓郁", "油腻",
    # 情感与性格
    "快乐", "幸福", "激动", "兴奋", "满足", "平静", "放松", "安心", "温暖", "感动", "自豪", "期待", "感激", "被爱",
    "悲伤", "痛苦", "愤怒", "焦虑", "恐惧", "沮丧", "孤独", "失望", "嫉妒", "羞耻", "压抑", "绝望", "烦躁",
    "温柔", "体贴", "善良", "诚实", "勇敢", "坚强", "独立", "开朗", "活泼", "幽默", "文静", "内向", "外向",
    "热情", "冷漠", "孤僻", "自私", "刻薄", "暴躁", "软弱", "懒惰", "勤奋", "认真", "细心", "马虎",
    # 能力与智力
    "聪明", "智慧", "愚蠢", "迟钝", "机灵", "天才", "白痴", "懂行", "不懂", "专业", "外行", "熟练", "精通",
    "擅长", "生疏", "新手", "专家", "全能", "专精", "强壮", "虚弱", "敏捷", "笨拙", "灵活", "僵硬", "耐力好", "易疲劳",
    # 价值与评价
    "好", "坏", "优秀", "差劲", "普通", "一般", "完美", "缺陷", "优质", "劣质", "贵", "便宜", "昂贵", "实惠",
    "划算", "不值", "奢侈", "廉价", "重要", "不重要", "关键", "次要", "核心", "边缘", "必要", "可有可无",
    "简单", "容易", "困难", "复杂", "繁琐", "轻松", "艰难", "危险", "安全", "可靠", "不可靠", "稳定", "不稳定",
    # 时间与频率
    "早", "晚", "及时", "迟到", "准时", "提前", "拖延", "瞬间", "长久", "短暂", "永久", "临时", "经常", "偶尔",
    "总是", "从不", "有时", "罕见", "频繁", "定期",
    # 空间与位置
    "高", "低", "远", "近", "上", "下", "左", "右", "内", "外", "前", "后", "中央", "边缘", "存在", "消失",
    "固定", "移动", "静止", "打开", "关闭", "完整", "破碎",
    # 感官与知觉
    "明亮", "黑暗", "清晰", "模糊", "闪烁", "刺眼", "柔和", "响亮", "嘈杂", "安静", "冷", "热", "痛", "痒", "麻",
    "舒服", "难受", "舒适", "不适", "愉悦", "痛苦", "香", "臭",
    # 抽象关系
    "正确", "错误", "矛盾", "合理", "荒谬", "可能", "必然", "偶然", "相同", "相似", "不同", "相反", "对等", "优劣",
    "导致", "引起", "因为", "所以", "结果", "原因",
    # 社会与道德
    "善良", "邪恶", "正义", "公平", "不公", "道德", "不道德", "受欢迎", "被排斥", "合群", "孤僻", "友善", "敌对",
    # 其他
    "新", "旧", "现代", "传统", "时尚", "过时", "真", "假", "真实", "虚假", "确定", "不确定", "一定", "也许"
]


def memory_sort(short_memory_json_path):
    """
    长期记忆的整理函数，把短期记忆整理为连贯的对话，并总结出条数
    short_memory_json_path是短期记忆的文件名，格式为"XXXXX.json"
    json格式需包含：
    {
    "role":(你的AI的名字 或 你的名字)
    "content":(你的AI说的话 或 你说的话)
    }
    存在其他字典也可以，但至少要有role和content

    """
    if os.path.exists(short_memory_json_path):
        try:
            with open(short_memory_json_path,'r',encoding = 'utf-8') as f:
                messages = json.load(f)
        except(FileNotFoundError, json.JSONDecodeError) as e:
            print("error:Can't open the file,check your file")
            print("error:无法打开文件，请检查对应文件")
            return "",0
        lines = []
        for msg in messages:
            # 兼容 "name"（sum/dialogue 版）和 "role"（all 版）两种字段名
            role = msg.get("name") or msg.get("role") or '未知'
            content = msg.get("content", "").strip()
            if content:  # 忽略空内容
                lines.append(f"{role}：{content}")

        text = "\n".join(lines)
        count = len(lines)
        return text, count
    else:
        print('Wrong file path')
        print('文件路径错误')
        return "",0

def memory_sum(talk_text, line_number, ai_name,user_name, api_key, ai_model, infinite_memory_save_path):
    '''
    长期记忆的总结函数，AI总结
    ai_name: AI角色名称
    api_key: API密钥
    ai_model: 选用的LLM
    infinite_memory_save_path: 无限记忆文件路径，用于读取上一条日记
    '''
    if line_number <= 10:
        max_token = 800
        max_words = '150'
    elif 10 <= line_number <= 20:
        max_token = 1800
        max_words = '300'
    else:
        max_token = 2400
        max_words = '500'

    # 尝试读取上一条日记（无限记忆的最后一条）
    last_diary = ""
    if os.path.exists(infinite_memory_save_path):
        try:
            with open(infinite_memory_save_path, 'r', encoding='utf-8') as f:
                memories = json.load(f)
            if isinstance(memories, list) and len(memories) > 0:
                last_entry = memories[-1]
                last_diary = last_entry.get("memory_content", "")
        except Exception as e:
            print(f"读取上一条日记失败: {e}")

    # 构建用户提示词，如果有上一条日记则添加
    user_content = f"对话文本:\n{talk_text}"
    if last_diary:
        user_content = f"上一条日记：{last_diary}\n\n{user_content}"

    messages = [
        {"role": "system", "content": f'''你是{ai_name}，以第一人称日记的形式总结收到的对话文本，总结为{max_words}字以内，优先保留要点。

【格式要求】
- 直接以日记内容开头，不要提"我是XXX"或任何自我介绍。
- 如有明确的时间信息（如"今天"、"昨天"、"上周"、具体日期等），必须在日记中保留。
- 日记中应体现对话发生的大致时间背景，例如"今天和{user_name}..."、"昨天{user_name}提到..."。

【内容要求】
- 有人物的喜好、厌恶、习惯等内容，必须特别记述，不可概括。
- 用户向你介绍了新知识、新事物，或纠正了你的错误，必须记录（这是你学习的过程）。
- 出现负面情绪（争吵、沮丧、焦虑、生气等）或正面情绪（兴奋、感动、开心等），要如实记录情绪氛围，不可淡化。
- 用户提到了未来的计划或承诺（如"明天要做XX"），要记录。
- 在不超字数的前提下尽可能全面，不要遗漏关键信息。

示例：
- "今天和{user_name}聊了音乐，{user_name}说没什么特别喜欢的。"
- "昨天{user_name}教了我什么是爵士乐，感觉很有意思。"
- "{user_name}今天看起来很沮丧，因为考试没考好，我安慰了他一会儿。"
- "和{user_name}吵了几句，关于XX的事，最后和解了。"
- "今天{user_name}说周末要去爬山，约我一起。"
'''},
        {"role": "user", "content": user_content}
    ]
    ai_answer = API_main.ask_ai(ai_model, api_key, messages, max_token)
    return ai_answer

def get_attributes_of_word(word,save_path,api_key,ai_model,attributes_list=None):
    """
    让 AI 判断一个词语具有哪些属性，并将结果存入 JSON 文件。

    参数:
        word (str): 要判断的词语
        attributes_list (list): 候选属性列表，若为 None 则使用超长列表
        save_path (str): 保存结果的 JSON 文件路径，默认 "word_attributes.json"

    返回:
        dict: 包含 "word" 和 "attributes" 的字典
    """
    if attributes_list is None:
        attributes_list = EXTENDED_ATTRIBUTES
    # 构建提示词
    attr_str = "、".join(attributes_list)
    prompt = f"""请判断词语"{word}"可能具有以下哪些属性。只输出符合的属性名称，多个属性用逗号分隔，输出至多15个属性。如果都不太符合，输出"无"。

属性列表：{attr_str}

输出示例：大、坚硬、冷、昂贵
或者：无

现在请判断"{word}"："""
    messages = [
        {"role": "system",
         "content": prompt, }
    ]
    # 调用 AI
    max_token = 500
    response = API_main.ask_ai(ai_model, api_key, messages, max_token)
    raw = response.strip()
    if raw == "无" or not raw:
        selected = []
    else:
        # 分割并清理
        selected = [attr.strip() for attr in raw.replace("，", ",").split(",") if attr.strip()]

    result = {
        "word": word,
        "attributes": selected
    }

    # 保存到 JSON
    if os.path.exists(save_path):
        with open(save_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    else:
        data = []

    # 更新或追加
    found = False
    for i, item in enumerate(data):
        if item.get("word") == word:
            data[i] = result
            found = True
            break
    if not found:
        data.append(result)

    with open(save_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    return result

def memory_split(talk_text,api_key,ai_model):
    '''
    长期记忆的微型拆分机制，用于拆出对话中的事物
    '''
    prompt = f'请从以下对话中提取关键事物，如人名、地点、作品、活动、话题等，直接输出事物，优先输出出现次数最多的事物，最多10个，多个事物间用逗号分隔\n对话内容：<{talk_text}>'
    messages = [
        {"role": "system",
         "content": prompt, }
    ]
    max_token = 300
    try:
        response = API_main.ask_ai(ai_model, api_key, messages, max_token)
    except Exception as e:
        print(f"调用AI失败: {e}")
        return []

    if not response or not isinstance(response, str):
        return []

    raw = response.strip()
    if raw == "无" or not raw:
        return []

    # 分割并清洗
    items = [item.strip() for item in raw.replace("，", ",").split(",") if item.strip()]

    return items

def infinite_memory_save(short_memory_json_path,infinite_memory_save_path,memory_content,things_list,first_time=None,last_time=None):
   '''
   无限记忆的保存机制
   内置AI属性检索与词汇分离
   short_memory_json_path是需要总结的短期记忆文件路径，格式为"XXXXX.json"
   需包含：
   {
   "role":"xxx"
   "content":"(对话文本)"
   "time":"(时间戳)"
   "frequency"(频率)
   }

   memory_content为已经总结好的长期记忆
   things为这段记忆中包含的事物

   first_time / last_time 可选参数：若调用方已提前读取，直接传入可跳过重新读文件（避免文件已清空导致的错误）
   '''
   # 1. 若未传入时间戳，则从短期记忆JSON文件中读取
   if first_time is None or last_time is None:
       try:
           with open(short_memory_json_path, 'r', encoding='utf-8') as f:
               short_memory = json.load(f)
       except (FileNotFoundError, json.JSONDecodeError):
           raise ValueError(f"无法读取或解析短期记忆文件: {short_memory_json_path}")

       if not isinstance(short_memory, list) or len(short_memory) == 0:
           raise ValueError("短期记忆文件内容必须为非空列表")

       first_entry = short_memory[0]
       last_entry = short_memory[-1]

       if "time" not in first_entry or "time" not in last_entry:
           raise KeyError("短期记忆记录中缺少 'time' 字段")

       first_time = first_entry["time"]
       last_time = last_entry["time"]

   # 2. 将things_list转换为字符串（逗号分隔）
   if isinstance(things_list, list):
       things_str = ", ".join(str(item) for item in things_list)
   else:
       things_str = str(things_list)

   # 3. 构建新记忆条目
   new_entry = {
       "memory_content": memory_content,
       "things": things_str,
       "first_time": first_time,
       "last_time": last_time,
       "last_called": int(time.time()),  # 当前时间戳
       "frequency": 20
   }

   # 4. 保存到无限记忆文件（追加模式，文件内容为JSON数组）
   if os.path.exists(infinite_memory_save_path):
       try:
           with open(infinite_memory_save_path, 'r', encoding='utf-8') as f:
               existing_data = json.load(f)
       except (json.JSONDecodeError, FileNotFoundError):
           existing_data = []
       if not isinstance(existing_data, list):
           existing_data = []
   else:
       existing_data = []

   existing_data.append(new_entry)

   with open(infinite_memory_save_path, 'w', encoding='utf-8') as f:
       json.dump(existing_data, f, ensure_ascii=False, indent=2)

   return True

def infinite_memory_save_use(short_memory_json_path,infinite_memory_save_path,attribute_save_path,ai_name,user_name,api_key,ai_model):
    '''
    无限记忆的一键使用
    参数：
    short_memory_json_path : 要总结的记忆路径，需json文件且需要存在role（对话角色）、content（具体对话句子）、time（秒级时间戳）
    infinite_memory_save_path:长期记忆的保存路径
    attribute_save_path : 事物属性保存路径，建议放在与记忆同目录下
    ai_name : 虚拟人物的名字
    ai_model : LLM名称，Deepseek、zhipu、Qwen三选一
    api_key : API密钥，支持Deepseek、zhipu、Qwen

    '''
    # ★ 竞态修复：原子性重命名 sum 文件，主线程后续写入会创建新文件，不会污染本次总结
    temp_path = short_memory_json_path + '.bak'
    if os.path.exists(short_memory_json_path):
        try:
            os.replace(short_memory_json_path, temp_path)
        except Exception as e:
            print(f'[总结] 重命名文件失败: {e}')
            return False
        # 从重命名后的临时文件读取并总结
        talk_text, line_number = memory_sort(temp_path)
        # 提取时间戳（从临时文件读取，此时原文件已被重命名）
        first_time_val, last_time_val = None, None
        try:
            with open(temp_path, 'r', encoding='utf-8') as f:
                _tmp = json.load(f)
            if isinstance(_tmp, list) and len(_tmp) > 0:
                first_time_val = _tmp[0].get("time")
                last_time_val = _tmp[-1].get("time")
        except Exception:
            pass
        # 处理完后删除临时文件（已总结的内容不需要保留）
        try:
            os.remove(temp_path)
        except Exception:
            pass
    else:
        print('[总结] 短期记忆文件不存在，跳过')
        return False

    if talk_text != '':
        memory_content = memory_sum(talk_text, line_number, ai_name, user_name,api_key, ai_model,infinite_memory_save_path)
        things_list = memory_split(talk_text, api_key, ai_model)
        if things_list != []:
            for i in things_list:
                attributes = get_attributes_of_word(i, attribute_save_path, api_key, ai_model, attributes_list=None)
        infinite_memory_save(short_memory_json_path, infinite_memory_save_path, memory_content, things_list,
                             first_time=first_time_val, last_time=last_time_val)
        return True
    else:
        print('无记忆')
        return False

def memory_decay_check(infinite_memory_save_path):
    '''
    记忆衰减检查（异步，每次服务启动时运行一次）

    根据每条无限记忆的 last_called 与当前时间之差，对 frequency 进行衰减：
      - 20分钟 < 差值 < 60分钟  →  frequency - 5
      - 差值 > 24小时            →  frequency - 3
      - 差值 > 15天              →  frequency - 1（与上一条独立叠加，共 -4）

    若 last_called 字段缺失，兜底使用 last_time（记忆创建时间）。
    衰减后 frequency 可以为负数，由调用方决定是否清理。
    '''
    if not os.path.exists(infinite_memory_save_path):
        print('[记忆衰减] 无限记忆文件不存在，跳过')
        return

    try:
        with open(infinite_memory_save_path, 'r', encoding='utf-8') as f:
            memories = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f'[记忆衰减] 读取文件失败: {e}')
        return

    if not isinstance(memories, list) or len(memories) == 0:
        print('[记忆衰减] 无记忆条目，跳过')
        return

    now = int(time.time())
    changed = False

    for entry in memories:
        # 优先取 last_called，若缺失则用 last_time 兜底
        last_called = entry.get('last_called') or entry.get('last_time')
        if last_called is None:
            continue

        diff = now - last_called  # 单位：秒
        current_freq = entry.get('frequency', 0)

        # frequency 已经是 1 时不再衰减
        if current_freq <= 1:
            continue

        decay = 0
        if 20 * 60 < diff < 60 * 60:
            decay -= 3                    # 20~60分钟未被调用
        if 60 * 60<=diff <= 15 * 24 * 3600:
            decay -= 2                    # 超过1小时未被调用
        if diff > 15 * 24 * 3600:
            decay -= 1                    # 超过15天未被调用（在-2基础上再叠加-1，共-3）

        if decay != 0:
            # 衰减后最低保留 1，不会降到 0 或负数
            entry['frequency'] = max(1, current_freq + decay)
            changed = True

    if changed:
        with open(infinite_memory_save_path, 'w', encoding='utf-8') as f:
            json.dump(memories, f, ensure_ascii=False, indent=2)
        print(f'[记忆衰减] 检查完成，共处理 {len(memories)} 条记忆，已写回')
    else:
        print(f'[记忆衰减] 检查完成，共 {len(memories)} 条记忆，无衰减发生')


def infinite_memory_load_time_subjective(user_words, short_memory_all_json_path, num):
    '''
    无限记忆的检索机制，获得时间戳，主观版
    short_memory_all_json_path: 完整版短期记忆路径
    num: 实际需要调用的时间戳个数（最大5，若大于5则取5）
    若无匹配的记忆句子，对应位置返回 None
    返回: (time1, time2, time3, time4, time5) 元组，前 min(num,5) 个为相似度最高的时间戳，
          剩余位置为 None
    '''
    # 限制 num 最大为 5
    if num > 5:
        num = 5

    if not os.path.exists(short_memory_all_json_path):
        return (None, None, None, None, None)

    try:
        with open(short_memory_all_json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            if not isinstance(data, list):
                return (None, None, None, None, None)
    except (json.JSONDecodeError, FileNotFoundError):
        return (None, None, None, None, None)

    if not data:
        return (None, None, None, None, None)

    scores = []
    for record in data:
        content = record.get("content", "")
        if not isinstance(content, str):
            continue
        sim = SequenceMatcher(None, user_words, content).ratio()
        t = record.get("time")
        if t is not None:
            scores.append((sim, t))

    # 按相似度降序排序
    scores.sort(key=lambda x: x[0], reverse=True)
    # 取前 num 条时间戳
    top_times = [t for _, t in scores[:num]]

    # 补全到 5 个（不足的补 None）
    while len(top_times) < 5:
        top_times.append(None)

    return (top_times[0], top_times[1], top_times[2], top_times[3], top_times[4])

def infinite_memory_load_subjective(timetime1,timetime2,timetime3,timetime4,timetime5,infinite_memory_save_path,exclude_indices=None):
    '''

    :param timetime1~5: 最合适的前5个文本的时间戳
    :param infinite_memory_save_path:无限记忆路径
    :return:获得的无限记忆拼接文本和一共调用了几句
    无限记忆格式：
    new_entry = {
       "memory_content": memory_content,
       "things": things_str,
       "first_time": first_time,
       "last_time": last_time,
       "last_called": int(time.time()),  # 当前时间戳
       "frequency": 20
   }
   预加功能：给检索到的无限记忆frequency加一
    '''
    # 检查文件是否存在
    if not os.path.exists(infinite_memory_save_path):
        return "", 0

    # 读取无限记忆
    try:
        with open(infinite_memory_save_path, 'r', encoding='utf-8') as f:
            memories = json.load(f)
            if not isinstance(memories, list):
                return "", 0
    except (json.JSONDecodeError, FileNotFoundError):
        return "", 0

    if not memories:
        return "", 0

    if exclude_indices is None:
        exclude_indices = set()

    # 收集所有时间戳（按优先级顺序，跳过 None）
    timestamps = []
    for ts in (timetime1, timetime2, timetime3, timetime4, timetime5):
        if ts is not None:
            timestamps.append(ts)

    # 记录已经选过的记忆索引（去重）
    selected_indices = set()
    selected_contents = []

    for ts in timestamps:
        # 按顺序遍历记忆列表，找到第一个满足时间范围且未选过的记忆
        for idx, mem in enumerate(memories):
            if idx in selected_indices or idx in exclude_indices:
                continue
            # 检查必要字段是否存在
            time_first = mem.get("first_time")
            time_last = mem.get("last_time")
            if time_first is None or time_last is None:
                continue
            # 判断时间戳是否在区间内（包含端点）
            if time_first <= ts <= time_last:
                content = mem.get("memory_content", "").strip()
                if content:
                    selected_indices.add(idx)
                    selected_contents.append(content)
                    break
                    # 找到一条后，结束当前时间戳的查找，继续下一个时间戳
            # 给选中的记忆 frequency 加一（最高频那条不加），并更新 last_called
    if selected_indices:
        max_freq_idx = max(selected_indices, key=lambda i: memories[i].get("frequency", 0))
        current_time = int(time.time())
        for idx in selected_indices:
            if idx != max_freq_idx:
                memories[idx]["frequency"] = memories[idx].get("frequency", 0) + 1
            memories[idx]["last_called"] = current_time

        with open(infinite_memory_save_path, 'w', encoding='utf-8') as f:
            json.dump(memories, f, ensure_ascii=False, indent=2)
    # 拼接结果
    content_all = "\n".join(selected_contents)
    num = len(selected_contents)
    return content_all, num

def infinite_memory_load_objective(user_word,infinite_memory_save_path,num,exclude_indices=None):
    '''
    无限记忆的检索机制，客观版
    user_word:用户句子
    infinite_memory_save_path:无限记忆路径
    num:需要的条数
    无限记忆格式：
    new_entry = {
       "memory_content": memory_content,
       "things": things_str,
       "first_time": first_time,
       "last_time": last_time,
       "last_called": int(time.time()),  # 当前时间戳
       "frequency": 20
   }
   预计功能：
   1.通过判断用户句子与每条无限记忆的things的重叠度来选取最高的前num项
   2.若重叠度低于3则不选（一个相同的字等于一个重叠度）
   3.拼接文本
   4.返回拼接好的文本和一共调用的记忆条数
   5.给调用的无限记忆frequency加一
    '''
    if num > 5:
        num = 5
    # 1. 读取无限记忆文件
    if not os.path.exists(infinite_memory_save_path):
        return "", 0
    try:
        with open(infinite_memory_save_path, 'r', encoding='utf-8') as f:
            memories = json.load(f)
            if not isinstance(memories, list):
                return "", 0
    except (json.JSONDecodeError, FileNotFoundError):
        return "", 0

    if not memories:
        return "", 0

    if exclude_indices is None:
        exclude_indices = set()

    # 辅助函数：统计用户句子中某个词汇出现的次数（可累加，子串计数）
    def count_word_in_sentence(sentence, word):
        cnt = 0
        start = 0
        while True:
            idx = sentence.find(word, start)
            if idx == -1:
                break
            cnt += 1
            start = idx + 1  # 允许重叠？题目未禁止，按非重叠简单处理
        return cnt

    # 2. 对每条记忆计算重叠度（累加用户句子中各事物的出现总次数）
    scores = []  # (index, total_match_count)
    for idx, mem in enumerate(memories):
        if idx in exclude_indices:
            continue
        things_str = mem.get("things", "")
        if not isinstance(things_str, str):
            continue
        # 解析事物列表，以逗号分隔，去除两边空格
        things = [t.strip() for t in things_str.split(",") if t.strip()]
        total = 0
        for thing in things:
            total += count_word_in_sentence(user_word, thing)
        if total >= 1:  # 只选取重叠度≥1的（只要提到任意一个事物即可触发）
            scores.append((idx, total))

    # 按重叠度降序排序
    scores.sort(key=lambda x: x[1], reverse=True)
    selected_indices = [idx for idx, _ in scores[:num]]

    if not selected_indices:
        return "", 0

    # 3. 拼接选中的记忆内容（按原序？为保持可预测性，按重叠度从高到低拼接）
    selected_contents = []
    for idx in selected_indices:
        content = memories[idx].get("memory_content", "")
        if content:
            selected_contents.append(content)

    content_all = "\n".join(selected_contents)
    selected_num = len(selected_contents)

    # 4. 给选中的记忆的 frequency 加一（最高频那条不加），并写回文件
    current_time = int(time.time())
    max_freq_idx = max(selected_indices, key=lambda i: memories[i].get("frequency", 0))
    for idx in selected_indices:
        if idx != max_freq_idx:
            memories[idx]["frequency"] = memories[idx].get("frequency", 0) + 1
        memories[idx]["last_called"] = current_time

    with open(infinite_memory_save_path, 'w', encoding='utf-8') as f:
        json.dump(memories, f, ensure_ascii=False, indent=2)


    return content_all, selected_num

def infinite_memory_load_attribute(user_word, infinite_memory_save_path, attribute_save_path, num, exclude_indices=None):
    '''
    无限记忆的属性桥接检索机制
    当客观检索（事物词匹配）未能命中时，通过事物属性与用户消息的交集来补充检索，
    弥补"用户换了说法但语义相关"的鸿沟。

    策略：
    1. 读取无限记忆和属性数据
    2. 对每条记忆，解析其 things 字段
    3. 若事物词已出现在用户消息中 → 跳过（客观检索已覆盖）
    4. 查找每个事物的属性列表
    5. 统计属性词在用户消息中出现的个数（属性交集度）
    6. 属性交集度 >= 2 的记忆纳入候选
    7. 按交集度排序，取前 num 条
    8. 更新选中记忆的 frequency 和 last_called
    9. 返回拼接文本和条数

    参数:
        user_word: 用户句子
        infinite_memory_save_path: 无限记忆路径
        attribute_save_path: 事物属性保存路径
        num: 需要的条数（最大5）
    返回:
        (拼接后的记忆文本, 检索条数)
    '''
    if num <= 0:
        return "", 0
    if num > 5:
        num = 5

    # 1. 读取无限记忆
    if not os.path.exists(infinite_memory_save_path):
        return "", 0
    try:
        with open(infinite_memory_save_path, 'r', encoding='utf-8') as f:
            memories = json.load(f)
            if not isinstance(memories, list):
                return "", 0
    except (json.JSONDecodeError, FileNotFoundError):
        return "", 0
    if not memories:
        return "", 0

    if exclude_indices is None:
        exclude_indices = set()

    # 2. 读取属性数据，构建查找表
    if not os.path.exists(attribute_save_path):
        return "", 0
    try:
        with open(attribute_save_path, 'r', encoding='utf-8') as f:
            attr_data = json.load(f)
            if not isinstance(attr_data, list):
                return "", 0
    except (json.JSONDecodeError, FileNotFoundError):
        return "", 0

    attr_lookup = {}
    for item in attr_data:
        word = item.get("word", "")
        attrs = item.get("attributes", [])
        if word and isinstance(attrs, list):
            attr_lookup[word] = attrs

    # 3. 对每条记忆计算属性交集度
    scores = []  # (index, overlap_count)
    for idx, mem in enumerate(memories):
        if idx in exclude_indices:
            continue
        things_str = mem.get("things", "")
        if not isinstance(things_str, str) or not things_str.strip():
            continue
        things = [t.strip() for t in things_str.split(",") if t.strip()]

        # 若事物词已出现在用户消息中 → 跳过（客观检索已覆盖）
        thing_already_matched = False
        for thing in things:
            if thing in user_word:
                thing_already_matched = True
                break
        if thing_already_matched:
            continue

        # 收集该记忆所有事物的属性
        all_attrs = set()
        for thing in things:
            if thing in attr_lookup:
                all_attrs.update(attr_lookup[thing])

        if not all_attrs:
            continue

        # 统计属性词在用户消息中出现的个数
        overlap = 0
        for attr in all_attrs:
            if attr in user_word:
                overlap += 1

        if overlap >= 2:
            scores.append((idx, overlap))

    if not scores:
        return "", 0

    # 4. 按交集度排序，取前 num 条
    scores.sort(key=lambda x: x[1], reverse=True)
    selected_indices = [idx for idx, _ in scores[:num]]

    # 5. 拼接内容
    selected_contents = []
    for idx in selected_indices:
        content = memories[idx].get("memory_content", "").strip()
        if content:
            selected_contents.append(content)

    if not selected_contents:
        return "", 0

    # 6. 更新选中记忆的 frequency（最高频那条不加）和 last_called
    current_time = int(time.time())
    max_freq_idx = max(selected_indices, key=lambda i: memories[i].get("frequency", 0))
    for idx in selected_indices:
        if idx != max_freq_idx:
            memories[idx]["frequency"] = memories[idx].get("frequency", 0) + 1
        memories[idx]["last_called"] = current_time

    with open(infinite_memory_save_path, 'w', encoding='utf-8') as f:
        json.dump(memories, f, ensure_ascii=False, indent=2)

    content_all = "\n".join(selected_contents)
    return content_all, len(selected_contents)

def infinite_memory_load_complete(infinite_memory_save_path, num_over, exclude_indices=None):
    '''
    无限记忆的补全检索，用于在主客观调用后补充剩余条数
    :param infinite_memory_save_path: 长期记忆路径
    :param num_over: 需要补充的条数
    :return: 拼接后的记忆文本（换行分隔）
    '''
    if num_over <= 0:
        return ""

    if not os.path.exists(infinite_memory_save_path):
        return ""

    try:
        with open(infinite_memory_save_path, 'r', encoding='utf-8') as f:
            memories = json.load(f)
            if not isinstance(memories, list):
                return ""
    except (json.JSONDecodeError, FileNotFoundError):
        return ""

    if not memories:
        return ""

    if exclude_indices is None:
        exclude_indices = set()

    current_time = int(time.time())
    # 候选列表：(索引, frequency, 内容)
    candidates = []
    for idx, mem in enumerate(memories):
        if idx in exclude_indices:
            continue
        last_called = mem.get("last_called")
        # 若 last_called 缺失或满足超过5秒未调用
        if last_called is None or (current_time - last_called > 5):
            freq = mem.get("frequency", 0)
            content = mem.get("memory_content", "").strip()
            if content:
                candidates.append((idx, freq, content))

    # 按 frequency 降序排序
    candidates.sort(key=lambda x: x[1], reverse=True)
    selected = candidates[:num_over]  # 取前 num_over 条

    if not selected:
        return ""

    selected_indices = [item[0] for item in selected]
    selected_contents = [item[2] for item in selected]

    # 更新选中记忆的 frequency（最高频那条不加）和 last_called
    for idx in selected_indices:
        if idx != max(selected_indices, key=lambda i: memories[i].get("frequency", 0)):
            memories[idx]["frequency"] = memories[idx].get("frequency", 0) + 1
        memories[idx]["last_called"] = current_time

    # 写回文件
    with open(infinite_memory_save_path, 'w', encoding='utf-8') as f:
        json.dump(memories, f, ensure_ascii=False, indent=2)

    return "\n".join(selected_contents)

def infinite_memory_load_recent(infinite_memory_save_path, max_num):
    '''
    近期记忆优先检索：获取近1小时内总结的长期记忆

    :param infinite_memory_save_path: 长期记忆路径
    :param max_num: 最多调用条数
    :return: (拼接文本, 实际条数, 选中索引集合)
    '''
    if max_num <= 0:
        return "", 0, set()

    if not os.path.exists(infinite_memory_save_path):
        return "", 0, set()

    try:
        with open(infinite_memory_save_path, 'r', encoding='utf-8') as f:
            memories = json.load(f)
            if not isinstance(memories, list):
                return "", 0, set()
    except (json.JSONDecodeError, FileNotFoundError):
        return "", 0, set()

    if not memories:
        return "", 0, set()

    now = int(time.time())
    one_hour_ago = now - 3600

    # 筛选近1小时内的记忆（按 last_time 判断）
    candidates = []
    for idx, mem in enumerate(memories):
        last_time = mem.get("last_time")
        if last_time is not None and last_time >= one_hour_ago:
            content = mem.get("memory_content", "").strip()
            if content:
                candidates.append((idx, last_time, content))

    # 按 last_time 降序（最新的在前）
    candidates.sort(key=lambda x: x[1], reverse=True)

    # 取前 max_num 条
    selected = candidates[:max_num]

    if not selected:
        return "", 0, set()

    selected_indices = set(item[0] for item in selected)
    selected_contents = [item[2] for item in selected]

    # 更新 frequency（最高频那条不加）和 last_called
    max_freq_idx = max(selected_indices, key=lambda i: memories[i].get("frequency", 0))
    for idx in selected_indices:
        if idx != max_freq_idx:
            memories[idx]["frequency"] = memories[idx].get("frequency", 0) + 1
        memories[idx]["last_called"] = now

    with open(infinite_memory_save_path, 'w', encoding='utf-8') as f:
        json.dump(memories, f, ensure_ascii=False, indent=2)

    content_all = "\n".join(selected_contents)
    return content_all, len(selected_contents), selected_indices

def count_recent_memories(infinite_memory_save_path):
    '''
    统计近1小时内总结的长期记忆条数（只读，不修改文件）
    '''
    if not os.path.exists(infinite_memory_save_path):
        return 0

    try:
        with open(infinite_memory_save_path, 'r', encoding='utf-8') as f:
            memories = json.load(f)
            if not isinstance(memories, list):
                return 0
    except (json.JSONDecodeError, FileNotFoundError):
        return 0

    if not memories:
        return 0

    now = int(time.time())
    one_hour_ago = now - 3600
    count = 0
    for mem in memories:
        last_time = mem.get("last_time")
        if last_time is not None and last_time >= one_hour_ago:
            content = mem.get("memory_content", "").strip()
            if content:
                count += 1
    return count

def infinite_memory_load_detail(infinite_memory_save_path, short_memory_all_path):
    '''
    细节回忆：在所有总结记忆中找 frequency 最高的，根据时间戳找回原始对话文本

    :param infinite_memory_save_path: 长期记忆路径
    :param short_memory_all_path: 短期记忆完整版路径
    :return: "以下是记忆细节：\n..." 或 ""
    '''
    if not os.path.exists(infinite_memory_save_path):
        return ""

    try:
        with open(infinite_memory_save_path, 'r', encoding='utf-8') as f:
            memories = json.load(f)
            if not isinstance(memories, list) or not memories:
                return ""
    except (json.JSONDecodeError, FileNotFoundError):
        return ""

    # 找 frequency 最高的记忆
    best = None
    best_freq = -1
    for mem in memories:
        freq = mem.get("frequency", 0)
        if freq > best_freq:
            best_freq = freq
            best = mem

    if best is None or best_freq <= 0:
        return ""

    first_time = best.get("first_time")
    last_time = best.get("last_time")
    if first_time is None or last_time is None:
        return ""

    # 读取原始对话
    if not os.path.exists(short_memory_all_path):
        return ""

    try:
        with open(short_memory_all_path, 'r', encoding='utf-8') as f:
            all_dialogues = json.load(f)
            if not isinstance(all_dialogues, list):
                return ""
    except (json.JSONDecodeError, FileNotFoundError):
        return ""

    # 筛选时间范围内的对话
    matched = []
    for entry in all_dialogues:
        t = entry.get("time")
        if t is not None and first_time <= t <= last_time:
            role = entry.get("role", "")
            content = entry.get("content", "")
            if content.strip():
                matched.append({"role": role, "content": content, "time": t})

    if not matched:
        return ""

    # 格式化输出
    lines = []
    for entry in matched:
        try:
            dt = datetime.fromtimestamp(entry["time"])
            time_str = dt.strftime("%Y-%m-%d %H:%M")
        except:
            time_str = ""
        lines.append(f"({entry['role']}): {entry['content']} ({time_str})")

    detail_text = "\n".join(lines)
    return f"以下是记忆细节：\n{detail_text}"

#==========以下为短期记忆保存机制==========
def short_memory_all_save(role,content,short_memory_all_json_path):
    '''
    短期记忆的保存机制·其一·完整版
    用于保存完整的对话数据，无限储存，作为日志和具体记忆追加检索
    role:说话的对象
    content:说的句子
    将保存为:
    {
    role:'XXX'
    content:'XXXXXXXXXX'
    time:(当前时间戳,秒级)
    }
    '''
    new_entry = {
        "role": role,
        "content": content,
        "time": int(time.time())
    }

    # 读取现有数据
    if os.path.exists(short_memory_all_json_path):
        try:
            with open(short_memory_all_json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if not isinstance(data, list):
                    data = []
        except (json.JSONDecodeError, FileNotFoundError):
            data = []
    else:
        data = []

    # 追加新记录
    data.append(new_entry)

    # 写回文件
    with open(short_memory_all_json_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    return True

def short_memory_sum_save(name,content,short_memory_sum_json_path):
    '''
    短期记忆的保存机制·其二·用于总结版
    用于保存需要总结的部分对话数据，作为无限记忆的总结内容
    name:说话的对象
    content:说的句子
    将保存为:
    {
    name:'XXX'
    content:'XXXXXXXXXX'
    time:(当前时间戳,秒级)
    }
    '''
    new_entry = {
        "name": name,
        "content": content,
        "time": int(time.time())
    }

    # 读取现有数据
    if os.path.exists(short_memory_sum_json_path):
        try:
            with open(short_memory_sum_json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if not isinstance(data, list):
                    data = []
        except (json.JSONDecodeError, FileNotFoundError):
            data = []
    else:
        data = []

    # 追加新记录
    data.append(new_entry)

    # 写回文件
    with open(short_memory_sum_json_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    return True

def short_memory_dialogue_save(name, content, short_memory_dialogue_json_path):
    '''
    短期记忆的保存机制·其三·对话版
    用于保存最近15条的对话数据，作为连贯性记忆提示词投喂给AI
    name:说话的对象
    content:说的句子
    将保存为:
    {
    name:'XXX'
    content:'XXXXXXXXXX'
    time:(当前时间戳,秒级)
    }
    '''
    MAX_ENTRIES = 15  # 内置变量，最多保留15条

    new_entry = {
        "name": name,
        "content": content,
        "time": int(time.time())
    }

    # 读取现有数据
    if os.path.exists(short_memory_dialogue_json_path):
        try:
            with open(short_memory_dialogue_json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if not isinstance(data, list):
                    data = []
        except (json.JSONDecodeError, FileNotFoundError):
            data = []
    else:
        data = []

    # 追加新记录
    data.append(new_entry)

    # 只保留最近的 MAX_ENTRIES 条
    if len(data) > MAX_ENTRIES:
        data = data[-MAX_ENTRIES:]

    # 写回文件
    with open(short_memory_dialogue_json_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    return True