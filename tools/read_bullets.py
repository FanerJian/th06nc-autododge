"""读取 th06nc 当前活跃子弹

地址依据见 `项目文档/02-内存布局/相关-游戏内存映射-MEMMAP.md` §2；常量取自 `tools/offsets.py`。

两个接口，共用同一次内存读取：
  `read_bullet_frame()` 一帧的全部字段（含 exFlags / 加速度 / 转向参数 / 计时器）
  `read_bullets()`      只要几何的旧接口（6 元组），保持既有调用点不变

用法:
  py tools\\read_bullets.py            # 打印一次
  py tools\\read_bullets.py 30         # 连续采 30 次，打印每次活跃子弹数
"""
import os
import struct
import sys
import time
from collections import namedtuple

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import th06
from offsets import (BM_RVA, BOMBS, BULLETS_OFF, BULLET_BLOCK, BULLET_COUNT,
                     BULLET_R, BULLET_STRIDE, B_OFF_ACCEL, B_OFF_ANGLE, B_OFF_DC_INT,
                     B_OFF_DC_MAX, B_OFF_DC_NUM, B_OFF_DC_ROT, B_OFF_DCSPEED,
                     B_OFF_EX5F0, B_OFF_EX5F1, B_OFF_EXFLAGS, B_OFF_GRAZE, B_OFF_HOLD,
                     B_OFF_SPEED, B_OFF_STATE, B_OFF_TIMER, B_OFF_VX, B_OFF_VY,
                     B_OFF_X, B_OFF_Y, CUR_STATE, EXF_ACCEL, EXF_TURN_AIM,
                     EXF_TURN_ANY, EXF_TURN_CONT, EXF_TURN_REL, GRAZE_R_MAX, LIVES,
                     NEXT_IDX_OFF, PLAYER_BASE, PLAYER_OFF_BOMB_INUSE,
                     PLAYER_OFF_RESPAWN, PLAYER_OFF_STATE, PLAYER_X)
from winmem import MemoryReadError, module_base

# 一帧的子弹池快照。几何（前 6 项）之外带**运动参数** —— 只按当前 vx/vy 匀速外推，
# 加速弹会偏近、转向弹在转向帧之后整段错（`dodge.bullet_paths()` 用这些字段逐帧推进）。
# 用命名元组：字段一多，位置解包会静默错位（同 `read_lasers.LaserFrame`）。
BulletFrame = namedtuple(
    'BulletFrame',
    'slots xs ys vxs vys brs exflags angles speeds dcspeeds timers hold '
    'accel_x accel_y turn_rot turn_int turn_num turn_max turn_rate speed_rate states')


def _f32col(raw, off):
    return raw[:, off:off + 4].copy().view('<f4').ravel()


def _i32col(raw, off):
    return raw[:, off:off + 4].copy().view('<i4').ravel()


def _u16col(raw, off):
    return raw[:, off:off + 2].copy().view('<u2').ravel()


def bullet_radius(raw, mask):
    """逐弹判定半径(px) = min(grazeSize.x, grazeSize.y) × 0.5

    依据 MEMMAP §3（反汇编 0x6A980）：`minss xmm6, [r8]` → `mulss xmm6, 0.5`
    → `addss xmm6, 自机半径`。**每颗子弹不同** —— 实测 4×4 档 → 2.0、6×6 档 → 3.0。

    异常值（槽未初始化读成 0、NaN、超过 GRAZE_R_MAX）回落 BULLET_R。
    """
    w = _f32col(raw, B_OFF_GRAZE)
    h = _f32col(raw, B_OFF_GRAZE + 4)
    br = np.minimum(w, h) * 0.5
    bad = ~np.isfinite(br) | (br <= 0.0) | (br > GRAZE_R_MAX)
    return np.where(bad, BULLET_R, br).astype(np.float32)[mask]


