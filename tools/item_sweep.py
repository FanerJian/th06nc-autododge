"""道具收集 vs 输出取舍 —— 离线闭环扫描（不需游戏）

为什么留着：捡道具与输出是**同层竞争**，改动任一方都会同时影响「捡到多少」与「打了多久」。
单看某一侧的护栏会漏掉取舍，所以把两者放进同一个闭环里量。

世界：敌人固定在 (140,120) 提供输出目标，每 55 帧朝下扇形发 3 颗弹；每 60 帧从敌人位置
掉一颗道具（真实下落规律：vy 从 −2.2 起、每帧 +0.03 到 3.0；y ≥ 432 消失）。
自机按 `dodge.plan()` 逐帧走，拾取判定 = x/y 各 14px（与游戏一致）。

对比三组（多种子平均，场景偏混沌，单种子结论不可信）：
  new = 现模型（时间外推 + 顺路 + 集群加成 + 紧张档同等安全）
  old = 旧模型（瞬时距离 + 垂直权重 0.35 + 紧张档纯躲，无顺路/集群）
  none = 不捡道具（item=0），纯输出基准

指标：收集率 / 水平对准 boss 帧数（子弹朝上飞，对准才打得到）/ 平均 y（离 boss 多远）。

末尾附「双组场景」：近侧单块 vs 远侧一簇同时落，唯一变量 = 集群加成开/关 ——
「一趟能捡最多」的实证：集群版应该跑远侧一趟收一簇，对照版只守近侧单块。

用法:
  py tools\\item_sweep.py                      # 默认 5 种子 × 1800 帧
  py tools\\item_sweep.py --seeds 7,11 --frames 900
  py tools\\item_sweep.py --item-wait 0        # 只在道具已到自机高度时才动
"""
import argparse
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dodge
from dodge import (DIRS, ITEM_CAP, ITEM_W, ITEM_WAIT, PLAYER_SPEED, STANDOFF, item_values,
                   pick_target, plan)
from offsets import FIELD_X0, FIELD_X1, FIELD_Y0, FIELD_Y1, ITEM_GRAB_DIST

DIRV = {n: (a, b) for n, a, b, _ in DIRS}
ENEMY = (np.array([140.0]), np.array([120.0]), np.array([32.0]), np.array([32.0]))
TX, TY = 140.0, 120.0
BAND = (TY + STANDOFF, TY + STANDOFF + 80.0)      # 理想输出带（不是「打得到」的判据）
PICK = ITEM_GRAB_DIST
BULLET_SPEED = 1.8


def old_item_cost(x, y, ix, iy, vals, vys=None, cap=ITEM_CAP, wait=ITEM_WAIT, **kw):
    """旧模型：瞬时加权距离 ÷ 价值（垂直 ×0.35），没有时间维度"""
    if len(ix) == 0:
        return 1.0
    d = np.sqrt((x - ix) ** 2 + ((y - iy) * 0.35) ** 2) / vals
    return min(1.0, float(d.min()) / cap)


def no_aim(ixs, vals, aim_x, **kw):
    """旧模型没有「顺路」衰减"""
    return vals


def no_cluster(x, y, ix, iy, vals, vys=None, delays=None, **kw):
    """关闭集群加成（对照组）：价值原样返回"""
    return vals


# 打桩用的真函数引用 —— run() 系列会把 dodge 里的三件套换成对照实现，
# 双组场景再把它们换回来（顺序见 main()）。
REAL_COST, REAL_AIM, REAL_CLUSTER = (dodge.item_cost, dodge.item_aim_vals,
                                     dodge.item_cluster_vals)


