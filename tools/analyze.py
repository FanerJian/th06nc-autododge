"""
内存差分分析工具 (numpy 加速)
子命令:
  stat                 统计可写内存中 float 的分布，猜测坐标系
  snap <name>          保存快照 gz
  diff <a> <b>         比较两个快照
  probe                交互式探测：快照A -> 按键 -> 快照B -> 差分
"""
import sys
import os
import time
import struct
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import th06
from winmem import MEM_PRIVATE, MEM_IMAGE, MEM_MAPPED

SNAP_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '_tmp', 'snaps')
os.makedirs(SNAP_DIR, exist_ok=True)


def regions_for(p, which='data'):
    """
    which:
      'data'  - 主模块可写段 (.data) —— 全局变量
      'priv'  - 私有堆
      'all'   - 全部可写（不含 MAPPED）
    """
    from winmem import module_base
    out = []
    mb = module_base(p.pid, 'th06nc.exe')
    for base, size, prot, typ in p.regions(min_size=0x1000, include_image=True):
        if typ == MEM_MAPPED:
            continue
        is_mod = mb and mb[0] <= base < mb[0] + mb[1]
        if which == 'data' and is_mod:
            out.append((base, size, typ))
        elif which == 'priv' and typ == MEM_PRIVATE:
            out.append((base, size, typ))
        elif which == 'all':
            out.append((base, size, typ))
    return out


def snapshot(p, which='data', lo=-1e9, hi=1e9, progress=False, max_region=None):
    """返回 (addrs, vals) numpy 数组"""
    A, V = [], []
    regs = regions_for(p, which)
    if max_region:
        regs = [r for r in regs if r[1] <= max_region]
    regs.sort(key=lambda r: r[1])
    tot = sum(r[1] for r in regs)
    if progress:
        print(f'  {len(regs)} 个区域, 合计 {tot/1024/1024:.1f} MB', flush=True)
    done = 0
    t0 = time.time()
    for i, (base, size, typ) in enumerate(regs):
        data = p.read(base, size)
        done += size
        if progress and (i % 50 == 0 or i == len(regs) - 1):
            el = time.time() - t0
            print(f'  [{i+1}/{len(regs)}] {done/1024/1024:.0f}/{tot/1024/1024:.0f} MB '
                  f'{el:.1f}s', flush=True)
        if not data:
            continue
        n = len(data) // 4
        if n == 0:
            continue
        arr = np.frombuffer(data[:n * 4], dtype='<f4').astype(np.float32)
        m = np.isfinite(arr) & (arr >= lo) & (arr <= hi)
        idx = np.nonzero(m)[0]
        if idx.size == 0:
            continue
        A.append(base + idx.astype(np.uint64) * 4)
        V.append(arr[idx])
    if not A:
        return np.zeros(0, np.uint64), np.zeros(0, np.float32)
    addrs = np.concatenate(A)
    vals = np.concatenate(V)
    order = np.argsort(addrs)
    return addrs[order], vals[order]


def save_snap(name, addrs, vals):
    np.savez_compressed(os.path.join(SNAP_DIR, name + '.npz'), addrs=addrs, vals=vals)


def load_snap(name):
    d = np.load(os.path.join(SNAP_DIR, name + '.npz'))
    return d['addrs'], d['vals']


def cmd_stat():
    p, pid = th06.get_proc()
    print('PID', pid)
    for which in ('data', 'priv'):
        rs = regions_for(p, which)
        total = sum(r[1] for r in rs)
        print(f'{which}: {len(rs)} 区域 {total/1024/1024:.1f} MB')
    addrs, vals = snapshot(p, 'data')
    print('data 段 float 数:', len(vals))
    for lo, hi in [(0, 100), (0, 200), (0, 384), (0, 448), (0, 500), (0, 800),
                   (0, 1080), (0, 1920), (-500, 500), (0, 5000)]:
        c = int(np.count_nonzero((vals >= lo) & (vals <= hi)))
        print(f'  [{lo}, {hi}]: {c}')
    # 整数分布
    print('data 段中常见小整数(float):')
    iv = vals[(vals == np.floor(vals)) & (np.abs(vals) < 100000)]
    if iv.size:
        u, c = np.unique(iv, return_counts=True)
        top = np.argsort(-c)[:20]
        for i in top:
            print(f'  {u[i]:.0f}: {c[i]}')
    p.close()


def cmd_snap(name):
    p, pid = th06.get_proc()
    t0 = time.time()
    addrs, vals = snapshot(p, 'data')
    print(f'data 快照 {len(vals)} 个 float, {time.time()-t0:.2f}s')
    save_snap(name, addrs, vals)
    p.close()


