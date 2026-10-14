"""游戏更新后自动适配地址 —— 一条命令把新构建的地址表重新定位出来

背景：Steam 更新 th06nc.exe 后 `offsets.py` 里所有全局地址失效，避弹立刻报废
（读错内存 → 判成不在关卡 → 拒发按键）。但实测多次更新对比证明：**结构内偏移、
池 stride、槽数从来没变过**，变的只是全局变量位置，所以地址能靠特征重新找到。

本脚本做的事：
  1. 静态定位「不依赖旧地址假设」的锚点
       · 帧计数   ← 全二进制唯一的 `inc byte [rip+X]`（每帧 +1）
       · curState ← switch 跳转表分派（movsxd 取值 + cmp 上限 + ja + jmp [rdx+rax*4]）
       · 池基址   ← 复用 relocate.py 的遍历特征（步长 + 槽内字段 + 槽数 cmp）
  2. 由锚点算「位移档」—— 位移是**分段**的，不是全局一个值
  3. 用位移档 + 「目标必须被代码引用」+ 「不得落在已知结构体内部」推其余标量
  4. 游戏在关卡内时做运行时读值验证（残机 1..8、火力 ≤128、指针落在合法区间）
  5. 写 `tools/addr_cache.json`；**源码一行不动**，由 addr.py 在 import 时套用

用法:
  py tools\\autofix.py                定位 + 尽力验证 + 写缓存
  py tools\\autofix.py --dry          只打印，不写缓存
  py tools\\autofix.py --exe <路径>   指定 exe
"""
import argparse
import hashlib
import json
import os
import struct
import sys
import time

import capstone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import numpy as np  # noqa: E402
import relocate  # noqa: E402
from addr import CACHE, CACHE_WRITE, ADDR_NAMES  # noqa: E402
from offsets import (BULLETS_OFF, ENEMIES_OFF, ENEMY_BLOCK,  # noqa: E402
                     ENEMY_COUNT, ENEMY_STRIDE, E_OFF_FLAGS1, E_OFF_X, E_OFF_Y,
                     E_OCCUPIED)

BASE = relocate.IMAGE_BASE_HINT

# 旧构建的基线地址 —— 特征来源与「位移」的参照，来自 offsets.py
OLD = {
    'PLAYER_BASE': 0x4FF3A0, 'PLAYER_X': 0x506AD0, 'PLAYER_Y': 0x506AD4,
    'PLAYER_HITBOX': 0x506AEC,
    'LIVES': 0x4FF0F0, 'BOMBS': 0x4FF0F1, 'RETRY': 0x4FF0F2,
    'POWER': 0x4F1E88, 'DEATHS': 0x4F1E60, 'DYING': 0x4F27B1,
    'NATIVE_TIME': 0x4F27B9, 'INPUT': 0xA6EC60, 'GUI': 0xA6EC08,
    'CUR_STATE': 0xC21D9C, 'WANT_STATE': 0xC21D98, 'CALC_COUNT': 0xC21C00,
    'BM_RVA': 0x3EC2A0, 'EM_RVA': 0xAA1E90, 'IM_RVA': 0xBAF0D8,
    'ITEM_NEXT_IDX': 0xC07238,
}
# 结构内固定偏移（**不随构建变**），用于派生与「候选落在结构内」的排除
DERIVE = {
    'PLAYER_Y': ('PLAYER_X', 4),
    'PLAYER_HITBOX': ('PLAYER_X', 28),
    'PLAYER_BASE': ('PLAYER_X', -0x7730),
    'WANT_STATE': ('CUR_STATE', -4),
}
# 已知结构体占用区间：(基址变量, 大小, 名字) —— 候选落进去说明是结构字段而非全局变量
STRUCTS = [('PLAYER_BASE', 0xA000, 'Player'), ('BM_RVA', 0x100000, 'BulletManager'),
           ('EM_RVA', 0x10B000, 'EnemyManager'), ('IM_RVA', 0x58000, 'ItemManager')]


# ── 反汇编 ──
def load_exe(path):
    data = open(path, 'rb').read()
    secs = relocate.parse_sections(data)
    text = next(s for s in secs if s['name'] == '.text')
    dsec = next(s for s in secs if s['name'] == '.data')
    code = data[text['rawptr']:text['rawptr'] + text['rawsize']]
    return data, secs, text, code, dsec['vaddr'], dsec['vaddr'] + dsec['vsize']


def make_md():
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
    md.detail = True
    md.skipdata = True          # 必须：.text 里嵌着跳转表数据，不设会只解出 1.4%
    return md


