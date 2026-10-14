"""实机验证「死亡炸弹」—— 被击中的 8 帧窗口内按 X，能否取消死亡

为什么单独一个工具：`check_autofire.py` 只能桩化验证「什么时候该按 X」，
而「按了之后游戏是否真的取消死亡」必须真机确认 —— 依据（反汇编 + 原版
`BombData.cpp`）说窗口内按 X 会执行角色 bomb 的 calc、把 playerState 改成
INVULNERABLE，但那终究是从代码推出来的，得看游戏自己认不认。

做法：切前台 → 自机**不动**（就是要挨打）→ 逐帧盯 `playerState`，
一进死亡窗口就立刻按 X，然后把之后 30 帧的状态变化全部打出来。

判据（三条同时成立才算救回）：
  1. `playerState` 从 DEAD(2) 变成 INVULNERABLE(3)；
  2. Bombs 减 1；
  3. Lives 不变、deaths 不变。

用法:
  py tools\\verify_bomb.py                 # 最多等 60 秒，自动切前台
  py tools\\verify_bomb.py --seconds 180   # 等更久（关卡前段没弹幕时用）
  py tools\\verify_bomb.py --no-focus      # 不抢前台（自己先把游戏切过来）
  py tools\\verify_bomb.py --no-press      # 只观察窗口，不按 X（对照：确认会掉命）

⚠ 会抢游戏前台、会让自机挨打。真救不回来就是掉一条命 —— 这正是一次真实验证。
"""
import argparse
import os
import struct
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import th06
from offsets import (BOMBS, DEATHS, LIVES, PLAYER_BASE, PLAYER_OFF_BOMB_INUSE,
                     PLAYER_OFF_RESPAWN, PLAYER_OFF_STATE, PLAYER_STATE_DEAD,
                     PLAYER_STATE_INVULNERABLE, RESPAWN_ALIVE)
from read_bullets import read_player_state  # noqa: F401  （判据同源，见 dodge.BombGuard）
from screen import read_state, screen_of
from winmem import find_windows, module_base, set_foreground

BOMB_KEY = 'x'
BOMB_HOLD_FRAMES = 3          # 与 dodge.BOMB_HOLD 一致：按下沿要跨帧才收得到


def _u8(p, mb, a):
    d = p.read(mb + a, 1)
    return d[0] if d else None


def _i32(p, mb, a):
    d = p.read(mb + a, 4)
    return struct.unpack('<i', d)[0] if d and len(d) == 4 else None


def snapshot(p, mb):
    """一帧的完整判据：状态 / 死亡窗口 / 炸弹 / 残机 / 死亡计数"""
    raw = p.read(mb + PLAYER_BASE + PLAYER_OFF_RESPAWN, PLAYER_OFF_STATE - PLAYER_OFF_RESPAWN + 1)
    return {
        'state': raw[PLAYER_OFF_STATE - PLAYER_OFF_RESPAWN] if raw else None,
        'respawn': struct.unpack('<i', raw[:4])[0] if raw else None,
        'bomb_in_use': _u8(p, mb, PLAYER_BASE + PLAYER_OFF_BOMB_INUSE),
        'bombs': _u8(p, mb, BOMBS),
        'lives': _u8(p, mb, LIVES),
        'deaths': _i32(p, mb, DEATHS),
    }


