"""notebook.py：笔记的文件名校验与读写。

``notebook.ROOT`` 默认指向 ``D:\\AI\\笔记``，那是禁止写入的真实目录。
底座在 setUp 里把它改到了临时目录，这里的用例只碰临时目录。

两处按代码改过：

* ``list_notes`` 给的是 ``preview``（开头 40 字）和 ``kb``，不是 ``head`` / ``bytes``。
* ``read_note`` 不校验文件名。名字不合法但文件不存在时，返回的是
  ``not_found``，还带上清洗后的文件名和一句 hint。
"""
import os

import _base  # noqa: F401  先把 code/ 加进 sys.path
import notebook

from _base import IsolatedTestCase


class NotebookTests(IsolatedTestCase):
    def test_root_is_redirected(self):
        # 防呆：确认没有一个用例会写到真实目录。
        self.assertNotEqual(notebook.ROOT, r"D:\AI\笔记")
        self.assertTrue(notebook.ROOT.startswith(self.data_dir))

    def test_bad_names_rejected(self):
        for name in ("1.txt", "笔记.txt", "a.txt", "   "):
            result = notebook.write_note(name, "内容")
            self.assertIs(result["ok"], False, name)
            self.assertEqual(result["reason"], "bad_name", name)
            self.assertIn("hint", result)

    def test_space_lets_a_generic_name_through(self):
        # 缺陷：校验先把数字、横线、空格、句点从主干里剥掉，再拿**剥掉之后**的
        # 主干去对黑名单。黑名单里是「新建文本文档」，但剥空格只发生在算长度
        # 那一步，对黑名单时用的是原文。于是「新建 文本文档.txt」两边都过：
        # 主干去掉空格还剩 6 个字，原文又对不上黑名单。
        result = notebook.write_note("新建 文本文档.txt", "内容")
        self.assertIs(result["ok"], True)
        self.assertEqual(result["name"], "新建 文本文档.txt")

    def test_bad_name_keeps_reason_but_names_the_file(self):
        result = notebook.write_note("1", "内容")
        self.assertEqual(result["name"], "1.txt")

    def test_empty_content_rejected(self):
        result = notebook.write_note("2026-11-06-测试爬山.txt", "   ")
        self.assertEqual(result["ok"], False)
        self.assertEqual(result["reason"], "empty")

    def test_too_long_rejected(self):
        result = notebook.write_note("2026-11-06-测试爬山.txt", "字" * (notebook.MAX_WRITE + 1))
        self.assertEqual(result["reason"], "too_long")
        self.assertEqual(result["limit"], notebook.MAX_WRITE)

    def test_write_then_read_roundtrip(self):
        result = notebook.write_note("2026-11-06-测试爬山.txt", "今天去爬山了")
        self.assertIs(result["ok"], True)
        self.assertEqual(result["chars"], len("今天去爬山了"))
        self.assertIs(result["created"], True)
        got = notebook.read_note("2026-11-06-测试爬山.txt")
        self.assertIs(got["ok"], True)
        self.assertEqual(got["content"], "今天去爬山了\n")
        self.assertIs(got["truncated"], False)

    def test_append_mode_adds_separator_and_timestamp(self):
        notebook.write_note("2026-11-06-测试爬山.txt", "第一段")
        second = notebook.write_note("2026-11-06-测试爬山.txt", "第二段", mode="append")
        self.assertIs(second["created"], False)
        got = notebook.read_note("2026-11-06-测试爬山.txt")["content"]
        self.assertIn("第一段", got)
        self.assertIn("\n---\n", got)
        self.assertGreater(got.index("第二段"), got.index("第一段"))

    def test_overwrite_replaces(self):
        notebook.write_note("2026-11-06-测试爬山.txt", "旧内容很长")
        notebook.write_note("2026-11-06-测试爬山.txt", "新内容", mode="overwrite")
        self.assertEqual(notebook.read_note("2026-11-06-测试爬山.txt")["content"], "新内容\n")

    def test_read_missing_returns_not_found(self):
        got = notebook.read_note("2026-11-06-不存在的笔记.txt")
        self.assertEqual(got["ok"], False)
        self.assertEqual(got["reason"], "not_found")
        self.assertEqual(got["name"], "2026-11-06-不存在的笔记.txt")
        self.assertIn("hint", got)

    def test_read_does_not_validate_the_name(self):
        # 读的时候不走文件名校验：名字再短，文件不存在也只是 not_found。
        got = notebook.read_note("1.txt")
        self.assertEqual(got["reason"], "not_found")
        self.assertEqual(got["name"], "1.txt")

    def test_read_truncates_at_max(self):
        notebook.write_note("2026-11-06-很长的一篇测试.txt", "字" * (notebook.MAX_READ + 50))
        got = notebook.read_note("2026-11-06-很长的一篇测试.txt")
        self.assertIs(got["truncated"], True)
        self.assertEqual(got["chars"], notebook.MAX_READ)

    def test_list_notes_shows_preview(self):
        notebook.write_note("2026-11-06-测试爬山.txt", "今天去爬山了，带了水。")
        notes = notebook.list_notes()
        self.assertEqual(len(notes), 1)
        self.assertEqual(notes[0]["name"], "2026-11-06-测试爬山.txt")
        self.assertIn("今天去爬山了", notes[0]["preview"])
        self.assertLessEqual(len(notes[0]["preview"]), 40)
        # 不足 0.05 KB 时 round(..., 1) 是 0.0，字段在但显示成 0。
        self.assertEqual(notes[0]["kb"], 0.0)
        self.assertRegex(notes[0]["updated"], r"\d{2}-\d{2} \d{2}:\d{2}")

    def test_list_notes_empty_dir(self):
        self.assertEqual(notebook.list_notes(), [])

    def test_list_notes_ignores_non_txt(self):
        os.makedirs(notebook.ROOT, exist_ok=True)
        with open(os.path.join(notebook.ROOT, "readme.md"), "w", encoding="utf-8") as f:
            f.write("不是笔记")
        self.assertEqual(notebook.list_notes(), [])

    def test_adds_txt_suffix(self):
        notebook.write_note("2026-11-06-没有后缀", "内容")
        self.assertTrue(os.path.exists(os.path.join(notebook.ROOT, "2026-11-06-没有后缀.txt")))

    def test_strips_illegal_characters(self):
        result = notebook.write_note("2026-11-06-含有:非法*字符", "内容")
        self.assertIs(result["ok"], True)
        self.assertNotIn(":", os.path.basename(result["name"]))
        self.assertNotIn("*", result["name"])
