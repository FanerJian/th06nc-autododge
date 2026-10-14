"""读取 th06nc 当前场上的掉落道具

地址依据（反汇编 ItemManager__SpawnItem 得出，见 MEMMAP §9）；常量取自 `tools/offsets.py`：
  items[0] = IM_RVA（全局对象），1024 槽 × stride 0x160，isInUse @ +0x00。

用法:
  py tools\\read_items.py            # 打印一次
  py tools\\read_items.py 30         # 连续采 30 次
"""
import os
import struct
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import th06
from offsets import (IM_RVA, ITEM_BLOCK, ITEM_COUNT, ITEM_STRIDE, I_OFF_INUSE,
                     I_OFF_STATE, I_OFF_TYPE, I_OFF_TX, I_OFF_TY, I_OFF_VY,
                     I_OFF_X, I_OFF_Y, POWER)
from read_bullets import read_player          # 自机坐标只留一份实现
from winmem import module_base

TYPE_NAME = {0: '小P', 1: '蓝点', 2: '大P', 3: 'Bomb', 4: '满P', 5: '1UP', 6: '清弹点'}
STATE_NAME = {0: '普通', 1: '追踪中', 2: '散射'}

_EMPTY_F = lambda: np.empty(0, dtype=np.float32)
_EMPTY_I = lambda: np.empty(0, dtype=np.int8)


def read_items(p, mb):
    """返回活跃道具的 (slots, xs, ys, vys, types, states, txs, tys)

    活跃判据：isInUse 非 0。整块只读一次 ReadProcessMemory（352 KB），
    列提取只对活跃行做（场上道具通常 < 50 个，全场道具数为 0 时几乎零开销）。

    vys = startPosition.y，即下落速度（px/帧，范围 [-2.2, 3.0]）；决策外推要用它。
    ⚠ state=2 且散射未结束时该字段是出生点 y（SpawnItem 用 currentPosition 覆写过
    startPosition）—— 只能当「散射中」的判据，不能当下落速度（见 MEMMAP §9）。
    txs / tys = targetPosition，仅 state=2 有意义（60 帧抛物线的终点，多在屏幕上部）。
    """
    data = p.read(mb + IM_RVA, ITEM_BLOCK)
    if not data or len(data) < ITEM_BLOCK:
        return None
    raw = np.frombuffer(data, dtype=np.uint8).reshape(ITEM_COUNT, ITEM_STRIDE)
    slots = np.nonzero(raw[:, I_OFF_INUSE] != 0)[0]
    if len(slots) == 0:
        return slots, _EMPTY_F(), _EMPTY_F(), _EMPTY_F(), _EMPTY_I(), _EMPTY_I(), \
            _EMPTY_F(), _EMPTY_F()
    sub = np.ascontiguousarray(raw[slots])
    col = lambda off: sub[:, off:off + 4].view('<f4').ravel()
    return (slots, col(I_OFF_X), col(I_OFF_Y), col(I_OFF_VY),
            sub[:, I_OFF_TYPE].astype(np.int8), sub[:, I_OFF_STATE].astype(np.int8),
            col(I_OFF_TX), col(I_OFF_TY))


def read_power(p, mb):
    """火力值（0..128）。128 = 满火力 —— 之后 Power 道具只转分数，不再是补火力的目标"""
    d = p.read(mb + POWER, 2)
    return struct.unpack('<H', d)[0] if d and len(d) == 2 else 0


def summarize(types, xs=None, ys=None):
    """把类型数组汇总成「小P×3 蓝点×2」这样的短串"""
    if len(types) == 0:
        return '无'
    uniq, cnt = np.unique(types, return_counts=True)
    return ' '.join(f'{TYPE_NAME.get(int(t), f"未知{t}")}×{c}' for t, c in zip(uniq, cnt))


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    p, pid = th06.get_proc()
    mb = module_base(pid, 'th06nc.exe')[0]
    print(f'PID {pid}  基址 0x{mb:X}  items[0] 0x{mb + IM_RVA:X}')
    for k in range(n):
        t0 = time.perf_counter()
        r = read_items(p, mb)
        dt = (time.perf_counter() - t0) * 1000
        if r is None:
            print('读取失败')
            break
        slots, xs, ys, vys, types, states, txs, tys = r
        px, py = read_player(p, mb)
        print(f'\n[{k}] 道具 {len(slots):3d} 个（{summarize(types)}）  '
              f'自机=({px:6.1f},{py:6.1f})  读+解析 {dt:.1f}ms')
        for i in range(len(slots)):
            d = max(abs(xs[i] - px), abs(ys[i] - py))
            tag = '可拾取' if d < 14.0 else ('被吸引' if states[i] == 1 else '')
            scatter = (f' →({txs[i]:.0f},{tys[i]:.0f})' if states[i] == 2 else '')
            print(f'    slot {slots[i]:4d}  ({xs[i]:8.2f},{ys[i]:8.2f})  vy={vys[i]:6.2f}  '
                  f'{TYPE_NAME.get(int(types[i]), "未知"):<6} {STATE_NAME.get(int(states[i]), "?")}'
                  f' 距自机 {d:6.1f}  {tag}{scatter}')
        if n > 1:
            time.sleep(0.1)
    p.close()


if __name__ == '__main__':
    main()
