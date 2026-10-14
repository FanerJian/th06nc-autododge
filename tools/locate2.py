"""
自机坐标定位 v2 —— 用「静止不变 ∩ 按键才变」这个强特征

  A: 暂停态快照
  B: 恢复 0.35s 不按键，再暂停   -> 自机坐标应与 A 完全相同
  C: 恢复后按左 0.35s，再暂停    -> 自机 x 应减小
  D: 恢复后按下 0.35s，再暂停    -> 自机 y 应增大

候选 = (|A-B| ~ 0) 且 (|A-C| 或 |A-D| 显著)
子弹/粒子/背景一直变 -> 被 |A-B| ~ 0 排除
"""
import sys
import os
import time
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import th06
from winmem import MEM_MAPPED

MAX_REGION = 4 * 1024 * 1024
LO, HI = 0.5, 520.0


def small_regions(p):
    out = []
    for base, size, prot, typ in p.regions(min_size=0x1000, include_image=True):
        if typ == MEM_MAPPED or size > MAX_REGION:
            continue
        out.append((base, size, typ))
    out.sort(key=lambda r: r[0])
    return out


def collect(p, regs):
    A, V = [], []
    for base, size, typ in regs:
        data = p.read(base, size)
        if not data:
            continue
        n = len(data) // 4
        if n == 0:
            continue
        arr = np.frombuffer(data[:n * 4], dtype='<f4')
        m = np.isfinite(arr) & (arr >= LO) & (arr <= HI)
        idx = np.nonzero(m)[0]
        if idx.size == 0:
            continue
        A.append(base + idx.astype(np.uint64) * 4)
        V.append(arr[idx])
    return np.concatenate(A), np.concatenate(V)


def reread(p, addrs):
    """按 64KB 页分组批量重读，返回 float 数组"""
    out = np.full(len(addrs), np.nan, np.float32)
    order = np.argsort(addrs)
    sa = addrs[order]
    page = sa >> 16
    bounds = np.nonzero(np.diff(page))[0] + 1
    for g in np.split(np.arange(len(sa)), bounds):
        if len(g) == 0:
            continue
        lo = int(sa[g[0]]) & ~0xFFFF
        hi = int(sa[g[-1]]) + 4
        data = p.read(lo, hi - lo)
        if not data:
            continue
        arr = np.frombuffer(data[:len(data) // 4 * 4], dtype='<f4')
        offs = ((sa[g] - lo) // 4).astype(np.int64)
        ok = offs < len(arr)
        out[order[g[ok]]] = arr[offs[ok]]
    return out


def cycle(p, key=None, hold=0.35, pre=0.10):
    """解除暂停 -> (可选按键 hold 秒) -> 暂停"""
    th06.tap('z', 80)
    time.sleep(pre)
    if key:
        th06.key_down(key)
        time.sleep(hold)
        th06.key_up(key)
        time.sleep(0.03)
    else:
        time.sleep(hold)
    th06.tap('esc', 80)
    time.sleep(0.30)


def main():
    p, pid = th06.get_proc()
    print('PID', pid, flush=True)
    th06._focus_game(pid)
    time.sleep(0.2)
    regs = small_regions(p)
    print(f'小块区域 {len(regs)} 个, {sum(r[1] for r in regs)/1024/1024:.0f} MB', flush=True)

    t0 = time.time()
    A, VA = collect(p, regs)
    print(f'扫描A: {len(A)} 个候选值 ({time.time()-t0:.2f}s)', flush=True)

    print('B: 恢复但不按键 0.35s ...', flush=True)
    cycle(p, None)
    VB = reread(p, A)

    print('C: 恢复并按左 0.35s ...', flush=True)
    cycle(p, 'left')
    VC = reread(p, A)

    print('D: 恢复并按下 0.35s ...', flush=True)
    cycle(p, 'down')
    VD = reread(p, A)

    ok = np.isfinite(VB) & np.isfinite(VC) & np.isfinite(VD)
    still = ok & (np.abs(VB - VA) < 0.02)
    d_left = VA - VC          # 左移 -> x 减小 -> 正值
    d_down = VD - VA          # 下移 -> y 增大 -> 正值
    mov_x = still & (d_left > 0.8)
    mov_y = still & (d_down > 0.8)

    print(f'\n静止不变(A==B)的: {still.sum()} / {ok.sum()}')
    print(f'其中 左移使值减小: {mov_x.sum()}')
    print(f'其中 下移使值增大: {mov_y.sum()}')

    def show(tag, mask):
        idx = np.nonzero(mask)[0]
        if len(idx) == 0:
            return
        print(f'\n--- {tag} ({len(idx)}) ---')
        print(f'{"addr":<18}{"A":>11}{"B":>11}{"C":>11}{"D":>11}')
        for i in idx[:60]:
            print(f'0x{A[i]:<16X}{VA[i]:>11.3f}{VB[i]:>11.3f}{VC[i]:>11.3f}{VD[i]:>11.3f}')

    show('左移时减小（x 坐标候选）', mov_x)
    show('下移时增大（y 坐标候选）', mov_y)

    # 交叉：x 候选和 y 候选在同一 64KB 页里
    xi = set((A[np.nonzero(mov_x)[0]] >> 16).tolist())
    yi = set((A[np.nonzero(mov_y)[0]] >> 16).tolist())
    print(f'\nx候选页数={len(xi)} y候选页数={len(yi)} 共同页={len(xi & yi)}')
    for pg in sorted(xi & yi):
        print(f'  共同页 0x{pg << 16:X}')
    p.close()


if __name__ == '__main__':
    main()
