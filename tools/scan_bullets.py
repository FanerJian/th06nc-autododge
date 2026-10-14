"""
在全部可写内存中定位子弹数组。
依据 ModeCode.cs 的清空循环:
    LEA RDX,[RCX+0x4C] ; MOV EAX,0x280 ; loop { MOV WORD[RDX],0 ; ADD RDX,0x620 ; DEC EAX }
  => 640 个槽, 每槽 stride = 0x620 = 1568 字节 = 392 floats, 槽首 WORD 为状态

特征: 若坐标字段在槽内固定偏移, 则活跃子弹的坐标在 float 索引上必然构成
      公差为 392 的等差数列 => 相邻命中索引之差是 392 的倍数。
"""
import sys
import os
import time
import struct
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import th06
from winmem import (MEM_MAPPED, PAGE_READWRITE, PAGE_EXECUTE_READWRITE,
                    PAGE_WRITECOPY, PAGE_EXECUTE_WRITECOPY)

STRIDE_F = 392            # 1568 / 4
LO, HI = 0.5, 440.0       # 覆盖 x∈[0,384] 与 y∈[0,448]


def writable_regions(p):
    return [r for r in p.regions(min_size=0x1000, include_image=True)
            if r[3] != MEM_MAPPED
            and r[2] in (PAGE_READWRITE, PAGE_EXECUTE_READWRITE,
                         PAGE_WRITECOPY, PAGE_EXECUTE_WRITECOPY)]


def main():
    p, pid = th06.get_proc()
    print('PID', pid, flush=True)
    regs = writable_regions(p)
    regs.sort(key=lambda r: -r[1])
    tot = sum(r[1] for r in regs)
    print(f'{len(regs)} 个可写区域, {tot/1024/1024:.0f} MB', flush=True)

    results = []
    t0 = time.time()
    done = 0
    for i, (base, size, prot, typ) in enumerate(regs):
        data = p.read(base, size)
        done += size
        if data and len(data) >= STRIDE_F * 16:
            arr = np.frombuffer(data[:len(data) // 4 * 4], dtype='<f4')
            m = (arr > LO) & (arr < HI)
            idx = np.nonzero(m)[0]
            if idx.size >= 12:
                d = np.diff(idx)
                hits = int(np.count_nonzero((d > 0) & (d % STRIDE_F == 0)))
                if hits >= 12:
                    results.append((hits, base, size, typ, int(idx.size)))
        if i % 200 == 0:
            print(f'  [{i+1}/{len(regs)}] {done/1024/1024:.0f}/{tot/1024/1024:.0f} MB '
                  f'{time.time()-t0:.1f}s 候选{len(results)}', flush=True)

    results.sort(reverse=True)
    print(f'\n=== 候选区域 (耗时 {time.time()-t0:.1f}s) ===')
    print(f'{"命中":>7}{"基址":>18}{"大小KB":>10}{"类型":>10}{"区内游乐区值":>12}')
    for hits, base, size, typ, nv in results[:30]:
        print(f'{hits:>7}  0x{base:<16X}{size/1024:>10.0f}  0x{typ:<8X}{nv:>12}')

    if results:
        # 对最佳候选做详细 dump：找出命中最密集的窗口
        hits, base, size, typ, nv = results[0]
        print(f'\n=== 最佳候选 0x{base:X} 详细分析 ===')
        data = p.read(base, min(size, 4 * 1024 * 1024))
        arr = np.frombuffer(data[:len(data) // 4 * 4], dtype='<f4')
        m = (arr > LO) & (arr < HI)
        idx = np.nonzero(m)[0]
        d = np.diff(idx)
        good = np.nonzero((d > 0) & (d % STRIDE_F == 0))[0]
        print(f'等差数列命中 {len(good)} 处，分布:')
        for k in good[:20]:
            i0, i1 = idx[k], idx[k + 1]
            print(f'  float[{i0}] = {arr[i0]:.3f}  ->  float[{i1}] = {arr[i1]:.3f}   '
                  f'(字节偏移 0x{i0*4:X})')
    p.close()


if __name__ == '__main__':
    main()
