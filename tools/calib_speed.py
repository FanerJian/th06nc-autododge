"""标定自机移动速度（px/帧）—— 帧计数计时 + 分方向 + 自动剔除撞墙

为什么不用 sleep 计时：`dodge.py --calib` 与 GUI 的「校准速度」都是"按住右键 1.5s ÷ 90 帧"。
它产出过自相矛盾的数据 —— MEMMAP §1 记的「按右 +92 / 按上 −88 / 按左 −36」，
左移 36px 其实是撞到左边界，不是速度。速度估偏会让 plan() 认为"能到"的位置实际到不了。

做法：以帧计数 `0xC21C00`（每帧 +1）为基准。
  1. 每个方向开测前先走到该方向的**反侧起点**（`start_spot()`）→ 正向至少 328px 余量。
     别用场地正中心：中心到上下边界仅 208px < need 212px，余量校验会全部作废；
  2. 先按住 2 帧再取起点 → 测的是稳态速度，不含按键送达延迟；
  3. 帧计数停滞（暂停/最小化）一律作废。
斜向每轴速度与直向的比值还能判定引擎是否做斜向归一化 —— plan() 的 9 向模型依赖它。

用法:
  py tools\\calib_speed.py               # 4 直向 + 4 斜向，各 40 帧
  py tools\\calib_speed.py --frames 60
  py tools\\calib_speed.py --focus       # 按住 Shift 标定低速（预期 = 高速的精确一半）
需游戏在关卡内（脚本会抢前台并按 Z 解除暂停；不在关卡内则拒绝执行）。
"""
import argparse
import math
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import th06
from offsets import CALC_COUNT, FIELD_CX, FIELD_CY, FIELD_X0, FIELD_X1, FIELD_Y0, FIELD_Y1
from read_bullets import read_player
from screen import read_state, screen_of
from winmem import module_base, find_windows, set_foreground

CENTER = (FIELD_CX, FIELD_CY)
SPEED_GUESS = 4.0            # 仅用于归中的步长估算
CENTER_TOL = 6.0
START_INSET = 40.0           # 出发点离边界多远（贴反侧起步，给正向留足空间）

STRAIGHT = [('right', (1, 0)), ('left', (-1, 0)), ('up', (0, -1)), ('down', (0, 1))]
DIAGONAL = [('ur', (1, -1)), ('ul', (-1, -1)), ('dr', (1, 1)), ('dl', (-1, 1))]


def start_spot(direction):
    """该方向的出发点：贴到要走的反侧，保证正向余量足够

    别用场地正中心当起点：中心到上下边界只有 208px，而 need = frames×5+12 = 212px，
    余量校验必然全部作废（实测 8 向全跳过）。贴反侧后每向至少有 328px。
    """
    dx, dy = direction
    bx = FIELD_X0 + START_INSET if dx > 0 else (FIELD_X1 - START_INSET if dx < 0 else FIELD_CX)
    by = FIELD_Y0 + START_INSET if dy > 0 else (FIELD_Y1 - START_INSET if dy < 0 else FIELD_CY)
    return bx, by


def frame_count(p, mb):
    d = p.read(mb + CALC_COUNT, 1)
    return d[0] if d else None


def wait_frames(p, mb, n, timeout=2.0):
    """等帧计数前进 n 帧。返回实际经过帧数；0 = 游戏没在跑（暂停 / 最小化）"""
    f0 = frame_count(p, mb)
    if f0 is None:
        return 0
    t0 = time.perf_counter()
    while True:
        f = frame_count(p, mb)
        if f is not None:
            d = (f - f0) & 0xFF
            if d >= n:
                return d
        if time.perf_counter() - t0 > timeout:
            return 0
        time.sleep(0.004)


def keys_for(name):
    return [k for k in ('up', 'down', 'left', 'right') if k in name]