def read_bullet_frame(p, mb):
    """返回一帧的 `BulletFrame`；读取失败返回 None

    活跃判据：x 或 y 非零。整块只读一次 ReadProcessMemory。
    运动字段的语义见 `offsets.B_OFF_*` / `EXF_*`（反汇编 `BulletManager__OnUpdate` 确证）。
    """
    data = p.read(mb + BM_RVA + BULLETS_OFF, BULLET_BLOCK)
    if not data or len(data) < BULLET_BLOCK:
        return None
    raw = np.frombuffer(data, dtype=np.uint8).reshape(BULLET_COUNT, BULLET_STRIDE)
    xs = _f32col(raw, B_OFF_X)
    ys = _f32col(raw, B_OFF_Y)
    mask = (xs != 0.0) | (ys != 0.0)
    return BulletFrame(
        np.nonzero(mask)[0], xs[mask], ys[mask],
        _f32col(raw, B_OFF_VX)[mask], _f32col(raw, B_OFF_VY)[mask],
        bullet_radius(raw, mask),
        _u16col(raw, B_OFF_EXFLAGS)[mask].astype(np.int32),
        _f32col(raw, B_OFF_ANGLE)[mask],
        _f32col(raw, B_OFF_SPEED)[mask],
        _f32col(raw, B_OFF_DCSPEED)[mask],
        _i32col(raw, B_OFF_TIMER)[mask],
        _i32col(raw, B_OFF_HOLD)[mask],
        _f32col(raw, B_OFF_ACCEL)[mask], _f32col(raw, B_OFF_ACCEL + 4)[mask],
        _f32col(raw, B_OFF_DC_ROT)[mask],
        _i32col(raw, B_OFF_DC_INT)[mask],
        _i32col(raw, B_OFF_DC_NUM)[mask],
        _i32col(raw, B_OFF_DC_MAX)[mask],
        _f32col(raw, B_OFF_EX5F1)[mask],
        _f32col(raw, B_OFF_EX5F0)[mask],
        _u16col(raw, B_OFF_STATE)[mask])


def read_bullets(p, mb):
    """返回活跃子弹的 (slot, xs, ys, vxs, vys, brs) —— 只要几何的老接口

    brs = 逐弹判定半径(px)，见 `bullet_radius()`。
    需要运动参数（加速 / 转向外推）时用 `read_bullet_frame()`。
    """
    f = read_bullet_frame(p, mb)
    if f is None:
        return None
    return (f.slots, f.xs, f.ys, f.vxs, f.vys, f.brs)


def empty_frame():
    """零弹的一帧（字段齐全、形状为空）—— 护栏桩内存读取时用，别再手写一遍"""
    z = np.zeros(0, dtype=np.float32)
    i = np.zeros(0, dtype=np.int32)
    return BulletFrame(np.zeros(0, dtype=np.int64), z, z, z, z, z, i, z, z, z, i, i,
                       z, z, z, i, i, i, z, z, np.zeros(0, dtype=np.uint16))


def describe_flags(exf):
    """exFlags → 人话（实机核对弹幕类型用）；未知位按十六进制原样带出"""
    if not exf:
        return ''
    tags = []
    if exf & EXF_ACCEL:
        tags.append('加速')
    if exf & EXF_TURN_CONT:
        tags.append('连续转向')
    if exf & EXF_TURN_ANY:
        tags.append('定时转向' + ('·追自机' if exf & EXF_TURN_AIM else
                                '·绝对' if exf & 0x100 else ''))
    if exf & 0x400 or exf & 0x800:
        tags.append('反弹')
    rest = exf & ~(EXF_ACCEL | EXF_TURN_CONT | EXF_TURN_ANY | 0x400 | 0x800 | 0x001)
    if rest:
        tags.append(f'0x{rest:X}')
    return '+'.join(tags)



def read_next_index(p, mb):
    v = p.read(mb + BM_RVA + NEXT_IDX_OFF, 4)
    return struct.unpack('<i', v)[0] if v and len(v) == 4 else None


