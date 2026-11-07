"""emotion_memory.py：纯函数，没有磁盘和网络。

``excited_and_negative_memory`` 不按比例算。它按 excited 分五档，
直接给出主客观条数，而且两边各自夹在 0~5，**不保证加起来等于 all_memory_num**。
``all_memory_num`` 只在负面情绪落进 [2, 10) 时才参与计算。
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "code")))

import emotion_memory


class HappinessTests(unittest.TestCase):
    def test_neutral_band(self):
        # 31~79 和 91 以上的缺口都落到 else，返回 7。90 本身还在「减一」那档。
        self.assertEqual(emotion_memory.happiness_memory(50), 7)
        self.assertEqual(emotion_memory.happiness_memory(79), 7)
        self.assertEqual(emotion_memory.happiness_memory(31), 7)

    def test_high_band_shrinks(self):
        self.assertEqual(emotion_memory.happiness_memory(80), 6)
        self.assertEqual(emotion_memory.happiness_memory(90), 6)
        self.assertEqual(emotion_memory.happiness_memory(91), 5)
        self.assertEqual(emotion_memory.happiness_memory(100), 5)

    def test_low_band_grows(self):
        self.assertEqual(emotion_memory.happiness_memory(30), 8)
        self.assertEqual(emotion_memory.happiness_memory(20), 8)
        self.assertEqual(emotion_memory.happiness_memory(19), 9)
        self.assertEqual(emotion_memory.happiness_memory(10), 9)
        self.assertEqual(emotion_memory.happiness_memory(9), 10)
        self.assertEqual(emotion_memory.happiness_memory(0), 10)

    def test_out_of_range_falls_back_to_seven(self):
        self.assertEqual(emotion_memory.happiness_memory(-1), 7)
        self.assertEqual(emotion_memory.happiness_memory(150), 7)


class ExcitedTests(unittest.TestCase):
    def test_middle_band(self):
        # 35~65：主观 3，客观 3。没有负面情绪时 all_memory_num 不参与。
        self.assertEqual(emotion_memory.excited_and_negative_memory(35, 0, 10), (3, 3))
        self.assertEqual(emotion_memory.excited_and_negative_memory(65, 0, 10), (3, 3))
        self.assertEqual(emotion_memory.excited_and_negative_memory(50, 0, 0), (3, 3))

    def test_low_band(self):
        self.assertEqual(emotion_memory.excited_and_negative_memory(0, 0, 10), (1, 5))
        self.assertEqual(emotion_memory.excited_and_negative_memory(19, 0, 10), (1, 5))

    def test_lower_middle_band(self):
        self.assertEqual(emotion_memory.excited_and_negative_memory(20, 0, 10), (2, 4))
        self.assertEqual(emotion_memory.excited_and_negative_memory(34, 0, 10), (2, 4))

    def test_upper_middle_band(self):
        self.assertEqual(emotion_memory.excited_and_negative_memory(66, 0, 10), (4, 2))
        self.assertEqual(emotion_memory.excited_and_negative_memory(80, 0, 10), (4, 2))

    def test_high_band(self):
        self.assertEqual(emotion_memory.excited_and_negative_memory(81, 0, 10), (5, 1))
        self.assertEqual(emotion_memory.excited_and_negative_memory(100, 0, 10), (5, 1))

    def test_negative_emotion_rebases_on_total(self):
        # 中档 + 负面 [2,5)：主观变成 4，客观 = all_memory_num - 主观。
        self.assertEqual(emotion_memory.excited_and_negative_memory(50, 2, 10), (4, 5))
        # 负面 [5,10)：主观加 2，但上限是 5。
        self.assertEqual(emotion_memory.excited_and_negative_memory(50, 5, 10), (5, 5))
        # 客观同样夹到 5：低档客观本应是 6，被夹成 5。
        self.assertEqual(emotion_memory.excited_and_negative_memory(10, 3, 10), (4, 5))

    def test_negative_below_two_is_ignored(self):
        self.assertEqual(emotion_memory.excited_and_negative_memory(50, 1, 10), (3, 3))

    def test_out_of_range_excited_raises(self):
        # 缺陷：excited 不在 [0, 100] 时两个局部变量都没有赋值，
        # 直接抛 UnboundLocalError，而不是夹到边界或返回明确的错误。
        with self.assertRaises(UnboundLocalError):
            emotion_memory.excited_and_negative_memory(150, 0, 10)
        with self.assertRaises(UnboundLocalError):
            emotion_memory.excited_and_negative_memory(-1, 0, 10)
