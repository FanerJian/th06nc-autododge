"""实机观测器 —— 后台只读盯盘：不发按键、不抢前台、可长期挂着

为什么需要：躲避脚本被打中时只留一行日志。要回答「为什么会被打中」必须看现场 ——
是谁碰上的、它怎么过来的、前几帧的间隙曲线长什么样。

三个事件各打一次现场（都不刷屏，只在**上升沿**触发）：
  进入判定圈  自机判定圆与某颗弹/某条激光相交的**那一帧**（游戏下一帧才判死）
  自机死亡    playerState == DEAD
  画面切换    screen_of() 的代号变了（NO_LIVES → CONTINUE 之类）

**纯只读**：只 ReadProcessMemory，不 SendInput、不切前台、不改游戏。

用法:
  py tools\\watch_live.py                    # 每秒一行关键指标
  py tools\\watch_live.py --quiet            # 静默：只打事件现场（后台挂着用这个）
  py tools\\watch_live.py --log _tmp\\w.log   # 输出同时写文件
  py tools\\watch_live.py --csv _tmp\\a.csv   # 逐帧落盘（事后画曲线）
  py tools\\watch_live.py --fps 20 --horizon 40
  py tools\\watch_live.py --hit-slack 6      # 判定圈外 6px 也算「差点撞上」，都报
"""
import argparse
import collections
import csv
import os
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:                                    # Windows 控制台默认 GBK，中文会乱码
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

import dodge                                                         # noqa: E402
import th06                                                          # noqa: E402
from offsets import (L_PHASE_FIRE, L_PHASE_WARN, PLAYER_R,           # noqa: E402
                     PLAYER_SPEED, PLAYER_STATE_DEAD)
from read_bullets import describe_flags, read_player_state           # noqa: E402
from read_lasers import read_lasers                                  # noqa: E402
from screen import read_state, screen_of                             # noqa: E402
from winmem import module_base                                       # noqa: E402


class Out:
    """输出：屏幕上打一份，可选同时落盘（后台 nohup 式运行靠文件看）"""

    def __init__(self, path=None):
        self.f = open(path, 'a', encoding='utf-8') if path else None

    def __call__(self, msg=''):
        print(msg, flush=True)
        if self.f:
            self.f.write(msg + '\n')
            self.f.flush()

    def close(self):
        if self.f:
            self.f.close()


def bullets_in_reach(bf, px, py, slack=0.0):
    """自机判定圆内（含 slack 余量）的弹 → (索引数组, 距离数组)

    判定 = 逐弹半径 + 自机半径（MEMMAP §3：`min(grazeSize) × 0.5 + 自机半径`）。
    """
    d = np.hypot(bf.xs - px, bf.ys - py)
    return np.nonzero(d <= bf.brs + PLAYER_R + slack)[0], d


def bullet_line(bf, i):
    return (f'slot{int(bf.slots[i]):>4} x={bf.xs[i]:8.2f} y={bf.ys[i]:8.2f} '
            f'vx={bf.vxs[i]:7.2f} vy={bf.vys[i]:7.2f} r={bf.brs[i]:.2f} '
            f'st={int(bf.states[i])} exF=0x{int(bf.exflags[i]):03X} '
            f'ang={np.degrees(bf.angles[i]):6.1f} spd={bf.speeds[i]:5.2f} '
            f't={int(bf.timers[i]):>4} {describe_flags(int(bf.exflags[i]))}')