def rip_target(insn):
    for op in insn.operands:
        if op.type == capstone.x86.X86_OP_MEM \
                and op.mem.base == capstone.x86.X86_REG_RIP:
            return insn.address - BASE + insn.size + op.mem.disp
    return None


def disasm_all(md, code, base_rva):
    insns = []
    for insn in md.disasm(code, BASE + base_rva):
        if insn.id:
            insns.append(insn)
    return insns


# ── 指纹定位 ──
def find_frame_counter(insns, lo, hi):
    """帧计数 = 全二进制里 `inc byte [rip+X]` 且 X 落在 .data 的那些（数量极少）"""
    out = []
    for i, insn in enumerate(insns):
        if insn.mnemonic != 'inc' or 'byte ptr [rip' not in insn.op_str:
            continue
        t = rip_target(insn)
        if t is not None and lo <= t < hi:
            out.append((t, insn.address - BASE))
    return out


def find_switch_vars(insns, lo, hi):
    """switch 分派读的全局 = 状态机 curState 的形态

    形态：mov/movsxd 从 [rip+X] 取索引 → 近邻有 cmp 上限 + 条件跳转 → 再 jmp 跳转表。
    """
    out = []
    for i, insn in enumerate(insns):
        if insn.mnemonic not in ('mov', 'movsxd') or 'dword ptr [rip' not in insn.op_str:
            continue
        t = rip_target(insn)
        if t is None or not (lo <= t < hi):
            continue
        w = insns[i + 1:i + 8]
        # 完整形态才收：cmp 上限 + 条件跳转 + 取跳转表基址 + 跳寄存器
        # 只判 cmp+ja 会捞到 37 个（大量普通边界检查），加后两条后只剩状态机分派
        if any(x.mnemonic == 'cmp' for x in w) and \
                any(x.mnemonic in ('ja', 'jae', 'jb', 'jbe') for x in w) and \
                any(x.mnemonic == 'lea' for x in w) and \
                any(x.mnemonic == 'jmp' and x.operands
                    and x.operands[0].type == capstone.x86.X86_OP_REG for x in w):
            out.append((t, insn.address - BASE))
    return out


def find_state_vars(insns, lo, hi, max_state=11):
    """状态机变量 = 被反复赋予**不同**场景号的全局

    为什么不能只靠 switch 指纹：实测它选中一个只有 1 处引用（`movsxd` 读进
    12 分支跳转表）、**从不被赋值**的变量（关卡内读 1，看着像菜单），而真正的
    curState 被赋 1/7/8/0xc 四个不同场景号、47 处引用。差 4 字节的后果是关卡内
    判成 MENU、脚本拒绝启动。

    判据：被赋 ≥2 个**不同**的小立即数（场景号）。普通计数器只会被赋 0/1。
    """
    writes = {}
    for insn in insns:
        if insn.mnemonic != 'mov' or len(insn.operands) < 2:
            continue
        dst, src = insn.operands[0], insn.operands[1]
        if dst.type != capstone.x86.X86_OP_MEM or src.type != capstone.x86.X86_OP_IMM:
            continue
        if dst.mem.base != capstone.x86.X86_REG_RIP or dst.size != 4:
            continue
        t = rip_target(insn)
        if t is None or not (lo <= t < hi) or not (0 <= src.imm <= max_state):
            continue
        writes.setdefault(t, set()).add(src.imm)
    return [t for t, vals in writes.items() if len(vals) >= 2]


