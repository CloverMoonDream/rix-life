"""memory.py 的测试：README 第三节的 17 个场景，加上每个公开函数的异常路径。

约定：
- 期望值都写成具体的值，不用 ``assertTrue(x)`` 这种只看真假的断言。
- 时间戳用固定的绝对秒数，不依赖"现在"，这样换一台机器结果一样。
- 凡是会触发 deepseek / ollama 的路径，都先把那个函数替成抛错或返回空，
  既保证离线，也避免 ``_compress_text`` 里那两次 1.5 秒的重试把测试拖慢。
"""
import json
import os
import threading
import time
from unittest import mock

import _base  # noqa: F401  先把 code/ 加进 sys.path
import config
import memory

from _base import IsolatedTestCase

# 2026-11-02 12:00:00（本地时区无关：下面所有断言都基于相对差值或显式传入的时间戳）
T0 = 1762056000


def _entry(content, first, key="private:10001", kind="objective", things="", **extra):
    e = {
        "memory_content": content,
        "things": things,
        "key": key,
        "kind": kind,
        "first_time": first,
        "last_time": first,
        "last_called": first,
        "frequency": 20,
        "layer": 1,
        "last_hit": 0,
        "next_due": 0,
    }
    e.update(extra)
    return e


class RecordAndShortTermTests(IsolatedTestCase):
    """场景 1、2：空库与短期记忆往返。"""

    def test_empty_store_reads_return_empty(self):
        # 场景 1：一个文件都没写过，读出来应是空，而不是抛异常。
        self.assertEqual(memory.all_chat_keys(), [])
        self.assertEqual(memory.get_short_term_text(current_key="private:10001"), "")
        pending = memory.get_pending("private:10001")
        self.assertEqual(pending["count"], 0)
        self.assertEqual(pending["text"], "")
        self.assertIsNone(pending["first_time"])
        self.assertIsNone(pending["last_time"])
        out = memory.recall("随便问一句", current_key="private:10001", with_ids=True)
        self.assertEqual(out["long_term"], "")
        self.assertEqual(out["long_term_count"], 0)
        # 2026-11-06 已修：一篇日记都没有时提前返回，原本返回值里没有 ids，
        # 和「有日记」那条路径形状不一致。现在两条路径都带 ids。
        self.assertEqual(out["ids"], [])
        self.assertEqual(set(out), {"short_term", "long_term", "long_term_count", "quota", "ids"})

    def test_record_turn_roundtrip(self):
        # 场景 2：写一条，用同一个 key 读回来，内容要一字不差。
        ok = memory.record_turn("private:10001", "用户", "早上好", nickname="测试用户")
        self.assertIs(ok, True)
        text = memory.get_short_term_text(current_key="private:10001")
        self.assertEqual(text, "测试用户：早上好")
        rows = self.read_json(os.path.join(self.chat_dir("private:10001"), "short_term.json"))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["role"], "用户")
        self.assertEqual(rows[0]["content"], "早上好")
        self.assertIs(rows[0]["consolidated"], False)

    def test_record_turn_blank_content_writes_nothing(self):
        # 异常路径：空内容直接返回，不建文件。
        self.assertIs(memory.record_turn("private:10001", "用户", "   "), True)
        self.assertFalse(os.path.exists(os.path.join(self.chat_dir("private:10001"), "short_term.json")))

    def test_record_turn_trims_to_short_term_max(self):
        # 边界：超过 short_term_max（默认 30）时只留最新的 30 条。
        for i in range(35):
            memory.record_turn("private:10001", "用户", "第%d句" % i)
        rows = self.read_json(os.path.join(self.chat_dir("private:10001"), "short_term.json"))
        self.assertEqual(len(rows), 30)
        self.assertEqual(rows[0]["content"], "第5句")
        self.assertEqual(rows[-1]["content"], "第34句")

    def test_get_short_term_text_respects_max_turns(self):
        memory.record_turn("private:10001", "用户", "第一句", nickname="甲")
        memory.record_turn("private:10001", "AI", "第二句", nickname="乙")
        memory.record_turn("private:10001", "用户", "第三句", nickname="甲")
        text = memory.get_short_term_text(max_turns=2, current_key="private:10001")
        self.assertEqual(text, "乙：第二句\n甲：第三句")

    def test_get_short_term_text_without_key_labels_source(self):
        # 不给 current_key 时要合并所有会话，并带来源标注。
        memory.record_turn("private:10001", "用户", "私聊的话", nickname="甲")
        memory.record_turn("group:20002", "用户", "群里的话", nickname="乙")
        text = memory.get_short_term_text()
        self.assertIn("[私聊(10001)]甲：私聊的话", text)
        self.assertIn("[群(20002)]乙：群里的话", text)

    def test_get_short_term_text_unknown_key_is_empty(self):
        self.assertEqual(memory.get_short_term_text(current_key="private:99999"), "")


