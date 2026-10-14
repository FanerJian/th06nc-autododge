"""内存画像：统计 th06nc 的内存区域构成，决定扫描策略

用法:
  py tools\\memprofile.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from winmem import (find_pids, module_base, Process, MEM_PRIVATE, MEM_IMAGE,
                    MEM_MAPPED, PAGE_READWRITE, PAGE_READONLY, PAGE_EXECUTE_READ,
                    PAGE_EXECUTE_READWRITE, PAGE_WRITECOPY, PAGE_EXECUTE_WRITECOPY)

PROT_NAME = {
    0x01: 'NOACCESS', 0x02: 'R', 0x04: 'RW', 0x08: 'WC',
    0x10: 'X', 0x20: 'XR', 0x40: 'XRW', 0x80: 'XWC',
}
TYPE_NAME = {0x20000: 'PRIVATE', 0x1000000: 'IMAGE', 0x40000: 'MAPPED', 0: 'FREE'}


def main():
    pids = find_pids('th06nc')
    if not pids:
        print('游戏未运行')
        return 1
    print('PID:', pids)

    with Process(pids[0]) as p:
        regs = p.regions(min_size=0x1000, include_image=True)
        print(f'区域数: {len(regs)}')
        agg = {}
        for base, size, prot, typ in regs:
            key = (TYPE_NAME.get(typ, hex(typ)), PROT_NAME.get(prot, hex(prot)))
            agg[key] = agg.get(key, 0) + size
        print(f'\n{"类型":<10}{"保护":<8}{"合计MB":>10}')
        for (t, pr), s in sorted(agg.items(), key=lambda x: -x[1]):
            print(f'{t:<10}{pr:<8}{s/1024/1024:>10.1f}')

        # 关键：可写的私有内存（真正的堆/数据）
        rw_priv = [r for r in regs if r[2] == PAGE_READWRITE and r[3] == MEM_PRIVATE]
        total = sum(r[1] for r in rw_priv)
        print(f'\n可写 PRIVATE 区域: {len(rw_priv)} 个, {total/1024/1024:.1f} MB, '
              f'约 {total//4/1e6:.1f}M 个 float')

        # 主模块的 .data 段
        mb = module_base(pids[0], 'th06nc.exe')
        print('主模块:', hex(mb[0]), 'size', hex(mb[1]))
        mod_regions = [r for r in regs if mb[0] <= r[0] < mb[0] + mb[1]]
        for base, size, prot, typ in sorted(mod_regions):
            print(f'  +0x{base-mb[0]:08X} size=0x{size:<8X} '
                  f'{PROT_NAME.get(prot,hex(prot))} {TYPE_NAME.get(typ,hex(typ))}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
