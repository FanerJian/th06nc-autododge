"""
自机坐标定位 v3 —— 对称循环消除「暂停/恢复」本身的干扰

  X1: 恢复 -> 不按键 0.4s -> 暂停
  X2: 恢复 -> 不按键 0.4s -> 暂停   (与 X1 同操作，差异=世界自然演化)
  X3: 恢复 -> 按左 0.4s  -> 暂停
  X4: 恢复 -> 按下 0.4s  -> 暂停

  still = |X1 - X2| ~ 0     -> 排除会自己动的东西（子弹/背景/计时器）
  mov_x = still & (X1 - X3 > th)   -> 按左时减小的 = 自机 x
  mov_y = still & (X4 - X3 > th)   -> 按下时增大的 = 自机 y
"""
import sys
import os
import time
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import th06
from winmem import MEM_MAPPED

MAX_REGION = 4 * 1024 * 1024
LO, HI = 0.5, 700.0
HOLD = 0.40


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


def cycle(p, key=None, hold=HOLD):
    th06.tap('z', 80)              # 解除暂停
    time.sleep(0.12)
    if key:
        th06.key_down(key)
        time.sleep(hold)
        th06.key_up(key)
        time.sleep(0.03)
    else:
        time.sleep(hold)
    th06.tap('esc', 80)            # 暂停
    time.sleep(0.28)


def main():
    p, pid = th06.get_proc()
    print('PID', pid, flush=True)
    th06._focus_game(pid)
    time.sleep(0.2)
    regs = small_regions(p)
    A, VA = collect(p, regs)
    print(f'初筛候选: {len(A)} 个 float', flush=True)

    print('X1: 恢复/不按键 ...', flush=True); cycle(p, None);      X1 = reread(p, A)
    print('X2: 恢复/不按键 ...', flush=True); cycle(p, None);      X2 = reread(p, A)
    print('X3: 恢复/按左  ...', flush=True); cycle(p, 'left');     X3 = reread(p, A)
    print('X4: 恢复/按下  ...', flush=True); cycle(p, 'down');     X4 = reread(p, A)

    ok = np.isfinite(X1) & np.isfinite(X2) & np.isfinite(X3) & np.isfinite(X4)
    still = ok & (np.abs(X1 - X2) < 0.02)
    mx = still & ((X1 - X3) > 1.0)
    my = still & ((X4 - X3) > 1.0)
    print(f'\n静止(X1==X2): {still.sum()} / {ok.sum()}')
    print(f'  左移减小(x候选): {mx.sum()}')
    print(f'  下移增大(y候选): {my.sum()}')

    def show(tag, mask):
        idx = np.nonzero(mask)[0]
        if len(idx) == 0:
            print(f'\n--- {tag}: 无 ---')
            return
        print(f'\n--- {tag} ({len(idx)}) ---')
        print(f'{"addr":<18}{"X1":>10}{"X2":>10}{"X3":>10}{"X4":>10}')
        for i in idx[:50]:
            print(f'0x{A[i]:<16X}{X1[i]:>10.3f}{X2[i]:>10.3f}{X3[i]:>10.3f}{X4[i]:>10.3f}')

    show('x 候选（按左减小）', mx)
    show('y 候选（按下增大）', my)

    # 同一 64KB 页里既有 x 又有 y 候选 -> 极可能是 Player 结构
    xp = np.nonzero(mx)[0]
    yp = np.nonzero(my)[0]
    if len(xp) and len(yp):
        xpages = {}
        for i in xp:
            xpages.setdefault(int(A[i]) >> 16, []).append(i)
        ypages = {}
        for i in yp:
            ypages.setdefault(int(A[i]) >> 16, []).append(i)
        common = sorted(set(xpages) & set(ypages))
        print(f'\n=== x/y 候选共处的 64KB 页: {len(common)} ===')
        for pg in common:
            print(f'\n页 0x{pg << 16:X}')
            for i in xpages[pg][:12]:
                print(f'   x 0x{A[i]:<16X} {X1[i]:>9.3f} -> {X3[i]:>9.3f}')
            for i in ypages[pg][:12]:
                print(f'   y 0x{A[i]:<16X} {X3[i]:>9.3f} -> {X4[i]:>9.3f}')
    p.close()


if __name__ == '__main__':
    main()