def read_player(p, mb):
    """读自机坐标 (x, y)

    失败抛 `MemoryReadError`，不返回 (0, 0) —— 躲避会把 (0,0) 当成真实位置去评分。
    x / y 相邻（MEMMAP §1），一次读完少一次系统调用。
    """
    d = p.read(mb + PLAYER_X, 8)
    if not d or len(d) < 8:
        raise MemoryReadError('读取自机坐标失败')
    return struct.unpack('<ff', d)


def read_scene(p, mb):
    """场景：1 = 标题主菜单，2 = 关卡进行中，7 = Game Over 结算（实测观察）"""
    d = p.read(mb + CUR_STATE, 4)
    if not d or len(d) < 4:
        raise MemoryReadError('读取 Scene 失败')
    return struct.unpack('<i', d)[0]


def read_lives(p, mb):
    d = p.read(mb + LIVES, 1)
    if not d:
        raise MemoryReadError('读取残机失败')
    return d[0]


def read_player_state(p, mb):
    """读自机状态 / 死亡窗口 / 灵击 —— 灵击决策的唯一输入（MEMMAP §11）

    返回 dict：state / respawn / bomb_in_use / bombs
    **死亡炸弹窗口 = state == DEAD 且 respawn > 0**：respawnTimer 在这段时间里逐帧递减，
    到 0 才结算掉命；窗口内按 X 仍可放技能，bomb 的 calc 会把 playerState 改成
    INVULNERABLE，死亡随之取消（依据：`Player__OnUpdate` + 原版 `BombData.cpp`）。
    """
    off0 = PLAYER_OFF_RESPAWN
    raw = p.read(mb + PLAYER_BASE + off0, PLAYER_OFF_STATE - off0 + 1)
    if not raw or len(raw) < PLAYER_OFF_STATE - off0 + 1:
        return None
    bi = p.read(mb + PLAYER_BASE + PLAYER_OFF_BOMB_INUSE, 1)
    bb = p.read(mb + BOMBS, 1)
    return {
        'respawn': struct.unpack('<i', raw[:4])[0],
        'state': raw[PLAYER_OFF_STATE - off0],
        'bomb_in_use': bi[0] if bi else 0,
        'bombs': bb[0] if bb else 0,
    }


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    p, pid = th06.get_proc()
    mb = module_base(pid, 'th06nc.exe')[0]
    print(f'PID {pid}  基址 0x{mb:X}  g_BulletManager 0x{mb + BM_RVA:X}')
    for k in range(n):
        t0 = time.perf_counter()
        r = read_bullet_frame(p, mb)
        dt = (time.perf_counter() - t0) * 1000
        if r is None:
            print('读取失败')
            break
        px, py = read_player(p, mb)
        kinds = {}
        for e in r.exflags:
            kinds[describe_flags(int(e)) or '普通'] = kinds.get(describe_flags(int(e)) or '普通', 0) + 1
        print(f'\n[{k}] 活跃 {len(r.slots):3d} 弹  nextIdx={read_next_index(p, mb)}  '
              f'自机=({px:6.1f},{py:6.1f})  读+解析 {dt:.1f}ms')
        print('    类型分布: ' + '  '.join(f'{k2}×{v}' for k2, v in
                                        sorted(kinds.items(), key=lambda kv: -kv[1])))
        for i in range(min(len(r.slots), 12)):
            print(f'    slot {r.slots[i]:3d}  x={r.xs[i]:8.3f} y={r.ys[i]:8.3f} '
                  f'vx={r.vxs[i]:8.3f} vy={r.vys[i]:8.3f}  r={r.brs[i]:.2f}  '
                  f'st={int(r.states[i])} exF=0x{int(r.exflags[i]):03X} '
                  f'{describe_flags(int(r.exflags[i]))}')
        if n > 1:
            time.sleep(0.1)
    p.close()


if __name__ == '__main__':
    main()
