"""进入关卡 —— 只在画面判据明确时才发键，不做任何盲按

用法:
  py tools\\start_game.py            # 只报告当前画面，不发任何键
  py tools\\start_game.py --resume   # 停在 Continue 画面时按一次 Z 续关

为什么不再自动导航菜单：`curState` 在标题/主菜单/难度/角色/御札/模式之间恒为 1，
**区分不了**，于是只能连续盲按 Z 与方向键 —— 那正是"把续关拨成不续关"的根源。
菜单内部分屏的判据尚未定位（见 MEMMAP §8 末尾），在那之前这里只报告、不按键。
"""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import th06
from read_bullets import read_lives
from screen import read_state, screen_of
from winmem import module_base, find_windows, set_foreground


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--resume', action='store_true',
                    help='停在 Continue 画面时按一次 Z 续关')
    args = ap.parse_args()

    p, pid = th06.get_proc()
    mb = module_base(pid, 'th06nc.exe')[0]
    st = read_state(p, mb)
    code, desc, ok = screen_of(st)
    print(f'PID {pid}，基址 0x{mb:X}。')
    print(f'当前画面：{code}，{desc}。')
    print(f'  curState={st["cur_state"]} Lives={st["lives"]} Bombs={st["bombs"]} '
          f'0x4FF0F2={st["retry"]} deaths={st["deaths"]}')

    if code == 'IN_GAME':
        print('已在关卡中，无需操作。')
    elif code == 'CONTINUE':
        if not args.resume:
            print('停在 Continue 画面。如需按 Z 续关，请显式加 --resume。')
        else:
            hwnd = find_windows(pid=pid)[0][0]
            set_foreground(hwnd)
            time.sleep(0.4)
            th06.tap('z', 60)
            time.sleep(1.2)
            c2, d2, _ = screen_of(read_state(p, mb))
            print(f'  续关后：{c2}，{d2}，Lives={read_lives(p, mb)}。')
    else:
        print('当前不在关卡中，且菜单内部分屏无法区分，不发送任何按键。')
        print('   请手动进入关卡，或先补上菜单判据（见 MEMMAP §8）。')
    p.close()


if __name__ == '__main__':
    main()
