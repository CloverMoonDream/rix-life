"""按指定顺序加载测试模块，确认结果不依赖发现顺序。"""
import sys
import unittest

import _base  # noqa: F401  先把 code/ 加进 sys.path

ORDER = [
    "test_notebook", "test_profiles", "test_emotion_memory",
    "test_vectors", "test_memory", "test_attributes", "test_config",
]

loader = unittest.defaultTestLoader
suite = unittest.TestSuite()
for name in ORDER:
    suite.addTests(loader.loadTestsFromName(name))
result = unittest.TextTestRunner(verbosity=1).run(suite)
print("ORDER_OK=%s" % result.wasSuccessful())
sys.exit(0 if result.wasSuccessful() else 1)
