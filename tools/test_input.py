"""
安全输入测试：不移焦，直接发方向键，看游戏（失焦状态）是否仍响应。
只用方向键 —— 即使打到其他窗口也不会输入文字。
"""
import ctypes
from ctypes import wintypes
import sys
import os
import time
import struct

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import th06
from offsets import PLAYER_X
from winmem import module_base, find_pids, find_windows

user32 = ctypes.WinDLL('user32', use_last_error=True)
user32.GetForegroundWindow.restype = wintypes.HWND

PX = PLAYER_X                    # x / y 相邻，一次读 8 字节


def main():
    p, pid = th06.get_proc()
    mb = module_base(pid, 'th06nc.exe')[0]

    fg = user32.GetForegroundWindow()
    games = find_windows(pid=pid, title_sub='Embodiment')
    ghwnd = games[0][0] if games else 0
    print(f'前台 hwnd=0x{fg:X}   游戏 hwnd=0x{ghwnd:X}   '
          f'{"游戏在前台" if fg == ghwnd else "游戏不在前台 ⚠"}')
    print(f'标题: {games[0][2] if games else "?"}')

    def xy():
        d = p.read(mb + PX, 8)
        return struct.unpack('<2f', d)

    x0, y0 = xy()
    print(f'\n当前自机 ({x0:.2f}, {y0:.2f})')

    print('发送 [左] 0.4s（不移焦）...')
    th06.key_down('left')
    time.sleep(0.4)
    th06.key_up('left')
    time.sleep(0.25)
    x1, y1 = xy()
    print(f'  -> ({x1:.2f}, {y1:.2f})   dx={x1-x0:+.2f}')

    print('发送 [右] 0.4s（不移焦）...')
    th06.key_down('right')
    time.sleep(0.4)
    th06.key_up('right')
    time.sleep(0.25)
    x2, y2 = xy()
    print(f'  -> ({x2:.2f}, {y2:.2f})   dx={x2-x1:+.2f}')

    moved = abs(x1 - x0) > 1 or abs(x2 - x1) > 1
    print(f'\n结论: 游戏{"在失焦状态下仍响应全局按键 ✓" if moved else "失焦时不响应按键 ✗"}')
    p.close()


if __name__ == '__main__':
    main()
