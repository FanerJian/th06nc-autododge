"""
用精确结构特征定位子弹数组。
已从反汇编确认 (RVA 0x1140D):
    子弹对象 stride = 0x620 = 1568 字节 = 392 floats
    子弹 x @ 槽 + 0x30   (float)
    子弹 y @ 槽 + 0x34   (float)   <- 与 x 相邻!
    存活标志 @ 槽 + 0x618

联合判据: 存在对齐 r, 使 arr[r::392] 落在 [0,384] 且 arr[r+1::392] 落在 [0,448]
随机同时命中的概率极低, 真子弹数组会给出远高于基线的计数。
"""
import sys
import os
import time
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import th06
from winmem import (module_base, MEM_MAPPED, PAGE_READWRITE,
                    PAGE_EXECUTE_READWRITE, PAGE_WRITECOPY, PAGE_EXECUTE_WRITECOPY)

STRIDE_F = 392
XOFF_F = 0x30 // 4     # 12
YOFF_F = 0x34 // 4     # 13
SLOTS = 640


def scan_buffer(arr, tag, results, filter_size=True):
    n = len(arr)
    if n < STRIDE_F * 20:
        return
    nsample = n // STRIDE_F
    if filter_size and not (300 <= nsample <= 1500):
        return
    for r in range(STRIDE_F):
        s = r + XOFF_F
        x = arr[s::STRIDE_F]
        y = arr[s + 1::STRIDE_F] if s + 1 < n else None
        if y is None or len(x) < 20 or len(y) != len(x):
            continue
        # 子弹坐标应散布在整个游玩区, 而不是挤在 0~1 (归一化图形数据)
        m = (x > 5.0) & (x < 384.0) & (y > 5.0) & (y < 448.0)
        cnt = int(np.count_nonzero(m))
        if cnt < 15:
            continue
        xr = x[m]
        span = float(xr.max() - xr.min()) if cnt else 0.0
        if span < 120.0:          # 坐标必须跨越大部分屏幕宽度
            continue
        ratio = cnt / len(x)
        if ratio < 0.75:
            results.append((cnt, tag, r, len(x), ratio, span))


def main():
    p, pid = th06.get_proc()
    mb = module_base(pid, 'th06nc.exe')[0]
    print(f'PID {pid} 模块基址 0x{mb:X}', flush=True)

    results = []
    t0 = time.time()

    # 1) 主模块 .data 段（子弹池很可能与 Player 同为模块内全局数组）
    DATA_LO, DATA_HI = 0x323000, 0xC29660
    data = p.read(mb + DATA_LO, DATA_HI - DATA_LO)
    if data:
        arr = np.frombuffer(data[:len(data) // 4 * 4], dtype='<f4').astype(np.float32)
        scan_buffer(arr, f'MODULE', results, filter_size=False)
        print(f'.data 扫描完 {len(results)} 个候选', flush=True)

    # 2) 全部可写区域
    regs = [r for r in p.regions(min_size=0x1000, include_image=True)
            if r[3] != MEM_MAPPED
            and r[2] in (PAGE_READWRITE, PAGE_EXECUTE_READWRITE,
                         PAGE_WRITECOPY, PAGE_EXECUTE_WRITECOPY)]
    for base, size, prot, typ in regs:
        d = p.read(base, size)
        if not d or len(d) < STRIDE_F * 20 * 4:
            continue
        arr = np.frombuffer(d[:len(d) // 4 * 4], dtype='<f4')
        scan_buffer(arr, f'0x{base:X}', results)

    print(f'\n总耗时 {time.time()-t0:.1f}s')
    results.sort(reverse=True)
    print(f'{"命中":>7}{"占比":>7}{"跨度":>8}  {"区域":>18} {"对齐r":>6} {"采样":>7}  '
          f'{"数组基址":>18}')
    for cnt, tag, r, n, ratio, span in results[:30]:
        if tag == 'MODULE':
            arrbase_rva = DATA_LO + (r) * 4 - XOFF_F * 4
            print(f'{cnt:>7}{ratio:>7.2f}{span:>8.0f}  {tag:>18} {r:>6} {n:>7}  '
                  f'RVA 0x{arrbase_rva:X}')
        else:
            base = int(tag, 16)
            arrbase = base + r * 4 - XOFF_F * 4
            print(f'{cnt:>7}{ratio:>7.2f}{span:>8.0f}  {tag:>18} {r:>6} {n:>7}  '
                  f'0x{arrbase:<16X}')
    p.close()


if __name__ == '__main__':
    main()
