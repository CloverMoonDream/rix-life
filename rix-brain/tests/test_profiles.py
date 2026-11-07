"""profiles.py：人物画像的读写与校验。

按代码改过的三点：

* 成功时计数字段叫 ``total``，不叫 ``count``。
* ``field="name"`` 是单独的分支，合法，只改称呼，不进 FIELDS 校验。
* 备份文件名是固定的 ``<key>.json.bak``，不是带时间戳的 ``.bak-``。
"""
import os

import _base  # noqa: F401  先把 code/ 加进 sys.path
import profiles

from _base import IsolatedTestCase


class ProfileTests(IsolatedTestCase):
    def test_read_missing_returns_shell(self):
        got = profiles.read("private:10001")
        self.assertEqual(got["key"], "private:10001")
        self.assertEqual(got["name"], "")
        self.assertEqual(got["updated_at"], 0)
        for field in ("traits", "preferences", "taboos", "routines", "promises", "notes"):
            self.assertEqual(got[field], [])

    def test_read_corrupt_file_returns_shell(self):
        p = profiles._path("private:10001")
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            f.write("{坏的")
        got = profiles.read("private:10001")
        self.assertEqual(got["traits"], [])

    def test_write_then_read_roundtrip(self):
        result = profiles.write("private:10001", "preferences", "喜欢爬山", name="测试用户")
        self.assertIs(result["ok"], True)
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["value"], "喜欢爬山")
        got = profiles.read("private:10001")
        self.assertEqual(got["name"], "测试用户")
        self.assertEqual(got["preferences"], ["喜欢爬山"])
        self.assertGreater(got["updated_at"], 0)

    def test_write_appends_and_dedups(self):
        profiles.write("private:10001", "taboos", "讨厌被叫先生")
        profiles.write("private:10001", "taboos", "讨厌被叫先生")
        profiles.write("private:10001", "taboos", "不吃香菜")
        got = profiles.read("private:10001")
        self.assertEqual(got["taboos"], ["讨厌被叫先生", "不吃香菜"])

    def test_write_without_key_fails(self):
        result = profiles.write("", "notes", "一条")
        self.assertIs(result["ok"], False)
        self.assertEqual(result["reason"], "need_key")
        self.assertIn("private:", result["hint"])

    def test_write_unknown_key_fails(self):
        # 空 key 会被归一成 "unknown"，同样拒绝。
        result = profiles.write("unknown", "notes", "一条")
        self.assertEqual(result["reason"], "need_key")

    def test_write_bad_field_fails(self):
        result = profiles.write("private:10001", "mood", "开心")
        self.assertEqual(result["ok"], False)
        self.assertEqual(result["reason"], "bad_field")
        self.assertIn("traits", result["hint"])

    def test_write_empty_text_fails(self):
        result = profiles.write("private:10001", "notes", "   ")
        self.assertEqual(result, {"ok": False, "reason": "empty"})

    def test_write_name_only(self):
        # field="name" 是合法分支：只改称呼，text 就是新称呼。
        result = profiles.write("private:10001", "name", "只改名字")
        self.assertIs(result["ok"], True)
        self.assertEqual(result["field"], "name")
        self.assertEqual(result["value"], "只改名字")
        self.assertEqual(profiles.read("private:10001")["name"], "只改名字")

    def test_write_name_does_not_touch_fields(self):
        profiles.write("private:10001", "notes", "先记一条")
        profiles.write("private:10001", "name", "新称呼")
        got = profiles.read("private:10001")
        self.assertEqual(got["name"], "新称呼")
        self.assertEqual(got["notes"], ["先记一条"])

    def test_backup_created_before_overwrite(self):
        profiles.write("private:10001", "notes", "第一条")
        profiles.write("private:10001", "notes", "第二条")
        backup = profiles._path("private:10001") + ".bak"
        self.assertTrue(os.path.exists(backup))
        # 备份留的是覆盖前的内容，不是最新的。
        import json
        with open(backup, encoding="utf-8") as f:
            old = json.load(f)
        self.assertEqual(old["notes"], ["第一条"])

    def test_first_write_has_no_backup(self):
        profiles.write("private:10001", "notes", "第一条")
        self.assertFalse(os.path.exists(profiles._path("private:10001") + ".bak"))

    def test_listing_summarises(self):
        profiles.write("private:10001", "notes", "一条", name="甲")
        profiles.write("private:10002", "taboos", "香菜", name="乙")
        rows = profiles.listing()
        by_key = {r["key"]: r for r in rows}
        self.assertEqual(set(by_key), {"private:10001", "private:10002"})
        self.assertEqual(by_key["private:10001"]["name"], "甲")
        self.assertEqual(by_key["private:10001"]["items"], 1)

    def test_field_capped_at_forty(self):
        for i in range(45):
            profiles.write("private:10001", "notes", "第%d条" % i)
        got = profiles.read("private:10001")
        self.assertEqual(len(got["notes"]), 40)
        self.assertEqual(got["notes"][0], "第5条")
        self.assertEqual(got["notes"][-1], "第44条")
