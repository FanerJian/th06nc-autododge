"""扫描 .text 段所有 RIP 相对引用，列出引用指定 RVA 的指令位置

用法: py tools\\scan_xrefs.py 0x3EC2A0 [更多目标RVA...]
用途: 确认某个全局变量/数据地址被哪些函数引用，交叉验证地址正确性。
"""
import re
import sys
import os
import capstone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import th06
from offsets import TEXT_HI, TEXT_LO
from winmem import module_base

RIP_RE = re.compile(r'\[rip ([+-]) (0x[0-9a-f]+)\]')


def scan(p, mb, targets):
    hits = {t: [] for t in targets}
    tset = set(targets)
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
    md.detail = False
    md.skipdata = True
    data = p.read(mb + TEXT_LO, TEXT_HI - TEXT_LO)
    if not data:
        return hits, 0
    total = 0
    for insn in md.disasm(data, TEXT_LO):
        total += 1
        if 'rip' not in insn.op_str:
            continue
        m = RIP_RE.search(insn.op_str)
        if not m:
            continue
        disp = int(m.group(2), 16)
        if m.group(1) == '-':
            disp = -disp
        tgt = insn.address + insn.size + disp
        if tgt in tset:
            hits[tgt].append((insn.address, insn.mnemonic, insn.op_str))
    return hits, total


def main():
    args = sys.argv[1:] or ['0x3EC2A0']
    targets = [int(a, 16) for a in args]
    p, pid = th06.get_proc()
    mb = module_base(pid, 'th06nc.exe')[0]
    print(f'PID {pid}  基址 0x{mb:X}')
    hits, total = scan(p, mb, targets)
    print(f'反汇编指令数 {total}')
    for t in targets:
        hs = hits[t]
        print(f'\n=== RVA 0x{t:X} 被 {len(hs)} 处 RIP 相对引用 ===')
        for addr, mn, ops in hs:
            print(f'  0x{addr:06X}  {mn:<8} {ops}')
    p.close()


if __name__ == '__main__':
    main()