def locate_pools(data, secs, md, code, text_rva, data_lo, data_hi):
    """复用 relocate.py 的特征引擎定位池/坐标（步长 + 槽内字段 + 槽数 cmp）

    返回 {offsets.py 里的变量名: (新 RVA, 锚点支持数, 说明)}。

    两道门都是必需的，少一道就会挑中热门全局（实测把子弹池引到 0x5542B0）：
      · 锚点邻域必须访问槽内字段 → 才算「在遍历这个池的代码」
      · 位移必须落在参考带内 → relocate.SHIFT_REF ± SHIFT_TOL
    """
    raw = {}
    for feat in relocate.FEATURES:
        kind, imm = feat['anchor']
        if kind == 'inc_mem':
            continue                      # 帧计数走自己的指纹（find_frame_counter）
        anchors = relocate.find_anchors(md, code, text_rva, kind, imm)
        score = {}
        for a_rva, _sz, _rel in anchors:
            has_want, has_field = relocate.probe_near(md, data, secs, a_rva,
                                                      feat['want'][1] if feat['want'] else None,
                                                      feat['field'])
            if feat['field'] is not None and not has_field:
                continue
            for t in relocate.lea_targets_near(md, data, secs, a_rva, data_lo, data_hi,
                                               only_lea=feat.get('ref', 'lea') == 'lea'):
                s = score.setdefault(t, [0, 0])
                s[0] += 1
                s[1] += 1 if has_want else 0
        if not score:
            continue
        ranked = sorted(score.items(), key=lambda kv: (-kv[1][1], -kv[1][0]))
        for t, sc in ranked:
            if abs((t - feat['old']) - relocate.SHIFT_REF) <= relocate.SHIFT_TOL:
                raw[feat['name']] = (t, sc[0], feat['why'])
                break

    out = {}
    for fname, (addr, n, why) in raw.items():
        var = relocate.OFFSET_VARS.get(fname)
        if var:
            out[var] = (addr, n, why)
    # lasers[0] 的三重特征比子弹池基址本身可靠，基址由它派生（MEMMAP §7 的硬关系）
    if 'BM_RVA' not in out and 'lasers[0]' in raw:
        out['BM_RVA'] = (raw['lasers[0]'][0] - 0xF5018, 1,
                         f'派生自 lasers[0] 0x{raw["lasers[0]"][0]:08X} − 0xF5018')
    return out


# ── 位置推断 ──
def compute_shifts(known):
    """(旧,新) 对 → {位移: 权重}

    位移是**分段**的（同一次更新里 +0x43260 / +0x4AC50 / +0x4C220 并存），所以不能
    只留一个值。权重 = 支持该档位的锚点数之和 —— 多档同时命中时靠它定夺
    （道具池 10 个锚点支持 +0x4C220，比只有 1 个锚点的档位可信得多）。
    """
    bands = {}
    for name, rec in known.items():
        if name not in OLD:
            continue
        sh = rec[0] - OLD[name]
        bands[sh] = bands.get(sh, 0) + max(int(rec[1]), 1)
    return bands


def pick_band(cands, old_addr, bands, tol=0x1000):
    """从指纹候选里只留「位移落在已知档位附近」的

    指纹本身很宽：`inc byte [rip+X]` 全二进制 4 处、switch 分派 12 处，
    但目标变量的位移必须和同一次更新的其它锚点一致 —— 这一条能滤掉绝大多数。
    """
    keep = []
    for c in cands:
        d = c[0] - old_addr
        for sh in bands:
            if abs(d - sh) <= tol:
                keep.append(c)
                break
    return keep


def in_any_struct(addr, resolved):
    """候选是否落在已知结构体内部 —— 是的话它是结构字段，不是全局变量"""
    for base_name, size, label in STRUCTS:
        b = resolved.get(base_name)
        if b is not None and b <= addr < b + size:
            return label
    return None


def locate_scalars(refd, bands, resolved, lo, hi):
    """用「位移档（按权重优先）+ 必须被引用 + 不得落在结构内」推标量"""
    out, notes = {}, {}
    ordered = [sh for sh, _w in sorted(bands.items(), key=lambda kv: -kv[1])]
    for name, old in OLD.items():
        if name in resolved or name in DERIVE:
            continue
        cands = []
        for sh in ordered:
            a = old + sh
            if a in refd:
                cands.append((sh, a, len(refd[a]), in_any_struct(a, resolved)))
        ok = [c for c in cands if c[3] is None]
        bad = [c for c in cands if c[3] is not None]
        if ok:
            sh, a, n, _ = ok[0]                  # 已按档位权重排好序
            out[name] = a
            notes[name] = f'位移 {sh:+#x} 命中（该档位权重最高），{n} 处引用'
        elif bad:
            sh, a, n, owner = bad[0]
            out[name] = a
            notes[name] = (f'注意：位移 {sh:+#x} 唯一候选 0x{a:08X}，但它落在 {owner} 结构'
                           f'内部（{n} 处引用）—— 可能是结构字段而非该全局；'
                           '需运行时读值判定（旧构建里该变量在结构外）')
        else:
            notes[name] = '没有任何位移档命中 —— 需要新特征'
    return out, notes


def apply_derive(resolved):
    """按固定结构内偏移把派生地址算出来（多轮，直到不再增长）"""
    added = {}
    for _ in range(4):
        grew = False
        for name, (src, delta) in DERIVE.items():
            if name in resolved or name in added or src not in resolved:
                continue
            if src in added:
                base_v = added[src]
            else:
                base_v = resolved[src]
            added[name] = base_v + delta
            grew = True
        if not grew:
            break
    return added


