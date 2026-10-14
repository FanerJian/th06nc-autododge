"""实机验证「低速模式」的按键链路 —— 脚本发的 Shift 游戏到底认不认

为什么单独一个工具：`check_autofire.py` 只能桩化验证「**什么时候**该按 Shift」，
而「按了之后游戏是否真的进低速」必须真机确认。依据（反汇编 `Player__OnUpdate`
0x690A2 段 + 自机结构常量 `+0x7860/0x7864` = 4.0/2.0）说 Shift 会把输入位图
`0xA6EC60` 的 bit2 置位、速度改用慢档 —— 但那终究是从代码推出来的。

判据：
  1. 按住 Shift 时输入位图 bit2 置位（游戏收到键）；
  2. 松开后 bit2 归零；
  3. 顺带打印自机结构的 focus 标志与四个速度字段（反汇编依据的实时值）。

安全性：**只按 Shift、不按方向键**，自机不动，所以不会因移动撞弹；
但仍然会抢前台约 0.6 秒 —— 所以先查「自机旁边有没有子弹」，太近就拒绝执行。
低速的实际速度比值另用 `py tools\\calib_speed.py --focus` 标定。

用法:
  py tools\\verify_focus.py                 # 自动切前台，0.6 秒后还原
  py tools\\verify_focus.py --no-focus      # 不抢前台（自己先把游戏切过来）
  py tools\\verify_focus.py --near 30       # 放宽「最近子弹」安全距离（默认 60px）
"""
import argparse
import ctypes
import os
import struct
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import th06
from calib_speed import wait_frames
from offsets import (FOCUS_INPUT_BIT, INPUT, PLAYER_BASE, PLAYER_OFF_FOCUS,
                     PLAYER_OFF_SPD_DIAG_FAST, PLAYER_OFF_SPD_DIAG_SLOW,
                     PLAYER_OFF_SPD_FAST, PLAYER_OFF_SPD_SLOW)
from read_bullets import read_bullets, read_player
from screen import read_state, screen_of
from winmem import find_windows, module_base, set_foreground

SAFE_NEAR = 60.0             # 最近子弹比它近就不动手（别在人家的弹幕里抢前台）
HOLD_FRAMES = 6              # 按下后先跑几帧再采样（按键送达要跨帧）
SAMPLES = 12


def snapshot(p, mb):
    """一帧读数：(输入位图, focus 标志, 四个速度字段)"""
    d = p.read(mb + INPUT, 4)
    inp = struct.unpack('<I', d)[0] if d and len(d) == 4 else -1
    raw = p.read(mb + PLAYER_BASE + PLAYER_OFF_FOCUS, 1)
    foc = raw[0] if raw else -1
    sp = []
    for off in (PLAYER_OFF_SPD_FAST, PLAYER_OFF_SPD_SLOW,
                PLAYER_OFF_SPD_DIAG_FAST, PLAYER_OFF_SPD_DIAG_SLOW):
        raw = p.read(mb + PLAYER_BASE + off, 4)
        sp.append(struct.unpack('<f', raw)[0] if raw and len(raw) == 4 else float('nan'))
    return inp, foc, sp


