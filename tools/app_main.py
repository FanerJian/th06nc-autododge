"""应用入口（源码双击与打包 exe 共用）—— 自检 → 自动重定位 → 拉起游戏 → 开控制台

为什么独立成文件：PyInstaller 只静态分析 `.py`，依赖树必须从真正的入口开始。
`tools/launcher.pyw` 因此退化成两行壳（桌面快捷方式仍指向它，双击不闪黑框）。

为什么是"启动器"而不是注入式 mod：本项目是**外部辅助**（不注入、不替换 DLL、
不改游戏文件）—— 本文件只负责把游戏拉起来、把控制台打开；真正的按键仍全部走
`dodge.py` 的安全闸。

用法:
  双击 tools\\launcher.pyw              （源码）或发布包里的 exe
  py tools\\app_main.py --auto          先走 Steam 启动游戏，再自动连接
  py tools\\app_main.py --check         只做环境自检，不开窗口
  <exe> --run autofix                  打包版内部子命令：exe 里没有 .py 可执行
"""
import argparse
import os
import subprocess
import sys
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import paths                                                   # noqa: E402

LOG = paths.log_path('launcher.log')


def _fix_streams():
    """让 print 在任何启动方式下都不会炸；返回「有没有真控制台」

    两种坏情况，任一都会让 alert() 自己也抛异常 → 彻底静默、用户什么都看不到：
      · pythonw / 打包版（双击的常规方式）：sys.stdout / sys.stderr 是 None
      · 有控制台但编码是 GBK：`✓` / `✗` 这类字符编不出来（实测 UnicodeEncodeError）
    """
    has_console = sys.stdout is not None
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    log = open(LOG, 'a', encoding='utf-8', buffering=1)
    if sys.stdout is None:
        sys.stdout = log
    if sys.stderr is None:
        sys.stderr = log
    for name in ('stdout', 'stderr'):
        f = getattr(sys, name, None)
        if f is not None and hasattr(f, 'reconfigure'):
            try:
                f.reconfigure(encoding='utf-8', errors='replace')
            except Exception:                            # noqa: BLE001
                pass
    return has_console


def alert(title, msg):
    """GUI 起不来时唯一还能通知用户的途径；连弹窗都失败就只剩日志

    `TH06NC_NO_ALERT=1` 时只写日志不弹窗 —— 打包脚本与 CI 的冒烟测试用，
    否则模态窗会一直等人点确定，把构建卡死。
    """
    try:
        print(f'{title}\n{msg}')
    except Exception:                                    # noqa: BLE001
        pass
    if os.environ.get('TH06NC_NO_ALERT'):
        return
    try:
        import tkinter as tk
        from tkinter import messagebox
        r = tk.Tk()
        r.withdraw()
        messagebox.showerror(title, msg)
        r.destroy()
    except Exception as e:                               # noqa: BLE001
        print(f'（弹窗也失败了：{e}）')


def run_subcommand(name, rest):
    """打包版内部子命令 —— exe 里没有 `.py` 可执行，只能再拉一个自己

    子进程而不是同进程调用：`autofix` 要用 capstone 反汇编整个 exe（约一分钟），
    放主进程里崩了会连带控制台一起没。名字在这里**显式 import**，
    否则打包器看不到 autofix（连带 capstone / relocate）这棵依赖树。
    """
    if name == 'autofix':
        import autofix
        sys.argv = ['autofix'] + list(rest)
        return autofix.main()
    print(f'✗ 未知子命令：{name}')
    return 2