# ── 运行时验证 ──
def pick_player_x(bands):
    """按「PLAYER_X + 0x1C 实读 ≈ 1.25」在各位移档候选里挑真正的自机 x

    为什么不能只信位移档：档位权重来自池定位的锚点数，实测把坐标带推错 ——
    `+0x43260`（权重 3）压过正确的 `+0x4AC50`（权重 1），而错档那个地址上放着
    **场地矩形常量** `{8,16,368,416}`。两个候选的值都落在场地内，看着都合理，
    静态分不出来；唯一能识破的是判定半径 —— 正确处 `+0x1C` 恒为 1.25、错处读 0.00。
    """
    try:
        from winmem import Process, find_pids, module_base
    except Exception as e:                                # noqa: BLE001
        return None, f'winmem 不可用（{e}）'
    pids = find_pids('th06nc.exe')
    if not pids:
        return None, '游戏未运行'
    hits = []
    try:
        base = module_base(pids[0], 'th06nc.exe')[0]
        with Process(pids[0]) as p:
            for sh in bands:
                a = OLD['PLAYER_X'] + sh
                d = p.read(base + a + 0x1C, 4)
                if d and len(d) == 4:
                    v = struct.unpack('<f', d)[0]
                    if 0.5 <= v <= 4.0:
                        hits.append((sh, a, v))
    except Exception as e:                                # noqa: BLE001
        return None, f'读取失败（{type(e).__name__}: {e}）'
    if len(hits) == 1:
        sh, a, v = hits[0]
        return a, f'0x{a:08X}（位移 {sh:+#x}）判定半径实读 {v:.4f} ≈ 1.25'
    if not hits:
        return None, '各档位候选的判定半径都不在 0.5..4.0 —— 游戏可能不在关卡内'
    return None, f'{len(hits)} 个档位候选都通过，无法区分'


def pick_enemy_mgr(bands, deltas=(0, 0x8, -0x8)):
    """选「base + ENEMIES_OFF 能读到占用槽」的敌人池基址

    为什么不能只信锚点：relocate 的锚点是「遍历步长 add rbx,0x10B0」，它 lea 到的
    是**遍历起点** `enemies[0]`（= manager + ENEMIES_OFF），不是 manager 基址。差这
    8 字节，调用方再加 ENEMIES_OFF 就每槽整体错位 —— 占用标志全读成 0，表现是
    「敌 0」→ `pick_target()` 恒 None → 进攻项被整段跳过，权重调多大都是 0。
    """
    try:
        from winmem import Process, find_pids, module_base
    except Exception as e:                                # noqa: BLE001
        return None, f'winmem 不可用（{e}）'
    pids = find_pids('th06nc.exe')
    if not pids:
        return None, '游戏未运行'
    best = None
    try:
        base = module_base(pids[0], 'th06nc.exe')[0]
        with Process(pids[0]) as p:
            for sh in bands:
                for d in deltas:
                    a = OLD['EM_RVA'] + sh + d
                    blk = p.read(base + a + ENEMIES_OFF, ENEMY_BLOCK)
                    if not blk or len(blk) < ENEMY_BLOCK:
                        continue
                    raw = np.frombuffer(blk, dtype=np.uint8).reshape(ENEMY_COUNT,
                                                                    ENEMY_STRIDE)
                    mask = (raw[:, E_OFF_FLAGS1] & E_OCCUPIED) != 0
                    if not mask.any():
                        continue
                    # 光看占用标志不够：错误基址上也可能有一批 bit7 恰好置位的字节
                    # （实测 +0x4ac50 那个候选有 32 个假占用），而真敌人必然有
                    # 落在场地内的坐标。**判据要用「占用 + 坐标合理」，不是数个数**。
                    xs = raw[:, E_OFF_X:E_OFF_X + 4].copy().view('<f4').ravel()[mask]
                    ys = raw[:, E_OFF_Y:E_OFF_Y + 4].copy().view('<f4').ravel()[mask]
                    n = int(np.count_nonzero((xs >= 8.0) & (xs <= 376.0)
                                             & (ys >= 16.0) & (ys <= 432.0)))
                    if n and (best is None or n > best[2]):
                        best = (a, sh, n)
    except Exception as e:                                # noqa: BLE001
        return None, f'读取失败（{type(e).__name__}: {e}）'
    if best is None:
        return None, '没有任何候选读到占用槽 —— 游戏可能不在关卡内（或池全空）'
    a, sh, n = best
    # 位移按**最终地址**算，不用候选档位 `sh` —— 带 deltas 修正时两者会差 8，写出来误导
    return a, f'0x{a:08X}（位移 {a - OLD["EM_RVA"]:+#x}）实读占用槽 {n} 个'