def cmd_diff(a, b):
    A, VA = load_snap(a)
    B, VB = load_snap(b)
    # 对齐（地址集合可能不同）
    common, ia, ib = np.intersect1d(A, B, return_indices=True)
    va, vb = VA[ia], VB[ib]
    d = vb - va
    nz = np.nonzero(d != 0)[0]
    print(f'{a}: {len(VA)}  {b}: {len(VB)}  公共地址: {len(common)}  变化的: {len(nz)}')
    if len(nz) == 0:
        return
    dd = d[nz]
    ca = common[nz]
    order = np.argsort(-np.abs(dd))[:40]
    print(f'{"地址":<18}{"旧值":>14}{"新值":>14}{"差值":>14}')
    for i in order:
        print(f'0x{ca[i]:<16X}{va[nz][i]:>14.3f}{vb[nz][i]:>14.3f}{dd[i]:>14.3f}')


def cmd_probe(which='all', lo=-50.0, hi=1200.0, move_ms=250, gap_ms=120):
    """完整探测：A -> 左移 -> B ; A -> 上移 -> C"""
    p, pid = th06.get_proc()
    print('PID', pid, ' 聚焦游戏...')
    th06._focus_game(pid)
    time.sleep(0.3)
    print(f'区域={which} 值域=[{lo},{hi}] 移动={move_ms}ms')

    print('快照 A ...')
    t0 = time.time()
    A, VA = snapshot(p, which, lo, hi)
    print('  ', len(VA), f'{time.time()-t0:.2f}s')

    print(f'按住 左 {move_ms}ms ...')
    th06.key_down('left')
    time.sleep(move_ms / 1000.0)
    th06.key_up('left')
    time.sleep(gap_ms / 1000.0)
    B, VB = snapshot(p, which, lo, hi)
    print('  ', len(VB))

    print(f'按住 上 {move_ms}ms ...')
    th06.key_down('up')
    time.sleep(move_ms / 1000.0)
    th06.key_up('up')
    time.sleep(gap_ms / 1000.0)
    C, VC = snapshot(p, which, lo, hi)
    print('  ', len(VC))

    save_snap('probe_A', A, VA)
    save_snap('probe_B', B, VB)
    save_snap('probe_C', C, VC)

    # 差分
    ca, ia, ib = np.intersect1d(A, B, return_indices=True)
    vb = VB[ib]
    dx = vb - VA[ia]
    ca2, ia2, ic = np.intersect1d(A, C, return_indices=True)
    vc = VC[ic]
    dy = vc - VA[ia2]

    # 找 A,B 都变化且 A,C 都变化的地址中，属于同一结构的
    # 先看 A->B 的变化分布
    nz = dx != 0
    print(f'\nA->B 变化数: {nz.sum()}')
    m = np.abs(dx[nz])
    print('  变化量绝对值 分位:', np.percentile(m, [50, 90, 99]).round(4))
    # 找 -0.1 ~ -20 之间的负变化（左移）
    cand = nz & (dx < -0.05) & (dx > -30)
    print(f'  左移候选(变化 -0.05..-30): {cand.sum()}')

    # 在候选中，找 A->C 中 y 也变化的（上移一般 y 减小）
    idx_cand = np.nonzero(cand)[0]
    addrs_cand = ca[idx_cand]
    # 匹配到 C 的差分
    pos = np.searchsorted(ca2, addrs_cand)
    pos = np.clip(pos, 0, len(ca2) - 1)
    ok = ca2[pos] == addrs_cand
    dyv = np.full(len(addrs_cand), np.nan, np.float32)
    dyv[ok] = dy[pos[ok]]
    print(f'  其中在 C 中也有记录的: {ok.sum()}')
    both = ok & (np.abs(dyv) > 0.05)
    print(f'  左移和上移都变化的: {both.sum()}')
    sel = np.nonzero(both)[0][:60]
    print(f'\n{"地址":<18}{"A(x)":>12}{"B":>12}{"dx":>10}{"C_y":>12}{"dy":>10}')
    for i in sel:
        ai = idx_cand[i]
        print(f'0x{ca[ai]:<16X}{VA[ia][ai]:>12.3f}{vb[ai]:>12.3f}{dx[ai]:>10.3f}'
              f'{vc[np.searchsorted(ca2, ca[ai])]:>12.3f}{dyv[i]:>10.3f}')
    p.close()


