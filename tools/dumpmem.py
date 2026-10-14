"""dump 指定地址附近内存，float/int/hex 三视图"""
import sys
import os
import struct

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import th06


def dump(p, base, size=0x400, stride_hint=None):
    d = p.read(base, size)
    if not d:
        print(f'  0x{base:X} 读取失败')
        return
    print(f'=== dump 0x{base:X} .. 0x{base+len(d):X} ===')
    for off in range(0, len(d), 16):
        c = d[off:off + 16]
        if len(c) < 16:
            break
        i0, i1, i2, i3 = struct.unpack('<4i', c)
        f0, f1, f2, f3 = struct.unpack('<4f', c)
        print(f'+{off:05X} |{f0:>13.4f}{f1:>13.4f}{f2:>13.4f}{f3:>13.4f} '
              f'| {i0:>11} {i1:>11} {i2:>11} {i3:>11}')


def main():
    p, pid = th06.get_proc()
    addrs = [int(a, 16) for a in sys.argv[1:]] or [0x1C0B4D78000]
    for a in addrs:
        dump(p, a & ~0xF, 0x400)
        print()
    p.close()


if __name__ == '__main__':
    main()