def run(item_fn, aim_fn, cluster_fn, risk, item_w, frames=1800, seed=7,
        item_wait=ITEM_WAIT, down_reach=None):
    dodge.item_cost, dodge.item_aim_vals = item_fn, aim_fn
    dodge.item_cluster_vals = cluster_fn
    rng = np.random.default_rng(seed)
    px, py, prev = 192.0, 380.0, 'none'
    bullets, items = [], []
    spawned = picked = 0
    aim_frames = band_frames = 0
    ysum = 0.0
    for f in range(frames):
        if f % 55 == 0:
            for k in (-1, 0, 1):
                ang = np.pi / 2 + k * 0.25
                bullets.append([TX, TY, BULLET_SPEED * np.cos(ang),
                                BULLET_SPEED * np.sin(ang)])
        if f % 60 == 0:
            items.append([TX + float(rng.uniform(-80, 80)), TY, -2.2,
                          0 if rng.random() < 0.7 else 1])
            spawned += 1
        for b in bullets:
            b[0] += b[2]
            b[1] += b[3]
        bullets = [b for b in bullets if FIELD_Y0 - 20 < b[1] < FIELD_Y1 + 20]
        alive = []
        for it in items:
            it[1] += it[2]
            it[2] = min(it[2] + 0.03, 3.0)
            if abs(px - it[0]) <= PICK and abs(py - it[1]) <= PICK:
                picked += 1
                continue
            if it[1] < FIELD_Y1:
                alive.append(it)
        items = alive

        bx = np.array([b[0] for b in bullets], dtype=np.float32)
        by = np.array([b[1] for b in bullets], dtype=np.float32)
        vx = np.array([b[2] for b in bullets], dtype=np.float32)
        vy = np.array([b[3] for b in bullets], dtype=np.float32)
        if items:
            ixs = np.array([i[0] for i in items], dtype=np.float32)
            iys = np.array([i[1] for i in items], dtype=np.float32)
            ivy = np.array([i[2] for i in items], dtype=np.float32)
            ityp = np.array([i[3] for i in items], dtype=np.int8)
            item = (ixs, iys, item_values(ityp, power=64), ivy)
        else:
            item = (np.empty(0, np.float32),) * 4

        tgt = pick_target(px, py, ENEMY, np.array([True]))
        kw = {} if down_reach is None else {'down_reach': down_reach}
        best, _ = plan(px, py, bx, by, vx, vy, PLAYER_SPEED, 30, 2.0, 8.0, prev, 0.2,
                       ENEMY, None, 6.0, attack=tgt, attack_w=20.0, standoff=STANDOFF,
                       margin_w=10.0, switch_margin=0.3,
                       item=item, item_w=item_w, item_wait=item_wait, risk=risk, **kw)
        dx, dy = DIRV[best]
        px = float(np.clip(px + dx * PLAYER_SPEED, FIELD_X0, FIELD_X1))
        py = float(np.clip(py + dy * PLAYER_SPEED, FIELD_Y0, FIELD_Y1))
        prev = best
        if abs(px - TX) <= 24.0:
            aim_frames += 1
        if BAND[0] <= py <= BAND[1]:
            band_frames += 1
        ysum += py
    return dict(spawned=spawned, picked=picked, aim=aim_frames, band=band_frames,
                ymean=ysum / frames, frames=frames)