class DiaryAndKeysTests(IsolatedTestCase):
    """场景 3、4：写日记、列会话、first_time 冲突。"""

    def test_append_diary_then_all_chat_keys(self):
        # 场景 3：写一条日记后，all_chat_keys 里能看到这个会话。
        memory.append_diary("今天去爬山了", things="爬山", key="private:10001",
                            first_time=T0, last_time=T0, kind="objective")
        keys = memory.all_chat_keys()
        self.assertIn("private_10001", keys)
        rows = self.read_json(os.path.join(self.chat_dir("private:10001"), "diary.json"))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["first_time"], T0)
        self.assertEqual(rows[0]["kind"], "objective")
        # 私聊日记开头要被强制打上「是谁」。
        self.assertTrue(rows[0]["memory_content"].startswith("【私聊 10001】"))
        self.assertIn("今天去爬山了", rows[0]["memory_content"])

    def test_append_diary_without_key_raises(self):
        # 异常路径：没给 key 必须抛 ValueError，不能默默写到 _default。
        with self.assertRaises(ValueError) as ctx:
            memory.append_diary("没头没尾的一条", first_time=T0)
        self.assertIn("append_diary", str(ctx.exception))
        self.assertEqual(memory.all_chat_keys(), [])

    def test_append_diary_empty_content_still_creates_row(self):
        # 边界：内容为空也会落一条（时间戳兜底用当前时间），但不能炸。
        before = int(time.time())
        memory.append_diary("", key="group:20002")
        rows = self.read_json(os.path.join(self.chat_dir("group:20002"), "diary.json"))
        self.assertEqual(len(rows), 1)
        self.assertGreaterEqual(rows[0]["first_time"], before)
        self.assertEqual(rows[0]["memory_content"], "")

    def test_duplicate_first_time_updates_in_place(self):
        # 场景 4（2026-11-06 已修）：first_time 是召回和编辑的唯一键。
        # 原来同一个 first_time 写两次会变成两条，edit_entry / flag_wrong
        # 只改得到第一条，第二条永远改不到。现在按 first_time 去重、原地更新。
        # （原来这条叫 ...creates_second_row，断言的是"会重复"。）
        memory.append_diary("第一条", key="private:10001", first_time=T0, kind="objective")
        memory.append_diary("第二条", key="private:10001", first_time=T0, kind="objective")
        rows = self.read_json(os.path.join(self.chat_dir("private:10001"), "diary.json"))
        self.assertEqual(len(rows), 1, "同一个 first_time 不该写出两条")
        self.assertEqual(rows[0]["first_time"], T0)
        # 正文会被 append_diary 加上日期前缀和「谁」标签，所以只查包含关系
        self.assertIn("第二条", rows[0]["memory_content"], "重复写入应更新为最新内容")
        self.assertNotIn("第一条", rows[0]["memory_content"])
        self.assertTrue(rows[0].get("edited"), "被更新过的条目要留个标记")

    def test_append_diary_guesses_kind_from_emotion_words(self):
        memory.append_diary("我觉得很难过也很担心他", key="private:10001", first_time=T0)
        rows = self.read_json(os.path.join(self.chat_dir("private:10001"), "diary.json"))
        self.assertEqual(rows[0]["kind"], "subjective")

    def test_append_diary_strips_relative_time_words_from_things(self):
        memory.append_diary("聊了爬山", things="今天,爬山,昨天", key="private:10001", first_time=T0)
        rows = self.read_json(os.path.join(self.chat_dir("private:10001"), "diary.json"))
        self.assertNotIn("今天", rows[0]["things"])
        self.assertNotIn("昨天", rows[0]["things"])
        self.assertIn("爬山", rows[0]["things"])

    def test_append_diary_marks_short_term_consolidated(self):
        # 写日记应把 last_time 之前的短期条目标成已总结，但不删除。
        p = os.path.join(self.chat_dir("private:10001"), "short_term.json")
        self.write_json(p, [
            {"key": "private:10001", "role": "用户", "content": "早", "time": T0, "consolidated": False},
            {"key": "private:10001", "role": "用户", "content": "晚", "time": T0 + 100, "consolidated": False},
        ])
        memory.append_diary("总结", key="private:10001", first_time=T0, last_time=T0)
        rows = self.read_json(p)
        self.assertEqual(len(rows), 2)
        self.assertIs(rows[0]["consolidated"], True)
        self.assertIs(rows[1]["consolidated"], False)

    def test_append_diary_does_not_duplicate_existing_date_prefix(self):
        memory.append_diary("十一月二号，已经写过日期了", key="group:20002", first_time=T0)
        rows = self.read_json(os.path.join(self.chat_dir("group:20002"), "diary.json"))
        self.assertEqual(rows[0]["memory_content"], "十一月二号，已经写过日期了")