def ensure_addrs():
    """地址没适配当前构建就自动重定位 —— 「游戏更新也能自动适配」的落点

    纯静态（读 exe 里的特征），不需要游戏在关卡内，一次约一分钟。
    子进程输出重定向到日志：pythonw / 打包版下没有控制台，不重定向就什么都留不下。
    """
    try:
        import addr
    except Exception as e:                               # noqa: BLE001
        print(f'! 地址模块不可用（{type(e).__name__}: {e}），跳过自动适配')
        return
    level, text = addr.status()
    if level != 'bad':
        return
    print(f'! {text}')
    print('  自动重定位中（读 exe 特征，不需要游戏在关卡内）…')
    logpath = paths.log_path('autofix.log')
    os.makedirs(os.path.dirname(logpath), exist_ok=True)
    cmd = ([sys.executable, '--run', 'autofix'] if paths.FROZEN
           else [sys.executable, os.path.join(HERE, 'autofix.py')])
    with open(logpath, 'a', encoding='utf-8') as logf:
        logf.write(f'\n===== {time.strftime("%Y-%m-%d %H:%M:%S")} 自动重定位 =====\n')
        logf.flush()
        rc = subprocess.call(cmd, stdout=logf, stderr=subprocess.STDOUT,
                             cwd=paths.app_dir())
    if rc == 0:
        print(f'✓ 已写入地址缓存（细节见 {logpath}），继续启动')
    else:
        print(f'✗ 自动重定位失败（退出码 {rc}）—— 细节见 {logpath}')


def check_env():
    """环境自检 -> [(级别, 文本)]

    Python 版本 / 依赖 / Steam / 游戏目录 / 构建版本全在 `env.check()` 里，别在这里重写；
    这里只额外确认整条工具链 import 得起来。
    """
    import env
    items = env.check()
    try:
        import dodge_gui  # noqa: F401
    except Exception as e:
        items.append(('bad', f'导入工具链失败：{type(e).__name__}: {e}'))
    return items


def game_running():
    from winmem import find_pids
    return bool(find_pids('th06nc'))


def launch_game(wait=90, log=print):
    """走 Steam 启动 —— 直接跑 exe 会因 SteamAPI_RestartIfNecessary 立即退出"""
    if game_running():
        log('游戏已在运行')
        return True
    import env
    steam, src = env.steam_exe()
    if not steam:
        log(f'✗ 定位不到 Steam：{src}')
        return False
    subprocess.Popen([steam, '-applaunch', env.APPID])
    log(f'已请求 Steam 启动（{src}），等待进程…')
    t0 = time.time()
    while time.time() - t0 < wait:
        if game_running():
            time.sleep(2.0)          # 等窗口建好，否则 find_windows 可能还是空的
            log('游戏进程已出现')
            return True
        time.sleep(0.5)
    log(f'✗ 等了 {wait}s 没等到游戏进程')
    return False


def main():
    has_console = _fix_streams()         # 打包版没有控制台：print 必须先有落点
    if sys.argv[1:2] == ['--run']:       # 内部子命令：exe 里没有 .py 可执行
        return run_subcommand(sys.argv[2], sys.argv[3:])
    ap = argparse.ArgumentParser()
    ap.add_argument('--auto', action='store_true', help='先启动游戏并自动连接')
    ap.add_argument('--check', action='store_true', help='只做环境自检，不开窗口')
    args = ap.parse_args()

    if not args.check:
        ensure_addrs()          # 构建变了先自动重定位，再走自检
    items = check_env()
    mark = {'ok': '✓', 'warn': '!', 'bad': '✗'}
    if args.check:
        bad = sum(1 for level, _ in items if level == 'bad')
        report = '\n'.join(['环境自检：' + ('通过 ✓' if not bad else f'{bad} 个必须修的问题')]
                           + [f'  {mark[level]} {text}' for level, text in items])
        print(report)
        if not has_console:     # 打包版没有控制台：结果同时走弹窗 + launcher.log
            alert('th06nc 自动避弹：环境自检', report)
        return 0 if not bad else 1
    bad = [text for level, text in items if level == 'bad']
    if bad:
        alert('th06nc 自动避弹：无法启动', '\n\n'.join(bad))
        return 1
    for level, text in items:
        if level == 'warn':
            print(f'! {text}')

    if args.auto:
        launch_game(log=lambda m: print(m))
    import dodge_gui
    dodge_gui.main(auto_connect=args.auto)
    return 0


def run():
    """入口包装：任何异常都要留下痕迹 —— 打包版双击时没有控制台可看"""
    try:
        return main()
    except SystemExit:
        raise
    except Exception:
        tb = traceback.format_exc()
        print(tb, file=sys.stderr)
        alert('th06nc 自动避弹：启动失败', tb[-700:])
        return 1


if __name__ == '__main__':
    sys.exit(run())
