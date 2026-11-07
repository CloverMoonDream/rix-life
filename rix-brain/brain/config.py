"""rix-brain 配置加载 + DeepSeek 客户端。

说明：
- 记忆服务"自身"的 LLM 调用只有两处：记忆检索的语义重排（rerank）、
  用户情绪的 AI 校准（user_mood.py 每 5 轮一次）。这两处走 config.json 里的
  deepseek.api_key + model（flash）。
- 记忆"总结"（日记/事物提取）按约定走 DSH，由 DSH 调 memory_append_diary 落盘，
  本模块不参与。
"""
import json
import os

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(PROJECT_ROOT, "config.json")

# emotion.py（复用自 mood.py）内部用相对路径 "AI_data/..." 存 mood.json，
# 这里切到项目根，保证数据统一落在 rix-brain/AI_data/ 下。
os.chdir(PROJECT_ROOT)


def load_config():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def data_dir():
    cfg = load_config()
    ai = cfg.get("ai_name", "ai")
    d = os.path.join(PROJECT_ROOT, "AI_data", f"{ai}_data")
    os.makedirs(d, exist_ok=True)
    return d


def deepseek_complete(messages, max_tokens=1200, model=None, thinking=False, temperature=None):
    """调用 DeepSeek chat completions，返回文本；失败抛异常。

    thinking=False（默认）：显式关闭思考。内部工具调用（记忆重排 / 用户情绪校准 /
    日记总结）只要一句话答案，而思考型模型会把 max_tokens 全烧在 reasoning 上、
    content 返回空串——实测 finish_reason=length、reasoning_tokens=max_tokens、
    content 0 字，导致重排静默退化成原顺序、日记总结写不出内容。
    """
    cfg = load_config()
    ds = cfg.get("deepseek", {})
    key = ds.get("api_key", "").strip()
    if not key:
        raise RuntimeError("请在 config.json 填写 deepseek.api_key")
    import urllib.request  # 标准库，不依赖 requests（2026-11-05）

    base = ds.get("base_url", "https://api.deepseek.com").rstrip("/")
    url = base + "/chat/completions"
    model = model or ds.get("model", "deepseek-flash")
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    data = {"model": model, "messages": messages, "max_tokens": int(max_tokens), "stream": False}
    if temperature is not None:
        # 只给重排用 0：MoE 模型在默认温度下同一输入会有细微波动，
        # 20 条基准里有一条卡在边界，一抖就掉出 top5。
        data["temperature"] = float(temperature)
    if not thinking:
        # 两个写法都实测有效（关掉思考后 finish_reason=stop、content 正常返回）
        data["reasoning_effort"] = "none"
        data["thinking"] = {"type": "disabled"}

    def _content(d):
        return ((d.get("choices") or [{}])[0].get("message") or {}).get("content") or ""

    def _call(body):
        req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"),
                                     headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=90) as r:
            return json.loads(r.read().decode("utf-8"))

    d = _call(data)
    out = _content(d)
    if not out.strip():
        # 兜底：内容为空（例如思考吃满预算）→ 放开思考、加倍预算重试一次
        body2 = dict(data)
        body2.pop("thinking", None)
        body2.pop("reasoning_effort", None)
        body2["max_tokens"] = max(2000, int(max_tokens) * 3)
        try:
            d2 = _call(body2)
            out = _content(d2)
        except Exception:
            pass
    return out