class RecallTests(IsolatedTestCase):
    """场景 5~10：召回的形状、配额、跨会话、时间窗、无关查询。"""

    def _seed(self):
        a = os.path.join(self.chat_dir("private:10001"), "diary.json")
        b = os.path.join(self.chat_dir("private:30003"), "diary.json")
        self.write_json(a, [
            _entry("（测试数据）周末一起去爬山，记得带水。", T0, things="爬山,水"),
            _entry("（测试数据）他问了一个圆柱体积的数学题。", T0 + 86400, things="数学,圆柱", kind="subjective"),
        ])
        self.write_json(b, [
            _entry("（测试数据）另一个人在聊帧数和显卡。", T0 + 43200,
                   key="private:30003", things="帧数,显卡"),
        ])

    def test_recall_empty_query_returns_empty_ids(self):
        # 2026-11-06 已修：查询是空串时候选池为空，picked 原本没有绑定，
        # 会抛 UnboundLocalError。现在兜底成空列表，返回一个结构完整的空结果。
        # （原来这条用例叫 test_recall_empty_query_crashes，断言的是崩；
        #   修完之后反过来了。）
        self._seed()
        out = memory.recall("", with_ids=True)
        self.assertIsInstance(out, dict)
        self.assertEqual(out["ids"], [])

    def test_recall_result_shape(self):
        # 场景 5、6：正常召回的返回值带四个键，ids 里每条都有 key 和 first_time。
        self._seed()
        out = memory.recall("爬山", with_ids=True)
        for key in ("short_term", "long_term", "quota", "ids"):
            self.assertIn(key, out)
        self.assertIsInstance(out["ids"], list)
        for item in out["ids"]:
            self.assertIn("key", item)
            self.assertIn("first_time", item)
            self.assertIsInstance(item["first_time"], int)

    def test_recall_max_total_caps_ids(self):
        # 场景 7：max_total=5 时返回条数不超过 5。
        base = os.path.join(self.chat_dir("private:10001"), "diary.json")
        rows = [_entry("（测试数据）第%d件小事%s。" % (i, "爬山" if i % 2 == 0 else "喝水"),
                       T0 + i * 3600, things="爬山" if i % 2 == 0 else "喝水")
                for i in range(12)]
        self.write_json(base, rows)
        out = memory.recall("爬山喝水", max_total=5, with_ids=True)
        self.assertLessEqual(len(out["ids"]), 5)
        self.assertEqual(out["quota"]["total"], 5)
        self.assertEqual(out["quota"]["source"], "caller")

    def test_recall_max_total_zero_uses_default_quota(self):
        # 场景 8：max_total=0 走默认配额，quota_now 固定返回 10。
        self._seed()
        out = memory.recall("爬山", max_total=0, with_ids=True)
        self.assertEqual(out["quota"]["total"], 10)
        self.assertEqual(out["quota"]["subjective"], 5)
        self.assertEqual(out["quota"]["objective"], 5)
        self.assertEqual(out["quota"]["source"], "emotion")
        self.assertLessEqual(len(out["ids"]), 10)

    def test_recall_does_not_bury_other_session(self):
        # 场景 9：跨会话召回不能把 B 的内容埋没。
        # 这里 A 有 40 条跟查询毫无关系的日记，B 只有 1 条正好对上。
        # 词面召回的候选上限是 candidate_limit（默认 10），B 的那条相关度最高，
        # 应该排进前几，而不是被 A 的数量挤出去。
        a = os.path.join(self.chat_dir("private:10001"), "diary.json")
        b = os.path.join(self.chat_dir("group:20002"), "diary.json")
        self.write_json(a, [
            _entry("（测试数据）今天天气不错，出门散步了%d。" % i, T0 + i * 60, things="天气,散步")
            for i in range(40)
        ])
        self.write_json(b, [
            _entry("（测试数据）群里有人在讨论一款游戏的帧数。", T0 + 5000,
                   key="group:20002", things="游戏,帧数"),
        ])
        out = memory.recall("游戏帧数怎么样", max_total=5, with_ids=True, current_key="private:10001")
        b_hits = [i for i in out["ids"] if i["key"] == "group:20002"]
        self.assertEqual(len(b_hits), 1, "B 会话那条唯一相关的日记应该被召回，实际 ids=%r" % out["ids"])
        self.assertEqual(b_hits[0]["first_time"], T0 + 5000)
        # 跨会话的正文要带来源标注。
        self.assertIn("[群(20002)的记忆]", out["long_term"])

    def test_time_window_is_boost_not_hard_filter(self):
        # 场景 10：查询里有「昨天」，时间窗应该是加权项，不是硬过滤。
        # 昨天有一条无关的，今天有一条正好对上「爬山」——硬过滤会把今天这条丢掉。
        now = time.time()
        yesterday = int(now - 86400)
        today = int(now - 3600)
        p = os.path.join(self.chat_dir("group:20002"), "diary.json")
        self.write_json(p, [
            _entry("（测试数据）昨天随便聊了聊天气。", yesterday, key="group:20002", things="天气"),
            _entry("（测试数据）今天终于去爬山了，带了水。", today, key="group:20002", things="爬山,水"),
        ])
        out = memory.recall("昨天说的爬山", max_total=5, with_ids=True)
        got = sorted(i["first_time"] for i in out["ids"])
        self.assertIn(today, got, "时间窗不该把窗口外但内容高度相关的条目过滤掉，实际 %r" % got)

    def test_unrelated_query_does_not_crash(self):
        # 场景 11：完全无关的查询要返回空结果或低相关结果，但不能抛异常。
        self._seed()
        out = memory.recall("量子纠缠与黑洞蒸发的霍金辐射", max_total=5, with_ids=True)
        self.assertIsInstance(out, dict)
        self.assertIn("long_term", out)
        self.assertLessEqual(len(out["ids"]), 5)
        for item in out["ids"]:
            self.assertIn("key", item)
            self.assertIn("first_time", item)

    def test_recall_without_with_ids_returns_empty_ids(self):
        self._seed()
        out = memory.recall("爬山", max_total=3)
        self.assertEqual(out["ids"], [])
        self.assertIn("爬山", out["long_term"])

    def test_recall_short_term_turns_zero_skips_short_text(self):
        memory.record_turn("private:10001", "用户", "这句话不该出现", nickname="甲")
        out = memory.recall("爬山", current_key="private:10001", short_term_turns=0)
        self.assertEqual(out["short_term"], "")

    def test_merged_entry_consumes_double_budget(self):
        # 带 merged_from 的条目按两条计：配额 4 时，选中一条合并条目后
        # 预算降到 3，最终只返回 3 条而不是 4 条。
        p = os.path.join(self.chat_dir("group:20002"), "diary.json")
        rows = [_entry("客观事实%d：他去爬山了。" % i, T0 + i, key="group:20002", things="爬山")
                for i in range(6)]
        rows[0]["merged_from"] = 3
        self.write_json(p, rows)
        out = memory.recall("爬山", max_total=4, with_ids=True)
        self.assertEqual(len(out["ids"]), 3)

    def test_recall_positive_short_term_turns_limits_window(self):
        # 正数窗口要真的生效：只取最近 1 轮，更早的那句不能出现。
        memory.record_turn("private:10001", "用户", "更早的一句", nickname="甲")
        memory.record_turn("private:10001", "用户", "最近的一句", nickname="甲")
        out = memory.recall("爬山", current_key="private:10001", short_term_turns=1)
        self.assertIn("最近的一句", out["short_term"])
        self.assertNotIn("更早的一句", out["short_term"])

    def test_recall_disputed_entry_is_flagged_in_text(self):
        p = os.path.join(self.chat_dir("group:20002"), "diary.json")
        self.write_json(p, [_entry("（测试数据）这条是错的。", T0, key="group:20002",
                             things="错误", disputed=True)])
        out = memory.recall("这条是错的", max_total=3)
        self.assertIn("【有争议·别当定论】", out["long_term"])

    def test_recall_subjective_ratio_override(self):
        p = os.path.join(self.chat_dir("group:20002"), "diary.json")
        self.write_json(p, [
            _entry("客观事实%d：他去爬山了。" % i, T0 + i, key="group:20002", kind="objective", things="爬山")
            for i in range(4)
        ] + [
            _entry("主观感受%d：我觉得爬山很开心。" % i, T0 + 100 + i, key="group:20002",
                   kind="subjective", things="爬山")
            for i in range(4)
        ])
        out = memory.recall("爬山", max_total=4, subjective_ratio=1.0, with_ids=True)
        self.assertEqual(out["quota"]["subjective"], 4)
        self.assertEqual(out["quota"]["objective"], 0)
        self.assertLessEqual(len(out["ids"]), 4)


