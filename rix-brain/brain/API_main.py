"""兼容 user_mood.py 的 API_main 接口（走 config.json 的 DeepSeek key）。

复用的 user_mood.py 在 detect_mood_ai 里执行 `import API_main` 并调用
`API_main.ask_ai(ai_model, api_key, messages, max_token)`；这里提供同名接口，
参数 ai_name/api_key 忽略，统一走 config.json。
"""
import config


def ask_ai(ai_name, api_key, user_message, max_token):
    try:
        # flash 是推理模型：思考会先消耗 token，user_mood 传的 20 太少，
        # 这里抬到至少 200，确保 content 正文不为空。
        return config.deepseek_complete(user_message, max_tokens=max(200, int(max_token)))
    except Exception:
        return None


def api_check(api_key):
    # 旧 launcher 时代用于验证 key；此处不做强校验，仅占位。
    return "deepseek"