def pick_frame_counter(cands, seconds=1.5):
    """在候选里测出真正每帧 +1 的那个，返回 (地址, 说明)

    为什么必须实测：`inc byte [rip+X]` 这个指纹**不够独特** —— 实测
    0xC6DFD6 / 0xC6DFD7 是一对相邻的动画计数器，各自都有完整的
    `inc` + `dec` + `cmp ...,9` 形态，却根本不随帧增长；真正的帧计数
    反而只有一处 rip 引用。静态分不出来，速率一秒就分出来了。
    """
    try:
        from winmem import Process, find_pids, module_base
    except Exception as e:                                # noqa: BLE001
        return None, f'winmem 不可用（{e}）'
    pids = find_pids('th06nc.exe')
    if not pids:
        return None, '游戏未运行'
    try:
        base = module_base(pids[0], 'th06nc.exe')[0]
        with Process(pids[0]) as p:
            first = {t: int.from_bytes(p.read(base + t, 2), 'little') for t in cands}
            time.sleep(seconds)
            last = {t: int.from_bytes(p.read(base + t, 2), 'little') for t in cands}
    except Exception as e:                                # noqa: BLE001
        return None, f'读取失败（{type(e).__name__}: {e}）'
    rates = {t: (last[t] - first[t]) / seconds for t in cands}
    best = max(rates, key=lambda t: rates[t])
    if rates[best] < 20:
        return None, (f'没有候选在增长（最高 0x{best:08X} 仅 {rates[best]:.1f}/秒）'
                      ' —— 游戏暂停或未在关卡内')
    return best, f'0x{best:08X} 以 {rates[best]:.0f}/秒 增长（60fps 下应约 60）'


