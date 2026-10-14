"""在 .text 段中搜索 CALL rel32 指向指定 RVA 的位置"""
import sys
import os
import struct

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import th06
from offsets import FN_COLLISION, TEXT_HI, TEXT_LO
from winmem import module_base


def find_callers(p, mb, target_rva):
    hits = []
    chunk = 0x100000
    off = TEXT_LO
    while off < TEXT_HI:
        n = min(chunk, TEXT_HI - off)
        data = p.read(mb + off, n)
        if data:
            i = 0
            while True:
                i = data.find(b'\xE8', i)
                if i < 0 or i + 5 > len(data):
                    break
                rel = struct.unpack('<i', data[i + 1:i + 5])[0]
                call_rva = off + i
                if call_rva + 5 + rel == target_rva:
                    hits.append(call_rva)
                i += 1
        off += n
    return hits


def main():
    p, pid = th06.get_proc()
    mb = module_base(pid, 'th06nc.exe')[0]
    print(f'PID {pid} 模块基址 0x{mb:X}')
    for tgt in [int(x, 16) for x in sys.argv[1:]] or [FN_COLLISION]:
        hits = find_callers(p, mb, tgt)
        print(f'\n调用 RVA 0x{tgt:X} 的位置 ({len(hits)} 处):')
        for h in hits:
            print(f'  0x{h:06X}')
    p.close()


if __name__ == '__main__':
    main()
