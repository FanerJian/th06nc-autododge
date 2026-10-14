"""读取 th06nc 当前活跃激光

地址依据（反汇编 SpawnLaserPattern + OnUpdate 激光循环，见 MEMMAP §7）；
常量取自 `tools/offsets.py`：lasers[] = g_BulletManager + LASERS_OFF，64 槽。

判定几何（`Player__CalcLaserHitbox` 入参，反汇编 0x1161D..0x11883 确证）：
**线段 = pos + 方向(angle) × [startOffset, endOffset]**，半宽 = width/2。
**pos 是轴原点，不是线段起点**；每帧 `endOffset += speed` → 激光会整体平移。

用法:
  py tools\\read_lasers.py            # 打印一次
  py tools\\read_lasers.py 30         # 连续采 30 次
"""
import math
import os
import sys
import time
from collections import namedtuple

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import th06
from offsets import (BM_RVA, LASERS_OFF, LASER_COUNT, LASER_STRIDE, L_OFF_ANGLE,
                     L_OFF_ENDOFF, L_OFF_FADE_FRAMES, L_OFF_FIRE_FRAMES, L_OFF_FLAGS,
                     L_OFF_SPEED, L_OFF_STARTOFF, L_OFF_STARTLEN, L_OFF_STATE,
                     L_OFF_TIMER, L_OFF_WARN_FRAMES, L_OFF_WIDTH, L_OFF_X, L_OFF_Y,
                     L_PHASE_FADE, L_PHASE_FIRE, L_PHASE_TAIL, L_PHASE_WARN)
from read_bullets import read_player          # 自机坐标只留一份实现
from winmem import module_base

LASER_BLOCK = LASER_STRIDE * LASER_COUNT      # 0xA600

PHASE_NAME = {L_PHASE_WARN: '预警', L_PHASE_FIRE: '发射', L_PHASE_FADE: '消散',
              L_PHASE_TAIL: '收尾'}

# 一帧的激光池快照。用命名元组而不是裸元组：字段一多，位置解包就会静默错位，
# 而这里最容易记混的恰恰是「起点偏移 / 终点偏移 / 长度上限 / 前进速度」这一组。
LaserFrame = namedtuple(
    'LaserFrame',
    'slots xs ys angles widths starts ends lens speeds phases timers totals')


def _f32col(raw, off):
    return raw[:, off:off + 4].copy().view('<f4').ravel()


def _i32col(raw, off):
    return raw[:, off:off + 4].copy().view('<i4').ravel()


def read_lasers(p, mb):
    """返回一帧的 LaserFrame（字段名即语义）；读取失败返回 None

    `starts` / `ends` / `lens` / `speeds` 是判定几何的全部输入：
    当前线段 = `pos + 方向(angle) × [starts, ends]`，`speeds` = 每帧偏移前进量(px)。
    `lens` 是长度上限（startOffset 被它推着走），预测时用它区分「还在伸长」与「整体平移」。

    `phases` 见 `offsets.L_PHASE_*` —— **只有 `L_PHASE_FIRE` 会调 `Player__CalcLaserHitbox`**，
    其余阶段打不到人（依据：`BulletManager__OnUpdate` 的激光循环四路分派）。
    `timers` 是当前阶段已过帧数、`totals` 是当前阶段总帧数，两者相减 = 还剩几帧切阶段。
    """
    data = p.read(mb + BM_RVA + LASERS_OFF, LASER_BLOCK)
    if not data or len(data) < LASER_BLOCK:
        return None
    raw = np.frombuffer(data, dtype=np.uint8).reshape(LASER_COUNT, LASER_STRIDE)
    mask = raw[:, L_OFF_STATE] != 0
    slots = np.nonzero(mask)[0]
    phase = raw[mask, L_OFF_FLAGS].astype(np.int32)
    timer = _i32col(raw, L_OFF_TIMER)[mask]
    warn = _i32col(raw, L_OFF_WARN_FRAMES)[mask]
    fire = _i32col(raw, L_OFF_FIRE_FRAMES)[mask]
    fade = _i32col(raw, L_OFF_FADE_FRAMES)[mask]
    total = np.where(phase <= L_PHASE_WARN, warn,
                     np.where(phase == L_PHASE_FIRE, fire, fade))
    return LaserFrame(
        slots,
        _f32col(raw, L_OFF_X)[mask], _f32col(raw, L_OFF_Y)[mask],
        _f32col(raw, L_OFF_ANGLE)[mask], _f32col(raw, L_OFF_WIDTH)[mask],
        _f32col(raw, L_OFF_STARTOFF)[mask], _f32col(raw, L_OFF_ENDOFF)[mask],
        _f32col(raw, L_OFF_STARTLEN)[mask], _f32col(raw, L_OFF_SPEED)[mask],
        phase, timer, total)


def frac(x):
    """浮点小数部分，用于识别未初始化的垃圾值"""
    return abs(x - int(x))


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    p, pid = th06.get_proc()
    mb = module_base(pid, 'th06nc.exe')[0]
    print(f'PID {pid}  基址 0x{mb:X}  lasers 0x{mb + BM_RVA + LASERS_OFF:X}')
    for k in range(n):
        lf = read_lasers(p, mb)
        if lf is None:
            print('读取失败')
            break
        px, py = read_player(p, mb)
        print(f'\n[{k}] 活跃 {len(lf.slots):2d} 条激光  自机=({px:6.1f},{py:6.1f})')
        for i in range(len(lf.slots)):
            ph = int(lf.phases[i])
            left = int(lf.totals[i] - lf.timers[i])
            print(f'    slot {lf.slots[i]:2d}  {PHASE_NAME.get(ph, f"阶段{ph}"):<2}'
                  f'{"" if ph == L_PHASE_FIRE else "（无判定）":<8}'
                  f'  还剩 {left:4d} 帧  pos=({lf.xs[i]:8.2f},{lf.ys[i]:8.2f})  '
                  f'angle={math.degrees(lf.angles[i]) % 360:6.1f}°  w={lf.widths[i]:6.2f}  '
                  f'线段 {lf.starts[i]:8.2f}→{lf.ends[i]:8.2f}'
                  f'（长 {lf.ends[i] - lf.starts[i]:7.2f}）  '
                  f'speed={lf.speeds[i]:6.2f}  len上限={lf.lens[i]:7.2f}')
        if n > 1:
            time.sleep(0.1)
    p.close()


if __name__ == '__main__':
    main()