def runtime_check(entries, timeout=3.0):
    """游戏在关卡内时读值验证：返回 {名字: (是否通过, 说明)}；游戏没跑就返回 {}"""
    try:
        from winmem import Process, find_pids, module_base
    except Exception:
        return {}
    pids = find_pids('th06nc.exe')
    if not pids:
        return {}
    try:
        pid = pids[0]
        base = module_base(pid, 'th06nc.exe')[0]
    except Exception:
        return {}
    res = {}
    with Process(pid) as p:
        def u8(r):
            return p.read(base + r, 1)[0]

        def u16(r):
            return struct.unpack('<H', p.read(base + r, 2))[0]

        def u32(r):
            return p.read_u32(base + r)

        def f32(r):
            return p.read_f32(base + r)

        # 游戏必须真的在推进，否则读到的是暂停瞬间的快照，判不出对错
        # （实测暂停时 LIVES 会读成 0，看着像地址错，其实是游戏没跑）。
        # 双重探针：帧计数没定位时，自机坐标也能判断「有没有在动」。
        def probe():
            out = []
            if 'CALC_COUNT' in entries:
                out.append(u8(entries['CALC_COUNT']))
            if 'PLAYER_X' in entries:
                out.append(round(f32(entries['PLAYER_X']), 3))
            if 'LIVES' in entries:
                out.append(u8(entries['LIVES']))
            return tuple(out)

        s0 = probe()
        time.sleep(0.5)
        s1 = probe()
        if not s0 or s0 == s1:
            return {'_paused': (False, f'游戏暂停或未在关卡内（探针 {s0} 两次相同）'
                                      ' —— 读值不作数，结果一律标为待验证')}

        def chk(name, cond, msg):
            if name in entries:
                res[name] = (bool(cond), msg)

        # 残机 0 是**合法状态**（最后一条命 / 已死等 Continue），别把 0 判成地址错
        for nm, lo, hi in (('LIVES', 0, 8), ('BOMBS', 0, 8), ('RETRY', 0, 255)):
            if nm in entries:
                v = u8(entries[nm])
                chk(nm, lo <= v <= hi, f'实读 {v}（期望 {lo}..{hi}）')
        if 'PLAYER_HITBOX' in entries:
            v = f32(entries['PLAYER_HITBOX'])
            # 判定半径恒为 1.25，是坐标基址**最硬**的判据：基址错档时这里读 0.00。
            # 判据放到 0.0 会让那个 0.00 假通过 —— 实测就是这么整体漏掉坐标错档的。
            chk('PLAYER_HITBOX', 0.5 <= v <= 4.0, f'实读 {v:.4f}（应为 1.25）')
        if 'POWER' in entries:
            v = u16(entries['POWER'])
            chk('POWER', 0 <= v <= 128, f'实读 {v}（火力 ≤128）')
        if 'CUR_STATE' in entries:
            v = u32(entries['CUR_STATE'])
            chk('CUR_STATE', 0 <= v <= 11, f'实读 {v}（switch 上限 0xb）')
        # curState 与 wantedState 相邻且**通常相等**（相等 = 没有场景切换进行中）。
        # 这是行为判据，不依赖任何静态指纹 —— 实测靠它一眼看出 curState 偏了 4 字节
        # （错位的组合读成 cur 1 / want 2，永远不等）。
        if 'CUR_STATE' in entries and 'WANT_STATE' in entries:
            c, w = u32(entries['CUR_STATE']), u32(entries['WANT_STATE'])
            pair_ok = c == w
            # 不能走 chk()：它按「名字必须在 entries 里」过滤，而 STATE_PAIR 不是地址
            res['STATE_PAIR'] = (pair_ok, f'curState {c} / wantedState {w}'
                                           '（应相等，不等 = 至少一个地址错位）')
            if not pair_ok:
                res['CUR_STATE'] = (False, f'实读 {c}，与 wantedState {w} 不等 → 地址可疑')
        if 'PLAYER_X' in entries and 'PLAYER_Y' in entries:
            x, y = f32(entries['PLAYER_X']), f32(entries['PLAYER_Y'])
            # 游戏把自机钳在场地矩形内（x 8..376、y 16..432）。判据放到 512/600 时，
            # 错档那个地址上的场地矩形常量 {8,16,...} 会假通过 —— 收紧到真实钳制范围。
            chk('PLAYER_X', 8.0 <= x <= 376.0, f'实读 {x:.2f}（场地 8..376）')
            chk('PLAYER_Y', 16.0 <= y <= 432.0, f'实读 {y:.2f}（场地 16..432）')
        # Player 结构内固定关系：LIVES 在 PLAYER_BASE − 0x2B0（不随构建变）。
        # 交叉验证坐标基址 —— 基址错档时这条立刻不等。
        if 'PLAYER_BASE' in entries and 'LIVES' in entries:
            d = entries['PLAYER_BASE'] - 0x2B0
            res['PLAYER_LAYOUT'] = (d == entries['LIVES'],
                                    f'PLAYER_BASE − 0x2B0 = 0x{d:08X} / '
                                    f'LIVES = 0x{entries["LIVES"]:08X}（应一致）')
        if 'GUI' in entries:
            v = struct.unpack('<Q', p.read(base + entries['GUI'], 8))[0]
            chk('GUI', 0x10000 <= v < (1 << 48), f'实读 0x{v:X}（像合法用户态指针）')

        # 池：读到落在场地内的实体才说明基址对。**空池不下结论** ——
        # 主菜单/关卡切换时池本来就是空的，那不算地址错。
        # 槽起点 = 池基址 + 数组偏移。少加这个偏移会让整块错位，而错位后照样能捞到
        # 几个「看着像坐标」的 float —— 实测 EM_RVA 差 8 字节时这条检查反而通过了。
        for nm, stride, off, ox, oy, label in (
                ('BM_RVA', 0x620, BULLETS_OFF, 0x30, 0x34, '子弹'),
                ('EM_RVA', 0x10B0, ENEMIES_OFF, 0xB0, 0xB4, '敌人')):
            if nm not in entries:
                continue
            n = 0
            for i in range(64):
                try:
                    x = f32(entries[nm] + off + i * stride + ox)
                    y = f32(entries[nm] + off + i * stride + oy)
                except Exception:                        # noqa: BLE001
                    break
                if 8.0 <= x <= 376.0 and 16.0 <= y <= 432.0:
                    n += 1
            if n:
                res[nm] = (True, f'前 64 槽有 {n} 个{label}落在场地内')
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--exe', default=None)
    ap.add_argument('--dry', action='store_true', help='只打印，不写缓存')
    args = ap.parse_args()

    exe = args.exe
    if not exe:
        try:
            import env
            d, _ = env.game_dir()
            exe = os.path.join(d, 'th06nc.exe') if d else None
        except Exception:
            exe = None
    if not exe or not os.path.exists(exe):
        raise SystemExit('找不到 th06nc.exe，用 --exe 指定')

    data = open(exe, 'rb').read()
    md5 = hashlib.md5(data).hexdigest()
    _data, secs, text, code, data_lo, data_hi = load_exe(exe)
    md = make_md()
    print(f'exe   {exe}')
    print(f'MD5   {md5}')
    print(f'.data 0x{data_lo:X}..0x{data_hi:X}\n')

    insns = disasm_all(md, code, text['vaddr'])
    print(f'反汇编 {len(insns):,} 条指令（skipdata 模式，必须）。')

    idx = relocate.build_ref_index(md, code, text['vaddr'])
    refd = idx
    print(f'被引用地址 {len(refd):,} 个\n')

    resolved, why = {}, {}

    # 1) 池基址（遍历特征 + 位移容差）—— 必须先做：它算出的位移档是后面一切筛选的基准
    print('池基址（遍历特征）：')
    pools = locate_pools(data, secs, md, code, text['vaddr'], data_lo, data_hi)
    for name, (addr, n, desc) in pools.items():
        print(f'    {name:<18} 0x{addr:08X}  位移 {addr - OLD[name]:+#x}  '
              f'锚点 {n} 个  {desc}')
        resolved[name] = addr
        why[name] = f'{desc}（锚点 {n} 个）'

    bands = compute_shifts(pools)
    print('\n位移档（权重 = 锚点支持数之和）：')
    for sh, w in sorted(bands.items(), key=lambda kv: -kv[1]):
        print(f'    {sh:+#10x}  权重 {w}')

    # 2) 指纹定位：不依赖旧地址的假设，但要靠位移带滤掉无关命中
    fc_all = find_frame_counter(insns, data_lo, data_hi)
    fc = pick_band([c for c in fc_all if c[0] not in resolved.values()],
                   OLD['CALC_COUNT'], bands)
    print(f'\n帧计数候选：{len(fc_all)} 个，位移带过滤后 {len(fc)} 个。')
    for t, at in fc:
        print(f'    0x{t:08X}  位移 {t - OLD["CALC_COUNT"]:+#x}  '
              f'引用 {len(refd.get(t, []))} 处  @0x{at:06X}')

    sw_all = find_switch_vars(insns, data_lo, data_hi)
    sv_all = find_state_vars(insns, data_lo, data_hi)
    # 两条指纹取并集：switch 分派说明「被主循环读」，被赋不同场景号说明「是状态
    # 变量」。单用前者会选中一个 1 处引用、从不被赋值的变量（见 find_state_vars）。
    sw = pick_band([(t, 0) for t in {t for t, _ in sw_all} | set(sv_all)],
                   OLD['CUR_STATE'], bands)
    # 状态机变量一定被反复读写 —— 引用数太少的排除
    sw = [c for c in sw if len(refd.get(c[0], [])) >= 3]
    sw.sort(key=lambda c: -len(refd.get(c[0], [])))
    print(f'\n状态变量候选：switch 分派 {len(sw_all)} 个，被赋场景号 {len(sv_all)} 个，'
          f'位移带与引用数过滤后 {len(sw)} 个。')
    for t, _at in sw[:8]:
        print(f'    0x{t:08X}  位移 {t - OLD["CUR_STATE"]:+#x}  '
              f'引用 {len(refd.get(t, []))} 处')

    # 3) 坐标改用**运行时判据**挑，别信位移档权重（理由见 pick_player_x）
    px, px_note = pick_player_x(bands)
    old_x = resolved.get('PLAYER_X')
    if px is not None and px != old_x:
        resolved['PLAYER_X'] = px
        why['PLAYER_X'] = (f'运行时判定半径确认：{px_note}'
                           + (f'；位移档原本给 0x{old_x:08X}' if old_x else ''))
    elif px is None:
        print(f'\n自机坐标未经运行时确认：{px_note}。')

    # 敌人池基址同理：锚点找到的是遍历起点 enemies[0]，要按占用槽回推到 manager
    em, em_note = pick_enemy_mgr(bands)
    old_em = resolved.get('EM_RVA')
    if em is not None and em != old_em:
        resolved['EM_RVA'] = em
        why['EM_RVA'] = (f'运行时占用槽确认：{em_note}'
                         + (f'；锚点原本给 0x{old_em:08X}' if old_em else ''))
    elif em is None:
        print(f'\n敌人池基址未经运行时确认：{em_note}。')

    # 4) 位移档推其余标量
    # 先把派生地址算出来 —— 「候选不得落在结构内」这条判据要用到 PLAYER_BASE，
    # 而它是从 PLAYER_X 派生的，不先算出来这道门就是空的。
    resolved.update(apply_derive(resolved))
    guess, notes = locate_scalars(refd, bands, resolved, data_lo, data_hi)
    # 帧计数：位移档与 `inc byte` 指纹会给出**不同**候选 —— 指纹那两个是相邻的
    # 动画计数器（形态齐全但不随帧增长，见 pick_frame_counter 的注释）。
    # 所以两边的候选合起来交给运行时按速率定夺，测不出来才退回位移档的结果。
    fc_cands = sorted({t for t, _ in fc}
                      | ({guess['CALC_COUNT']} if 'CALC_COUNT' in guess else set()))
    fc_verified = False
    if fc_cands:
        picked, note = pick_frame_counter(fc_cands)
        if picked is not None:
            guess['CALC_COUNT'] = picked
            why['CALC_COUNT'] = f'运行时速率确认：{note}'
            fc_verified = True
        else:
            why['CALC_COUNT'] = (
                f'位移档候选（运行时未能确认：{note}）；'
                f'候选集 {" ".join(f"0x{t:08X}" for t in fc_cands)}')
    if sw:
        guess['CUR_STATE'] = sw[0][0]          # 已按引用数降序，取引用最多的
        why['CUR_STATE'] = (f'状态变量指纹（被赋不同场景号 ∪ switch 分派），'
                            f'{len(refd.get(sw[0][0], []))} 处引用')
    else:
        notes['CUR_STATE'] = '两条指纹都没有带内命中 —— 退回位移档结果'

    resolved.update(guess)
    resolved.update(apply_derive(resolved))

    print('\n推断结果：')
    for name in ADDR_NAMES:
        if name in resolved:
            tag = why.get(name) or notes.get(name) or '位移档 + 引用命中'
            conf = 'static'
            if name in DERIVE:
                conf = 'derived'
            if name in why:
                conf = 'static'
            print(f'    {name:<16} 0x{resolved[name]:08X}  [{conf}] {tag}')
        else:
            print(f'    {name:<16} {"—":>12}  {notes.get(name, "未定位")}')

    # 4) 运行时验证
    print('\n运行时验证：')
    rt = runtime_check(resolved)
    if not rt:
        print('    游戏未运行，跳过（地址仍会写入，但标记为待运行时验证）。')
    elif '_paused' in rt:
        print(f'    注意：{rt["_paused"][1]}')
    else:
        for k, (ok, msg) in rt.items():
            print(f'    {"通过" if ok else "失败"} {k:<16} {msg}')

    if args.dry:
        print('\n--dry：不写缓存。')
        return 0

    # 5) 写缓存
    node = {
        'game': 'th06nc.exe', 'exe_size': len(data),
        'exe_mtime': time.strftime('%Y-%m-%d %H:%M:%S',
                                   time.localtime(os.path.getmtime(exe))),
        'resolved_at': time.strftime('%Y-%m-%d'),
        'resolved_by': 'tools/autofix.py（位移分档 + 反汇编指纹）',
        'shift_bands': [{'shift': f'0x{sh:X}', 'weight': w}
                        for sh, w in sorted(bands.items(), key=lambda kv: -kv[1])],
        'entries': {},
    }
    for name, rva in sorted(resolved.items()):
        if name not in ADDR_NAMES:
            continue
        if name in rt:
            conf = 'verified' if rt[name][0] else 'unverified'
        elif name == 'CALC_COUNT' and fc_verified:
            conf = 'verified'            # 速率确认过（约 60/秒），比读值域更硬
        elif name in DERIVE:
            conf = 'derived'
        else:
            conf = 'static'
        node['entries'][name] = {
            'rva': f'0x{rva:08X}', 'shift': f'0x{rva - OLD[name]:X}',
            'confidence': conf, 'how': why.get(name) or notes.get(name, ''),
        }
    cache = {}
    src = CACHE_WRITE if os.path.exists(CACHE_WRITE) else CACHE
    if os.path.exists(src):
        try:
            cache = json.load(open(src, encoding='utf-8'))
        except ValueError:
            cache = {}
    # 保留 `_readme` 说明与其它构建的条目，只替换本构建这一节
    cache = {k: v for k, v in cache.items() if k == '_readme' or not k.startswith('_')}
    cache[md5] = node
    with open(CACHE_WRITE, 'w', encoding='utf-8') as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)
    print(f'\n已写入 {CACHE_WRITE}（构建 {md5[:12]}…，{len(node["entries"])} 个地址）')
    print('源码未改动；addr.py 会在 import offsets 时自动套用。')
    return 0


if __name__ == '__main__':
    sys.exit(main())
