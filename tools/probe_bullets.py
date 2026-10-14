"""
探针：先让妖精开火，再冻结，然后扫描子弹池。

背景：屏幕上"没有弹幕"时扫描必然失败 —— 这是之前数轮误判的根因。
实测确认: 子弹槽 stride=0x620(1568B), x@+0x30, y@+0x34 (RVA 0x1140D 反汇编)
"""
import sys
import os
import time
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import th06
from winmem import (MEM_MAPPED, PAGE_READWRITE, PAGE_EXECUTE_READWRITE,
                    PAGE_WRITECOPY, PAGE_EXECUTE_WRITECOPY)

STRIDE_F = 392          # 1568 / 4
XOFF_F = 0x30 // 4      # 12
YOFF_F = 0x34 // 4      # 13
MAX_REGION = 4 << 20    # 子弹池约 1MB


def regions(p):
    rs = [r for r in p.regions(min_size=0x1000, include_image=True)
          if r[3] != MEM_MAPPED
          and r[2] in (PAGE_READWRITE, PAGE_EXECUTE_READWRITE,
                       PAGE_WRITECOPY, PAGE_EXECUTE_WRITECOPY)]
    rs.sort(key=lambda r: -r[1])
    return rs


def scan(regs_data, results):
    for base, arr in regs_data:
        n = len(arr)
        if n < STRIDE_F * 100:
            continue
        for r in range(STRIDE_F):
            s = r + XOFF_F
            if s + 1 >= n:
                continue
            x = arr[s::STRIDE_F]
            y = arr[s + 1::STRIDE_F]
            if len(x) < 100 or len(y) != len(x):
                continue
            m = np.isfinite(x) & np.isfinite(y) & (x >= 0) & (x <= 384) & (y >= 0) & (y <= 448)
            cnt = int(np.count_nonzero(m))
            if cnt < 15:
                continue
            xs, ys = x[m], y[m]
            sx = float(xs.max() - xs.min())
            sy = float(ys.max() - ys.min())
            if sx < 100 or sy < 80:      # 必须散布整个游玩区
                continue
            results.append((cnt, base, r, len(x), sx, sy))


def main():
    wait = float(sys.argv[1]) if len(sys.argv) > 1 else 3.5
    p, pid = th06.get_proc()
    print(f'PID {pid}', flush=True)
    th06._focus_game(pid)
    time.sleep(0.2)

    print(f'解除暂停(Z)，等 {wait}s 让妖精开火 ...', flush=True)
    th06.tap('z', 80)
    time.sleep(wait)
    th06.tap('esc', 80)
    time.sleep(0.5)
    print('已暂停，开始扫描', flush=True)

    regs = regions(p)
    data = []
    for base, size, prot, typ in regs:
        if size > MAX_REGION:
            continue
        d = p.read(base, size)
        if not d or len(d) < STRIDE_F * 100 * 4:
            continue
        data.append((base, np.frombuffer(d[:len(d) // 4 * 4], dtype='<f4').copy()))
    print(f'扫描 {len(data)} 个区域', flush=True)

    results = []
    t0 = time.time()
    scan(data, results)
    print(f'耗时 {time.time()-t0:.2f}s, 候选 {len(results)}', flush=True)

    results.sort(reverse=True)
    print(f'\n{"命中":>6}{"采样":>7}{"跨度x":>8}{"跨度y":>8}  {"槽基址(区域+偏移)":>26}')
    for cnt, base, r, n, sx, sy in results[:20]:
        slot0 = base + (r + XOFF_F) * 4 - XOFF_F * 4   # = 区域基址 + r*4
        print(f'{cnt:>6}{n:>7}{sx:>8.0f}{sy:>8.0f}  0x{slot0:<16X} (区域 0x{base:X})')

    if results:
        cnt, base, r, n, sx, sy = results[0]
        arr = dict(data)[base]
        s = r + XOFF_F
        x = arr[s::STRIDE_F]
        y = arr[s + 1::STRIDE_F]
        m = np.isfinite(x) & np.isfinite(y) & (x >= 0) & (x <= 384) & (y >= 0) & (y <= 448)
        idx = np.nonzero(m)[0]
        print(f'\n=== 最佳候选前 25 颗子弹 (槽基址 0x{base + r*4:X}) ===')
        print(f'{"槽号":>6}{"x":>11}{"y":>11}')
        for i in idx[:25]:
            print(f'{i:>6}{x[i]:>11.4f}{y[i]:>11.4f}')
    p.close()


if __name__ == '__main__':
    main()