class MergeDecayEditTests(IsolatedTestCase):
    """场景 12~15：合并、衰减、编辑、迁移。"""

    def test_merge_window_noop_when_sparse(self):
        # 场景 12：间隔超过窗口的日记不应该被合并。
        p = os.path.join(self.chat_dir("private:10001"), "diary.json")
        self.write_json(p, [
            _entry("第一条。", T0, things="甲"),
            _entry("第二条。", T0 + 5 * 3600, things="乙"),
        ])
        report = memory.merge_window(window_minutes=120, max_per_window=2)
        self.assertEqual(report, [])
        rows = self.read_json(p)
        self.assertEqual(len(rows), 2)
        self.assertNotIn("merged_from", rows[0])

    def test_merge_window_merges_dense_cluster(self):
        # 2 小时内 4 篇，超过 2 篇，应该合成 1 篇，内容都还在。
        p = os.path.join(self.chat_dir("group:20002"), "diary.json")
        self.write_json(p, [
            _entry("第一段提到苹果。", T0 + i * 600, key="group:20002", things="苹果")
            if i == 0 else
            _entry("第%d段提到橘子。" % (i + 1), T0 + i * 600, key="group:20002", things="橘子")
            for i in range(4)
        ])
        report = memory.merge_window(window_minutes=120, max_per_window=2, key="group:20002")
        self.assertEqual(len(report), 1)
        self.assertEqual(report[0]["from"], 4)
        self.assertEqual(report[0]["to"], 1)
        rows = self.read_json(p)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["merged_from"], 4)
        self.assertIn("苹果", rows[0]["memory_content"])
        self.assertIn("橘子", rows[0]["memory_content"])
        # 合并前要留备份。
        self.assertTrue(any(name.startswith("diary.json.bak-") for name in os.listdir(self.chat_dir("group:20002"))))

    def test_merge_window_dry_run_does_not_write(self):
        p = os.path.join(self.chat_dir("group:20002"), "diary.json")
        before = [_entry("甲。", T0 + i * 60, key="group:20002") for i in range(4)]
        self.write_json(p, before)
        report = memory.merge_window(key="group:20002", dry_run=True)
        self.assertEqual(len(report), 1)
        self.assertEqual(self.read_json(p), before)

    def test_merge_window_skips_edited_sessions(self):
        # 有人手工改过的会话一律不合并，避免把修改压掉。
        p = os.path.join(self.chat_dir("group:20002"), "diary.json")
        self.write_json(p, [_entry("甲。", T0 + i * 60, key="group:20002", edited="manual") for i in range(4)])
        self.assertEqual(memory.merge_window(key="group:20002"), [])
        self.assertEqual(len(self.read_json(p)), 4)

    def test_merge_days_delegates_to_merge_window(self):
        p = os.path.join(self.chat_dir("group:20002"), "diary.json")
        self.write_json(p, [_entry("甲。", T0 + i * 60, key="group:20002") for i in range(3)])
        report = memory.merge_days(key="group:20002")
        self.assertEqual(len(report), 1)
        self.assertEqual(len(self.read_json(p)), 1)

    def test_merge_days_honours_min_entries(self):
        # 2026-11-06 已修：days_back 和 min_entries 原本完全不参与计算，
        # 要求「至少 99 篇才合并」，3 篇照样被压成 1 篇。
        # 现在 min_entries 真的当门槛：要到 99 篇才合并，3 篇不动。
        # （原来这条叫 ...ignores_its_own_arguments，断言的是"参数无效"。）
        p = os.path.join(self.chat_dir("group:20002"), "diary.json")
        self.write_json(p, [_entry("甲。", T0 + i * 60, key="group:20002") for i in range(3)])
        report = memory.merge_days(days_back=1, min_entries=99, key="group:20002")
        self.assertEqual(report, [], "3 篇达不到 min_entries=99，不该合并")
        self.assertEqual(len(self.read_json(p)), 3)

    def test_merge_days_merges_when_threshold_met(self):
        # 门槛放低到 2 篇时，3 篇应该被合并成 1 篇（正常路径）。
        p = os.path.join(self.chat_dir("group:20002"), "diary.json")
        self.write_json(p, [_entry("乙。", T0 + i * 60, key="group:20002") for i in range(3)])
        report = memory.merge_days(days_back=1, min_entries=2, key="group:20002")
        self.assertEqual(len(report), 1)
        self.assertEqual(len(self.read_json(p)), 1)

    def test_decay_check_is_idempotent_in_same_window(self):
        # 2026-11-06 已修：衰减原本不记「这次已经扣过」，时间窗没变也照样再扣，
        # 10→8→6 一直扣到 1 才停。现在扣完会写 last_decay 当基准，
        # 同一时间窗内第二次是空操作。
        # （原来这条叫 test_decay_check_keeps_decaying_until_floor，断言的是重复扣。）
        p = os.path.join(self.chat_dir("private:10001"), "diary.json")
        long_ago = int(time.time()) - 2 * 3600
        self.write_json(p, [_entry("旧日记。", long_ago, frequency=10, last_called=long_ago)])
        frozen = long_ago + 2 * 3600
        with mock.patch("memory.time.time", return_value=frozen):
            first = memory.decay_check()
            after_first = self.read_json(p)[0]["frequency"]
            second = memory.decay_check()
            after_second = self.read_json(p)[0]["frequency"]
        self.assertEqual(first, 1)
        self.assertEqual(after_first, 8)          # >1h 且 ≤15 天，扣 2
        self.assertEqual(second, 0)               # 同一窗口：不再动
        self.assertEqual(after_second, 8)

    def test_decay_check_stops_at_one(self):
        # 扣到 1 之后才真正幂等：frequency <= 1 的条目直接跳过。
        p = os.path.join(self.chat_dir("private:10001"), "diary.json")
        long_ago = int(time.time()) - 2 * 3600
        self.write_json(p, [_entry("旧日记。", long_ago, frequency=2, last_called=long_ago)])
        frozen = long_ago + 2 * 3600
        with mock.patch("memory.time.time", return_value=frozen):
            self.assertEqual(memory.decay_check(), 1)
            self.assertEqual(self.read_json(p)[0]["frequency"], 1)
            self.assertEqual(memory.decay_check(), 0)
            self.assertEqual(self.read_json(p)[0]["frequency"], 1)

    def test_decay_check_never_below_one(self):
        p = os.path.join(self.chat_dir("private:10001"), "diary.json")
        long_ago = int(time.time()) - 20 * 86400
        self.write_json(p, [_entry("很老。", long_ago, frequency=1, last_called=long_ago)])
        self.assertEqual(memory.decay_check(), 0)
        self.assertEqual(self.read_json(p)[0]["frequency"], 1)

    def test_decay_check_empty_store(self):
        self.assertEqual(memory.decay_check(), 0)

    def test_edit_entry_missing_returns_failure(self):
        # 场景 14：改一个不存在的条目，要明确返回失败，不能假装成功。
        memory.append_diary("存在的一条", key="private:10001", first_time=T0)
        result = memory.edit_entry(T0 + 999, content="改不存在的", key="private:10001")
        self.assertEqual(result, {"ok": False, "reason": "not_found", "first_time": T0 + 999})
        rows = self.read_json(os.path.join(self.chat_dir("private:10001"), "diary.json"))
        self.assertNotIn("改不存在的", rows[0]["memory_content"])

    def test_edit_entry_updates_only_given_fields(self):
        memory.append_diary("原文", things="旧", key="private:10001", first_time=T0, kind="objective")
        result = memory.edit_entry(T0, content="新的正文", key="private:10001")
        self.assertIs(result["ok"], True)
        self.assertEqual(result["first_time"], T0)
        row = self.read_json(os.path.join(self.chat_dir("private:10001"), "diary.json"))[0]
        self.assertEqual(row["memory_content"], "「新的正文」")
        self.assertEqual(row["things"], "旧")          # 没传的字段保持原样
        self.assertEqual(row["kind"], "objective")
        self.assertEqual(row["edited"], "ai")
        self.assertIs(row["disputed"], False)

    def test_edit_entry_rejects_unknown_kind(self):
        memory.append_diary("原文", key="private:10001", first_time=T0, kind="objective")
        memory.edit_entry(T0, kind="nonsense", key="private:10001")
        row = self.read_json(os.path.join(self.chat_dir("private:10001"), "diary.json"))[0]
        self.assertEqual(row["kind"], "objective")

    def test_edit_entry_without_key_searches_every_session(self):
        # 不传 key 时要扫全部会话，而不是只看某一个。
        memory.append_diary("在另一个会话里", key="group:20002", first_time=T0)
        result = memory.edit_entry(T0, content="改到了")
        self.assertIs(result["ok"], True)
        # 返回的 key 是目录名（冒号换成下划线），不是原始会话 key。
        self.assertEqual(result["key"], "group_20002")
        row = self.read_json(os.path.join(self.chat_dir("group:20002"), "diary.json"))[0]
        self.assertEqual(row["memory_content"], "「改到了」")

    def test_flag_wrong_missing_returns_failure(self):
        result = memory.flag_wrong(T0, reason="记错了", key="private:10001")
        self.assertEqual(result["ok"], False)
        self.assertEqual(result["reason"], "not_found")

    def test_flag_wrong_marks_entry(self):
        memory.append_diary("有问题的一条", key="private:10001", first_time=T0)
        result = memory.flag_wrong(T0, reason="人名写错", key="private:10001")
        self.assertIs(result["ok"], True)
        row = self.read_json(os.path.join(self.chat_dir("private:10001"), "diary.json"))[0]
        self.assertIs(row["disputed"], True)
        self.assertEqual(row["dispute_reason"], "人名写错")

    def test_migrate_legacy_splits_by_key(self):
        self.write_json(os.path.join(self.data_dir, "short_term.json"), [
            {"key": "private:10001", "role": "用户", "content": "甲", "time": T0},
            {"key": "group:20002", "role": "用户", "content": "乙", "time": T0 + 1},
        ])
        self.write_json(os.path.join(self.data_dir, "infinite_memory.json"), [
            _entry("旧日记", T0),
        ])
        changed = memory.migrate_legacy()
        self.assertEqual(len(changed), 2)
        self.assertFalse(os.path.exists(os.path.join(self.data_dir, "short_term.json")))
        self.assertTrue(os.path.exists(os.path.join(self.data_dir, "short_term.json.migrated")))
        a = self.read_json(os.path.join(self.chat_dir("private:10001"), "short_term.json"))
        b = self.read_json(os.path.join(self.chat_dir("group:20002"), "short_term.json"))
        self.assertEqual([r["content"] for r in a], ["甲"])
        self.assertEqual([r["content"] for r in b], ["乙"])
        diary = self.read_json(os.path.join(self.chat_dir("private:10001"), "diary.json"))
        self.assertEqual(diary[0]["memory_content"], "旧日记")

    def test_migrate_legacy_noop_when_absent(self):
        self.assertEqual(memory.migrate_legacy(), [])

    def test_migrate_legacy_blank_key_goes_to_default(self):
        self.write_json(os.path.join(self.data_dir, "infinite_memory.json"), [
            _entry("没有 key 的旧日记", T0, key=""),
        ])
        memory.migrate_legacy()
        rows = self.read_json(os.path.join(self.chat_dir("_default"), "diary.json"))
        self.assertEqual(len(rows), 1)


