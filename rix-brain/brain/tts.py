"""edge-tts 语音生成：把文字合成 mp3 写进桥接语音库，供 qq_send_voice 发送。

安全边界：只写到 config.json 的 tts.output_dir（默认 qq-bridge 的 audio/ 语音库），
且固定用同一个文件名（tts_latest.mp3）覆盖写入 —— AI拿到 name 后调 qq_send_voice(name)，
桥接侧有自己的一套「AI 只能取语音库内文件」的白名单校验。
"""
import asyncio
import os
import threading

import edge_tts

import config

_lock = threading.Lock()

DEFAULT_VOICE = "zh-CN-XiaoxiaoNeural"
DEFAULT_OUT = r"C:/Users/Clover/Documents/deepseek-harness/default-workspace/qq-bridge-main/audio"
DEFAULT_NAME = "tts_latest.mp3"


def _cfg():
    c = config.load_config()
    return c.get("tts", {}) or {}


async def _synth(text, voice, path, rate=None, pitch=None, volume=None):
    kwargs = {}
    if rate:
        kwargs["rate"] = rate
    if pitch:
        kwargs["pitch"] = pitch
    if volume:
        kwargs["volume"] = volume
    communicate = edge_tts.Communicate(text, voice, **kwargs)
    await communicate.save(path)


def _run_async(coro):
    """在独立线程里跑 asyncio.run：调用方可能已经在事件循环里（MCP 工具就是这样），
    直接 asyncio.run 会报「cannot be called from a running event loop」。"""
    box = {}

    def _runner():
        try:
            box["ret"] = asyncio.run(coro)
        except BaseException as e:
            box["err"] = e

    t = threading.Thread(target=_runner, daemon=True, name="tts-synth")
    t.start()
    t.join()
    if "err" in box:
        raise box["err"]
    return box["ret"]


def _local_tts(text, voice):
    """调用本地 CosyVoice2 HTTP 服务，返回 (ok, wav_bytes, 实际音色, 参考标记) 或 (False, errmsg, '', '')。"""
    import requests  # 延迟导入，避免拖慢 MCP 启动
    cfg = _cfg()
    url = str(cfg.get("local_server") or "http://127.0.0.1:8765/tts")
    try:
        r = requests.post(url, json={"text": text, "voice": voice}, timeout=300)
        if r.status_code != 200:
            return False, f"local server returned {r.status_code}", "", ""
        data = r.content
        if not data or len(data) < 200:
            return False, "local server returned empty audio", "", ""
        # 服务端会按语言自动选嗓，用响应头回报实际用了哪个
        return True, data, r.headers.get("X-Voice", voice), r.headers.get("X-Ref", "")
    except Exception as e:
        return False, str(e)[:150], "", ""


def _wav_to_mp3(wav_path, mp3_path):
    """用 imageio-ffmpeg 自带的 ffmpeg 把 wav 转成 mp3（放到语音库）。"""
    import subprocess
    import imageio_ffmpeg
    ff = imageio_ffmpeg.get_ffmpeg_exe()
    subprocess.run([ff, "-y", "-loglevel", "error", "-i", wav_path, "-codec:a", "libmp3lame",
                    "-b:a", "128k", mp3_path], check=True, timeout=60, capture_output=True)


def _finalize(tmp_audio_path, out_path, is_wav):
    """把临时音频转成 mp3 落位到语音库（wav 先转码），返回文件字节数。"""
    import os
    if is_wav:
        mp3_tmp = out_path + ".conv.mp3"
        try:
            _wav_to_mp3(tmp_audio_path, mp3_tmp)
        finally:
            try:
                if os.path.exists(tmp_audio_path):
                    os.remove(tmp_audio_path)
            except Exception:
                pass
        tmp_audio_path = mp3_tmp
    try:
        if os.path.exists(out_path):
            os.remove(out_path)
    except Exception:
        pass
    os.replace(tmp_audio_path, out_path)
    return os.path.getsize(out_path)


def _log_fallback(reason, voice):
    """降级到 edge-tts 时留痕：写日志 + 顺手查一次本地 /health，方便定位。"""
    try:
        import time as _t
        cfg = _cfg()
        health_txt = ""
        try:
            import requests
            base = str(cfg.get("local_server") or "http://127.0.0.1:8765/tts").rsplit("/", 1)[0]
            r = requests.get(base + "/health", timeout=8)
            health_txt = r.text[:200]
        except Exception as e:
            health_txt = "health 查询失败: %s" % str(e)[:80]
        line = "%s 降级到 edge-tts（%s）| 本地原因: %s | /health: %s\n" % (
            _t.strftime("%Y-%m-%d %H:%M:%S"), voice, reason, health_txt)
        with open(os.path.join(config.data_dir(), "tts_fallback.log"), "a", encoding="utf-8") as f:
            f.write(line)
    except Exception:
        pass