def fmt(s):
    return (f'state={s["state"]} respawn={s["respawn"]:>2} bombInUse={s["bomb_in_use"]} '
            f'bombs={s["bombs"]} lives={s["lives"]} deaths={s["deaths"]}')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--seconds', type=float, default=60.0, help='最多盯多少秒')
    ap.add_argument('--no-focus', action='store_true', help='不抢前台（自己先切好）')
    ap.add_argument('--no-press', action='store_true', help='只观察，不按 X（对照用）')
    args = ap.parse_args()

    p, pid = th06.get_proc()
    mb = module_base(pid, 'th06nc.exe')[0]
    w = find_windows(pid=pid)
    hwnd = w[0][0]
    print(f'PID {pid}  基址 0x{mb:X}  hwnd 0x{hwnd:X}')

    st = read_state(p, mb)
    code, desc, _ = screen_of(st)
    print(f'开始前画面：{code}（{desc}）')
    if code not in ('IN_GAME', 'CONTINUE'):
        print('✗ 需要游戏停在关卡里（有敌人会打你）。请先进入关卡再跑本工具。')
        p.close()
        return 1

    orig_fg = None
    if not args.no_focus:
        import ctypes
        orig_fg = ctypes.WinDLL('user32').GetForegroundWindow()
        set_foreground(hwnd)
        time.sleep(0.5)

    print(f'盯着 {args.seconds:.0f} 秒，自机不动等着挨打'
          f'{"（不按 X，对照看会不会掉命）" if args.no_press else '，进死亡窗口就按 X'}…')

    base = snapshot(p, mb)
    print(f'起始：{fmt(base)}')
    if base['respawn'] != RESPAWN_ALIVE:
        print(f'⚠ 起始 respawn={base["respawn"]}（存活应为 {RESPAWN_ALIVE}）—— '
              '可能已经在死亡窗口里，或该构建的存活值不同。')

    t0 = time.perf_counter()
    period = 1.0 / 60.0
    windows = []          # 每次死亡窗口：(帧序, 进入时的 respawn, 是否按了 X)
    pressed_hold = 0
    reporting = 0
    last = base
    frame = 0
    try:
        while time.perf_counter() - t0 < args.seconds:
            tick = time.perf_counter()
            frame += 1
            s = snapshot(p, mb)
            code, desc, ok = screen_of(read_state(p, mb))

            if s == last and not reporting:
                if code not in ('IN_GAME', 'DYING'):
                    print(f'✗ 画面变为 {code}（{desc}）—— 结束观测')
                    break
                time.sleep(period)
                continue

            # 死亡窗口 = DEAD 且还有 respawn 帧可用（与 dodge.BombGuard 同一判据）
            in_window = (s['state'] == PLAYER_STATE_DEAD and (s['respawn'] or 0) > 0)
            if in_window and not (last['state'] == PLAYER_STATE_DEAD and (last['respawn'] or 0) > 0):
                print(f'\n[{frame:5d}] ★ 进入死亡窗口：{fmt(s)}')
                windows.append([frame, s['respawn'], False])
                reporting = 30
                if not args.no_press and s['bombs']:
                    th06.key_down(BOMB_KEY)
                    pressed_hold = BOMB_HOLD_FRAMES
                    windows[-1][2] = True
                    print(f'         → 按 {BOMB_KEY.upper()}（按住 {BOMB_HOLD_FRAMES} 帧）')
                elif not s['bombs']:
                    print('         → 没炸弹了，救不了')

            elif reporting > 0:
                print(f'[{frame:5d}]    {fmt(s)}')
                reporting -= 1
                if reporting == 0:
                    ok_rescue = (s['state'] == PLAYER_STATE_INVULNERABLE
                                 and s['lives'] == base['lives']
                                 and s['deaths'] == base['deaths'])
                    verdict = '✓ 救回（死亡被取消）' if ok_rescue else '✗ 没救回来'
                    print(f'         {verdict}')

            if pressed_hold > 0:
                pressed_hold -= 1
                if pressed_hold == 0:
                    th06.key_up(BOMB_KEY)

            last = s
            dt = time.perf_counter() - tick
            if dt < period:
                time.sleep(period - dt)
    except KeyboardInterrupt:
        print('\n（中断）')
    finally:
        if pressed_hold:
            th06.key_up(BOMB_KEY)
        if orig_fg:
            set_foreground(orig_fg)

    print(f'\n观测 {frame} 帧 / {time.perf_counter() - t0:.1f}s')
    end = snapshot(p, mb)
    print(f'结束：{fmt(end)}')
    if not windows:
        print('✗ 这段时间里自机没被击中过 —— 换个有弹幕的位置/时段再跑（Stage 1 前段很空）。')
        p.close()
        return 1
    print(f'死亡窗口 {len(windows)} 次：' +
          '，'.join(f'第 {f} 帧(respawn={r}{"，按了X" if x else "，没按"})' for f, r, x in windows))
    lost = (base['lives'] or 0) - (end['lives'] or 0)
    used = (base['bombs'] or 0) - (end['bombs'] or 0)
    print(f'结果：掉命 {lost} 条，消耗炸弹 {used} 颗')
    good = lost == 0 and used >= 1
    print('判定：' + ('✓ 死亡炸弹成立 —— 窗口内按 X 取消了死亡' if good
                    else '✗ 未确认（掉命说明没救回；一颗炸弹没消耗说明 X 没送达游戏）'))
    p.close()
    return 0 if good else 1


if __name__ == '__main__':
    sys.exit(main())
