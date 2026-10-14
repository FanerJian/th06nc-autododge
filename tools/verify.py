"""
候选地址验证 + 结构 dump
"""
import sys
import os
import time
import struct
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import th06


CANDS = [0x1C0C91360C0, 0x1C0C91360F0, 0x1C0C3BB9808,
         0x1C0A6019044, 0x1C0C4476754]


def read_pairs(p, addrs):
    out = []
    for a in addrs:
        d = p.read(a, 8)
        if d and len(d) == 8:
            out.append(struct.unpack('<2f', d))
        else:
            out.append((float('nan'), float('nan')))
    return out


def dump(p, base, size=0x200):
    d = p.read(base, size)
    if not d:
        print('  读取失败')
        return
    print(f'  dump 0x{base:X} .. 0x{base+len(d):X}')
    for off in range(0, len(d), 16):
        chunk = d[off:off + 16]
        if len(chunk) < 16:
            break
        i0, i1, i2, i3 = struct.unpack('<4i', chunk)
        f0, f1, f2, f3 = struct.unpack('<4f', chunk)
        print(f'  +{off:04X}  {i0:>11} {i1:>11} {i2:>11} {i3:>11}   |'
              f'{f0:>12.4f} {f1:>12.4f} {f2:>12.4f} {f3:>12.4f}')


def move(p, key, ms):
    th06.tap('z', 80); time.sleep(0.25)          # 解除暂停
    th06.key_down(key); time.sleep(ms / 1000.0); th06.key_up(key)
    time.sleep(0.03)
    th06.tap('esc', 80); time.sleep(0.35)        # 暂停
    return read_pairs(p, CANDS)


def main():
    p, pid = th06.get_proc()
    print('PID', pid)
    th06._focus_game(pid)
    time.sleep(0.2)

    print('\n当前值（暂停中）:')
    cur = read_pairs(p, CANDS)
    for a, (x, y) in zip(CANDS, cur):
        print(f'  0x{a:<16X} x={x:>10.4f}  y={y:>10.4f}')

    print('\n>>> 按 右 0.6s')
    r = move(p, 'right', 600)
    for a, (x, y) in zip(CANDS, r):
        print(f'  0x{a:<16X} x={x:>10.4f}  y={y:>10.4f}')

    print('\n>>> 按 下 0.6s')
    d = move(p, 'down', 600)
    for a, (x, y) in zip(CANDS, d):
        print(f'  0x{a:<16X} x={x:>10.4f}  y={y:>10.4f}')

    print('\n>>> 按 左 0.6s')
    l = move(p, 'left', 600)
    for a, (x, y) in zip(CANDS, l):
        print(f'  0x{a:<16X} x={x:>10.4f}  y={y:>10.4f}')

    print('\n=== 变化量 ===')
    for i, a in enumerate(CANDS):
        print(f'0x{a:<16X} '
              f'dx(右)={r[i][0]-cur[i][0]:+9.3f} '
              f'dy(下)={d[i][1]-r[i][1]:+9.3f} '
              f'dx(左)={l[i][0]-d[i][0]:+9.3f}')

    print('\n=== 附近内存结构 (0x1C0C9136000) ===')
    dump(p, 0x1C0C9136000, 0x200)
    p.close()


if __name__ == '__main__':
    main()
