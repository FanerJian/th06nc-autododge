"""
用「槽首状态 WORD」特征定位子弹数组。
依据 ModeCode.cs: 640 槽, stride 0x620=1568B=784 words, 槽首 2 字节是状态
(清空时 MOV WORD PTR [RDX],0), 激光 64 槽 stride 0x298=664B。

判据: 存在索引 r 使得 w[r::784] 的前 640 项满足
      「相当比例是 0, 且非零值都是小整数」
"""
import sys
import os
import time
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import th06
from winmem import MEM_MAPPED, PAGE_READWRITE, PAGE_EXECUTE_READWRITE

STRIDE_W = 784          # 1568 / 2
SLOTS = 640
MIN_REGION = 1 << 20    # 子弹数组约 0.96MB, 只扫 >=1MB 的区域


def main():
    p, pid = th06.get_proc()
    print('PID', pid, flush=True)
    regs = [r for r in p.regions(min_size=MIN_REGION, include_image=True)
            if r[3] != MEM_MAPPED and r[2] in (PAGE_READWRITE, PAGE_EXECUTE_READWRITE)]
    regs.sort(key=lambda r: -r[1])
    print(f'{len(regs)} 个大区域, {sum(r[1] for r in regs)/1024/1024:.0f} MB', flush=True)

    t0 = time.time()
    results = []
    for base, size, prot, typ in regs:
        data = p.read(base, size)
        if not data or len(data) < SLOTS * STRIDE_W * 2:
            continue
        w = np.frombuffer(data[:len(data) // 2 * 2], dtype='<u2')
        n = len(w)
        best = None
        for r in range(STRIDE_W):
            sub = w[r:r + SLOTS * STRIDE_W:STRIDE_W]
            if len(sub) < SLOTS:
                continue
            nz = sub[sub != 0]
            zeros = len(sub) - len(nz)
            ratio = zeros / len(sub)
            if not (0.02 < ratio < 0.995):
                continue
            if len(nz) == 0:
                continue
            mx = int(nz.max())
            if mx > 64:                       # 状态码应当很小
                continue
            score = len(nz)
            if best is None or score > best[0]:
                best = (score, r, ratio, mx)
        if best:
            results.append((best[0], base, size, typ, best[1], best[2], best[3]))
            print(f'  候选 0x{base:<14X} 非零槽={best[0]:>4} r={best[1]:>4} '
                  f'空槽比={best[2]:.3f} 最大状态={best[3]}', flush=True)

    print(f'\n耗时 {time.time()-t0:.1f}s, 候选 {len(results)} 个')
    results.sort(reverse=True)
    for sc, base, size, typ, r, ratio, mx in results[:20]:
        print(f'  非零={sc:>4} base=0x{base:<14X} size={size/1024/1024:.1f}MB '
              f'r={r} 空槽比={ratio:.3f} 最大状态={mx}')
    p.close()


if __name__ == '__main__':
    main()
