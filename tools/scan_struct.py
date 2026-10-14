"""扫描函数访问的结构偏移 / 追踪指针来源 —— 定位「某结构各字段在哪」

为什么需要它：`tools/scan_globals.py` 只列**全局地址**（RIP 相对引用），
但结构字段访问是 `[reg+disp]`，它看不见。本次定位敌人射击字段时手工重复了三次，
故固化成一条命令。

用法:
  py tools\\scan_struct.py 0x28A80 0x200            # 列出该范围访问的所有 [reg+disp]
  py tools\\scan_struct.py 0x28A80 0x200 --reg rdi  # 只看某个基址寄存器（定位结构字段）
  py tools\\scan_struct.py 0xF870 0x200 --src rdi   # 找"谁写了 rdi"（追参数来源/确定指针含义）

判读要点：
  - 同一结构被反复访问的偏移簇 = 该结构的字段；被访问最多的通常是热点字段。
  - `--src` 给 `lea rX, [rY+disp]` 时，disp 就是该指针相对 rY 的偏移（本次即由此确证
    `bulletProps = Enemy + 0x26C`）。
"""
import argparse
import os
import sys
from collections import Counter

import capstone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import th06
from winmem import module_base

OP_MEM = capstone.x86.X86_OP_MEM
OP_REG = capstone.x86.X86_OP_REG
OP_IMM = capstone.x86.X86_OP_IMM


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('rva', help='起始 RVA，如 0x28A80')
    ap.add_argument('size', help='扫描长度（字节），如 0x200')
    ap.add_argument('--reg', help='只看该基址寄存器的 [reg+disp]')
    ap.add_argument('--src', help='改为追踪：列出写入该寄存器的指令')
    ap.add_argument('--call', help='改为追踪：列出 call 该 RVA 的位置及其参数来源')
    a = ap.parse_args()

    p, pid = th06.get_proc()
    mb = module_base(pid, 'th06nc.exe')[0]
    rva, size = int(a.rva, 16), int(a.size, 16)
    code = p.read(mb + rva, size)
    if not code:
        print('读取失败')
        return
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
    md.detail = True
    md.skipdata = True
    insns = [i for i in md.disasm(code, rva) if i.id != 0]   # skipdata 的 data 伪指令要跳过
    print(f'PID {pid}  基址 0x{mb:X}  RVA 0x{rva:X}..0x{rva+size:X}  {len(insns)} 条指令')

    if a.src:
        print(f'\n=== 写入 {a.src} 的指令 ===')
        for i in insns:
            if i.mnemonic in ('lea', 'mov', 'add', 'sub') and i.operands:
                d = i.operands[0]
                if d.type == OP_REG and i.reg_name(d.reg) == a.src:
                    print(f'  0x{i.address:06X}  {i.mnemonic:<6} {i.op_str}')
        return

    if a.call:
        tgt = int(a.call, 16)
        print(f'\n=== call 0x{tgt:X} 的位置 + 参数来源 ===')
        for idx, i in enumerate(insns):
            if i.mnemonic != 'call' or not i.operands:
                continue
            o = i.operands[0]
            if o.type != OP_IMM or o.imm != tgt:
                continue
            print(f'\n  @ 0x{i.address:06X}')
            for k in range(idx - 1, max(0, idx - 8), -1):
                ii = insns[k]
                if ii.mnemonic in ('lea', 'mov') and ii.operands:
                    d = ii.operands[0]
                    if d.type == OP_REG and i.reg_name(d.reg) in ('rcx', 'rdx', 'r8', 'r9') \
                            and ii.operands[1].type == OP_MEM:
                        print(f'    {i.reg_name(d.reg)} <- 0x{ii.address:06X}  {ii.op_str}')
        return

    cnt = Counter()
    for i in insns:
        for o in i.operands:
            if o.type == OP_MEM:
                base = i.reg_name(o.mem.base)
                if base and base not in ('rip', 'rsp', 'rbp') and o.mem.index == 0:
                    cnt[(base, o.mem.disp)] += 1
    regs = [a.reg] if a.reg else sorted({b for b, _ in cnt})
    for base in regs:
        offs = sorted((d, n) for b, d in cnt if b == base for n in [cnt[(b, d)]])
        if not offs:
            continue
        print(f'\n[{base}] 共 {len(offs)} 个偏移:')
        print('  ' + '  '.join(f'0x{d:X}({n})' for d, n in offs))
    p.close()


if __name__ == '__main__':
    main()