class PendingAndQuotaTests(IsolatedTestCase):
    """get_pending / quota_now / write_pending_counts / check_dir / export_check。"""

    def test_get_pending_skips_consolidated(self):
        p = os.path.join(self.chat_dir("private:10001"), "short_term.json")
        self.write_json(p, [
            {"key": "private:10001", "role": "用户", "nickname": "甲", "content": "已总结", "time": T0, "consolidated": True},
            {"key": "private:10001", "role": "用户", "nickname": "甲", "content": "还没总结", "time": T0 + 60, "consolidated": False},
        ])
        pending = memory.get_pending("private:10001")
        self.assertEqual(pending["count"], 1)
        self.assertIn("还没总结", pending["text"])
        self.assertNotIn("已总结", pending["text"])
        self.assertEqual(pending["first_time"], T0 + 60)
        self.assertEqual(pending["last_time"], T0 + 60)

    def test_get_pending_all_sessions_labels_source(self):
        self.write_json(os.path.join(self.chat_dir("private:10001"), "short_term.json"), [
            {"key": "private:10001", "role": "用户", "nickname": "甲", "content": "私聊内容", "time": T0},
        ])
        self.write_json(os.path.join(self.chat_dir("group:20002"), "short_term.json"), [
            {"key": "group:20002", "role": "用户", "nickname": "乙", "content": "群聊内容", "time": T0 + 10},
        ])
        pending = memory.get_pending("")
        self.assertEqual(pending["count"], 2)
        self.assertIn("[私聊(10001)]", pending["text"])
        self.assertIn("[群(20002)]", pending["text"])
        self.assertEqual(pending["first_time"], T0)
        self.assertEqual(pending["last_time"], T0 + 10)

    def test_get_pending_empty_session(self):
        pending = memory.get_pending("private:99999")
        self.assertEqual(pending["count"], 0)
        self.assertEqual(pending["text"], "")
        self.assertEqual(pending["key"], "private:99999")

    def test_quota_now_is_fixed(self):
        q = memory.quota_now()
        self.assertEqual(q["total"], 10)
        self.assertEqual(q["subjective"], 5)
        self.assertEqual(q["objective"], 5)
        self.assertIsNone(q["happiness"])

    def test_write_pending_counts_reflects_unconsolidated(self):
        # 落盘位置按源码往上数三层目录推出来，会写到盘符根的 state\ 下。
        # 底座把它改到了临时目录里的 pending-counts.json，这里读那个位置。
        self.write_json(os.path.join(self.chat_dir("private:10001"), "short_term.json"), [
            {"content": "甲", "time": T0, "consolidated": False},
            {"content": "乙", "time": T0 + 1, "consolidated": True},
            {"content": "丙", "time": T0 + 2, "consolidated": False},
        ])
        memory.write_pending_counts()
        got = self.read_json(os.path.join(self.data_dir, "pending-counts.json"))
        self.assertEqual(got["counts"], {"private:10001": 2})
        self.assertGreater(got["at"], 0)

    def test_export_check_empty_when_nothing_merged(self):
        memory.append_diary("普通日记", key="private:10001", first_time=T0)
        day = time.strftime("%Y-%m-%d", time.localtime(T0))
        result = memory.export_check(day, key="private:10001")
        self.assertEqual(result["count"], 0)
        self.assertEqual(result["path"], "")
        self.assertEqual(result["keys"], [])

    def test_export_check_writes_merged_entries(self):
        p = os.path.join(self.chat_dir("group:20002"), "diary.json")
        self.write_json(p, [_entry("合并后的正文。", T0, key="group:20002", merged_from=3)])
        day = time.strftime("%Y-%m-%d", time.localtime(T0))
        result = memory.export_check(day)
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["date"], day)
        self.assertTrue(os.path.exists(result["path"]))
        with open(result["path"], encoding="utf-8") as f:
            text = f.read()
        self.assertIn("合并后的正文。", text)
        self.assertIn("first_time=%d" % T0, text)

    def test_check_dir_is_under_data_dir(self):
        d = memory.check_dir()
        self.assertEqual(d, os.path.join(self.data_dir, "check"))
        self.assertTrue(os.path.isdir(d))


