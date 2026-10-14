"""
放宽判据找子弹池: 对 stride=0x620(1568B=784 words) 的每一种对齐,
统计 w[r::784] 里落在 [1,100] 的"小整数"个数。
子弹槽里会有类型/状态/计时器等小整数, 且屏幕上弹幕越多命中越多。
"""
import sys
import os
import time
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import th06
from winmem import MEM_MAPPED, PAGE_READWRITE, PAGE_EXECUTE_READWRITE

STRIDE_W = 784
SLOTS = 640
MIN_REGION = 512 * 1024


def main():
    p, pid = th06.get_proc()
    print('PID', pid, flush=True)
    regs = [r for r in p.regions(min_size=MIN_REGION, include_image=True)
            if r[3] != MEM_MAPPED and r[2] in (PAGE_READWRITE, PAGE_EXECUTE_READWRITE)]
    regs.sort(key=lambda r: -r[1])
    print(f'{len(regs)} 区域 {sum(r[1] for r in regs)/1024/1024:.0f} MB', flush=True)

    t0 = time.time()
    allhits = []
    for base, size, prot, typ in regs:
        data = p.read(base, size)
        if not data or len(data) < SLOTS * STRIDE_W * 2:
            continue
        w = np.frombuffer(data[:len(data) // 2 * 2], dtype='<u2')
        wlen = len(w)
        for r in range(STRIDE_W):
            sub = w[r:r + SLOTS * STRIDE_W:STRIDE_W]
            if len(sub) < SLOTS:
                continue
            n_small = int(np.count_nonzero((sub >= 1) & (sub <= 100)))
            if n_small >= 40:
                allhits.append((n_small, base + r * 2, base, size, r))

    allhits.sort(reverse=True)
    print(f'\n耗时 {time.time()-t0:.1f}s  候选 {len(allhits)} 个')
    print(f'{"小整数数":>9}  {"数组起点":>18}  {"所属区域":>18} {"区域MB":>8}')
    seen = set()
    shown = 0
    for n, addr, base, size, r in allhits:
        key = addr >> 16
        if key in seen:
            continue
        seen.add(key)
        print(f'{n:>9}  0x{addr:<16X}  0x{base:<16X} {size/1024/1024:>8.2f}')
        shown += 1
        if shown >= 25:
            break
    p.close()


if __name__ == '__main__':
    main()
