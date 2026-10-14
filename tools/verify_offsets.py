"""验证 relocate.py 给出的候选地址 —— 读内存看结构对不对

为什么必须单独一步：`relocate.py` 只是**静态特征匹配**，候选会有误命中
（实测子弹池被引到 `0x5542B0`，那是个被引用 54 次的热门全局；靠「位移约束」才排掉）。
真正的池有静态看不出来的结构特征：

  · 敌人池：占用标志 `+0xBC` 呈 0/1 分布，位置 `+0xB0/+0xB4` 落在场地内
  · 子弹池：槽内位置在场地内，`+0x5F4`（grazeSize）出现已知档位
  · 激光池：`+0x274`（state）∈ {0,1}，`+0x290`（phase）∈ {0,1,2,3}
  · 道具池：`+0x0C`（state）∈ {0,1,2}，`+0x34`（type）∈ 0..6
  · 自机坐标：落在场地内，且**移动时会变**

用法（游戏需在关卡内；运行态最好，暂停态也能看结构）:
  py tools\\verify_offsets.py           只验证
  py tools\\verify_offsets.py --motion  额外做「移动自机看坐标是否跟着变」的检查
"""
import argparse
import os
import struct
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import th06                                     # noqa: E402
from offsets import (BULLET_COUNT, BULLET_STRIDE, ENEMY_COUNT, ENEMY_STRIDE,
                     FIELD_X0, FIELD_X1, FIELD_Y0, FIELD_Y1, ITEM_COUNT,
                     ITEM_STRIDE, LASER_COUNT, LASER_STRIDE)  # noqa: E402
from winmem import module_base                  # noqa: E402

# 当前候选（来自 py tools\relocate.py 的静态定位，全部**待验证**）
CANDIDATES = [
    dict(name='g_EnemyManager', rva=0xAEE0B8, kind='enemy',
         why='特征（5 锚点 + 槽内 +0xBC 命中）+ 外推差 4'),
    dict(name='g_BulletManager', rva=0x436EF0, kind='bullet',
         why='派生 lasers[0] − 0xF5018；外推差与 lasers[0] 同为 0x15D4（同为前段）'),
    dict(name='lasers[0]', rva=0x52BF08, kind='laser',
         why='三重特征 cmp[+0x274] / add 0x298 / cmp 0x40'),
    dict(name='items[0]', rva=0xBFB2F8, kind='item',
         why='10 锚点支持 + 外推差 4（全表最干净之一）'),
    dict(name='PLAYER_X', rva=0x549D30, kind='player',
         why='3 锚点；锚点所在函数 0x6A761..0x6AE7A 含旧 FN_COLLISION'),
    dict(name='CALC_COUNT', rva=0xC6DFD6, kind='byte_inc',
         why='inc byte [rip+X] 锚点，外推差 0x1B2'),
    dict(name='ITEM_NEXT_IDX', rva=0xC53458, kind='idx',
         why='位移标定 +0x4C220，信噪比 10:1（39 处引用 vs 次优 4）'),
]


def f32(data, off):
    return struct.unpack_from('<f', data, off)[0]


def read_pool(p, mb, rva, stride, count):
    return p.read(mb + rva, stride * count)


def check_enemy(p, mb, rva):
    data = read_pool(p, mb, rva + 8, ENEMY_STRIDE, ENEMY_COUNT)
    if not data or len(data) < ENEMY_STRIDE * ENEMY_COUNT:
        return False, '读取失败'
    raw = np.frombuffer(data, dtype=np.uint8).reshape(ENEMY_COUNT, ENEMY_STRIDE)
    occ = (raw[:, 0xBC] & 0x80) != 0
    n = int(occ.sum())
    if n == 0:
        return False, f'占用槽 0/{ENEMY_COUNT} —— 像是空地址（或不在关卡里）'
    xs = raw[occ, 0xB0:0xB4].copy().view('<f4').ravel()
    ys = raw[occ, 0xB4:0xB8].copy().view('<f4').ravel()
    ok = bool(np.all((xs > FIELD_X0 - 64) & (xs < FIELD_X1 + 64)
                     & (ys > FIELD_Y0 - 64) & (ys < FIELD_Y1 + 64)))
    return ok, (f'占用 {n} 槽，x {xs.min():.0f}..{xs.max():.0f} '
                f'y {ys.min():.0f}..{ys.max():.0f}')


