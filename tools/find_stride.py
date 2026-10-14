"""
搜索遍历子弹池的循环: ADD r64, 0x620  (stride 递增)
编码: 48/49 81 C? 20 06 00 00
跑这条指令的地方必在"for (i=0;i<640;i++) bullet[i]..." 循环里,
附近就能看到数组基址。
"""
import sys
import os
import struct

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import th06
from offsets import TEXT_HI, TEXT_LO
from winmem import module_base

# 各种寄存器的 ADD r64, imm32 前缀
PATTERNS = [
    (b'\x48\x81\xc3\x20\x06\x00\x00', 'ADD RBX, 0x620'),
    (b'\x48\x81\xc7\x20\x06\x00\x00', 'ADD RDI, 0x620'),
    (b'\x48\x81\xc6\x20\x06\x00\x00', 'ADD RSI, 0x620'),
    (b'\x48\x81\xc5\x20\x06\x00\x00', 'ADD RBP, 0x620'),
    (b'\x48\x81\xc0\x20\x06\x00\x00', 'ADD RAX, 0x620'),
    (b'\x48\x81\xc1\x20\x06\x00\x00', 'ADD RCX, 0x620'),
    (b'\x48\x81\xc2\x20\x06\x00\x00', 'ADD RDX, 0x620'),
    (b'\x49\x81\xc4\x20\x06\x00\x00', 'ADD R12, 0x620'),
    (b'\x49\x81\xc5\x20\x06\x00\x00', 'ADD R13, 0x620'),
    (b'\x49\x81\xc6\x20\x06\x00\x00', 'ADD R14, 0x620'),
    (b'\x49\x81\xc7\x20\x06\x00\x00', 'ADD R15, 0x620'),
    # 也可能用 LEA r, [r + 0x620]
    (b'\x48\x8d\x9b\x20\x06\x00\x00', 'LEA RBX, [RBX+0x620]'),
    (b'\x48\x8d\xbf\x20\x06\x00\x00', 'LEA RDI, [RDI+0x620]'),
    (b'\x48\x8d\xb6\x20\x06\x00\x00', 'LEA RSI, [RSI+0x620]'),
]


def main():
    p, pid = th06.get_proc()
    mb = module_base(pid, 'th06nc.exe')[0]
    print(f'PID {pid} 基址 0x{mb:X}  (stride 0x620 = 1568)')

    data = p.read(mb + TEXT_LO, TEXT_HI - TEXT_LO)
    if not data:
        print('.text 读取失败')
        return
    print(f'.text 读取 {len(data)} 字节\n')

    found = 0
    for pat, name in PATTERNS:
        i = 0
        while True:
            i = data.find(pat, i)
            if i < 0:
                break
            print(f'  RVA 0x{TEXT_LO + i:06X}   {name}')
            found += 1
            i += 1
    # 也搜 imm32 出现在其他位置的 ADD r/m64
    print(f'\n共 {found} 处')
    p.close()


if __name__ == '__main__':
    main()
