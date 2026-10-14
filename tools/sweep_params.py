"""软项参数扫描 —— 离线，不碰游戏

调 `--switch` / `--inertia` / `--margin` 前先跑这个：三个判据同时看，
避免「治了抖动却粘住该动的」。历史教训：门槛 1.5 时抖动没了，但自机粘在中途
（水平偏差 139px）连敌人都打不到。

判据：
  U2  贴左边(x=30，边界 8) 必须往右脱出        —— 门槛过大就粘死
  C   无弹幕场景要水平对齐到敌人(y=80)宽度内     —— 门槛过大就停在中途
  D   合成密集弹幕场景的方向切换次数越少越好     —— 去抖效果

用法:
  py tools\\sweep_params.py
"""
import os
import sys
from collections import Counter

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dodge import (DIRS, EDGE_MARGIN, MARGIN_W, SWITCH_MARGIN, pick_target, plan)  # noqa: E402
from offsets import FIELD_X0, FIELD_X1, FIELD_Y0, FIELD_Y1, PLAYER_SPEED  # noqa: E402

SPEED, HZ, SAFE, EDGE, COMFORT, ATTACK_W, STANDOFF, INERTIA = (
    PLAYER_SPEED, 30, 2.0, 8.0, 6.0, 20.0, 48.0, 0.2)
ENEMY_HALF_W = 14.0        # 敌机 hitbox 半宽：水平偏差小于它才打得到
DIRV = {n: (a, b) for n, a, b, _ in DIRS}
EMPTY = np.array([])


def walk(px, py, enemy, bx, by, vx, vy, frames, sweep_key, sweep_val):
    """按 plan() 逐帧走到停，返回 (末 x, 末 y, 方向序列)"""
    kw = dict(margin_w=MARGIN_W, switch_margin=SWITCH_MARGIN)
    kw[sweep_key] = sweep_val
    prev, seq = 'none', []
    for _ in range(frames):
        tgt = pick_target(px, py, enemy, None)
        best, _ = plan(px, py, bx, by, vx, vy, SPEED, HZ, SAFE, EDGE, prev, INERTIA,
                       enemy, None, COMFORT, attack=tgt, attack_w=ATTACK_W,
                       standoff=STANDOFF, **kw)
        seq.append(best)
        dx, dy = DIRV[best]
        px = float(np.clip(px + dx * SPEED, FIELD_X0, FIELD_X1))
        py = float(np.clip(py + dy * SPEED, FIELD_Y0, FIELD_Y1))
        prev = best
    return px, py, seq


# 合成密集弹幕：一圈向心弹 + 上方敌人，模拟最坏抖动场景
_rng = np.random.default_rng(7)
_ang = _rng.uniform(0, 2 * np.pi, 40)
_rad = _rng.uniform(90, 200, 40)
DBX, DBY = 192 + _rad * np.cos(_ang), 224 + _rad * np.sin(_ang)
DVX, DVY = -np.cos(_ang) * 1.5, -np.sin(_ang) * 1.5
EN_DENSE = (np.array([192.0]), np.array([70.0]), np.array([28.0]), np.array([28.0]))
EN_SIDE = (np.array([300.0]), np.array([80.0]), np.array([28.0]), np.array([28.0]))

print(f'判据：U2 贴边脱出 | C 水平偏差 < {ENEMY_HALF_W:.0f}px 才打得到 '
      f'| D 密集弹幕切换次数\n')
print(f'{"参数":<10}{"值":>6} | {"U2":>8} | {"C 末位置":>16}{"偏差":>7} | {"D 切换":>6}')
for key, vals in (('switch_margin', (0.0, 0.3, 0.5, 0.8, 1.0, 1.5)),):
    for v in vals:
        _, _, useq = walk(30.0, 224.0, None, np.array([300.0]), np.array([100.0]),
                          np.zeros(1), np.zeros(1), 40, key, v)
        cx, cy, _ = walk(100.0, 420.0, EN_SIDE, EMPTY, EMPTY, EMPTY, EMPTY, 240, key, v)
        _, _, dseq = walk(192.0, 400.0, EN_DENSE, DBX, DBY, DVX, DVY, 180, key, v)
        sw = sum(1 for i in range(1, len(dseq)) if dseq[i] != dseq[i - 1])
        off = abs(cx - 300.0)
        u2 = '通过 往右' if useq[0] == 'right' else f'失败 {useq[0]}'
        print(f'{key:<10}{v:6.1f} | {u2:>8} | ({cx:5.1f},{cy:5.1f}){off:7.1f} | {sw:6d}'
              f'{"  ← 对齐达标" if off < ENEMY_HALF_W else ""}')

print(f'\n当前默认：switch={SWITCH_MARGIN} margin={MARGIN_W} '
      f'edge={EDGE}（贴边作用距离 {EDGE_MARGIN:.0f}px）')
print('D 场景计数示例（当前默认）：',
      dict(Counter(walk(192.0, 400.0, EN_DENSE, DBX, DBY, DVX, DVY, 180,
                        'switch_margin', SWITCH_MARGIN)[2])))
