"""反汇编指定 RVA 范围，列出所有 RIP 相对引用的全局地址

用法: py tools\\scan_globals.py 0x68820 0x1500 [更多 起始RVA 长度 对...]
用途: 找一个函数引用了哪些全局变量；多段合并后**被反复引用的地址簇**就是大结构
      （如 g_GameManager）——比按原版偏移硬猜可靠。
"""
import os
import re
import sys
from collections import Counter

import capstone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import th06
from winmem import module_base

RIP_RE = re.compile(r'\[rip ([+-]) (0x[0-9a-f]+)\]')


def scan(p, mb, rva, size):
    code = p.read(mb + rva, size)
    if not code:
        return []
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
    md.detail = False
    md.skipdata = True
    out = []
    for insn in md.disasm(code, rva):
        m = RIP_RE.search(insn.op_str)
        if not m:
            continue
        disp = int(m.group(2), 16)
        if m.group(1) == '-':
            disp = -disp
        out.append((insn.address + insn.size + disp, insn.address,
                    insn.mnemonic, insn.op_str))
    return out


def main():
    args = sys.argv[1:]
    if len(args) < 2:
        print(__doc__)
        return
    p, pid = th06.get_proc()
    mb = module_base(pid, 'th06nc.exe')[0]
    print(f'PID {pid}  基址 0x{mb:X}')
    pairs = [(int(args[i], 16), int(args[i + 1], 16))
             for i in range(0, len(args) - 1, 2)]
    allhits = []
    for rva, size in pairs:
        hits = scan(p, mb, rva, size)
        allhits += hits
        print(f'\n=== RVA 0x{rva:X}..0x{rva + size:X}  {len(hits)} 处 RIP 引用 ===')
        cnt = Counter(t for t, *_ in hits)
        for tgt, n in sorted(cnt.items()):
            ex = next(h for h in hits if h[0] == tgt)
            print(f'  0x{tgt:06X}  x{n:<3} 例: 0x{ex[1]:06X}  {ex[2]} {ex[3]}')
    if len(pairs) > 1:
        print(f'\n=== 合并 {len(pairs)} 段：被 >=2 处引用 ===')
        cnt = Counter(t for t, *_ in allhits)
        for tgt, n in sorted(cnt.items()):
            if n >= 2:
                print(f'  0x{tgt:06X}  x{n}')
    p.close()


if __name__ == '__main__':
    main()