def cmd_probe_paused(which='all', lo=-50.0, hi=1200.0, move_ms=300):
    """
    前提：游戏当前处于暂停状态（世界冻结）。
    A(暂停) -> 恢复+左移+暂停 -> B -> 恢复+上移+暂停 -> C
    冻结态快照噪声最小。
    """
    p, pid = th06.get_proc()
    th06._focus_game(pid)
    time.sleep(0.25)
    print(f'区域={which} 值域=[{lo},{hi}] 移动={move_ms}ms')

    def snap(tag):
        t0 = time.time()
        print(f'  扫描{tag} ...', flush=True)
        a, v = snapshot(p, which, lo, hi, progress=True)
        print(f'  快照{tag}: {len(v)} 个 float, {time.time()-t0:.2f}s', flush=True)
        return a, v

    def resume_move_pause(key):
        th06.tap('z', 80)            # 解除暂停（默认高亮「解除暂停」）
        time.sleep(0.25)
        th06.key_down(key)
        time.sleep(move_ms / 1000.0)
        th06.key_up(key)
        time.sleep(0.03)
        th06.tap('esc', 80)          # 暂停
        time.sleep(0.35)

    A, VA = snap('A')
    print('  恢复 + 左移 + 暂停 ...')
    resume_move_pause('left')
    B, VB = snap('B')
    print('  恢复 + 上移 + 暂停 ...')
    resume_move_pause('up')
    C, VC = snap('C')

    save_snap('probe2_A', A, VA)
    save_snap('probe2_B', B, VB)
    save_snap('probe2_C', C, VC)

    # ---- 差分 ----
    ca, ia, ib = np.intersect1d(A, B, return_indices=True)
    vb = VB[ib]
    va = VA[ia]
    dx = vb - va
    ca2, ia2, ic = np.intersect1d(A, C, return_indices=True)
    vc = VC[ic]
    dy = vc - VA[ia2]

    print(f'\nA->B 变化地址: {(dx != 0).sum()} / {len(dx)}')
    print(f'A->C 变化地址: {(dy != 0).sum()} / {len(dy)}')

    # 左移：x 减小；上移：y 减小
    left_idx = np.nonzero((dx < -0.2) & (dx > -60))[0]
    print(f'左移候选 (dx in -0.2..-60): {len(left_idx)}')

    # 在这些地址里，找 A->C 也有变化的（上移时 y 变化）
    addrs = ca[left_idx]
    pos = np.searchsorted(ca2, addrs)
    pos = np.clip(pos, 0, max(0, len(ca2) - 1))
    ok = (len(ca2) > 0) & (ca2[pos] == addrs) if len(ca2) else np.zeros(len(addrs), bool)
    dyv = np.zeros(len(addrs), np.float32)
    dyv[ok] = dy[pos[ok]]

    both = ok & (np.abs(dyv) > 0.2)
    print(f'其中 A->C 也变化: {both.sum()}')

    sel = np.nonzero(both)[0]
    sel = sel[np.argsort(-np.abs(dyv[sel]))][:80]
    print(f'\n{"地址":<18}{"A_x":>12}{"B_x":>12}{"dx":>10}{"C_y":>12}{"dy":>10}')
    for i in sel:
        ai = left_idx[i]
        ad = ca[ai]
        j = np.searchsorted(ca2, ad)
        print(f'0x{ad:<16X}{va[ai]:>12.4f}{vb[ai]:>12.4f}{dx[ai]:>10.4f}'
              f'{vc[j] if j < len(vc) else float("nan"):>12.4f}{dyv[i]:>10.4f}')

    # 额外：直接找「值在游玩区范围内」且成对相邻的地址
    print('\n--- 相邻对 (addr, addr+4) 同时为左移候选 ---')
    s = set(ca[left_idx].tolist())
    pairs = [(a, a + 4) for a in s if (a + 4) in s]
    for a, b in pairs[:40]:
        i1 = np.searchsorted(ca, a)
        i2 = np.searchsorted(ca, b)
        print(f'  0x{a:<16X} {va[i1]:>10.3f} -> {vb[i1]:>10.3f}   '
              f'0x{b:<16X} {va[i2]:>10.3f} -> {vb[i2]:>10.3f}')
    p.close()


if __name__ == '__main__':
    cmd = sys.argv[1]
    if cmd == 'stat':
        cmd_stat()
    elif cmd == 'snap':
        cmd_snap(sys.argv[2])
    elif cmd == 'diff':
        cmd_diff(sys.argv[2], sys.argv[3])
    elif cmd == 'probe':
        which = sys.argv[2] if len(sys.argv) > 2 else 'all'
        cmd_probe(which)
    elif cmd == 'probe2':
        which = sys.argv[2] if len(sys.argv) > 2 else 'all'
        cmd_probe_paused(which)
