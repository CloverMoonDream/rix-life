"""测试公共底座。

只做隔离，不改业务逻辑：

1. 把 ``config.data_dir`` 指到 ``tempfile.TemporaryDirectory``，
   所有读写都落在临时目录里，项目目录和真实数据目录一个字节都不动。
2. 把 ``notebook.ROOT`` 指到同一个临时目录。它的默认值是
   ``D:\\AI\\笔记``，那是禁止写入的真实目录。
3. 拦截 ``urllib.request.urlopen``。被测代码里凡是要联网的地方
   （ollama 嵌入、deepseek 补全）都会立刻抛 ``URLError``，
   走各自的降级分支，测试全程离线。
4. ``config.load_config`` 返回一份最小配置。项目根下没有
   ``config.json``，而 ``record_turn`` / ``append_diary`` / ``recall``
   都会无条件去读它；不补这一层，整组测试在第一行就抛
   ``FileNotFoundError``，根本到不了被测逻辑。
5. ``memory._pending_counts_path`` 指到临时目录。原实现用
   ``dirname`` 往上数三层，落在盘符根的 ``state\\`` 下，
   测试不能往那里写。

``config`` 模块在导入时会 ``os.chdir`` 到项目根目录，这里不拦——
那是它自己的副作用，测试进程结束就没了，不写任何文件。
"""
import os
import sys
import tempfile
import unittest
import urllib.error
from unittest import mock

_HERE = os.path.dirname(os.path.abspath(__file__))
_CODE = os.path.normpath(os.path.join(_HERE, "..", "brain"))
# ``python -m unittest discover -s tests`` 把 tests 目录放在 sys.path[0]，
# 被测模块在上一级的 code/ 里，必须显式加进去。
if _CODE not in sys.path:
    sys.path.insert(0, _CODE)

import config  # noqa: E402  必须先改 sys.path

# 记下被替换前的原函数。个别用例要测原始行为（文件缺失时抛异常、
# data_dir 按 ai_name 拼路径），那些用例自己再 patch 回去。
_orig_load_config = config.load_config
_orig_data_dir = config.data_dir


def _offline(*_a, **_k):
    raise urllib.error.URLError("测试环境禁止联网")


# 被测代码只读 memory.short_term_max / frequency_initial / idle_summarize_seconds
# 和 retrieval.top_k / candidate_limit，给齐这些就够了。
_TEST_CONFIG = {
    "ai_name": "测试",
    "memory": {
        "short_term_max": 30,
        "frequency_initial": 20,
        "idle_summarize_seconds": 900,
    },
    "retrieval": {"top_k": 3, "candidate_limit": 10},
}


class IsolatedTestCase(unittest.TestCase):
    """每个用例一个干净的临时数据目录，结束时整体删除。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="memtest-")
        self.data_dir = self._tmp.name
        self._patches = [
            mock.patch("config.data_dir", return_value=self.data_dir),
            mock.patch("config.load_config", return_value=_TEST_CONFIG),
            mock.patch("urllib.request.urlopen", side_effect=_offline),
            # 原路径是盘符根下的 state\pending-counts.json，测试不能写到那里。
            mock.patch("memory._pending_counts_path",
                       return_value=os.path.join(self.data_dir, "pending-counts.json")),
        ]
        for p in self._patches:
            p.start()
        # notebook 的根目录是写死的真实路径，必须在 import 之后立刻改掉，
        # 否则 list_notes/write_note 会去碰 D:\AI\笔记。
        import notebook
        self._notebook_root = notebook.ROOT
        notebook.ROOT = os.path.join(self.data_dir, "notes")
        # 日记全量缓存是模块级全局变量，上一个用例的签名不能带进来。
        import memory
        memory._DIARY_CACHE["sig"] = None
        memory._DIARY_CACHE["rows"] = None

    def tearDown(self):
        import notebook
        notebook.ROOT = self._notebook_root
        for p in reversed(self._patches):
            p.stop()
        self._tmp.cleanup()

    # —— 小工具 ——

    def chat_dir(self, key):
        import memory
        return os.path.join(self.data_dir, "chats", memory._safe_key(key))

    def write_json(self, path, data):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        import json
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)

    def read_json(self, path):
        import json
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
