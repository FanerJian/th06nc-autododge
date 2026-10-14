"""
子弹池定位（严格版）

强特征（三条同时满足，随机命中率极低）：
  1. 区域大小 ≈ 1MB  -> 采样数（区域大小/1568）落在 [500, 800]
     依据: 640 槽 × 1568B = 0x4C+0xF5000+激光区 ≈ 1.03MB
  2. 命中率 5%~60%   -> 排除 0-1 归一化图形数据（命中率>70%）
  3. x 跨度>100 且 y 跨度>100 -> 坐标散布整个游玩区

游戏须处于暂停（冻结）态，子弹才停在内存里。
"""
import sys
import os
import time
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import th06
from winmem import (MEM_MAPPED, PAGE_READWRITE, PAGE_EXECUTE_READWRITE,
                    PAGE_WRITECOPY, PAGE_EXECUTE_WRITECOPY)

STRIDE_F = 392
XOFF_F = 0x30 // 4
YOFF_F = 0x34 // 4
SAMPLE_LO, SAMPLE_HI = 500, 800


def main():
    p, pid = th06.get_proc()
    print(f'PID {pid}', flush=True)
    regs = [r for r in p.regions(min_size=0x1000, include_image=True)
            if r[3] != MEM_MAPPED
            and r[2] in (PAGE_READWRITE, PAGE_EXECUTE_READWRITE,
                         PAGE_WRITECOPY, PAGE_EXECUTE_WRITECOPY)]

    results = []
    t0 = time.time()
    checked = 0
    for base, size, prot, typ in regs:
        nsample = size // 1568
        if not (SAMPLE_LO <= nsample <= SAMPLE_HI):
            continue
        d = p.read(base, size)
        if not d or len(d) < STRIDE_F * 100 * 4:
            continue
        checked += 1
        arr = np.frombuffer(d[:len(d) // 4 * 4], dtype='<f4')
        n = len(arr)
        for r in range(STRIDE_F):
            s = r + XOFF_F
            if s + 1 >= n:
                continue
            x = arr[s::STRIDE_F]
            y = arr[s + 1::STRIDE_F]
            if len(x) < 100 or len(y) != len(x):
                continue
            m = (np.isfinite(x) & np.isfinite(y)
                 & (x >= 3) & (x <= 381) & (y >= 3) & (y <= 445))
            cnt = int(np.count_nonzero(m))
            if cnt < 10:
                continue
            ratio = cnt / len(x)
            if ratio > 0.60:
                continue
            xs, ys = x[m], y[m]
            sx = float(xs.max() - xs.min()); sy = float(ys.max() - ys.min())
            if sx < 100 or sy < 100:
                continue
            results.append((cnt, base, r, len(x), ratio, sx, sy))

    print(f'检查 {checked} 个 ≈1MB 区域, 耗时 {time.time()-t0:.2f}s, 候选 {len(results)}',
          flush=True)

    results.sort(reverse=True)
    print(f'\n{"命中":>6}{"采样":>7}{"占比":>7}{"跨度x":>7}{"跨度y":>7}  {"槽基址":>18}')
    for cnt, base, r, n, ratio, sx, sy in results[:15]:
        print(f'{cnt:>6}{n:>7}{ratio:>7.2f}{sx:>7.0f}{sy:>7.0f}  0x{base + r*4:<16X}')

    if results:
        cnt, base, r, n, ratio, sx, sy = results[0]
        d = p.read(base, 0x100000)
        arr = np.frombuffer(d[:len(d) // 4 * 4], dtype='<f4')
        s = r + XOFF_F
        x = arr[s::STRIDE_F]; y = arr[s + 1::STRIDE_F]
        m = (np.isfinite(x) & np.isfinite(y)
             & (x >= 3) & (x <= 381) & (y >= 3) & (y <= 445))
        idx = np.nonzero(m)[0]
        slot0 = base + r * 4 - XOFF_F * 4
        print(f'\n槽基址 = 0x{slot0:X}   (RVA 0x{slot0 - (base & ~0xFFFFFFFFFFFFF):X})')
        print(f'{"槽号":>6}{"x":>11}{"y":>11}')
        for i in idx[:30]:
            print(f'{i:>6}{x[i]:>11.4f}{y[i]:>11.4f}')
    p.close()


if __name__ == '__main__':
    main()