def laser_report(lf, px, py, top=3):
    """发射中的激光按与自机的间隙排序 → 每条的完整参数（找出是哪一条、怎么过来的）

    只认 `L_PHASE_FIRE` —— 预警阶段没有伤害判定，算它的间隙会虚报危险。
    """
    if lf is None or not len(lf.xs):
        return []
    keep = lf.phases == L_PHASE_FIRE
    if not keep.any():
        return []
    seg = dodge.laser_segments(lf, keep)
    xs, ys, angs = seg[0], seg[1], seg[2]
    ox = np.array([px], dtype=np.float32)
    oy = np.array([py], dtype=np.float32)
    rank = []
    for i in range(len(xs)):
        g = float(dodge.laser_gap(ox, oy, xs[i:i + 1], ys[i:i + 1], angs[i:i + 1],
                                  seg[3][i:i + 1], seg[4][i:i + 1], seg[5][i:i + 1],
                                  seg[6][i:i + 1])[0])
        rank.append((g, i))
    rank.sort()
    return [f'间隙 {g:7.2f}px  pos=({xs[i]:7.1f},{ys[i]:7.1f}) '
            f'ang={np.degrees(angs[i]):6.1f}°  start={seg[3][i]:6.1f} end={seg[4][i]:6.1f} '
            f'len={seg[5][i]:6.1f} w={seg[6][i]:5.1f} 伸长={seg[7][i]:5.2f}/帧  '
            f'轴移=({seg[8][i]:5.2f},{seg[9][i]:5.2f})/帧  转角={np.degrees(seg[10][i]):5.2f}°/帧'
            for g, i in rank[:top]]


