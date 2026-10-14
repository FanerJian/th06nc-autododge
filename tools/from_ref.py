"""校验 offsets.py 的地址与参考项目公布的一致，并 dump Player 结构

参考: https://github.com/sky1641/th06nc-practice
地址来源见 MEMMAP §1；本工具的价值是"用参考项目的 RVA 独立复核一遍"。

用法:
  py tools\\from_ref.py
"""
import os
import struct
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import th06
from offsets import (BOMBS, CUR_STATE, INPUT, LIVES, NATIVE_TIME, PLAYER_BASE,
                     POWER)
from winmem import module_base

PLAYER_SCAN = 0x8000      # Player 结构起码 0x7738+ 这么大
X_LO, X_HI = 0.0, 400.0
Y_LO, Y_HI = 0.0, 460.0


def main():
    p, pid = th06.get_proc()
    print('PID', pid)
    mb = module_base(pid, 'th06nc.exe')
    print(f'模块基址 0x{mb[0]:X} 大小 0x{mb[1]:X}')
    base = mb[0]

    # 1) 验证资源 RVA
    d = p.read(base + LIVES, 1)
    print(f'Lives(0x{LIVES:X}) = {d[0] if d else "读失败"}')
    d = p.read(base + BOMBS, 1)
    print(f'Bombs(0x{BOMBS:X}) = {d[0] if d else "读失败"}')
    d = p.read(base + POWER, 2)
    print(f'Power(0x{POWER:X}) = {struct.unpack("<H", d)[0] if d else "读失败"}')
    d = p.read(base + CUR_STATE, 4)
    print(f'Scene(0x{CUR_STATE:X}) = {struct.unpack("<i", d)[0] if d else "读失败"}')
    d = p.read(base + NATIVE_TIME, 1)
    print(f'NativeTime(0x{NATIVE_TIME:X}) = {d[0] if d else "读失败"}')
    d = p.read(base + INPUT, 2)
    print(f'Input(0x{INPUT:X}) = 0x{struct.unpack("<H", d)[0]:04X}' if d else 'Input 读失败')

    # 2) dump Player 结构，找坐标对
    data = p.read(base + PLAYER_BASE, PLAYER_SCAN)
    if not data:
        print('Player 结构读取失败')
        return 1
    arr = np.frombuffer(data[:len(data) // 4 * 4], dtype='<f4')
    x = arr[:-1]
    y = arr[1:]
    m = (np.isfinite(x) & np.isfinite(y)
         & (x >= X_LO) & (x <= X_HI) & (y >= Y_LO) & (y <= Y_HI))
    idx = np.nonzero(m)[0]
    print(f'\nPlayer 结构里「相邻两 float 都在游玩区」的位置: {len(idx)} 个')
    print(f'{"偏移":<10}{"x":>12}{"y":>12}')
    for i in idx[:80]:
        print(f'0x{i*4:<8X}{x[i]:>12.4f}{y[i]:>12.4f}')

    # 3) 也在 Player 结构里找单值（可能是 x 或 y 单独存放）
    print('\nPlayer 结构里 0x7700-0x7780 区间:')
    for off in range(0x7700, 0x7780, 4):
        v = arr[off // 4]
        iv = struct.unpack('<i', data[off:off + 4])[0]
        print(f'  +0x{off:04X}  float={v:>14.4f}  int={iv:>12}')
    p.close()
    return 0


if __name__ == '__main__':
    sys.exit(main())