class ResolveKeyTests(IsolatedTestCase):
    """裸数字 key 的归一：只有一个会话真实存在时要解析到它。"""

    def test_bare_number_resolves_to_existing_group(self):
        os.makedirs(self.chat_dir("group:20002"))
        self.assertEqual(memory._resolve_key("20002"), "group:20002")

    def test_bare_number_defaults_to_private(self):
        self.assertEqual(memory._resolve_key("10001"), "private:10001")

    def test_prefixed_key_passes_through(self):
        self.assertEqual(memory._resolve_key("private:10001"), "private:10001")
        self.assertEqual(memory._resolve_key("group:20002"), "group:20002")

    def test_nickname_passes_through(self):
        self.assertEqual(memory._resolve_key("小明"), "小明")

    def test_get_pending_with_bare_number_finds_existing_session(self):
        # 这是 2026-10-24 那个事故的回归：只传裸数字时，如果群目录真实存在，
        # 应该读到那个群的待总结，而不是新建一个空的私聊目录后返回 0。
        p = os.path.join(self.chat_dir("group:20002"), "short_term.json")
        self.write_json(p, [
            {"key": "group:20002", "role": "用户", "nickname": "乙", "content": "群里说的", "time": T0},
        ])
        pending = memory.get_pending("20002")
        self.assertEqual(pending["key"], "group:20002")
        self.assertEqual(pending["count"], 1)
        self.assertIn("群里说的", pending["text"])


class TimeSubjectiveRecallTests(IsolatedTestCase):
    def test_matches_similar_short_term_line(self):
        p = os.path.join(self.chat_dir("private:10001"), "short_term.json")
        self.write_json(p, [
            {"key": "private:10001", "role": "用户", "content": "周末我们去爬山记得带水", "time": T0},
        ])
        diary = os.path.join(self.chat_dir("private:10001"), "diary.json")
        self.write_json(diary, [_entry("周末去爬山，带了水。", T0)])
        memories = memory._load_all_diaries()
        hits = memory.time_subjective_recall("周末我们去爬山记得带水", memories, current_key="private:10001")
        self.assertEqual(hits, [0])

    def test_without_current_key_returns_empty(self):
        self.assertEqual(memory.time_subjective_recall("任何话", [], current_key=None), [])

    def test_no_similar_line_returns_empty(self):
        p = os.path.join(self.chat_dir("private:10001"), "short_term.json")
        self.write_json(p, [
            {"key": "private:10001", "role": "用户", "content": "今天天气真好", "time": T0},
        ])
        hits = memory.time_subjective_recall("量子力学的波函数怎么归一化", [], current_key="private:10001")
        self.assertEqual(hits, [])


class ConcurrencyTests(IsolatedTestCase):
    """场景 17：并发写日记不能损坏 JSON。"""

    def test_concurrent_append_diary_keeps_valid_json(self):
        barrier = threading.Barrier(8)
        errors = []

        def worker(i):
            try:
                barrier.wait(timeout=5)
                memory.append_diary("并发写入的第%d条" % i, things="并发", key="private:10001",
                                    first_time=T0 + i, kind="objective")
            except Exception as e:  # 线程里的异常不会自己冒出来
                errors.append(repr(e))

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        # 2026-11-06 已修：原来临时文件名固定为 path+".tmp"，多线程互踩，
        # Windows 上 os.replace 抛 PermissionError 且没有重试 → 那一次写入丢掉。
        # 现在临时名带 pid+线程号，且 replace 失败会短重试，8 条要全部落地。
        # （原来这条断言的是"会丢"，缺陷修完后反过来。）
        self.assertEqual(errors, [], "并发写入不该再抛异常")
        p = os.path.join(self.chat_dir("private:10001"), "diary.json")
        with open(p, encoding="utf-8") as f:
            rows = json.load(f)
        self.assertIsInstance(rows, list)
        got = sorted(r["first_time"] for r in rows)
        self.assertEqual(got, [T0 + i for i in range(8)], "8 条并发写入一条都不能少")


class RobustnessTests(IsolatedTestCase):
    """坏数据、原子写、以及文档里点名的历史事故。"""

    def test_load_corrupt_json_returns_default(self):
        p = os.path.join(self.chat_dir("private:10001"), "diary.json")
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            f.write("{这不是合法的 json")
        self.assertEqual(memory._load(p, []), [])

    def test_load_non_list_returns_default(self):
        p = os.path.join(self.chat_dir("private:10001"), "diary.json")
        self.write_json(p, {"不是": "列表"})
        self.assertEqual(memory._load(p, []), [])

    def test_save_replaces_atomically(self):
        # 正常情况下写完之后不应该留下 .tmp，目标文件内容完整。
        p = os.path.join(self.data_dir, "chats", "private_10001", "diary.json")
        memory._save(p, [{"a": 1}])
        self.assertFalse(os.path.exists(p + ".tmp"))
        self.assertEqual(self.read_json(p), [{"a": 1}])

    def test_save_crash_mid_write_does_not_destroy_original(self):
        # 文档第六节点名的事故：非原子写在写到一半时崩溃，把文件截成 0 字节。
        # memory._save 先写 .tmp 再 os.replace，所以中途崩溃应该只留下一个
        # 半截的 .tmp，原来的文件保持完整。
        p = os.path.join(self.data_dir, "chats", "private_10001", "diary.json")
        memory._save(p, [{"memory_content": "原内容", "first_time": T0}])

        real_open = open

        def boom(path, mode="r", *a, **k):
            # 临时文件名现在是 path + ".tmp-<pid>-<tid>"，用「包含 .tmp」匹配
            if ".tmp" in str(path) and "w" in mode:
                f = real_open(path, mode, *a, **k)
                f.write("{")
                f.close()
                raise OSError("模拟写到一半断电")
            return real_open(path, mode, *a, **k)

        with mock.patch("builtins.open", side_effect=boom):
            with self.assertRaises(OSError):
                memory._save(p, [{"memory_content": "新内容", "first_time": T0 + 1}])
        self.assertEqual(self.read_json(p)[0]["memory_content"], "原内容")

    def test_recall_when_rerank_raises_still_returns(self):
        # deepseek 挂了的时候召回要降级，不能把异常甩给调用方。
        p = os.path.join(self.chat_dir("group:20002"), "diary.json")
        self.write_json(p, [_entry("（测试数据）今天去爬山了。", T0, key="group:20002", things="爬山")])
        with mock.patch.object(config, "deepseek_complete", side_effect=RuntimeError("deepseek 挂了")):
            out = memory.recall("爬山", max_total=3, with_ids=True)
        self.assertGreaterEqual(len(out["ids"]), 1)
        self.assertEqual(out["ids"][0]["first_time"], T0)

    def test_diary_cache_invalidates_after_write(self):
        p = os.path.join(self.chat_dir("group:20002"), "diary.json")
        self.write_json(p, [_entry("第一条。", T0, key="group:20002")])
        first = memory._load_all_diaries()
        self.assertEqual(len(first), 1)
        self.write_json(p, [
            _entry("第一条。", T0, key="group:20002"),
            _entry("第二条。", T0 + 1, key="group:20002"),
        ])
        # 写完立刻再读，缓存必须失效，不能还是 1 条。
        second = memory._load_all_diaries()
        self.assertEqual(len(second), 2)


