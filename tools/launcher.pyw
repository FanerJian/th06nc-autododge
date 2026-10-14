"""桌面一键启动（.pyw 壳）—— 双击不闪黑框

实现全在 `tools/app_main.py`：打包（PyInstaller）需要一个 `.py` 入口才能静态分析依赖树，
`.pyw` 不在 Python 的源码后缀里、import 不进来，所以这里只做转发。
桌面快捷方式仍指向本文件，行为不变。

用法:
  双击本文件
  py tools\\launcher.pyw --check      只做环境自检，不开窗口
  pyw tools\\launcher.pyw --auto      先走 Steam 启动游戏，再自动连接
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import app_main                                                # noqa: E402

if __name__ == '__main__':
    sys.exit(app_main.run())
