"""源码运行 / 打包运行两套路径的唯一落点

为什么单独一个模块：PyInstaller 打包后 `__file__` 指向解包目录（onedir 是 `_internal/`），
**只读**；可写数据（控制台保存的参数、地址缓存、启动日志）必须落到 exe 旁边。
判断只写在这里，其它模块 import 本模块 —— 别各自再写一遍 `dirname(__file__)`。

| 场景 | 可写根 `app_dir()` | 只读资源根 `res_dir()` |
|---|---|---|
| 源码运行 | 项目根 | 项目根（资源在 `tools/` 下） |
| 打包运行 | exe 所在目录 | 解包目录 `sys._MEIPASS` |

打包时按 `--add-data` 保持 `tools/xxx` 的相对布局，所以 `res('tools', 'a', 'b')`
在两种场景下都成立。
"""
import os
import sys

FROZEN = bool(getattr(sys, 'frozen', False))

_SRC_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def app_dir():
    """可写根目录：打包 = exe 所在目录；源码 = 项目根

    打包版要求这个目录可写（保存参数、autofix 更新地址缓存都写它）。
    装进 `Program Files` 之类只读位置会失败 —— README 里已写明放用户目录。
    """
    if FROZEN:
        return os.path.dirname(os.path.abspath(sys.executable))
    return _SRC_ROOT


def res_dir():
    """只读资源根目录：打包 = 解包目录；源码 = 项目根"""
    if FROZEN:
        return getattr(sys, '_MEIPASS', app_dir())
    return _SRC_ROOT


def res(*parts):
    """只读资源路径，两种场景布局一致（如 `res('tools', 'assets', 'th06nc.ico')`）"""
    return os.path.join(res_dir(), *parts)


def outside(*parts):
    """可写根下的路径（如 `outside('dodge_params.json')`）"""
    return os.path.join(app_dir(), *parts)


def log_path(name):
    """启动日志：源码落 `_tmp/`（临时区，可整目录删）；打包落 exe 旁（无 `_tmp` 概念）"""
    if FROZEN:
        return os.path.join(app_dir(), name)
    return os.path.join(_SRC_ROOT, '_tmp', name)


def external_first(name, *res_parts):
    """可写数据文件：外部优先，缺失时回退包内基线。返回 `(读路径, 写路径)`

    打包版（`addr_cache.json` 的实际用法）：玩家目录里的副本一旦存在就优先，
    `autofix` 更新的是它，包内基线永远不动 —— 升级程序时直接覆盖文件夹即可。
    源码版：只有一处，读写同路径（与打包前行为完全一致）。
    """
    if not FROZEN:
        p = os.path.join(res_dir(), *res_parts)
        return p, p
    ext = os.path.join(app_dir(), name)
    if os.path.exists(ext):
        return ext, ext
    return os.path.join(res_dir(), *res_parts), ext
