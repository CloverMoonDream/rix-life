"""覆盖率统计入口。trace 不支持 ``-m``，所以由它来启动 unittest。"""
import unittest

loader = unittest.TestLoader()
suite = loader.discover("tests")
result = unittest.TextTestRunner(verbosity=1).run(suite)
raise SystemExit(0 if result.wasSuccessful() else 1)