def nearest_bullet(p, mb):
    r = read_bullets(p, mb)
    if r is None:
        return None
    _, bx, by, _, _, _ = r
    if not len(bx):
        return float('inf')
    px, py = read_player(p, mb)
    return float(((bx - px) ** 2 + (by - py) ** 2).min() ** 0.5)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--no-focus', action='store_true', help='不抢前台（自己先切好）')
    ap.add_argument('--near', type=float, default=SAFE_NEAR,
                    help=f'最近子弹安全距离(px)，默认 {SAFE_NEAR:.0f}')
    args = ap.parse_args()

    p, pid = th06.get_proc()
    mb = module_base(pid, 'th06nc.exe')[0]
    hwnd = find_windows(pid=pid)[0][0]
    code, desc, _ = screen_of(read_state(p, mb))
    near = nearest_bullet(p, mb)
    print(f'PID {pid}  基址 0x{mb:X}  hwnd 0x{hwnd:X}')
    print(f'画面 {code}（{desc}）')
    if near is None:
        print('✗ 子弹读取失败 —— 未发送任何按键')
        p.close()
        return 1
    print(f'最近子弹 {near:.1f}px')

    if code not in ('IN_GAME', 'NO_LIVES'):
        print('✗ 需要游戏停在关卡里（暂停菜单不刷新输入位图）。未发送任何按键。')
        p.close()
        return 1
    if near < args.near:
        print(f'✗ 最近子弹 {near:.1f}px < {args.near:.0f}px —— 正在弹幕里，'
              '拒绝抢前台（未发送任何按键）。等关卡开头的飞行段 / 对话时再跑。')
        p.close()
        return 1
    if wait_frames(p, mb, 3) == 0:
        print('✗ 帧计数不走（游戏被暂停或最小化）—— 未发送任何按键')
        p.close()
        return 1

    orig = None
    if not args.no_focus:
        orig = ctypes.WinDLL('user32').GetForegroundWindow()
        set_foreground(hwnd)
        time.sleep(0.4)
        if th06.user32.GetForegroundWindow() != hwnd:
            print('✗ 游戏未取得前台焦点 —— 未发送任何按键')
            p.close()
            return 1

    ok = False
    try:
        inp0, foc0, sp = snapshot(p, mb)
        print(f'基线     ：Input=0x{inp0:04X}  focus={foc0}   速度 直快={sp[0]:g} 直慢={sp[1]:g} '
              f'斜快={sp[2]:g} 斜慢={sp[3]:g}')
        if sp[0] and sp[1]:
            print(f'           结构常量比值 慢/快 = {sp[1] / sp[0]:.4f}（依据预期 0.5）'
                  + ('  ✓' if abs(sp[1] / sp[0] - 0.5) < 0.01 else '  ⚠ 与依据不符'))

        th06.key_down('shift')
        if wait_frames(p, mb, HOLD_FRAMES) == 0:
            print('✗ 按住 Shift 期间帧计数停了 —— 结果不可信')
            return 1
        hits = []
        for _ in range(SAMPLES):
            hits.append(snapshot(p, mb)[0])
            time.sleep(0.008)
        foc_held = snapshot(p, mb)[1]
        th06.key_up('shift')
        wait_frames(p, mb, HOLD_FRAMES)
        inp2, foc2, _ = snapshot(p, mb)

        lit = sum(1 for v in hits if v & FOCUS_INPUT_BIT)
        print(f'按住 Shift：Input 采样 {[f"0x{v:04X}" for v in hits]}')
        print(f'            focus 标志={foc_held}')
        print(f'松开后   ：Input=0x{inp2:04X}  focus={foc2}')
        print()
        c1 = lit > 0
        c2 = not (inp2 & FOCUS_INPUT_BIT)
        print(f'{"✓" if c1 else "✗"} Shift 送达游戏（输入位图 bit2 置位）：{lit}/{len(hits)} 次采样')
        print(f'{"✓" if c2 else "✗"} 松开后 bit2 归零')
        print(f'·  focus 标志（Player+0x{PLAYER_OFF_FOCUS:X}）={"跟上了" if foc_held else "没跟上"}'
              '（无方向输入时该标志可能不刷新，仅供参考）')
        ok = c1 and c2
        print('\n判定：' + ('✓ 低速模式的按键链路成立' if ok
                          else '✗ 未确认 —— Shift 没被游戏收到，低速模式不会生效'))
    except KeyboardInterrupt:
        print('\n（中断）')
    finally:
        for k in ('shift', 'up', 'down', 'left', 'right'):
            th06.key_up(k)
        if orig:
            set_foreground(orig)
    p.close()
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
