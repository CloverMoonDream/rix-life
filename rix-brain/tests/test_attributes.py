"""attributes.py：联想库的读取、桥接打分、以及模型失败时的降级。

真实格式跟测试初稿不一样，这里按代码来：

* 没有 ``lookup``。读一个词用 ``attributes_of``（属性）和 ``assoc_of``（联想）。
* 存盘是 ``{"词": {"a": [...], "s": [...]}}``，``_save`` 只收数据、自己算路径。
* ``bridge_scores`` 不看正文，只看 ``things`` 里的词；词已经出现在
  query 里的直接跳过（词面召回覆盖了）。属性命中 +1，联想命中 +2。
* ``ensure_attributes`` 收的是**词的列表**，不是记忆条目。
"""
import os
from unittest import mock

import _base  # noqa: F401  先把 code/ 加进 sys.path
import attributes
import config

from _base import IsolatedTestCase

T0 = 1762056000


def _mem(first, things="", key="private:10001"):
    return {"memory_content": "正文不参与打分", "first_time": first, "things": things, "key": key}


class AttributeStoreTests(IsolatedTestCase):
    def test_missing_word_returns_empty(self):
        self.assertEqual(attributes.attributes_of("圆柱"), [])
        self.assertEqual(attributes.assoc_of("圆柱"), [])

    def test_corrupt_file_reads_as_empty(self):
        p = attributes._path()
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            f.write("{坏的")
        self.assertEqual(attributes._load(), {})

    def test_bridge_scores_empty_inputs(self):
        self.assertEqual(attributes.bridge_scores("", []), [])
        self.assertEqual(attributes.bridge_scores("圆柱", []), [])

    def test_bridge_scores_empty_store(self):
        # 库是空的时直接返回，不去逐条比。
        self.assertEqual(attributes.bridge_scores("圆柱", [_mem(T0, "体积")]), [])

    def test_bridge_scores_attribute_hit(self):
        # 「体积」的属性里有「高」，query 里出现了「高」，记 1 分。
        attributes._save({"体积": {"a": ["高", "底面积"], "s": []}})
        memories = [
            _mem(T0, "无关"),
            _mem(T0 + 1, "体积"),
        ]
        hits = attributes.bridge_scores("这道题的高是多少", memories)
        self.assertEqual(hits, [(1, 1)])

    def test_bridge_scores_association_hit(self):
        # query 切出「苹果」，它的联想集里有「水果」；记忆的 things 是「水果」，
        # 被点亮，记 2 分。
        attributes._save({"苹果": {"a": [], "s": ["水果", "牛顿"]}})
        memories = [_mem(T0, "水果")]
        hits = attributes.bridge_scores("苹果", memories)
        self.assertEqual(hits, [(0, 2)])

    def test_bridge_scores_skips_literal_overlap(self):
        # things 里的词已经出现在 query 里：词面召回覆盖了，这里不计分。
        attributes._save({"圆柱": {"a": ["体积"], "s": []}})
        memories = [_mem(T0, "圆柱")]
        self.assertEqual(attributes.bridge_scores("圆柱的体积", memories), [])

    def test_bridge_scores_ignores_body(self):
        # 正文里写满了属性词也没用，things 是空的就不参与。
        attributes._save({"体积": {"a": ["高"], "s": []}})
        memories = [{"memory_content": "高和高", "first_time": T0, "things": "", "key": "k"}]
        self.assertEqual(attributes.bridge_scores("高", memories), [])

    def test_bridge_scores_respects_exclude_and_max_hits(self):
        attributes._save({"水": {"a": [], "s": []}, "苹果": {"a": [], "s": ["水"]}})
        memories = [_mem(T0 + i, "水") for i in range(5)]
        hits = attributes.bridge_scores("苹果", memories, exclude={0, 1}, max_hits=2)
        self.assertEqual([i for i, _s in hits], [2, 3])

    def test_bridge_scores_ranks_higher_first(self):
        attributes._save({
            "体积": {"a": ["高", "底面积"], "s": []},
            "形状": {"a": ["圆"], "s": []},
        })
        memories = [
            _mem(T0, "形状"),   # 只命中「圆」，1 分
            _mem(T0 + 1, "体积"),  # 命中「高」和「底面积」，2 分
        ]
        hits = attributes.bridge_scores("底面积乘高再看圆不圆", memories)
        self.assertEqual([i for i, _s in hits], [1, 0])
        self.assertEqual(hits[0][1], 2)
        self.assertEqual(hits[1][1], 1)

    def test_ensure_attributes_zero_when_model_down(self):
        # deepseek 连不上时返回 0，不抛异常，也不写文件。
        n = attributes.ensure_attributes(["圆柱"])
        self.assertEqual(n, 0)
        self.assertFalse(os.path.exists(attributes._path()))

    def test_ensure_attributes_empty_input(self):
        self.assertEqual(attributes.ensure_attributes([]), 0)
        self.assertEqual(attributes.ensure_attributes(["", "  "]), 0)

    def test_ensure_attributes_skips_known_words(self):
        # 已经是新格式（dict）的词不再问模型。
        attributes._save({"爬山": {"a": ["陡"], "s": ["山"]}})
        with mock.patch.object(config, "deepseek_complete") as call:
            n = attributes.ensure_attributes(["爬山"])
        self.assertEqual(n, 0)
        call.assert_not_called()

    def test_ensure_attributes_rewrites_legacy_list(self):
        # 旧格式是纯列表，不算「已补齐」，还是要再问一次模型。
        attributes._save({"圆柱": ["体积"]})
        payload = '[["圆柱", {"a": ["圆", "高"], "s": ["几何"]}]'
        payload = '[["圆柱", {"a": ["圆", "高"], "s": ["几何"]}]]'
        with mock.patch.object(config, "deepseek_complete", return_value=payload):
            n = attributes.ensure_attributes(["圆柱"])
        self.assertEqual(n, 1)
        self.assertEqual(attributes.attributes_of("圆柱"), ["圆", "高"])

    def test_ensure_attributes_writes_new_word(self):
        payload = '[["圆柱", {"a": ["体积", "高"], "s": ["几何", "公式"]}]]'
        with mock.patch.object(config, "deepseek_complete", return_value=payload):
            n = attributes.ensure_attributes(["圆柱"])
        self.assertEqual(n, 1)
        self.assertEqual(attributes.attributes_of("圆柱"), ["体积", "高"])
        self.assertEqual(attributes.assoc_of("圆柱"), ["几何", "公式"])

    def test_ensure_attributes_ignores_garbage_reply(self):
        with mock.patch.object(config, "deepseek_complete", return_value="我不知道你在说什么"):
            n = attributes.ensure_attributes(["圆柱"])
        self.assertEqual(n, 0)
        self.assertEqual(attributes._load(), {})

    def test_ensure_attributes_caps_batch(self):
        # batch 限制一次问几个词，多出来的这次不补。
        words = ["甲一", "乙二", "丙三"]
        payload = "[" + ",".join(
            '["%s", {"a": ["属性"], "s": []}]' % w for w in words) + "]"
        with mock.patch.object(config, "deepseek_complete", return_value=payload) as call:
            n = attributes.ensure_attributes(words, batch=2)
        asked = call.call_args.args[0][0]["content"]
        self.assertNotIn("丙三", asked)
        # batch 只限制「问模型问几个词」，不限制「模型回了几个就写几个」：
        # 回复里多带的词一样会被落盘。
        self.assertEqual(n, 3)
        self.assertEqual(attributes.attributes_of("丙三"), ["属性"])

    def test_missing_words_lists_unknown(self):
        attributes._save({"爬山": {"a": ["陡"], "s": []}})
        memories = [_mem(T0, "爬山,水,帐篷"), _mem(T0 + 1, "水,地图")]
        self.assertEqual(attributes.missing_words(memories), ["水", "帐篷", "地图"])

    def test_stats_counts(self):
        attributes._save({"圆柱": {"a": ["圆", "高"], "s": ["几何"]}})
        self.assertEqual(attributes.stats(), {"words": 1, "attrs": 2, "assoc": 1})
