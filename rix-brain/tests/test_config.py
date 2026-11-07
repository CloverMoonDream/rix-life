"""config.py：只测不联网的部分。

``deepseek_complete`` 真的会发 HTTP 请求，这里一律用假的 urlopen，
既验证重试逻辑，也保证测试离线。
"""
import io
import json
import os
import tempfile
import urllib.error
from unittest import mock

import _base  # noqa: F401  先把 code/ 加进 sys.path
import config

from _base import IsolatedTestCase


def _resp(payload):
    class FakeResp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    return FakeResp(json.dumps(payload).encode("utf-8"))


class DeepseekCompleteTests(IsolatedTestCase):
    def test_raises_when_api_key_missing(self):
        with mock.patch.object(config, "load_config", return_value={"deepseek": {"api_key": ""}}):
            with self.assertRaises(RuntimeError) as ctx:
                config.deepseek_complete([{"role": "user", "content": "hi"}])
        self.assertIn("api_key", str(ctx.exception))

    def test_returns_content(self):
        body = {"choices": [{"message": {"content": "回答"}}]}
        with mock.patch.object(config, "load_config", return_value={"deepseek": {"api_key": "sk-test"}}), \
             mock.patch("urllib.request.urlopen", return_value=_resp(body)):
            self.assertEqual(config.deepseek_complete([{"role": "user", "content": "hi"}]), "回答")

    def test_retries_once_on_empty_content(self):
        calls = {"n": 0}

        def fake_urlopen(*a, **k):
            calls["n"] += 1
            content = "" if calls["n"] == 1 else "第二次有内容"
            return _resp({"choices": [{"message": {"content": content}}]})

        with mock.patch.object(config, "load_config", return_value={"deepseek": {"api_key": "sk-test"}}), \
             mock.patch("urllib.request.urlopen", side_effect=fake_urlopen):
            self.assertEqual(config.deepseek_complete([{"role": "user", "content": "hi"}]), "第二次有内容")
        self.assertEqual(calls["n"], 2)

    def test_returns_empty_when_both_attempts_empty(self):
        body = {"choices": [{"message": {"content": ""}}]}
        with mock.patch.object(config, "load_config", return_value={"deepseek": {"api_key": "sk-test"}}), \
             mock.patch("urllib.request.urlopen", return_value=_resp(body)):
            self.assertEqual(config.deepseek_complete([{"role": "user", "content": "hi"}]), "")

    def test_malformed_response_returns_empty(self):
        with mock.patch.object(config, "load_config", return_value={"deepseek": {"api_key": "sk-test"}}), \
             mock.patch("urllib.request.urlopen", return_value=_resp({"不是": "预期结构"})):
            self.assertEqual(config.deepseek_complete([{"role": "user", "content": "hi"}]), "")

    def test_http_error_propagates(self):
        with mock.patch.object(config, "load_config", return_value={"deepseek": {"api_key": "sk-test"}}), \
             mock.patch("urllib.request.urlopen", side_effect=urllib.error.URLError("连不上")):
            with self.assertRaises(urllib.error.URLError):
                config.deepseek_complete([{"role": "user", "content": "hi"}])


class LoadConfigTests(IsolatedTestCase):
    def test_missing_file_raises(self):
        # 缺陷：文件不存在时直接抛 FileNotFoundError，没有兜底成 {}。
        # record_turn / append_diary / recall 都无条件调用它，
        # 所以项目根下缺 config.json 时这三条入口全坏。
        # 底座把 load_config 替成了固定字典，这里临时撤掉再测。
        missing = os_path_missing()
        with mock.patch.object(config, "CONFIG_PATH", missing), \
             mock.patch.object(config, "load_config", _base._orig_load_config):
            with self.assertRaises(FileNotFoundError):
                config.load_config()

    def test_reads_json(self):
        path = os_path_missing()
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"ai_name": "测试"}, f)
        with mock.patch.object(config, "CONFIG_PATH", path), \
             mock.patch.object(config, "load_config", _base._orig_load_config):
            self.assertEqual(config.load_config(), {"ai_name": "测试"})

    def test_data_dir_uses_ai_name(self):
        # data_dir 由 ai_name 决定，并会顺手把目录建出来。
        # 底座替掉了 data_dir，这里临时撤掉，但把项目根指到临时目录，避免写到仓库里。
        root = tempfile.mkdtemp(prefix="cfgroot-")
        with mock.patch.object(config, "PROJECT_ROOT", root), \
             mock.patch.object(config, "load_config", return_value={"ai_name": "甲"}), \
             mock.patch.object(config, "data_dir", _base._orig_data_dir):
            d = config.data_dir()
        self.assertEqual(d, os.path.join(root, "AI_data", "甲_data"))
        self.assertTrue(os.path.isdir(d))


def os_path_missing():
    import tempfile
    d = tempfile.mkdtemp(prefix="cfg-")
    return os.path.join(d, "不存在.json")
