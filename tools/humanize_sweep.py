"""人类化反应延迟的量化扫描 —— 离线仿真，不碰游戏

调「安全时反应延迟」（`--react` / GUI 滑条）前先跑这个。它回答一个问题：
**多等这几帧，究竟是更像人，还是只是更迟钝？**

对比 react ∈ {0, 2, 4, 8} 在三类局面下的表现：
  人味指标：等待帧占比（多少帧在从容等待，而不是每帧即时响应）、方向切换次数
  能力指标：末位置对齐偏差、道具拾取、全程最小间隙、真实中弹帧

判据（三条同时看，缺一条就会被"治好了抖动，粘住了该动的"骗过去）：
  1. 最小间隙与中弹**不得变差** —— 延迟若降低安全，就是拿命换像人，方向错了
  2. 密集弹幕的方向切换次数越少越像人（真人不每帧改主意）
  3. 对齐偏差仍要小于敌人半宽 14px、道具仍要捡得到 —— 迟几帧不能变成够不着

当前实测（240 帧闭环）：4 帧把密集弹幕切换从 38 降到 13 次（−66%），最小间隙不变（21.1px），
对齐 1.3 → 4.9px，道具照捡；8 帧则对齐场景切换反升到 16 次、间隙降到 18.6px —— 4 是拐点。

用法:
  py tools\\humanize_sweep.py
"""
import os
import random
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dodge import (DIRS, ITEM_W, MARGIN_W, ReactionGate, SWITCH_MARGIN,  # noqa: E402
                   pick_target, plan, threat_present)
from offsets import (BULLET_R, FIELD_X0, FIELD_X1, FIELD_Y0, FIELD_Y1,  # noqa: E402
                     PLAYER_R, PLAYER_SPEED)

EDGE_W, INERTIA, COMFORT, HZ, SAFE = 8.0, 0.2, 6.0, 30, 2.0
ATTACK_W, STANDOFF = 20.0, 48.0
DIRV = {n: (a, b) for n, a, b, _ in DIRS}
EMPTY = np.array([])
PICK_HALF = 14.0
REACTS = (0.0, 2.0, 4.0, 8.0)


def sim(kind, react, frames=240, seed=7):
    """按 plan + ReactionGate 闭环走 frames 帧，返回指标 dict"""
    gate = ReactionGate(random.Random(seed))
    if kind == 'C':                       # 无弹幕 + 右侧敌人：对齐能力 / 切换次数
        px, py = 100.0, 420.0
        bx = by = vx = vy = EMPTY
        enemy = (np.array([300.0]), np.array([80.0]), np.array([28.0]), np.array([28.0]))
        item = None
    elif kind == 'D':                     # 密集向心弹 + 上方敌人：安全性（子弹逐帧推进）
        px, py = 192.0, 400.0
        r = np.random.default_rng(7)
        ang, rad = r.uniform(0, 2 * np.pi, 40), r.uniform(90, 200, 40)
        bx, by = 192 + rad * np.cos(ang), 224 + rad * np.sin(ang)
        vx, vy = -np.cos(ang) * 1.5, -np.sin(ang) * 1.5
        enemy = (np.array([192.0]), np.array([70.0]), np.array([28.0]), np.array([28.0]))
        item = None
    else:                                 # 空档期 + 下落道具：拾取能力
        # 道具在自机右上方 40px、约 20 帧后才落到自机高度：水平 9 帧就该对齐，
        # 余量够 4 帧延迟用 —— 这个场景量的正是「慢半拍会不会错过」。
        px, py = 100.0, 400.0
        bx = by = vx = vy = EMPTY
        enemy = None
        item = [140.0, 340.0, 3.0]        # x, y, 下落速度 px/帧

    ex_dir, waits, switches, min_gap, hit_at, picked = 'none', 0, 0, 1e9, None, False
    for frame in range(frames):
        tgt = pick_target(px, py, enemy, None)
        it = (np.array([item[0]]), np.array([item[1]]), np.array([1.0])) if item else None
        best, scores = plan(px, py, bx, by, vx, vy, PLAYER_SPEED, HZ, SAFE, EDGE_W, ex_dir,
                            INERTIA, enemy, None, COMFORT, attack=tgt, attack_w=ATTACK_W,
                            standoff=STANDOFF, margin_w=MARGIN_W,
                            switch_margin=SWITCH_MARGIN, item=it,
                            item_w=ITEM_W if it else 0.0)
        ed = gate.update(best, ex_dir, scores, COMFORT, react,
                         threat=threat_present(bx, enemy, None))
        waits += 1 if gate.waited else 0
        switches += 1 if ed != ex_dir else 0
        min_gap = min(min_gap, scores[ed])
        ex_dir = ed

        dx, dy = DIRV[ed]
        px = float(np.clip(px + dx * PLAYER_SPEED, FIELD_X0, FIELD_X1))
        py = float(np.clip(py + dy * PLAYER_SPEED, FIELD_Y0, FIELD_Y1))
        if len(bx):
            bx, by = bx + vx, by + vy
            keep = (bx > -20) & (bx < FIELD_X1 + 20) & (by > -20) & (by < FIELD_Y1 + 20)
            bx, by, vx, vy = bx[keep], by[keep], vx[keep], vy[keep]
            if len(bx) and hit_at is None and \
                    float(np.min(np.hypot(bx - px, by - py))) < PLAYER_R + BULLET_R:
                hit_at = frame
        if item:
            item[1] += item[2]
            if abs(item[0] - px) < PICK_HALF and abs(item[1] - py) < PICK_HALF:
                picked = True
            if item[1] > FIELD_Y1 + 40:
                item = None
    return dict(waits=waits, switches=switches, min_gap=min_gap, hit=hit_at,
                picked=picked, px=px, py=py, frames=frames)


print(f'场地 x∈[{FIELD_X0:.0f},{FIELD_X1:.0f}] y∈[{FIELD_Y0:.0f},{FIELD_Y1:.0f}]  '
      f'自机速度 {PLAYER_SPEED}  60fps  （等待帧 = 在从容等待的帧数；占比越高越"慢半拍"）\n')
print(f'{"react":>5} {"场景":<5}{"等待帧":>7}{"占比":>7}{"切换":>5}'
      f'{"最小间隙":>9}{"中弹":>7}  末位置 / 其他')
for react in REACTS:
    for kind, note in (('C', '对齐'), ('D', '密集弹'), ('I', '捡道具')):
        r = sim(kind, react)
        extra = (f'({r["px"]:5.1f},{r["py"]:5.1f}) 偏差 {abs(r["px"] - 300.0):5.1f}px'
                 if kind == 'C' else
                 f'({r["px"]:5.1f},{r["py"]:5.1f})'
                 if kind == 'D' else
                 f'道具拾取 {"通过" if r["picked"] else "失败"}  末 x={r["px"]:5.1f}')
        print(f'{react:5.0f} {note:<5}{r["waits"]:7d}{r["waits"] / r["frames"] * 100:6.0f}%'
              f'{r["switches"]:5d}{r["min_gap"]:9.1f}'
              f'{("第" + str(r["hit"]) + "帧") if r["hit"] is not None else "—":>7}  {extra}')
    print()
