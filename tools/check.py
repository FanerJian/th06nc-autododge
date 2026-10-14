"""快速检查游戏状态"""
import sys
import os
import struct

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import th06
from offsets import (BOMBS, CUR_STATE, INPUT, LIVES, NATIVE_TIME, PLAYER_BASE,
                     PLAYER_OFF_X, PLAYER_OFF_X2, PLAYER_OFF_Y, PLAYER_OFF_Y2, POWER)
from winmem import module_base

P = PLAYER_BASE
FIELDS = [
    ('Lives', LIVES, 1), ('Bombs', BOMBS, 1), ('Power', POWER, 2),
    ('Scene', CUR_STATE, 4), ('NativeTime', NATIVE_TIME, 1),
    ('Input', INPUT, 2),
    ('Player.x', P + PLAYER_OFF_X, 4), ('Player.y', P + PLAYER_OFF_Y, 4),
    ('Player.hitx', P + PLAYER_OFF_X2, 4), ('Player.hity', P + PLAYER_OFF_Y2, 4),
]


def main():
    p, pid = th06.get_proc()
    mb = module_base(pid, 'th06nc.exe')[0]
    print(f'PID {pid}  moduleBase 0x{mb:X}')
    for name, rva, w in FIELDS:
        d = p.read(mb + rva, max(w, 4))
        if not d:
            print(f'  {name:<12} 读失败')
            continue
        if w == 1:
            v = d[0]
        elif w == 2:
            v = struct.unpack('<H', d[:2])[0]
        else:
            v = struct.unpack('<i', d[:4])[0]
            f = struct.unpack('<f', d[:4])[0]
            print(f'  {name:<12} int={v:<12} float={f:.4f}   (RVA 0x{rva:X})')
            continue
        print(f'  {name:<12} = {v}   (RVA 0x{rva:X})')
    p.close()


if __name__ == '__main__':
    main()