def check_bullet(p, mb, rva):
    data = read_pool(p, mb, rva + 8, BULLET_STRIDE, BULLET_COUNT)
    if not data or len(data) < BULLET_STRIDE * BULLET_COUNT:
        return False, '读取失败'
    raw = np.frombuffer(data, dtype=np.uint8).reshape(BULLET_COUNT, BULLET_STRIDE)
    xs = raw[:, 0x30:0x34].copy().view('<f4').ravel()
    ys = raw[:, 0x34:0x38].copy().view('<f4').ravel()
    live = (xs > FIELD_X0 - 32) & (xs < FIELD_X1 + 32) \
        & (ys > FIELD_Y0 - 32) & (ys < FIELD_Y1 + 32)
    n = int(live.sum())
    if n == 0:
        return False, f'场地内子弹 0/{BULLET_COUNT} —— 像是空地址'
    grz = raw[live, 0x5F4:0x5F8].copy().view('<f4').ravel()
    return True, (f'场地内 {n}/{BULLET_COUNT} 颗，grazeSize.x 实测档位 '
                  f'{sorted(set(np.round(grz, 1)))[:6]}')


def check_laser(p, mb, rva):
    data = read_pool(p, mb, rva, LASER_STRIDE, LASER_COUNT)
    if not data or len(data) < LASER_STRIDE * LASER_COUNT:
        return False, '读取失败'
    raw = np.frombuffer(data, dtype=np.uint8).reshape(LASER_COUNT, LASER_STRIDE)
    state = raw[:, 0x274]
    phase = raw[:, 0x290]
    active = state == 1
    n = int(active.sum())
    if n == 0:
        return False, (f'槽状态全非 1（state 取值 {sorted(set(state.tolist()))[:6]}）'
                       f' —— 可能此刻没有激光，或地址不对')
    ph = sorted(set(phase[active].tolist()))
    ok = all(v <= 3 for v in ph)
    return ok, f'活跃 {n}/{LASER_COUNT} 条，phase 取值 {ph}'


def check_item(p, mb, rva):
    data = read_pool(p, mb, rva, ITEM_STRIDE, ITEM_COUNT)
    if not data or len(data) < ITEM_STRIDE * ITEM_COUNT:
        return False, '读取失败'
    raw = np.frombuffer(data, dtype=np.uint8).reshape(ITEM_COUNT, ITEM_STRIDE)
    inuse = raw[:, 0x00] != 0
    n = int(inuse.sum())
    st = sorted(set(raw[inuse, 0x0C].tolist())) if n else []
    tp = sorted(set(raw[inuse, 0x34].tolist())) if n else []
    ok = all(v <= 2 for v in st)
    note = f'在用 {n} 个' if n else '当前无道具（结构无法判，换个有掉落的时机再看）'
    return (ok or n == 0), f'{note}，state {st}，type {tp}'


def check_player(p, mb, rva):
    d = p.read(mb + rva, 8)
    if not d or len(d) < 8:
        return False, '读取失败'
    x, y = struct.unpack('<ff', d)
    ok = FIELD_X0 - 32 <= x <= FIELD_X1 + 32 and FIELD_Y0 - 32 <= y <= FIELD_Y1 + 32
    return ok, f'坐标 ({x:.1f}, {y:.1f})'


def check_byte_inc(p, mb, rva):
    """帧计数：u8，且**两次读取之间必须递增**（唯一可靠的动态特征）"""
    d1 = p.read(mb + rva, 1)
    time.sleep(0.06)
    d2 = p.read(mb + rva, 1)
    if not d1 or not d2:
        return False, '读取失败'
    a, b = d1[0], d2[0]
    delta = (b - a) & 0xFF
    ok = 1 <= delta <= 20
    return ok, (f'{a} → {b}（+{delta}）' +
                ('  ✓ 六十分之一秒内递增，是帧计数' if ok
                 else '  ✗ 没递增 —— 游戏暂停，或这不是帧计数'))


def check_idx(p, mb, rva):
    """池的 nextIndex：i32，应落在 [0, 槽数] 内"""
    d = p.read(mb + rva, 4)
    if not d or len(d) < 4:
        return False, '读取失败'
    v = struct.unpack('<i', d)[0]
    ok = 0 <= v <= 2048
    return ok, f'nextIndex = {v}' + ('' if ok else '  ✗ 越界（不像索引）')


