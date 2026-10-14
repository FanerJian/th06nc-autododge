"""
让子弹飞 0.25s，找出"变化最密集的内存页" -> 那里就是弹幕/实体数组。
暂停冻结态下做，避免暂停/恢复本身的干扰（用两次同操作做基准）。
"""
import sys
import os
import time
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import th06
from winmem import MEM_MAPPED, PAGE_READWRITE, PAGE_EXECUTE_READWRITE

PAGE = 0x10000


def writable_regions(p, min_size=0x1000):
    return [r for r in p.regions(min_size=min_size, include_image=True)
            if r[3] != MEM_MAPPED
            and r[2] in (PAGE_READWRITE, PAGE_EXECUTE_READWRITE)]


def snapshot(p, regs):
    """返回 {page_base: float32 array}"""
    out = {}
    for base, size, prot, typ in regs:
        data = p.read(base, size)
        if not data or len(data) < 8:
            continue
        n = len(data) // 4
        arr = np.frombuffer(data[:n * 4], dtype='<f4')
        # 按 64KB 页切分存储
        pf = PAGE // 4
        for i in range(0, len(arr), pf):
            chunk = arr[i:i + pf]
            if len(chunk) < 8:
                continue
            out[base + i * 4] = chunk.copy()
    return out


def cycle(p, hold):
    th06.tap('z', 80)
    time.sleep(0.10)
    time.sleep(hold)
    th06.tap('esc', 80)
    time.sleep(0.28)


def main():
    p, pid = th06.get_proc()
    print('PID', pid, flush=True)
    th06._focus_game(pid)
    time.sleep(0.2)
    regs = writable_regions(p)
    print(f'{len(regs)} 区域 {sum(r[1] for r in regs)/1024/1024:.0f} MB', flush=True)

    print('基准快照 A1 (暂停态) ...', flush=True)
    A1 = snapshot(p, regs)
    print('对照: 恢复但不按键 0.25s (A2)', flush=True)
    cycle(p, 0.25)
    A2 = snapshot(p, regs)
    print('实验: 恢复正常跑 0.25s (B)', flush=True)
    cycle(p, 0.25)
    B = snapshot(p, regs)

    keys = sorted(set(A1) & set(A2) & set(B))
    print(f'\n可比对页数: {len(keys)}')

    rows = []
    for k in keys:
        a1, a2, b = A1[k], A2[k], B[k]
        if not (len(a1) == len(a2) == len(b)):
            continue
        base_change = np.count_nonzero(np.abs(a2 - a1) > 0.001)
        real_change = np.count_nonzero(np.abs(b - a1) > 0.001)
        rows.append((real_change - base_change, real_change, base_change, k))

    rows.sort(reverse=True)
    print(f'\n{"净变化":>8}{"总变化":>8}{"基准变化":>9}   页地址')
    for net, rc, bc, k in rows[:25]:
        print(f'{net:>8}{rc:>8}{bc:>9}   0x{k:X}')

    if rows:
        best = rows[0][3]
        print(f'\n=== 变化最密集的页 0x{best:X} ===')
        a1, b = A1[best], B[best]
        d = np.abs(b - a1)
        idx = np.nonzero(d > 0.001)[0]
        print(f'该页 {len(a1)} 个 float, {len(idx)} 个变化')
        print(f'{"偏移":<10}{"A":>14}{"B":>14}{"差值":>12}')
        for i in idx[:60]:
            print(f'0x{i*4:<8X}{a1[i]:>14.4f}{b[i]:>14.4f}{b[i]-a1[i]:>12.4f}')
        # 检查变化索引的间隔分布（找 stride）
        if len(idx) > 3:
            diffs = np.diff(idx)
            u, c = np.unique(diffs, return_counts=True)
            top = np.argsort(-c)[:12]
            print('\n变化索引间隔 TOP:')
            for t in top:
                print(f'  stride {u[t]} floats ({u[t]*4} B)  x{c[t]}')
    p.close()


if __name__ == '__main__':
    main()
