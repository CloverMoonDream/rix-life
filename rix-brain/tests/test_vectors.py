"""vectors.py：嵌入缓存与 top_k。

ollama 在测试里是打不开的（底座拦截了 urlopen），所以这里要么走「缓存命中」
这条不联网的路径，要么显式断言「连不上时返回空、不抛异常」。

跟初稿不同的三点，都按代码改了：

* 缓存键是 ``_entry_id``，值是 ``{"h": 内容哈希, "v": 向量}``，不是裸向量。
* 余弦函数叫 ``_cos``，不叫 ``_cosine``。
* ``embed`` 不校验维度。返回 3 维也照单全收，维度检查并不存在。
"""
import json
import os
from unittest import mock

import _base  # noqa: F401  先把 code/ 加进 sys.path
import vectors

from _base import IsolatedTestCase

T0 = 1762056000


def _mem(content, first, key="private:10001"):
    return {"memory_content": content, "first_time": first, "key": key,
            "_src": key.replace(":", "_")}


def _fake_resp(payload):
    class FakeResp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return json.dumps(payload).encode("utf-8")

    return FakeResp()


class EmbedTests(IsolatedTestCase):
    def test_embed_returns_empty_when_ollama_down(self):
        # 场景 16 的底层：连不上时返回空列表，不抛。
        self.assertEqual(vectors.embed(["你好"]), [])

    def test_embed_empty_input(self):
        self.assertEqual(vectors.embed([]), [])
        self.assertEqual(vectors.embed(["", "   "]), [])

    def test_embed_returns_whatever_dimension_it_gets(self):
        # 代码没有维度校验：回了 3 维就存 3 维，不会整批作废。
        short = [[0.1, 0.2, 0.3]]
        with mock.patch("urllib.request.urlopen", return_value=_fake_resp({"embeddings": short})):
            self.assertEqual(vectors.embed(["你好"]), short)

    def test_embed_missing_field_returns_empty(self):
        with mock.patch("urllib.request.urlopen",
                        return_value=_fake_resp({"不是": "embeddings"})):
            self.assertEqual(vectors.embed(["你好"]), [])


class TopKTests(IsolatedTestCase):
    def test_top_k_empty_inputs(self):
        # 场景 15：空查询、空记忆库都不抛异常。
        self.assertEqual(vectors.top_k("", []), [])
        self.assertEqual(vectors.top_k("爬山", []), [])
        self.assertEqual(vectors.top_k("", [_mem("今天去爬山", T0)]), [])

    def test_cache_roundtrip_then_top_k(self):
        # 场景 15：缓存命中后 top_k 返回 [(下标, 分数)]，按分数从高到低。
        memories = [
            _mem("今天去爬山了", T0),
            _mem("晚上在家看书", T0 + 1),
            _mem("明天还要去爬山", T0 + 2),
        ]
        up = [1.0, 0.0]
        down = [-1.0, 0.0]
        db = {}
        for mem, vec in zip(memories, (up, down, up)):
            db[vectors._entry_id(mem)] = {"h": vectors._hash(mem["memory_content"]), "v": vec}
        vectors._save(db)

        loaded = vectors._load()
        self.assertEqual(len(loaded), 3)
        self.assertEqual(loaded[vectors._entry_id(memories[0])]["v"], up)

        with mock.patch.object(vectors, "embed", return_value=[up]):
            hits = vectors.top_k("爬山", memories, k=2)
        self.assertEqual([i for i, _s in hits], [0, 2])
        self.assertGreater(hits[0][1], 0.9)
        self.assertAlmostEqual(hits[0][1], hits[1][1], places=6)

    def test_top_k_skips_entries_without_vector(self):
        # 只有一条有缓存，其余的嵌入又失败了：只返回那一条，不报错。
        memories = [_mem("甲", T0), _mem("乙", T0 + 1)]
        vec = [1.0, 0.0]
        vectors._save({
            vectors._entry_id(memories[0]): {"h": vectors._hash("甲"), "v": vec},
        })
        def fake_embed(texts):
            # 待补的那条（乙）嵌入失败；查询本身要能拿到向量，否则整批直接返回空。
            return [vec] if texts == ["甲"] else []

        with mock.patch.object(vectors, "embed", side_effect=fake_embed):
            hits = vectors.top_k("甲", memories, k=3)
        self.assertEqual(hits, [(0, 1.0)])

    def test_top_k_refreshes_when_content_changes(self):
        # 内容变了哈希对不上，会重新嵌入，不沿用旧向量。
        mem = _mem("今天去爬山了", T0)
        vectors._save({vectors._entry_id(mem): {"h": "过期的哈希", "v": [-1.0, 0.0]}})
        fresh = [1.0, 0.0]
        with mock.patch.object(vectors, "embed", return_value=[fresh]):
            hits = vectors.top_k("爬山", [mem], k=1)
        self.assertEqual(hits, [(0, 1.0)])
        self.assertEqual(vectors._load()[vectors._entry_id(mem)]["v"], fresh)

    def test_corrupt_cache_reads_as_empty(self):
        p = vectors._path()
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            f.write("不是 json")
        self.assertEqual(vectors._load(), {})

    def test_cosine_orthogonal_is_zero(self):
        self.assertEqual(vectors._cos([1.0, 0.0], [0.0, 1.0]), 0.0)

    def test_cosine_zero_vector_is_zero(self):
        self.assertEqual(vectors._cos([0.0, 0.0], [1.0, 0.0]), 0.0)

    def test_cosine_empty_is_zero(self):
        self.assertEqual(vectors._cos([], [1.0]), 0.0)

    def test_save_crash_truncates_cache(self):
        # 缺陷：vectors._save 直接 open(..., "w") 再 dump，不是先写临时文件再替换。
        # 写到一半抛异常时，原文件已经被截成半截，旧缓存回不来了。
        p = vectors._path()
        original = {"private_10001::1": {"h": "abc", "v": [1.0, 0.0]}}
        vectors._save(original)
        self.assertEqual(vectors._load(), original)

        real_open = open

        def boom(path, mode="r", *a, **k):
            f = real_open(path, mode, *a, **k)
            if os.path.normcase(str(path)) == os.path.normcase(p) and "w" in mode:
                f.write("{")
                f.close()
                raise OSError("模拟写到一半断电")
            return f

        with mock.patch("builtins.open", side_effect=boom):
            with self.assertRaises(OSError):
                vectors._save({"private_10001::2": {"h": "def", "v": [0.0, 1.0]}})

        with open(p, encoding="utf-8") as f:
            left = f.read()
        # 原子写的话这里应该还能读回 original；现在只剩一个 "{"。
        self.assertEqual(left, "{")
        self.assertNotIn("private_10001::1", left)
