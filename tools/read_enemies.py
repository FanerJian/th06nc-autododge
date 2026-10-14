"""读取 th06nc 当前活跃敌人本体

地址依据（反汇编 EnemyManager__SpawnEnemy 得出，见 MEMMAP §6）；常量取自 `tools/offsets.py`：
  g_EnemyManager = EM_RVA（全局对象），enemies[] = mgr + ENEMIES_OFF，256 槽。

用法:
  py tools\\read_enemies.py            # 打印一次
  py tools\\read_enemies.py 30         # 连续采 30 次
"""
import os
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import th06
from offsets import (EM_RVA, ENEMIES_OFF, ENEMY_BLOCK, ENEMY_COUNT, ENEMY_STRIDE,
                     E_BOSS, E_COLLIDABLE, E_INVISIBLE, E_OCCUPIED, E_OFF_FLAGS1,
                     E_OFF_FLAGS2, E_OFF_FLAGS3, E_OFF_HBH, E_OFF_HBW, E_OFF_LIFE,
                     E_OFF_SHOOT_INTERVAL, E_OFF_SHOOT_TIMER, E_OFF_X, E_OFF_Y)
from read_bullets import read_player          # 自机坐标只留一份实现
from winmem import module_base


def shoot_countdown(intervals, timers):
    """每个敌人还有几帧发下一波弹；-1 = 当前不射击（interval <= 0）

    依据：0x028A8A 段 —— `0 < shootInterval` 才递增 timer，到 interval 即发射并清零。
    这不是「预测弹幕形状」，只是「预测下一波什么时候来」。
    """
    return np.where(intervals > 0, intervals - timers, -1)


def read_enemies(p, mb):
    """返回活跃敌人的 (slots, xs, ys, lifes, hbws, hbhs, flags2, flags3, intervals, timers)

    活跃判据：flags1 的 bit7（有符号比较 < 0）。整块只读一次 ReadProcessMemory。
    intervals / timers 用于弹幕预警（见 `shoot_countdown()`）。
    """
    data = p.read(mb + EM_RVA + ENEMIES_OFF, ENEMY_BLOCK)
    if not data or len(data) < ENEMY_BLOCK:
        return None
    raw = np.frombuffer(data, dtype=np.uint8).reshape(ENEMY_COUNT, ENEMY_STRIDE)
    mask = (raw[:, E_OFF_FLAGS1] & E_OCCUPIED) != 0
    slots = np.nonzero(mask)[0]
    xs = raw[:, E_OFF_X:E_OFF_X + 4].copy().view('<f4').ravel()[mask]
    ys = raw[:, E_OFF_Y:E_OFF_Y + 4].copy().view('<f4').ravel()[mask]
    lifes = raw[:, E_OFF_LIFE:E_OFF_LIFE + 4].copy().view('<i4').ravel()[mask]
    hbws = raw[:, E_OFF_HBW:E_OFF_HBW + 4].copy().view('<f4').ravel()[mask]
    hbhs = raw[:, E_OFF_HBH:E_OFF_HBH + 4].copy().view('<f4').ravel()[mask]
    iv = raw[:, E_OFF_SHOOT_INTERVAL:E_OFF_SHOOT_INTERVAL + 4].copy().view('<i4').ravel()[mask]
    tm = raw[:, E_OFF_SHOOT_TIMER:E_OFF_SHOOT_TIMER + 4].copy().view('<i4').ravel()[mask]
    return (slots, xs, ys, lifes, hbws, hbhs, raw[mask, E_OFF_FLAGS2], raw[mask, E_OFF_FLAGS3],
            iv, tm)


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    p, pid = th06.get_proc()
    mb = module_base(pid, 'th06nc.exe')[0]
    print(f'PID {pid}  基址 0x{mb:X}  g_EnemyManager 0x{mb + EM_RVA:X}')
    for k in range(n):
        t0 = time.perf_counter()
        r = read_enemies(p, mb)
        dt = (time.perf_counter() - t0) * 1000
        if r is None:
            print('读取失败')
            break
        slots, xs, ys, lifes, hbws, hbhs, f2, f3, iv, tm = r
        px, py = read_player(p, mb)
        cds = shoot_countdown(iv, tm)
        print(f'\n[{k}] 占用槽 {len(slots):3d}  自机=({px:6.1f},{py:6.1f})  读+解析 {dt:.1f}ms')
        for i in range(len(slots)):
            tag = []
            if f2[i] & E_BOSS:
                tag.append('BOSS')
            if f2[i] & E_COLLIDABLE:
                tag.append('可碰撞')
            if f3[i] & E_INVISIBLE:
                tag.append('隐形')
            if cds[i] >= 0:
                tag.append(f'★{cds[i]}帧后发弹')
            d = ((xs[i] - px) ** 2 + (ys[i] - py) ** 2) ** 0.5
            print(f'    slot {slots[i]:3d}  ({xs[i]:8.2f},{ys[i]:8.2f})  life={lifes[i]:6d} '
                  f'hitbox=({hbws[i]:.2f},{hbhs[i]:.2f})  距自机 {d:6.1f}  {" ".join(tag)}')
        if n > 1:
            time.sleep(0.1)
    p.close()


if __name__ == '__main__':
    main()
