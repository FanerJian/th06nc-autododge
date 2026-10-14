"""抓一次真实的活跃激光 —— 全程只读，不发按键，不抢焦点

为什么需要：激光池偏移（MEMMAP §7）是反汇编推出来的，还没在实机激光场景读到过非零值。
抢焦点会让游戏自动暂停（PITFALLS），所以本工具只读内存，不碰输入。

判据不看 state 单一项：`state != 0` 与「pos 落在场地合理范围」分别列出 ——
若两者不一致，说明 §7 的某个槽内偏移还不对，原始数据已落盘可供再反汇编。

用法（在游戏里打到有激光的关卡，另开一个终端跑；不影响游戏）:
  py tools\\sample_lasers.py --seconds 1800    # 等到抓中为止
  py tools\\sample_lasers.py --now             # 立刻 dump 一次当前池（含空闲基线）
抓中后连续采 5 帧，落盘到 _tmp/laser_samples/。
"""
import argparse
import os
import struct
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import th06
from read_bullets import read_player
from screen import read_state, screen_of
from winmem import module_base

# 激光池常量集中在 offsets.py；本文件沿用短名，OFF_* 均指激光槽内偏移
from offsets import (BM_RVA, LASERS_OFF, LASER_COUNT as COUNT, LASER_STRIDE as STRIDE,
                     L_OFF_ANGLE as OFF_ANGLE, L_OFF_ENDOFF as OFF_ENDOFF,
                     L_OFF_FLAGS as OFF_FLAGS, L_OFF_SPEED as OFF_SPEED,
                     L_OFF_STARTOFF as OFF_STARTOFF, L_OFF_STARTLEN as OFF_STARTLEN,
                     L_OFF_STATE as OFF_STATE, L_OFF_WIDTH as OFF_WIDTH,
                     L_OFF_X as OFF_X, L_OFF_Y as OFF_Y, L_OFF_Z as OFF_Z)
BLOCK = STRIDE * COUNT

FIELD = (-40.0, 440.0, -40.0, 480.0)     # pos 合理范围（场地 + 一圈余量）
FLOAT_WINDOW = (0x258, 0x298)            # 打印这一段全部 float，便于核对偏移
OUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       '_tmp', 'laser_samples')


def f32col(raw, off):
    return raw[:, off:off + 4].copy().view('<f4').ravel()


def f32(raw, off):
    return struct.unpack('<f', raw[off:off + 4].tobytes())[0]


def scan(raw):
    """返回 [(槽号, state, x, y, 位置是否合理, flags)]，state 与位置分别判，互不掩盖"""
    state = raw[:, OFF_STATE]
    x, y = f32col(raw, OFF_X), f32col(raw, OFF_Y)
    flags = raw[:, OFF_FLAGS]
    inside = ((x >= FIELD[0]) & (x <= FIELD[1]) & (y >= FIELD[2]) & (y <= FIELD[3]))
    hits = []
    for i in range(COUNT):
        if state[i] != 0 or inside[i]:
            hits.append((i, int(state[i]), float(x[i]), float(y[i]), bool(inside[i]),
                         int(flags[i])))
    return hits


def slot_detail(raw, i):
    """一个槽的全部已推字段 + 附近原始 float（偏移若不对，这里看得出来）"""
    slot = raw[i]
    w = f32(slot, OFF_WIDTH)
    a = f32(slot, OFF_ANGLE)
    x, y, z = f32(slot, OFF_X), f32(slot, OFF_Y), f32(slot, OFF_Z)
    ln = f32(slot, OFF_STARTLEN)
    so = f32(slot, OFF_STARTOFF)
    eo = f32(slot, OFF_ENDOFF)
    sp = f32(slot, OFF_SPEED)
    lines = [f'slot {i:2d}  state={int(slot[OFF_STATE]):3d}  flags={int(slot[OFF_FLAGS]):3d}  '
             f'width={w:8.3f}  angle={a:8.4f} ({np.degrees(a) % 360:6.1f}°)',
             f'          pos=({x:9.3f},{y:9.3f},{z:9.3f})  '
             f'线段 {so:9.3f}→{eo:9.3f}（长 {eo - so:8.3f}）  '
             f'len上限={ln:9.3f}  speed={sp:8.3f} px/帧']
    lo, hi = FLOAT_WINDOW
    vals = ' '.join(f'+{o:03X}={f32(slot, o):.4g}' for o in range(lo, hi, 4))
    lines.append('          ' + vals)
    return lines