CHECKERS = dict(enemy=check_enemy, bullet=check_bullet, laser=check_laser,
                item=check_item, player=check_player,
                byte_inc=check_byte_inc, idx=check_idx)


def scan_delta(p, mb, center, span=0x800, wait=0.06, max_delta=20):
    """找「过一会儿值增加了」的字节 —— 帧计数 CALC_COUNT 的唯一特征

    为什么靠它：标量变量的静态特征已被证明无效（引用计数法会把 8 个目标一起钓到
    同一个热门全局上）。但帧计数有一个谁也没有的动态特征 —— **每帧 +1**。
    读两次内存，间隔约 3~4 帧（60fps），值增加 1..max_delta 的字节就是候选。
    定位它之后，同区域的 `CUR_STATE` / `WANT_STATE` 也就近可找了。
    """
    lo = max(center - span, 0x1000)
    n = span * 2
    d1 = p.read(mb + lo, n)
    time.sleep(wait)
    d2 = p.read(mb + lo, n)
    if not d1 or not d2 or len(d1) < n or len(d2) < n:
        return []
    hits = []
    for i in range(n):
        d = (d2[i] - d1[i]) & 0xFF
        if 1 <= d <= max_delta:
            hits.append((lo + i, d1[i], d2[i], d))
    return hits


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--motion', action='store_true',
                    help='额外检查：连读两次自机坐标，看是否随游戏推进变化')
    ap.add_argument('--scan-delta', type=lambda s: int(s, 0), default=None,
                    metavar='RVA',
                    help='在该 RVA 附近扫描「每帧递增」的字节（定位帧计数用）')
    args = ap.parse_args()

    p, pid = th06.get_proc()
    mb = module_base(pid, 'th06nc.exe')[0]
    print(f'PID {pid}  基址 0x{mb:X}\n')

    if args.scan_delta is not None:
        print(f'=== 扫描「每帧递增」的字节 — 围绕 0x{args.scan_delta:08X} '
              f'（帧计数的唯一特征）===')
        hits = scan_delta(p, mb, args.scan_delta)
        if not hits:
            print('  没找到。要么游戏暂停（帧计数不走），要么预测值偏得太远。')
            print('  提示：确认画面在 IN_GAME，再试试 --scan-delta 换个中心值。')
        for rva, a, b, d in hits[:20]:
            print(f'  0x{rva:08X}  {a:>3} → {b:>3}   (+{d})')
        print(f'  共 {len(hits)} 个候选（60fps 下约 3~4 帧对应 +3~+4）')
        p.close()
        return

    n_ok = 0
    for c in CANDIDATES:
        try:
            ok, detail = CHECKERS[c['kind']](p, mb, c['rva'])
        except Exception as e:                       # noqa: BLE001
            ok, detail = False, f'检查抛错：{e}'
        mark = '✓' if ok else '✗'
        n_ok += 1 if ok else 0
        print(f'{mark} {c["name"]:<18} RVA 0x{c["rva"]:08X}   {detail}')
        print(f'    依据：{c["why"]}')

    if args.motion:
        print('\n=== 移动检查（自机坐标应随游戏推进变化）===')
        d1 = p.read(mb + 0x549D30, 8)
        time.sleep(0.2)
        d2 = p.read(mb + 0x549D30, 8)
        if d1 and d2:
            a = struct.unpack('<ff', d1)
            b = struct.unpack('<ff', d2)
            moved = abs(a[0] - b[0]) > 0.01 or abs(a[1] - b[1]) > 0.01
            print(f'  {"✓" if moved else "✗"} 0.2s 内 ({a[0]:.1f},{a[1]:.1f}) → '
                  f'({b[0]:.1f},{b[1]:.1f})  '
                  f'{"有变化" if moved else "没变（游戏暂停？或地址不是自机坐标）"}')
    p.close()
    print(f'\n通过 {n_ok}/{len(CANDIDATES)}')
    if n_ok < len(CANDIDATES):
        print('未通过的项：先确认游戏在关卡内且不是暂停态；仍不过就说明该候选是误命中，'
              '回 relocate.py 调特征。')


if __name__ == '__main__':
    main()