def send_voice(name, key, token, label="", verify=True):
    """把语音库里刚合成的文件直接发给 QQ（2026-11-01：合成完自动发，不再单独调发送工具）。

    走桥接的 /api/socialV2/send-voice，必须带会话令牌；桥接侧还会校验文件名确实在语音库内、
    并（verify=true 时）回读 get_msg 确认 record 段落地。
    返回 {ok, verified, ...} 或 {ok: false, error}。
    """
    import requests
    cfg = _cfg()
    base = str(cfg.get("bridge_url") or "http://127.0.0.1:3100").rstrip("/")
    # 桥接控制台前面有一道统一鉴权（x-console-token），agent token 只用来判"能不能动这个会话"，
    # 两个都要带，否则会在业务分支之前就被 401 拦掉。
    console_token = ""
    tok_file = str(cfg.get("bridge_token_file") or "")
    if tok_file and os.path.exists(tok_file):
        try:
            with open(tok_file, "r", encoding="utf-8") as f:
                console_token = f.read().strip()
        except Exception:
            console_token = ""
    headers = {"x-agent-token": token}
    if console_token:
        headers["x-console-token"] = console_token
    try:
        r = requests.post(
            base + "/api/socialV2/send-voice",
            json={
                "key": key,
                "voice": name,
                "label": label or "",
                "verify": verify is not False,
                "readback": False,
                "token": token,
            },
            headers=headers,
            timeout=300,
        )
        try:
            data = r.json()
        except Exception:
            data = {"raw": (r.text or "")[:300]}
        if r.status_code != 200:
            return {"ok": False, "status": r.status_code, "error": str(data)[:300]}
        return {"ok": True, "res": data}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


def speak(text, voice=""):
    """合成语音并写入语音库，返回 {ok, name, bytes, voice, backend} 或 {ok: false, error}。

    backend=auto 时：优先本地 CosyVoice2 服务（cosyvoice），失败重试一次，
    仍失败才回退 edge-tts —— 并在返回值里带 fallback_reason、写 tts_fallback.log，
    避免「悄悄变成微软音色」只能靠耳朵发现。
    """
    cfg = _cfg()
    backend = str(cfg.get("backend") or "auto")
    edge_voice = str(cfg.get("voice") or DEFAULT_VOICE)
    arg_voice = str(voice or "").strip()
    # 音色优先级：调用方显式传入 > 配置里的本地音色 > 留空交给服务端自动判断。
    # 服务端会自动按语言选嗓：含假名=日语→atri，其余→syq。
    local_voice = arg_voice or str(cfg.get("local_voice") or "").strip()
    out_dir = str(cfg.get("output_dir") or DEFAULT_OUT)
    fname = str(cfg.get("filename") or DEFAULT_NAME)
    text = (text or "").strip()
    if not text:
        return {"ok": False, "error": "empty text"}
    if len(text) > 500:
        text = text[:500]
    try:
        os.makedirs(out_dir, exist_ok=True)
    except Exception as e:
        return {"ok": False, "error": f"mkdir failed: {e}"}

    out_path = os.path.join(out_dir, fname)
    fallback_reason = ""
    with _lock:
        tmp = out_path + ".tmp"
        # 1) 本地 CosyVoice2 服务（auto/local）：失败重试一次（CUDA 抖动/瞬时故障）
        if backend in ("auto", "local"):
            for attempt in (1, 2):
                okwav, wav, used_voice, ref = _local_tts(text, local_voice)
                if okwav:
                    try:
                        with open(tmp, "wb") as f:
                            f.write(wav)
                        size = _finalize(tmp, out_path, is_wav=True)
                        return {"ok": True, "name": fname, "bytes": size,
                                "voice": used_voice or local_voice, "ref": ref, "backend": "cosyvoice"}
                    except Exception as e:
                        fallback_reason = "本地音频落盘失败: %s" % str(e)[:80]
                        try:
                            if os.path.exists(tmp):
                                os.remove(tmp)
                        except Exception:
                            pass
                        break
                fallback_reason = wav          # _local_tts 失败时第二个返回值是错误信息
                if attempt == 1:
                    import time as _t
                    _t.sleep(1.5)              # 给服务端一点恢复时间再试
            _log_fallback(fallback_reason, edge_voice)
        # 2) edge-tts（backend=edge 或本地失败回退）
        try:
            _run_async(_synth(text, edge_voice, tmp,
                              rate=cfg.get("rate"), pitch=cfg.get("pitch"), volume=cfg.get("volume")))
            size = _finalize(tmp, out_path, is_wav=False)
        except Exception as e:
            for p in (tmp,):
                try:
                    if os.path.exists(p):
                        os.remove(p)
                except Exception:
                    pass
            return {"ok": False, "error": str(e)[:200]}
    ret = {"ok": True, "name": fname, "bytes": size, "voice": edge_voice, "backend": "edge"}
    if fallback_reason:
        ret["fallback_reason"] = fallback_reason
    return ret