"""让 ``python -m unittest discover -s tests`` 能找到 code/ 下的被测模块。

discover 导入测试模块时，``tests`` 目录本身就在 sys.path 上（它是顶层目录），
所以这个文件一定比各个 test_*.py 先执行。被测代码在上一级的 code/ 里。
"""
import os
import sys

_CODE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "code")
_CODE = os.path.normpath(_CODE)
if _CODE not in sys.path:
    sys.path.insert(0, _CODE)
