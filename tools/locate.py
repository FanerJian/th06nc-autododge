"""
自机坐标定位 —— 优化版
思路：
  1. 只扫描"小块"可写内存（跳过 >4MB 的巨型区域 —— 那里是图形/音频资源缓冲）
  2. 只保留「相邻两个 float 都在游玩区范围内」的候选对 (x@addr, y@addr+4)
  3. 移动自机（暂停冻结保护）后重读这些地址，找真正跟着变的
"""
import sys
import os
import time
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import th06
from winmem import MEM_MAPPED

MAX_REGION = 4 * 1024 * 1024      # 跳过大于 4MB 的区域
X_LO, X_HI = 1.0, 400.0            # 自机 x 可能范围（384 宽 + 余量）
Y_LO, Y_HI = 1.0, 460.0            # 自机 y 可能范围（448 高 + 余量）


def small_regions(p):
    out = []
    for base, size, prot, typ in p.regions(min_size=0x1000, include_image=True):
        if typ == MEM_MAPPED:
            continue
        if size > MAX_REGION:
            continue
        out.append((base, size, typ))
    out.sort(key=lambda r: r[0])
    return out


def collect_pairs(p, regs):
    """返回 (addrs, vx, vy)：addr 指向 x，addr+4 是 y"""
    A, VX, VY = [], [], []
    for base, size, typ in regs:
        data = p.read(base, size)
        if not data:
            continue
        n = len(data) // 4
        if n < 2:
            continue
        arr = np.frombuffer(data[:n * 4], dtype='<f4')
        x = arr[:-1]
        y = arr[1:]
        m = ((x >= X_LO) & (x <= X_HI) & (y >= Y_LO) & (y <= Y_HI)
             & np.isfinite(x) & np.isfinite(y))
        idx = np.nonzero(m)[0]
        if idx.size == 0:
            continue
        A.append(base + idx.astype(np.uint64) * 4)
        VX.append(x[idx])
        VY.append(y[idx])
    if not A:
        return (np.zeros(0, np.uint64), np.zeros(0, np.float32), np.zeros(0, np.float32))
    return np.concatenate(A), np.concatenate(VX), np.concatenate(VY)


def reread(p, addrs):
    """按地址逐个重读 (x, y) —— 用区域分组批量读，快"""
    vx = np.full(len(addrs), np.nan, np.float32)
    vy = np.full(len(addrs), np.nan, np.float32)
    order = np.argsort(addrs)
    sa = addrs[order]
    # 按 64KB 页分组
    page = sa >> 16
    bounds = np.nonzero(np.diff(page))[0] + 1
    groups = np.split(np.arange(len(sa)), bounds)
    for g in groups:
        if len(g) == 0:
            continue
        lo = int(sa[g[0]]) & ~0xFFFF
        hi = int(sa[g[-1]]) + 8
        data = p.read(lo, hi - lo)
        if not data:
            continue
        arr = np.frombuffer(data[:len(data) // 4 * 4], dtype='<f4')
        offs = ((sa[g] - lo) // 4).astype(np.int64)
        ok = offs + 1 < len(arr)
        vx[order[g[ok]]] = arr[offs[ok]]
        vy[order[g[ok]]] = arr[offs[ok] + 1]
    return vx, vy


def main():
    p, pid = th06.get_proc()
    print('PID', pid, flush=True)
    th06._focus_game(pid)
    time.sleep(0.2)

    regs = small_regions(p)
    tot = sum(r[1] for r in regs)
    print(f'小块区域: {len(regs)} 个, 合计 {tot/1024/1024:.1f} MB', flush=True)

    t0 = time.time()
    A, VX, VY = collect_pairs(p, regs)
    print(f'候选相邻对: {len(A)} 个  ({time.time()-t0:.2f}s)', flush=True)
    if len(A) == 0:
        print('无候选，放宽范围'); return

    # 移动：左
    print('解除暂停 + 左移 0.3s + 暂停 ...', flush=True)
    th06.tap('z', 80); time.sleep(0.25)
    th06.key_down('left'); time.sleep(0.30); th06.key_up('left')
    time.sleep(0.03)
    th06.tap('esc', 80); time.sleep(0.35)
    BX, BY = reread(p, A)

    # 移动：上
    print('解除暂停 + 上移 0.3s + 暂停 ...', flush=True)
    th06.tap('z', 80); time.sleep(0.25)
    th06.key_down('up'); time.sleep(0.30); th06.key_up('up')
    time.sleep(0.03)
    th06.tap('esc', 80); time.sleep(0.35)
    CX, CY = reread(p, A)

    dx = BX - VX
    dy = CY - VY
    ok = np.isfinite(dx) & np.isfinite(dy)
    # 左移 => x 变小 ; 上移 => y 变小
    hit = ok & (dx < -0.5) & (dx > -80) & (dy < -0.5) & (dy > -80)
    print(f'\n同时满足「左移时 x 减小」和「上移时 y 减小」的候选: {hit.sum()}', flush=True)

    idx = np.nonzero(hit)[0]
    if len(idx) == 0:
        print('没有命中，放宽条件：')
        hit2 = ok & (np.abs(dx) > 0.3) & (np.abs(dy) > 0.3)
        idx = np.nonzero(hit2)[0]
        print(f'  「两次移动都有变化」的候选: {len(idx)}')

    order = np.argsort(np.abs(dy[idx]))
    sel = idx[order][:60]
    print(f'\n{"addr":<18}{"A_x":>10}{"B_x":>10}{"dx":>9}{"A_y":>10}{"C_y":>10}{"dy":>9}')
    for i in sel:
        print(f'0x{A[i]:<16X}{VX[i]:>10.3f}{BX[i]:>10.3f}{dx[i]:>9.3f}'
              f'{VY[i]:>10.3f}{CY[i]:>10.3f}{dy[i]:>9.3f}')
    p.close()


if __name__ == '__main__':
    main()