def main():
    ap = argparse.ArgumentParser(description='实机观测器（只读，不按键）')
    ap.add_argument('--fps', type=float, default=20.0, help='采样频率')
    ap.add_argument('--horizon', type=int, default=30, help='间隙前瞻帧数')
    ap.add_argument('--history', type=int, default=60, help='事件现场回看的帧数')
    ap.add_argument('--quiet', action='store_true', help='不打周期行，只打事件')
    ap.add_argument('--hit-slack', type=float, default=0.0,
                    help='判定圈外多少 px 内也算「差点撞上」')
    ap.add_argument('--csv', default=None, help='逐帧落盘路径')
    ap.add_argument('--log', default=None, help='输出同时写文件')
    ap.add_argument('--seconds', type=float, default=0.0, help='0 = 一直跑')
    args = ap.parse_args()

    out = Out(args.log)
    p, pid = th06.get_proc()
    mb = module_base(pid, 'th06nc.exe')[0]
    out(f'# watch_live  PID {pid}  基址 0x{mb:X}  fps={args.fps:g}  '
        f'horizon={args.horizon}  只读，不发按键')

    fcsv = open(args.csv, 'w', newline='', encoding='utf-8') if args.csv else None
    wr = csv.writer(fcsv) if fcsv else None
    if wr:
        wr.writerow(['t', 'code', 'px', 'py', 'gap', 'best', 'n_bullet', 'n_laser',
                     'n_enemy', 'lives', 'bombs', 'dying', 'reach'])
        fcsv.flush()

    motion = dodge.LaserMotion()          # 激光轴原点平移 + 朝向旋转的逐帧差分
    enemy_motion = dodge.EnemyMotion()
    ring = collections.deque(maxlen=args.history)
    last_code = None
    was_dead = False
    last_hit = np.zeros(0, dtype=np.int64)
    period = 1.0 / max(args.fps, 1.0)
    t0 = time.perf_counter()
    tick = 0
    deaths = hits = 0
    try:
        while True:
            t_start = time.perf_counter()
            if args.seconds and t_start - t0 > args.seconds:
                break
            st = read_state(p, mb)
            code, desc, _ = screen_of(st)
            ps = read_player_state(p, mb)
            w = dodge.read_frame(p, mb, motion=motion, enemy_motion=enemy_motion)
            if w is None:
                out('! read_frame 失败（进程退出？）')
                break
            px, py, bf = w['px'], w['py'], w['bf']
            best, sc = dodge.plan(px, py, w['bx'], w['by'], w['vx'], w['vy'],
                                  PLAYER_SPEED, args.horizon, 2.0, br=w.get('br'),
                                  enemy=w['enemy'], laser=w['laser'], bf=bf)
            gap = float(sc.get(best, 0.0))
            order = sorted(sc.items(), key=lambda kv: -kv[1])
            idx, dist = bullets_in_reach(bf, px, py, args.hit_slack)
            lf = read_lasers(p, mb) if w['n_laser'] else None
            lreps = laser_report(lf, px, py, 3)
            lgap = None
            if lreps:
                lgap = float(lreps[0].split()[1].rstrip('px'))
            dead = ps is not None and ps['state'] == PLAYER_STATE_DEAD
            el = time.perf_counter() - t0
            ring.append((el, code, px, py, gap, best, len(bf.xs), int(idx.size)))

            if code != last_code:
                out(f'[{el:7.2f}s] 画面 {last_code} → {code}（{desc}）  '
                    f'弹{len(bf.xs)} 激{w["n_laser"]}  自机({px:.1f},{py:.1f})')
                last_code = code

            # 进入判定圈：游戏下一帧才判死，这一帧就是"谁碰上了"的答案
            if idx.size and not np.isin(idx, last_hit).all():
                hits += 1
                out(f'[{el:7.2f}s] ★ 命中判定圈  #{hits}  自机({px:.1f},{py:.1f}) '
                    f'判定半径 {PLAYER_R}px')
                for i in idx[np.argsort(dist[idx])][:4]:
                    over = dist[i] - (bf.brs[i] + PLAYER_R)
                    out(f'      d={dist[i]:6.2f}px (超出判定 {over:+.2f})  '
                        f'{bullet_line(bf, i)}')
                out('      前 %d 帧最优间隙: %s' % (
                    len(ring), ' '.join(f'{r[4]:.1f}' for r in ring)))
            last_hit = idx

            if dead and not was_dead:
                deaths += 1
                out(f'[{el:7.2f}s] ★★ 自机死亡  #{deaths}  ({px:.1f},{py:.1f})  '
                    f'Lives={st["lives"]} deaths={st["deaths"]}')
                near = np.argsort(dist)[:4] if idx.size else \
                    np.argsort(np.hypot(bf.xs - px, bf.ys - py))[:4]
                for i in near:
                    out(f'      最近弹 d={dist[i]:6.2f}px  {bullet_line(bf, i)}')
                if lreps:
                    out(f'      发射中的激光 {len(lreps)} 条（按间隙排序）')
                    for line in lreps:
                        out(f'        {line}')
                out('      前 %d 帧最优间隙: %s' % (
                    len(ring), ' '.join(f'{r[4]:.1f}' for r in ring)))
            was_dead = dead

            if wr:
                wr.writerow([f'{el:.3f}', code, f'{px:.2f}', f'{py:.2f}', f'{gap:.2f}',
                             best, len(bf.xs), w['n_laser'], w['n_enemy'],
                             st['lives'], st['bombs'], int(bool(st['dying'])),
                             int(idx.size)])
                fcsv.flush()

            tick += 1
            if not args.quiet and tick % max(int(args.fps), 1) == 0:
                near = float(dist.min()) if dist.size else float('nan')
                out(f'[{el:7.2f}s] {code:<9} 自机({px:6.1f},{py:6.1f}) '
                    f'弹{len(bf.xs):3d} 激{w["n_laser"]:2d} 敌{w["n_enemy"]:2d} '
                    f'最优间隙 {gap:6.1f}px({best})  次优 '
                    f'{order[1][1] if len(order) > 1 else 0:6.1f}  '
                    f'最近弹 {near:5.1f}px  判定圈 {idx.size}  '
                    f'激光 {lgap if lgap is None else round(lgap, 1)}')

            dt = time.perf_counter() - t_start
            if dt < period:
                time.sleep(period - dt)
    except KeyboardInterrupt:
        out('\n# 中断')
    finally:
        out(f'# 结束：{tick} 次采样，命中事件 {hits}，死亡事件 {deaths}')
        if fcsv:
            fcsv.close()
        out.close()
        p.close()


if __name__ == '__main__':
    main()