class HelperTests(IsolatedTestCase):
    """不经过 recall 的内部函数：召回的打分、合并的拼接、情绪快照。"""

    def test_count_overlapping_occurrences(self):
        # 「哈哈」在「哈哈哈」里算两次：第二次从第一次起点的下一位开始找。
        self.assertEqual(memory._count("哈哈哈", "哈哈"), 2)
        self.assertEqual(memory._count("今天去爬山", "爬山"), 1)
        self.assertEqual(memory._count("随便一句", ""), 0)
        self.assertEqual(memory._count("没有这个词", "苹果"), 0)

    def test_pick_kind_borrows_from_the_other_side(self):
        memories = [
            {"kind": "subjective"}, {"kind": "subjective"},
            {"kind": "objective"},
        ]
        # 要 3 条、主观占一半 → 主观 2、客观 1，刚好够。
        self.assertEqual(memory._pick_kind([0, 1, 2], memories, 3, 0.5), [0, 1, 2])
        # 要 3 条但全是主观 → 客观配额借给主观，3 条都取到。
        only_subj = [{"kind": "subjective"}] * 3
        self.assertEqual(memory._pick_kind([0, 1, 2], only_subj, 3, 0.5), [0, 1, 2])
        self.assertEqual(memory._pick_kind([0], memories, 0, 0.5), [])

    def test_frequency_fill_skips_recently_called(self):
        now = 1_000_000
        memories = [
            {"memory_content": "甲", "frequency": 5, "last_called": now - 3},   # 3 秒前，跳过
            {"memory_content": "乙", "frequency": 9, "last_called": now - 100},
            {"memory_content": "丙", "frequency": 1, "last_called": None},
            {"memory_content": "   ", "frequency": 99, "last_called": None},    # 空正文，跳过
        ]
        with mock.patch("memory.time.time", return_value=now):
            got = memory._frequency_fill(memories, selected={0}, need=5)
        # 0 已选中被排除；乙频率更高排在丙前面；空正文不进候选。
        self.assertEqual(got, [1, 2])

    def test_frequency_top_orders_by_frequency(self):
        memories = [
            {"memory_content": "甲", "frequency": 1},
            {"memory_content": "乙", "frequency": 30},
            {"memory_content": "", "frequency": 99},
        ]
        self.assertEqual(memory._frequency_top(memories, exclude={1}, n=2), [0])

    def test_clip_sentence_cuts_at_punctuation(self):
        text = "第一句。第二句！第三句？"
        self.assertEqual(memory._clip_sentence(text, 100), text)
        # 限 5 个字：前 5 字是「甲乙丙。丁」，后半段（下标 > 2.5）里最近的句号
        # 在下标 3，切在它后面。
        self.assertEqual(memory._clip_sentence("甲乙丙。丁戊己", 5), "甲乙丙。")
        # 后半段没有任何句号时，就硬切在上限上。
        self.assertEqual(memory._clip_sentence("一二三四五六七八", 4), "一二三四")

    def test_split_head_and_natural_join(self):
        tag, day, period, stamp, rest = memory._split_head(
            "【私聊(10001)】十月二十八日下午，去爬山了")
        self.assertEqual(tag, "【私聊(10001)】")
        self.assertEqual(day, "十月二十八日")
        self.assertEqual(period, "下午")
        self.assertEqual(stamp, "十月二十八日下午")
        self.assertEqual(rest, "去爬山了")

        group = [
            {"first_time": T0, "memory_content": "十月二十八日上午，去爬山了"},
            {"first_time": T0 + 1, "memory_content": "十月二十八日下午，下山吃饭"},
            {"first_time": T0 + 2, "memory_content": "十月二十九日，在家休息"},
        ]
        joined = memory._natural_join(group)
        # 同一天的第二段不再重复日期，改成「到了下午」。
        self.assertIn("到了下午，下山吃饭", joined)
        # 跨天保留完整日期戳。
        self.assertIn("十月二十九日，在家休息", joined)
        # 空正文的条目不参与拼接。
        self.assertEqual(memory._natural_join([{"first_time": T0, "memory_content": "  "}]), "")

    def test_tidy_tail_adds_period(self):
        self.assertEqual(memory._tidy_tail("没有结尾"), "没有结尾。")
        self.assertEqual(memory._tidy_tail("已经有了。"), "已经有了。")
        self.assertEqual(memory._tidy_tail(""), "")

    def test_compress_prompt_contains_the_text(self):
        prompt = memory._compress_prompt("正文内容", 800)
        self.assertIn("正文内容", prompt)
        self.assertIn("800", prompt)

    def test_compress_text_returns_model_output(self):
        # 模型正常回了一段 ≥ 40 字的压缩结果，直接采用，不再重试。
        long_reply = "压" * 50
        with mock.patch.object(config, "deepseek_complete", return_value=long_reply) as call:
            got = memory._compress_text("原" * 900, 800, tries=2)
        self.assertEqual(got, long_reply)
        self.assertEqual(call.call_count, 1)

    def test_compress_text_gives_up_after_short_replies(self):
        # 两次都回了不到 40 字，视为失败，返回空串交给调用方截断。
        # sleep 换成空操作，否则两次重试要白等 3 秒。
        with mock.patch.object(config, "deepseek_complete", return_value="太短"), \
                mock.patch("memory.time.sleep"):
            got = memory._compress_text("原" * 900, 800, tries=2)
        self.assertEqual(got, "")

    def test_emo_snapshot_reads_mood_file(self):
        self.write_json(os.path.join(self.data_dir, "mood.json"),
                        {"happiness": 80, "excited": 20, "negative_emotion": 5})
        self.assertEqual(memory._emo_snapshot(), {"h": 80, "e": 20, "n": 5})
        self.assertEqual(memory._mood_now(), (80, 20, 5))

    def test_emo_snapshot_falls_back_when_missing(self):
        # mood.json 不存在时给中性值，不抛错。
        self.assertEqual(memory._emo_snapshot(), {"h": 50, "e": 50, "n": 0})
        self.assertEqual(memory._mood_now(), (50, 50, 0))

    def test_emo_distance(self):
        self.assertEqual(memory._emo_distance(None, {"h": 50}), 999)
        # |80-50| + |20-60| + |10-0| * 0.5 = 30 + 40 + 5
        self.assertEqual(memory._emo_distance({"h": 80, "e": 20, "n": 10},
                                              {"h": 50, "e": 60, "n": 0}), 75.0)

    def test_all_short_term_keeps_only_lines_with_emotion(self):
        self.write_json(os.path.join(self.chat_dir("private:10001"), "short_term.json"), [
            {"content": "有情绪", "time": T0, "emo": {"h": 70}},
            {"content": "没情绪", "time": T0 + 1},
        ])
        rows = memory._all_short_term()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["content"], "有情绪")

    def test_diary_covering_prefers_exact_range(self):
        memories = [
            {"first_time": T0, "last_time": T0 + 100, "source_from": T0, "source_to": T0 + 100},
            {"first_time": T0 + 1000, "last_time": T0 + 1000},
        ]
        # 落在第一篇的 source 区间里，gap 为 0，应该选它。
        self.assertIs(memory._diary_covering(T0 + 50, memories), memories[0])
        # 两边都覆盖不到时，选时间上更近的那篇。
        self.assertIs(memory._diary_covering(T0 + 900, memories), memories[1])

    def test_emotion_echo_nudges_mood_every_fifth_tick(self):
        mood_path = os.path.join(self.data_dir, "mood.json")
        self.write_json(mood_path, {"happiness": 50, "excited": 60, "echo_tick": 4})
        memories = [{"emo": {"h": 70, "e": 40}}]
        got = memory._emotion_echo(memories, picked=[0])
        # (70-50)*0.2 = +4，(40-60)*0.2 = -4。
        self.assertEqual(got, {"dh": 4, "de": -4})
        saved = self.read_json(mood_path)
        self.assertEqual(saved["temp_happiness"], 54)
        self.assertEqual(saved["excited"], 56)
        self.assertEqual(saved["echo_tick"], 5)

    def test_emotion_echo_skips_between_ticks(self):
        mood_path = os.path.join(self.data_dir, "mood.json")
        self.write_json(mood_path, {"happiness": 50, "excited": 60, "echo_tick": 0})
        got = memory._emotion_echo([{"emo": {"h": 90, "e": 90}}], picked=[0])
        self.assertIsNone(got)
        # 计数照样加一，只是这一轮不动情绪。
        self.assertEqual(self.read_json(mood_path)["echo_tick"], 1)
        # 没召回任何东西时直接返回，连 mood.json 都不碰。
        self.assertIsNone(memory._emotion_echo([{}], picked=[]))

    def test_extra_by_emotion_picks_closest_mood(self):
        self.write_json(os.path.join(self.data_dir, "mood.json"),
                        {"happiness": 80, "excited": 80, "negative_emotion": 0})
        self.write_json(os.path.join(self.chat_dir("private:10001"), "short_term.json"), [
            {"content": "低落", "time": T0, "emo": {"h": 10, "e": 10, "n": 0}},
            {"content": "高兴", "time": T0 + 5, "emo": {"h": 82, "e": 78, "n": 0}},
        ])
        memories = [
            {"first_time": T0, "last_time": T0, "memory_content": "低落的那天"},
            {"first_time": T0 + 5, "last_time": T0 + 5, "memory_content": "高兴的那天"},
        ]
        # 当前心情 80/80，抽样里最接近的是「高兴」，它被第二篇日记覆盖。
        self.assertEqual(memory._extra_by_emotion(memories, picked=[], take=10), 1)
        # 已经在 picked 里的不重复返回。
        self.assertIsNone(memory._extra_by_emotion(memories, picked=[1], take=10))

    def test_hot_tracking_persists_across_recalls(self):
        # 2026-11-06 已修：原来 _write_back 只在「摘到原文」时调用，
        # 而摘原文要求先攒够 3 次命中 —— 鸡生蛋，热度机制从没生效过。
        # 现在只要记过命中就写回，recall_hits 会跨调用累积。
        # （原来这条叫 test_hot_tracking_never_persists，断言的是"永远写不回"。）
        p = os.path.join(self.chat_dir("group:20002"), "diary.json")
        now = T0 + 1000
        self.write_json(p, [_entry("（测试数据）今天去爬山了。", T0, key="group:20002", things="爬山",
                             recall_hits=[now - 120, now - 60], hot_used=0)])
        with mock.patch("memory.time.time", return_value=now):
            memory.recall("爬山", max_total=3, with_ids=True)
        row = self.read_json(p)[0]
        self.assertEqual(row["recall_hits"], [now - 120, now - 60, now],
                         "这次的命中应该记上并写回")
        self.assertEqual(row["hot_used"], 0)

    def test_trim_short_term_keeps_the_tail(self):
        p = os.path.join(self.chat_dir("private:10001"), "short_term.json")
        self.write_json(p, [{"content": "甲", "time": T0},
                            {"content": "乙", "time": T0 + 1},
                            {"content": "丙", "time": T0 + 2}])
        memory._trim_short_term("private:10001", keep=2)
        left = self.read_json(p)
        self.assertEqual([m["content"] for m in left], ["乙", "丙"])
        # 没超过上限时原样不动。
        memory._trim_short_term("private:10001", keep=10)
        self.assertEqual(len(self.read_json(p)), 2)


class OllamaDownTests(IsolatedTestCase):
    """场景 16：ollama 挂了要降级，recall 不能崩。"""

    def test_recall_survives_embed_failure(self):
        import vectors
        p = os.path.join(self.chat_dir("group:20002"), "diary.json")
        self.write_json(p, [_entry("（测试数据）今天去爬山了。", T0, key="group:20002", things="爬山")])
        with mock.patch.object(vectors, "embed", return_value=[]):
            out = memory.recall("爬山", max_total=3, with_ids=True)
        self.assertIsInstance(out, dict)
        self.assertIn("long_term", out)
        self.assertLessEqual(len(out["ids"]), 3)
