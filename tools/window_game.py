"""
把游戏窗口改成指定大小/位置（窗口化），并增强输入安全性。
"""
import ctypes
from ctypes import wintypes
import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from winmem import find_pids, find_windows, set_foreground

user32 = ctypes.WinDLL('user32', use_last_error=True)
user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int,
                                ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT]
user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
user32.GetForegroundWindow.restype = wintypes.HWND
user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
user32.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_long]

GWL_STYLE = -16
WS_POPUP = 0x80000000
WS_OVERLAPPEDWINDOW = 0x00CF0000
SWP_NOZORDER = 0x0004
SWP_FRAMECHANGED = 0x0020
SWP_SHOWWINDOW = 0x0040


def find_game_hwnd():
    pids = find_pids('th06nc')
    if not pids:
        return None, None
    ws = find_windows(pid=pids[0], title_sub='Embodiment')
    if not ws:
        ws = find_windows(pid=pids[0])
    return (ws[0][0], ws[0][4]) if ws else (None, None)


def main():
    args = sys.argv[1:]
    hwnd, rect = find_game_hwnd()
    if hwnd is None:
        print('游戏未运行')
        return
    print(f'游戏窗口 hwnd=0x{hwnd:X} rect={rect}')

    if not args:
        fg = user32.GetForegroundWindow()
        print(f'当前前台 hwnd=0x{fg:X}')
        return

    if args[0] == 'move':
        x, y, w, h = (int(v) for v in args[1:5])
        style = user32.GetWindowLongW(hwnd, GWL_STYLE)
        print(f'原样式 0x{style & 0xFFFFFFFF:08X}')
        # 去掉 WS_POPUP, 恢复可调整边框窗口
        newstyle = (style & ~WS_POPUP) | WS_OVERLAPPEDWINDOW
        user32.SetWindowLongW(hwnd, GWL_STYLE, newstyle)
        ok = user32.SetWindowPos(hwnd, None, x, y, w, h,
                                 SWP_NOZORDER | SWP_FRAMECHANGED | SWP_SHOWWINDOW)
        print(f'SetWindowPos -> {bool(ok)}  新样式 0x{newstyle & 0xFFFFFFFF:08X}')
        time.sleep(0.6)
        rc = wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rc))
        print(f'现在 rect=({rc.left},{rc.top},{rc.right},{rc.bottom}) '
              f'尺寸 {rc.right-rc.left}x{rc.bottom-rc.top}')

    elif args[0] == 'focus':
        r = set_foreground(hwnd)
        time.sleep(0.4)
        fg = user32.GetForegroundWindow()
        print(f'set_foreground={r}  前台现在 hwnd=0x{fg:X} '
              f'{"= 游戏 ✓" if fg == hwnd else "≠ 游戏 ✗"}')


if __name__ == '__main__':
    main()
