"""
1) 验证自机坐标 RVA = Player(0x4FF3A0) + 0x7730/0x7734
2) 扫描 .data 段定位子弹数组（640 槽, stride 1568B = 392 floats）
   依据 ModeCode.cs 的清空循环: bullets 从 manager+0x4C 起, stride 0x620
"""
import sys
import os
import time
import struct
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import th06
from winmem import module_base

PLAYER_RVA = 0x4FF3A0
PX = 0x4FF3A0 + 0x7730          # 0x4F6AD0
PY = 0x4FF3A0 + 0x7734          # 0x4F6AD4
PX2 = 0x4FF3A0 + 0x7740
PY2 = 0x4FF3A0 + 0x7744

BULLET_STRIDE = 1568            # 0x620
BULLET_STRIDE_F = BULLET_STRIDE // 4   # 392 floats
BULLET_SLOTS = 640              # 0x280

DATA_RVA_LO, DATA_RVA_HI = 0x323000, 0xC29660   # 主模块 .data 段


def read_xy(p, base):
    d = p.read(base + PX, 16)
    x, y, x2, y2 = struct.unpack('<4f', d)
    return x, y, x2, y2


def cycle(p, key, hold=0.35):
    th06.tap('z', 80); time.sleep(0.12)
    th06.key_down(key); time.sleep(hold); th06.key_up(key); time.sleep(0.03)
    th06.tap('esc', 80); time.sleep(0.30)


def main():
    p, pid = th06.get_proc()
    mb = module_base(pid, 'th06nc.exe')[0]
    print(f'模块基址 0x{mb:X}')
    print(f'自机坐标 RVA: x=0x{PX:X} y=0x{PY:X}  (判定/副坐标 0x{PX2:X},0x{PY2:X})')

    th06._focus_game(pid); time.sleep(0.2)
    x, y, x2, y2 = read_xy(p, mb)
    print(f'\n当前: x={x:.3f} y={y:.3f}   (x2={x2:.3f} y2={y2:.3f})')

    print('\n>>> 按 右 0.5s')
    cycle(p, 'right', 0.5)
    xr, yr, xr2, yr2 = read_xy(p, mb)
    print(f'  x={xr:.3f} y={yr:.3f}   dx={xr-x:+.3f}  dy={yr-y:+.3f}')

    print('>>> 按 上 0.5s')
    cycle(p, 'up', 0.5)
    xu, yu, xu2, yu2 = read_xy(p, mb)
    print(f'  x={xu:.3f} y={yu:.3f}   dx={xu-xr:+.3f}  dy={yu-yr:+.3f}')

    print('>>> 按 左 0.5s')
    cycle(p, 'left', 0.5)
    xl, yl, xl2, yl2 = read_xy(p, mb)
    print(f'  x={xl:.3f} y={yl:.3f}   dx={xl-xu:+.3f}  dy={yl-yu:+.3f}')

    lo = min(x, xr, xu, xl); hi = max(x, xr, xu, xl)
    print(f'\nx 变化范围 {lo:.1f}..{hi:.1f}  -> {"符合自机坐标" if abs(hi-lo) > 20 else "变化太小，需复查"}')

    # ---------- 扫描 .data 段找子弹数组 ----------
    print('\n=== 扫描 .data 段定位子弹数组 ===')
    t0 = time.time()
    data = p.read(mb + DATA_RVA_LO, DATA_RVA_HI - DATA_RVA_LO)
    if data is None:
        # 逐区域读
        chunks = []
        off = DATA_RVA_LO
        while off < DATA_RVA_HI:
            n = min(0x100000, DATA_RVA_HI - off)
            c = p.read(mb + off, n)
            chunks.append(c if c else b'\x00' * n)
            off += n
        data = b''.join(chunks)
    arr = np.frombuffer(data[:len(data) // 4 * 4], dtype='<f4').copy()
    print(f'读到 {len(arr)} 个 float ({time.time()-t0:.2f}s)')

    # 对每个"子弹内偏移"(0..392 float)，检查以 stride 392 采样时落在游玩区的比例
    print(f'{"内偏移B":<10}{"采样数":>8}{"游玩区x数":>10}{"游玩区y数":>10}')
    hits = []
    for off_f in range(0, BULLET_STRIDE_F):
        sub = arr[off_f::BULLET_STRIDE_F]
        if len(sub) < 1000:
            continue
        v = sub[(sub > 0.5) & (sub < 380)]
        if len(v) > 30:
            hits.append((len(v), off_f))
    hits.sort(reverse=True)
    for cnt, off_f in hits[:25]:
        print(f'  0x{off_f*4:<8X}{len(arr[off_f::BULLET_STRIDE_F]):>8}{cnt:>10}')
    if not hits:
        print('  .data 段没找到明显的子弹 stride 模式')
    print(f'耗时 {time.time()-t0:.2f}s')
    p.close()


if __name__ == '__main__':
    main()