def center_player(p, mb, target=CENTER, tol=CENTER_TOL, tries=8, log=print):
    """分段按键把自机带到场地中心。斜向每轴速度未知，先走一半靠多轮收敛。"""
    for _ in range(tries):
        x, y = read_player(p, mb)
        dx, dy = target[0] - x, target[1] - y
        if abs(dx) <= tol and abs(dy) <= tol:
            return True
        keys = []
        if dx > tol:
            keys.append('right')
        elif dx < -tol:
            keys.append('left')
        if dy > tol:
            keys.append('down')
        elif dy < -tol:
            keys.append('up')
        if not keys:
            return True
        n = int(max(abs(dx) if keys[0] in ('left', 'right') else 0,
                    abs(dy) if keys[0] in ('up', 'down') else 0) / SPEED_GUESS)
        n = min(30, max(2, n if len(keys) == 1 else n // 2))
        for k in keys:
            th06.key_down(k)
        ok = wait_frames(p, mb, n)
        for k in keys:
            th06.key_up(k)
        time.sleep(0.04)
        if ok == 0:
            log('归中途中帧计数停滞（游戏已暂停或最小化）。')
            return False
    return False


def measure(p, mb, keys, frames, focus=False):
    """按住 keys（focus 时连 Shift 一起）走 frames 帧，返回 (vx, vy, 实际帧数, 起点, 终点)

    `focus` = 按住 Shift 走低速。低速 = 精确半速是反汇编 + 结构常量给的结论
    （`Player+0x7860/0x7864` = 4.0/2.0），这里量的是本机真实值。
    """
    ks = list(keys) + (['shift'] if focus else [])
    for k in ks:
        th06.key_down(k)
    if wait_frames(p, mb, 2) == 0:          # 先跑 2 帧丢掉按键送达延迟
        for k in ks:
            th06.key_up(k)
        return None
    x0, y0 = read_player(p, mb)
    n = wait_frames(p, mb, frames)
    x1, y1 = read_player(p, mb)
    for k in ks:
        th06.key_up(k)
    if n == 0 or n < frames // 2:
        return None
    return (x1 - x0) / n, (y1 - y0) / n, n, (x0, y0), (x1, y1)


def room_to_move(x, y, direction, need):
    """起点到该方向边界是否有 need px 余量"""
    dx, dy = direction
    if dx > 0 and x + need > FIELD_X1:
        return False
    if dx < 0 and x - need < FIELD_X0:
        return False
    if dy > 0 and y + need > FIELD_Y1:
        return False
    if dy < 0 and y - need < FIELD_Y0:
        return False
    return True


def calibrate(p, mb, hwnd, frames=40, focus=False, log=print):
    """归中 + 8 向标定。返回 dict；供 CLI 与 GUI 共用，标定逻辑只此一处"""
    out = {'ok': False, 'frames': frames, 'focus': focus, 'straight': {}, 'diagonal': {},
           'speed': None, 'diag_axis': None, 'normalized': None}
    need = frames * 5.0 + 12.0               # 按速度上限 5 px/帧留余量（低速只会更宽裕）

    def run(keys, direction, tag):
        spot = start_spot(direction)
        if not center_player(p, mb, spot, log=log):
            log(f'  {tag}：未能走到出发点 ({spot[0]:.0f},{spot[1]:.0f})，跳过。')
            return None
        x, y = read_player(p, mb)
        if not room_to_move(x, y, direction, need):
            log(f'  {tag}：距边界不足 {need:.0f}px（起点 {x:.0f},{y:.0f}），跳过。')
            return None
        r = measure(p, mb, keys, frames, focus=focus)
        if r is None:
            log(f'  {tag}：帧计数停滞或按住帧数不足，跳过。')
            return None
        vx, vy, n, (x0, y0), (x1, y1) = r
        log(f'  {tag}：({x0:6.1f},{y0:6.1f}) 至 ({x1:6.1f},{y1:6.1f})，'
            f'{n} 帧，vx={vx:+.3f} vy={vy:+.3f}。')
        return vx, vy

    log('直向：')
    for name, d in STRAIGHT:
        r = run(keys_for(name), d, name)
        if r:
            out['straight'][name] = math.hypot(*r)
    log('斜向：')
    for name, d in DIAGONAL:
        r = run(keys_for(name), d, name)
        if r:
            out['diagonal'][name] = r          # 保留分量：归一化与否要看每轴

    if out['straight']:
        out['speed'] = sum(out['straight'].values()) / len(out['straight'])
    if out['diagonal'] and out['speed']:
        axes = [max(abs(vx), abs(vy)) for vx, vy in out['diagonal'].values()]
        out['diag_axis'] = sum(axes) / len(axes)
        ratio = out['diag_axis'] / out['speed']
        out['normalized'] = abs(ratio - 0.7071) < abs(ratio - 1.0)
    out['ok'] = bool(out['straight'])
    return out


def report(out, log=print):
    log('')
    if not out['ok']:
        log('没有取得任何有效方向，标定失败。')
        return
    s = out['speed']
    tag = '低速（按住 Shift）' if out.get('focus') else '高速'
    log(f'{tag}直向 {s:.3f} px/帧（{len(out["straight"])} 向）。')
    r = 1.0
    if out['diag_axis']:
        r = out['diag_axis'] / s
        kind = ('归一化（斜向总速度等于直向）' if out['normalized']
                else '分轴独立（斜向总速度为直向的 √2 倍）')
        log(f'斜向每轴 {out["diag_axis"]:.3f} px/帧，为直向的 {r:.3f} 倍，判定为{kind}。')
    log('')
    if out.get('focus'):
        log(f'低速实测 {s:.2f} px/帧。低速为精确半速（反汇编 `Player__OnUpdate` 与结构常量 '
            f'0x7860/0x7864 = 4.0/2.0），故不按住 Shift 时应约为 {s * 2:.2f}。')
        log('低速模式的门槛与速度比见 dodge.py 的 FOCUS_* 常量；此处只测绝对值。')
        return
    log(f'建议：plan() 的 speed 取 {s:.2f}'
        + ('（分轴独立：DIRS 的斜向分量应改为 ±1，由 speed 统一缩放）'
           if out['diag_axis'] and not out['normalized'] else ''))
    log('下一步：将 speed 写入 dodge.py 默认值与 MEMMAP §1，并附本次 8 向原始数据。')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--frames', type=int, default=40, help='每个方向按住多少帧（默认 40）')
    ap.add_argument('--no-unpause', action='store_true', help='开始前不按 Z')
    ap.add_argument('--focus', action='store_true',
                    help='按住 Shift 标定**低速**速度（预期 = 高速的精确一半）')
    args = ap.parse_args()

    p, pid = th06.get_proc()
    mb = module_base(pid, 'th06nc.exe')[0]
    hwnd = find_windows(pid=pid)[0][0]
    print(f'PID {pid}  基址 0x{mb:X}  hwnd 0x{hwnd:X}', flush=True)

    set_foreground(hwnd)
    time.sleep(0.4)
    if th06.user32.GetForegroundWindow() != hwnd:
        print('失败 游戏未取得前台焦点 —— 未发送任何按键（避免打进别的程序）')
        p.close()
        return 1
    if not args.no_unpause:
        th06.tap('z', 60)
        time.sleep(0.4)

    st = read_state(p, mb)
    code, desc, ok = screen_of(st)
    if code != 'IN_GAME':
        print(f'失败 当前画面 {code}：{desc} —— 标定需要「关卡进行中」，未发送任何按键')
        p.close()
        return 1
    if wait_frames(p, mb, 3) == 0:
        print('失败 帧计数不走（游戏被暂停或最小化）—— 未发送任何按键')
        p.close()
        return 1

    print(f'标定中：{"低速（按住 Shift）" if args.focus else "高速"}8 向 × {args.frames} 帧，'
          f'请不要操作键鼠…', flush=True)
    out = calibrate(p, mb, hwnd, args.frames, focus=args.focus, log=print)
    report(out)
    p.close()
    return 0 if out['ok'] else 1


if __name__ == '__main__':
    sys.exit(main())