def sample_once(p, mb, addr):
    raw = p.read(addr, BLOCK)
    if not raw or len(raw) < BLOCK:
        return None, None
    arr = np.frombuffer(raw, dtype=np.uint8).reshape(COUNT, STRIDE)
    return raw, scan(arr)


def save(raw, lines):
    os.makedirs(OUT_DIR, exist_ok=True)
    ts = time.strftime('%Y%m%d-%H%M%S')
    bin_path = os.path.join(OUT_DIR, f'{ts}_pool.bin')
    txt_path = os.path.join(OUT_DIR, f'{ts}_summary.txt')
    with open(bin_path, 'wb') as f:
        f.write(raw)
    with open(txt_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')
    return bin_path, txt_path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--seconds', type=float, default=900, help='最多等多少秒（默认 900）')
    ap.add_argument('--frames', type=int, default=5, help='抓中后连续采几帧')
    ap.add_argument('--now', action='store_true', help='不等待，立刻 dump 一次当前池')
    args = ap.parse_args()

    p, pid = th06.get_proc()
    mb = module_base(pid, 'th06nc.exe')[0]
    addr = mb + BM_RVA + LASERS_OFF
    print(f'PID {pid}  基址 0x{mb:X}  lasers 0x{addr:X}', flush=True)
    print(f'只读模式：不发任何按键、不抢焦点（抢焦点会让游戏暂停）', flush=True)

    deadline = time.time() + args.seconds
    while True:
        st = read_state(p, mb)
        code, desc, _ = screen_of(st)
        px, py = read_player(p, mb)
        raw, hits = sample_once(p, mb, addr)
        if raw is None:
            print('读取失败'); p.close(); return 1

        if args.now or hits:
            header = [f'time={time.strftime("%Y-%m-%d %H:%M:%S")}  PID={pid}  基址=0x{mb:X}',
                      f'画面={code}（{desc}）  curState={st["cur_state"]} '
                      f'帧计数={st["calc_count"]}  Lives={st["lives"]}',
                      f'自机=({px:.2f},{py:.2f})  候选槽={len(hits)}']
            print('\n'.join(header), flush=True)
            body = list(header)
            for k in range(args.frames if hits else 1):
                raw, hits = sample_once(p, mb, addr)
                if raw is None:
                    break
                block = [f'--- 第 {k + 1} 帧：候選 {len(hits)} 个 ---']
                for i, state, x, y, inside, flags in hits:
                    block.append(f'  slot {i:2d} state={state:3d} pos=({x:9.3f},{y:9.3f}) '
                                 f'位置合理={"是" if inside else "否"} flags={flags}')
                for i, *_ in hits[:8]:
                    block.extend(slot_detail(np.frombuffer(raw, dtype=np.uint8)
                                             .reshape(COUNT, STRIDE), i))
                print('\n'.join(block), flush=True)
                body.extend(block)
                if hits and k < args.frames - 1:
                    time.sleep(0.1)
            bin_path, txt_path = save(raw, body)
            print(f'\n已落盘：\n  {bin_path}\n  {txt_path}')
            p.close()
            return 0 if hits else 2

        if time.time() > deadline:
            print(f'✗ 等了 {args.seconds:.0f}s 没抓到活跃激光（画面 {code}）。')
            print('  激光主要在 Stage 4/5/6；确认已经在关卡里，再用 --now 看一次基线。')
            p.close()
            return 2
        time.sleep(0.4)


if __name__ == '__main__':
    sys.exit(main())