def run_pairs(cluster_fn, frames=1800, seed=7, item_wait=ITEM_WAIT):
    """双组场景：近侧单块 vs 远侧一簇 —— 「一趟能捡最多」的实证

    每 150 帧同时落两组道具（同高度、同初速，到达时刻相同）：
      右侧 x≈320：1 块蓝点（val 1.5）；左侧 x≈60：3 块小P 挤在 ±20px 内。
    自机从场心 x=190 出发，两侧水平距离对称（各 130px）。两侧相距 260px ——
    守一侧时另一侧的等效距离超出 ITEM_CAP（互斥：捡完一侧另一侧已掉出场），
    只留价值结构差异：无集群时右侧赢（单块更值钱），有集群时左侧每块
    val = 1.0 + 2×邻居 → 一趟收一簇。无威胁源（纯捡，走空档期等待上限）。
    """
    dodge.item_cost, dodge.item_aim_vals = REAL_COST, REAL_AIM
    dodge.item_cluster_vals = cluster_fn
    rng = np.random.default_rng(seed)
    px, py, prev = 190.0, 380.0, 'none'
    items = []
    spawned = picked = far_picked = 0
    for f in range(frames):
        if f % 150 == 0:
            items.append([320.0 + float(rng.uniform(-10, 10)), 60.0, -2.2, 1])  # 右：蓝点
            for _ in range(3):
                items.append([60.0 + float(rng.uniform(-20, 20)), 60.0, -2.2, 0])  # 左：小P
            spawned += 4
        alive = []
        for it in items:
            it[1] += it[2]
            it[2] = min(it[2] + 0.03, 3.0)
            if abs(px - it[0]) <= PICK and abs(py - it[1]) <= PICK:
                picked += 1
                if it[0] < 190.0:
                    far_picked += 1
                continue
            if it[1] < FIELD_Y1:
                alive.append(it)
        items = alive
        if items:
            ixs = np.array([i[0] for i in items], dtype=np.float32)
            iys = np.array([i[1] for i in items], dtype=np.float32)
            ivy = np.array([i[2] for i in items], dtype=np.float32)
            ityp = np.array([i[3] for i in items], dtype=np.int8)
            item = (ixs, iys, item_values(ityp, power=128), ivy)
        else:
            item = (np.empty(0, np.float32),) * 4
        best, _ = plan(px, py, np.empty(0, np.float32), np.empty(0, np.float32),
                       np.empty(0, np.float32), np.empty(0, np.float32),
                       PLAYER_SPEED, 30, 2.0, 0.0, prev, 0.2, None, None, 6.0,
                       item=item, item_w=ITEM_W, item_wait=item_wait, risk=1.0)
        dx, dy = DIRV[best]
        px = float(np.clip(px + dx * PLAYER_SPEED, FIELD_X0, FIELD_X1))
        py = float(np.clip(py + dy * PLAYER_SPEED, FIELD_Y0, FIELD_Y1))
        prev = best
    return dict(spawned=spawned, picked=picked, far=far_picked, frames=frames)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--seeds', default='7,11,23,42,101', help='逗号分隔的随机种子')
    ap.add_argument('--frames', type=int, default=1800)
    ap.add_argument('--item', type=float, default=ITEM_W)
    ap.add_argument('--item-wait', type=float, default=ITEM_WAIT)
    ap.add_argument('--down-reach', type=float, default=None,
                    help='覆盖 ITEM_DOWN_REACH（下方牵引上限，默认取代码常量）')
    a = ap.parse_args()
    seeds = [int(s) for s in a.seeds.split(',')]

    rows = [('new ', dodge.item_cost, dodge.item_aim_vals, REAL_CLUSTER, 1.0, a.item),
            ('old ', old_item_cost, no_aim, no_cluster, 0.0, a.item),
            ('none', old_item_cost, no_aim, no_cluster, 0.0, 0.0)]
    print(f'{len(seeds)} 种子 × {a.frames} 帧    item={a.item:g}  '
          f'item_wait={a.item_wait:g}  down_reach={a.down_reach}')
    print(f'{"方案":<6}{"收集率":>8}{"捡到":>7}{"对准帧":>8}{"对准率":>7}'
          f'{"平均y":>7}{"带内帧":>8}')
    for tag, fn, aim, cfn, risk, iw in rows:
        rs = [run(fn, aim, cfn, risk, iw, frames=a.frames, seed=s, item_wait=a.item_wait,
                  down_reach=a.down_reach) for s in seeds]
        n = len(rs)
        got = sum(r['picked'] for r in rs) / max(sum(r['spawned'] for r in rs), 1)
        aim_f = sum(r['aim'] for r in rs) / n
        print(f'{tag:<6}{got:>8.0%}{sum(r["picked"] for r in rs) / n:>7.1f}'
              f'{aim_f:>8.0f}{aim_f / a.frames:>7.0%}'
              f'{sum(r["ymean"] for r in rs) / n:>7.0f}'
              f'{sum(r["band"] for r in rs) / n:>8.0f}')

    print('\n双组场景（近侧单块 vs 远侧一簇，唯一变量 = 集群加成）')
    print(f'{"方案":<13}{"收集率":>8}{"捡到":>7}{"远簇捡到":>9}')
    for tag, cfn in [('cluster on ', REAL_CLUSTER), ('cluster off', no_cluster)]:
        rs = [run_pairs(cfn, frames=a.frames, seed=s, item_wait=a.item_wait)
              for s in seeds]
        n = len(rs)
        sp = max(sum(r['spawned'] for r in rs), 1)
        print(f'{tag:<13}{sum(r["picked"] for r in rs) / sp:>8.0%}'
              f'{sum(r["picked"] for r in rs) / n:>7.1f}'
              f'{sum(r["far"] for r in rs) / n:>9.1f}')


if __name__ == '__main__':
    main()
