"""监控「被代码引用的全局变量」随时间的变化，用于发现画面判据

背景：新典把游戏状态拆成了独立全局（GameManager 布局与原版不同），按原版偏移
推算必然错位。改为先从 .text 收集所有 RIP 相对引用目标，再周期采样，只记录变化 —— 
用户按自己的节奏操作游戏，工具只读，不发任何按键。

用法:
  py tools\\watch_globals.py --seconds 600
输出: _tmp\\watch_<时间戳>.log   （格式: 秒  地址  旧值 -> 新值）
"""
import argparse
import os
import re
import sys
import time

import capstone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import th06
from offsets import TEXT_HI, TEXT_LO
from winmem import module_base

RIP_RE = re.compile(r'\[rip ([+-]) (0x[0-9a-f]+)\]')
CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '_tmp', 'globals_cache.txt')


def collect_targets(p, mb, mod_size):
    """扫描 .text 收集所有 RIP 相对引用目标（模块内），结果缓存到 _tmp/"""
    if os.path.exists(CACHE):
        return [int(x) for x in open(CACHE).read().split()]
    print('首次运行：扫描 .text 收集全局引用目标（约需 1 分钟，之后走缓存）...')
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
    md.detail = False
    md.skipdata = True
    data = p.read(mb + TEXT_LO, TEXT_HI - TEXT_LO)
    tg = set()
    for insn in md.disasm(data, TEXT_LO):
        m = RIP_RE.search(insn.op_str)
        if not m:
            continue
        d = int(m.group(2), 16)
        if m.group(1) == '-':
            d = -d
        t = insn.address + insn.size + d
        if 0 < t < mod_size:
            tg.add(t)
    tg = sorted(tg)
    with open(CACHE, 'w') as f:
        f.write('\n'.join(map(str, tg)))
    return tg


def to_regions(targets, gap=0x400):
    """把目标合并成区间，减少 ReadProcessMemory 次数"""
    regs, base, end = [], None, None
    for t in targets:
        if base is None:
            base, end = t, t + 8
        elif t <= end + gap:
            end = max(end, t + 8)
        else:
            regs.append((base, end - base))
            base, end = t, t + 8
    if base is not None:
        regs.append((base, end - base))
    return regs


def snapshot(p, mb, regs):
    out = {}
    for b, s in regs:
        d = p.read(mb + b, s)
        if d and len(d) == s:
            out[b] = d
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--seconds', type=float, default=600)
    ap.add_argument('--every', type=float, default=0.15)
    ap.add_argument('--out', default=None)
    args = ap.parse_args()

    p, pid = th06.get_proc()
    mb, size = module_base(pid, 'th06nc.exe')[:2]
    tg = collect_targets(p, mb, size)
    regs = to_regions(tg)
    print(f'PID {pid}  基址 0x{mb:X}  模块 0x{size:X}')
    print(f'全局目标 {len(tg)} 个 → {len(regs)} 个区间，共 {sum(s for _, s in regs) / 1024:.1f} KB')

    out = args.out or os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '_tmp',
                                   time.strftime('watch_%Y%m%d_%H%M%S.log'))
    print(f'输出 → {out}   现在开始操作游戏即可（工具只读，不发按键）')
    prev = snapshot(p, mb, regs)
    t0, changes = time.time(), 0
    with open(out, 'w', encoding='utf-8') as f:
        f.write('# 秒  地址  旧值 -> 新值\n')
        while time.time() - t0 < args.seconds:
            time.sleep(args.every)
            cur = snapshot(p, mb, regs)
            t = time.time() - t0
            for b, d in cur.items():
                a = prev.get(b)
                if a == d:
                    continue
                for i in range(len(d)):
                    if a is None or a[i] != d[i]:
                        f.write(f'{t:8.2f}  0x{b + i:06X}  {a[i] if a else -1:3d} -> {d[i]:3d}\n')
                        changes += 1
                prev[b] = d
            f.flush()
    print(f'采集结束：{changes} 条变化 → {out}')
    p.close()


if __name__ == '__main__':
    main()
