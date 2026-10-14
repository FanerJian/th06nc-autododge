"""按「特征」在新构建的 th06nc.exe 里重新定位地址 —— 游戏更新后一条命令恢复

为什么需要：Steam 每次更新游戏，`offsets.py` 里所有 RVA 立刻失效
（2026-09-24 那次更新就是这么让整套地址报废的：脚本读到未初始化内存，判成
「不在关卡」后拒绝发键）。但实测三次更新对比证明，改的只是**布局**而非**结构**：

  · 结构内偏移不变 —— 敌人 position 仍在 `+0xB0`、激光阶段机仍在 `+0x290`
  · 池 stride 不变 —— `0x620` / `0x298` / `0x10B0` / `0x160` 全部命中
  · 槽数不变 —— `640` / `64` / `256` / `0x400` 全部命中
  · 函数只在旧 RVA 数百字节内平移

所以地址能靠**特征**重新找到，不必重做逆向。特征来源 = MEMMAP 当初定位该地址时
用的反汇编依据（本文件把它形式化；改地址时**同步改这里**，它才是可执行的依据）。

用法:
  py tools\\relocate.py                 列出全部目标的候选
  py tools\\relocate.py --only laser    只看名字含 laser 的
  py tools\\relocate.py --exe <路径>    指定 exe（默认读 env.py 的游戏目录）
"""
import argparse
import os
import struct
import sys

import capstone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

WINDOW = 0x180        # 判断「锚点邻域是否访问槽内字段」的窗口（前后各一份）
LEA_BACK = 0x60       # 只在锚点**之前**这么多字节里找 lea（池基址是循环前加载的）
IMAGE_BASE_HINT = 0x140000000

# `.data` 的整体位移：实测 g_EnemyManager(+0x4C228) 与 items[0](+0x4C220) 几乎一致，
# lasers[0] 是 +0x4AC50（前段另有约 5.5KB 的局部插入）。偏离参考带太远的候选
# 基本可以排除 —— 实测子弹池误命中偏离 1.1MB（那是个被引用 54 次的热门全局）。
SHIFT_REF = 0x4C220
SHIFT_TOL = 0x40000

# `.data` 增长量 —— 比 SHIFT_REF 更硬的整体位移基准：
#   旧 0x323000..0xC29660  →  新 0x36D000..0xC75884   上界 +0x4C224
# 实测校验（外推 vs 独立特征定出的候选）：
#   g_EnemyManager  0xAA1E90 + 0x4C224 = 0xAEE0B4   候选 0xAEE0B8   差 4
#   items[0]        0xBAF0D8 + 0x4C224 = 0xBFB2FC   候选 0xBFB2F8   差 4
#   CALC_COUNT      0xC21C00 + 0x4C224 = 0xC6DE24   候选 0xC6DFD6   差 0x1B2
# 精度到几字节量级，所以「特征候选」与「外推预测」可以互为独立验证。
PDATA_SHIFT = 0x4C224
OLD_DATA_HI = 0xC29660      # offsets.py 记的旧 .data 上界，用来现算增长量

# 尚未加特征、先靠外推定位的目标（名字 → 旧 RVA）。
# 用途：不读内存也能粗验外推 —— **正确的全局一定有指令引用它**，
# 错位的地址则无人问津。引用数为 0 就是在警告「这个外推值没落在任何变量上」。
PREDICT_TARGETS = [
    ('LIVES', 0x4FF0F0), ('BOMBS', 0x4FF0F1), ('RETRY', 0x4FF0F2),
    ('POWER', 0x4F1E88), ('DEATHS', 0x4F1E60), ('DYING', 0x4F27B1),
    ('NATIVE_TIME', 0x4F27B9), ('INPUT', 0xA6EC60), ('GUI', 0xA6EC08),
    ('CUR_STATE', 0xC21D9C), ('WANT_STATE', 0xC21D98), ('CALC_COUNT', 0xC21C00),
    ('ITEM_NEXT_IDX', 0xC07238), ('PLAYER_BASE', 0x4FF3A0),
    ('g_BulletManager', 0x3EC2A0), ('g_EnemyManager', 0xAA1E90),
    ('lasers[0]', 0x4E12B8), ('items[0]', 0xBAF0D8),
]

# ---- 派生地址：MEMMAP 里的硬关系，用来交叉验证（定位一个即可推出另一个）----
# 这些关系抓出过真实错误：独立定位给 g_BulletManager=0x5542B0、
# 给 lasers[0]=0x52BF08，而后者反推 g_BulletManager=0x43CEF0 —— 差 1.1MB，
# 至少一个是误命中。改地址时这些 delta 不变（它们在同一对象内部）。
DERIVED = [
    dict(name='g_BulletManager', src='lasers[0]', delta=-0xF5018,
         why='lasers[0] = g_BulletManager + 0xF5018（MEMMAP §7）'),
    dict(name='g_EnemyManager.enemies[0]', src='g_EnemyManager', delta=0x8,
         why='enemies[] = g_EnemyManager + 8（MEMMAP §6）'),
    dict(name='PLAYER_BASE', src='PLAYER_X', delta=-0x7730,
         why='自机 x = Player + 0x7730（MEMMAP §1）'),
]

# 静态已定、但特征形态不适合放进 FEATURES 的结果（直接写进 results）。
# ITEM_NEXT_IDX：`--calibrate` 给出位移 +0x4C220 → 0xC53458，
# 且信噪比 10:1（39 处引用 vs 次优 4 处），是全表最干净的一个。
EXTRA_RESULTS = {
    'ITEM_NEXT_IDX': 0xC07238 + 0x4C220,
}

# ---- 特征表：每个目标 = 「锚点指令」+「锚点邻域的结构字段访问」 ----
# anchor: 池遍历步长 / 特征立即数（MEMMAP 记录的反汇编原文）
# field : 锚点邻域内**必须**出现的槽内字段偏移 —— 这才是真正的指纹。
#         只用 `add reg,imm` 不够：实测 25/11/9/9 处命中，邻域里的 lea→.data
#         是各种热门全局，会把 4 个目标全指向同一个地址（0xBFB2F8）。
#         加上「槽内字段」后，命中的才是「在遍历这个池」的那段代码。
# want  : 槽数上限的 cmp 立即数（加分项）
FEATURES = [
    dict(name='g_BulletManager', old=0x3EC2A0, anchor=('add', 0x620),
         field=0x5F4, want=('cmp', 640),
         why='子弹池遍历 add rbx,0x620（槽内有 grazeSize +0x5F4）'),
    dict(name='g_EnemyManager', old=0xAA1E90, anchor=('add', 0x10B0),
         field=0xBC, want=('cmp', 256),
         why='敌人池遍历 add rbx,0x10B0（槽内有占用标志 +0xBC）'),
    dict(name='lasers[0]', old=0x4E12B8, anchor=('add', 0x298),
         field=0x274, want=('cmp', 0x40),
         why='激光池找空槽：cmp byte [rbx+0x274],0 → add rbx,0x298'),
    dict(name='items[0]', old=0xBAF0D8, anchor=('imul', 0x160),
         field=0x0C, want=('cmp', 0x400),
         why='道具池 imul rbx,rcx,0x160（槽内有 state +0x0C）'),
    # Player 结构：字段偏移 +0x7730（自机 x）非常独特，直接用「谁访问这个偏移」当锚点。
    # 注意目标不是 lea 而是**直接的 rip 相对读写**（movss xmm,[rip+0x506AD0]），
    # 所以 data_refs 要把所有 rip 引用都收进来，不能只收 lea。
    dict(name='PLAYER_X', old=0x506AD0, anchor=('field', 0x7730),
         field=None, want=None, ref='any',
         why='Player::OnUpdate 读写 [reg+0x7730]（自机 x = Player + 0x7730）；'
             '坐标没有 lea，必须收 mov 类引用'),
    # 状态变量：静态特征弱，但「自增一个 rip 相对字节」对帧计数是唯一形态
    dict(name='CALC_COUNT', old=0xC21C00, anchor=('inc_mem', None),
         field=None, want=None, ref='any',
         why='帧计数每帧 +1 → inc byte [rip+X]；screen.is_running 靠它判断暂停'),
]


def parse_sections(data):
    e = struct.unpack_from('<I', data, 0x3C)[0]
    coff = e + 4
    nsec = struct.unpack_from('<H', data, coff + 2)[0]
    opt_size = struct.unpack_from('<H', data, coff + 16)[0]
    opt = coff + 20
    magic = struct.unpack_from('<H', data, opt)[0]
    if magic != 0x20B:
        raise SystemExit(f'不是 PE32+（magic=0x{magic:X}）')
    sec = opt + opt_size
    out = []
    for i in range(nsec):
        o = sec + i * 40
        name = data[o:o + 8].rstrip(b'\0').decode('ascii', 'replace')
        vsize, vaddr, rawsize, rawptr = struct.unpack_from('<IIII', data, o + 8)
        out.append(dict(name=name, vaddr=vaddr, vsize=vsize,
                        rawptr=rawptr, rawsize=rawsize))
    return out


def rva_to_off(secs, rva):
    for s in secs:
        if s['vaddr'] <= rva < s['vaddr'] + max(s['vsize'], s['rawsize']):
            return s['rawptr'] + (rva - s['vaddr'])
    return None


def parse_pdata(data, secs):
    """解析 .pdata（x64 异常处理表）→ 全部函数边界 [(begin, end), ...]

    这是定位**函数起点**的可靠办法：表里每项 12 字节 = (BeginAddress, EndAddress,
    UnwindInfoAddress)，覆盖 .text 里所有正规函数。比猜函数序言靠谱得多 ——
    有了它，「某条特征指令落在哪个函数里」就是一次区间查找。
    """
    pd = next((s for s in secs if s['name'] == '.pdata'), None)
    if pd is None:
        return []
    raw = data[pd['rawptr']:pd['rawptr'] + pd['rawsize']]
    out = []
    for i in range(0, len(raw) - 11, 12):
        b, e, _u = struct.unpack_from('<III', raw, i)
        if b and e > b:
            out.append((b, e))
    out.sort()
    return out


def func_of(rva, funcs):
    """区间查找：返回包含 rva 的函数起点；找不到返回 None"""
    lo, hi = 0, len(funcs) - 1
    while lo <= hi:
        mid = (lo + hi) // 2
        b, e = funcs[mid]
        if rva < b:
            hi = mid - 1
        elif rva >= e:
            lo = mid + 1
        else:
            return b, e
    return None


def find_anchors(md, code, base_rva, kind, imm):
    """返回 [(锚点 RVA, 指令长度, 关联目标 RVA 或 None), ...]

    `关联目标` 只对 **direct 类**锚点有意义：那种锚点**本身就是对目标地址的引用**
    （如帧计数的 `inc byte [rip+X]`，X 就是 CALC_COUNT），不需要再去邻域找 lea。
    池基址类锚点则相反 —— 锚点只圈定「在遍历这个池的代码」，目标要从邻域里的
    `lea rbx,[rip+…]` 取。
    """
    hits = []
    for insn in md.disasm(code, IMAGE_BASE_HINT + base_rva):
        if insn.id == 0:
            continue
        rel = None
        ok = False
        if kind == 'add':
            if insn.mnemonic in ('add', 'sub') and len(insn.operands) == 2 \
                    and insn.operands[1].type == capstone.x86.X86_OP_IMM \
                    and insn.operands[1].imm == imm:
                ok = True
        elif kind == 'imul':
            if insn.mnemonic == 'imul' and len(insn.operands) == 3 \
                    and insn.operands[2].type == capstone.x86.X86_OP_IMM \
                    and insn.operands[2].imm == imm:
                ok = True
        elif kind == 'field':
            # 锚点 = 「谁访问了这个独特的结构偏移」（如 Player + 0x7730）
            for op in insn.operands:
                if op.type == capstone.x86.X86_OP_MEM and op.mem.disp == imm \
                        and op.mem.base != capstone.x86.X86_REG_RIP:
                    ok = True
                    break
        elif kind == 'inc_mem':
            # 锚点 = 「自增一个 rip 相对字节」（帧计数 CALC_COUNT 每帧 +1）——direct 类
            if insn.mnemonic == 'inc' and len(insn.operands) == 1:
                op = insn.operands[0]
                if op.type == capstone.x86.X86_OP_MEM \
                        and op.mem.base == capstone.x86.X86_REG_RIP \
                        and op.size == 1:
                    ok = True
                    rel = insn.address + insn.size + op.mem.disp - IMAGE_BASE_HINT
        if ok:
            hits.append((insn.address - IMAGE_BASE_HINT, insn.size, rel))
    return hits


def lea_targets_near(md, data, secs, anchor_rva, data_lo, data_hi, only_lea=True):
    """在锚点**之前**的小窗口里找 `rip → .data` 的引用

    方向和窗口都是刻意的。MEMMAP §7 记的激光池定位顺序是：

        lea rbx,[rip+…]        ← 池基址，就在循环开始前
        cmp byte [rbx+0x274],0 ← 槽是否空闲
        add rbx,0x298          ← 锚点
        cmp eax,0x40           ← 槽数上限

    基址在锚点**之前**几条指令内加载。先前开成前后各 0x180 时会捞进邻居函数的
    lea，实测 4 个目标全指向同一个热门全局（0xBFB2F8），完全失去区分度。

    `only_lea` 区分两类目标 —— 实测混用会让候选失稳：
      · **池基址**（True）：基址是 `lea rbx,[rip+…]` 一次性加载的。
        放开收 `mov` 会把噪声引进来（g_EnemyManager 的位移从 +8 恶化到 −0x33254）。
      · **自机坐标**（False）：它是 `movss xmm,[rip+X]` 直接读写，压根没有 lea。
    """
    lo = max(anchor_rva - LEA_BACK, 0x1000)
    off = rva_to_off(secs, lo)
    if off is None or anchor_rva <= lo:
        return []
    chunk = data[off:off + (anchor_rva - lo)]
    found = []
    for insn in md.disasm(chunk, IMAGE_BASE_HINT + lo):
        if insn.id == 0:
            continue
        if only_lea and insn.mnemonic != 'lea':
            continue
        for op in insn.operands:
            if op.type != capstone.x86.X86_OP_MEM \
                    or op.mem.base != capstone.x86.X86_REG_RIP:
                continue
            tgt = insn.address + insn.size + op.mem.disp - IMAGE_BASE_HINT
            if data_lo <= tgt < data_hi:
                found.append(tgt)
    return found


def probe_near(md, data, secs, anchor_rva, want_imm, field_off):
    """锚点邻域里找：特征立即数（加分）+ 槽内字段访问（必须）

    返回 (有特征立即数, 有字段访问)。
    """
    lo = max(anchor_rva - WINDOW, 0x1000)
    off = rva_to_off(secs, lo)
    if off is None:
        return False, False
    chunk = data[off:off + WINDOW * 2]
    has_want = has_field = False
    for insn in md.disasm(chunk, IMAGE_BASE_HINT + lo):
        if insn.id == 0:
            continue
        if not has_want and insn.mnemonic in ('cmp', 'test'):
            for op in insn.operands:
                if op.type == capstone.x86.X86_OP_IMM and op.imm == want_imm:
                    has_want = True
        if not has_field:
            for op in insn.operands:
                if op.type == capstone.x86.X86_OP_MEM and op.mem.disp == field_off \
                        and op.mem.base != capstone.x86.X86_REG_RIP:
                    has_field = True
        if has_want and has_field:
            break
    return has_want, has_field


def build_ref_index(md, code, base_rva):
    """一次反汇编，建立「被引用地址 → 引用它的指令 RVA 列表」索引

    比逐个目标扫一遍快得多（全量反汇编约 9 秒，十个目标就是一分半）。
    """
    idx = {}
    for insn in md.disasm(code, IMAGE_BASE_HINT + base_rva):
        if insn.id == 0:
            continue
        for op in insn.operands:
            if op.type != capstone.x86.X86_OP_MEM \
                    or op.mem.base != capstone.x86.X86_REG_RIP:
                continue
            tgt = insn.address + insn.size + op.mem.disp - IMAGE_BASE_HINT
            idx.setdefault(tgt, []).append(insn.address - IMAGE_BASE_HINT)
    return idx


def show_predictions(idx, pdata_shift):
    """外推验证：预测地址是否真的被代码引用

    不读内存也能粗筛 —— 正确的全局变量一定有指令访问它；错位的地址则无人问津。
    注意它只是**必要条件**：引用数 >0 不代表地址对（可能正落在两个变量之间的填充，
    或引用的是相邻变量），所以最终仍要 `verify_offsets.py` 读值确认。
    """
    print('=== 外推预测的引用检查（不读内存的粗筛）===')
    print(f'    预测 = 旧 RVA + {pdata_shift:+#x}')
    print(f'    {"目标":<18} {"旧 RVA":>10} {"预测 RVA":>10} {"引用数":>6}   判定')
    n_ok = 0
    for name, old in PREDICT_TARGETS:
        pred = old + pdata_shift
        n = len(idx.get(pred, []))
        n_ok += 1 if n else 0
        verdict = '✓ 被引用' if n else '✗ 无人引用 —— 外推值可疑'
        print(f'    {name:<18} 0x{old:08X} 0x{pred:08X} {n:>6}   {verdict}')
    print(f'\n    {n_ok}/{len(PREDICT_TARGETS)} 个预测地址在代码里被引用')
    print('    （引用数 0 的那几项说明 +0x4C224 对它们不成立，要单独找特征）\n')


def calibrate_shift(idx, old_rva, name, lo=0x30000, hi=0x60000, top=6,
                    hot=60):
    """标定某个旧地址的**实际位移**：在范围内扫，看哪个位移让预测地址被指令引用

    为什么需要：位移不是全局常量。`.data` 上界增长 `+0x4C224`，但那是**后段**的值；
    前段（`0x4F1E60~0x506AD0`）实测只有 `+0x43260` —— 拿后段的值去外推 `LIVES`/`POWER`
    会得到无人引用的地址（实测引用数 0）。逐段标定才靠谱。

    **必须排除热门全局**（`hot`）：引用数最多的地址对**每个**目标都排第一，
    于是所有目标都被吸到同一个地址上 —— 实测 `0x53CAD0`（引 138 次）一次钓走了
    `LIVES`/`BOMBS`/`RETRY`/`POWER`/`DEATHS`/`DYING`/`PLAYER_BASE`/`lasers[0]` 八个目标，
    `0xABAC30`（引 581 次）钓走了 `INPUT`/`GUI`。**可信的恰恰是引用数低的那些**：
    `items[0]` 以 27 次引用定出 `0xBFB2F8`，与独立特征候选完全一致。
    """
    hits = []
    for d in range(lo, hi + 1):
        n = len(idx.get(old_rva + d, []))
        if n and n <= hot:
            hits.append((n, d))
    if not hits:
        print(f'    {name:<18} 范围内（{lo:+#x}..{hi:+#x}）没有非热门的被引用位移')
        return None
    hits.sort(reverse=True)
    best_n, best_d = hits[0]
    print(f'    {name:<18} 最佳位移 {best_d:+#x} → 0x{old_rva + best_d:08X}'
          f'（引用 {best_n} 处）')
    if len(hits) > 1:
        print('       次优 ' + ', '.join(
            f'{d:+#x}({n})' for n, d in hits[1:top]))
    return best_d


def who_refs(idx, funcs, target_rva, top=8):
    """列出引用某地址的**函数**（用 .pdata 把引用点归到所属函数）

    用途：已知一个全局的新地址，反查操作它的函数。
    例 —— `INPUT` 的新地址 `0xABAE84`（68 处引用）→ 引用它的函数就是
    `Player::OnUpdate`（MEMMAP §4 记它「读输入位图 0xA6EC60」），
    找到它就能顺带定出相邻的 `Player::AddedCallback`。
    """
    refs = idx.get(target_rva, [])
    if not refs:
        print(f'    0x{target_rva:08X} 没有任何引用')
        return []
    by_func = {}
    for r in refs:
        hit = func_of(r, funcs)
        fb, fe = hit if hit else (r, r + 1)
        rec = by_func.setdefault(fb, [0, fe])
        rec[0] += 1
    ranked = sorted(by_func.items(), key=lambda kv: -kv[1][0])
    print(f'    0x{target_rva:08X} 共 {len(refs)} 处引用，分布在 {len(by_func)} 个函数里：')
    for fb, (cnt, fe) in ranked[:top]:
        print(f'      函数 0x{fb:08X}..0x{fe:08X}  引用 {cnt} 处')
    return ranked


# ── 把定位结果写回 offsets.py ──
# 目标名 → offsets.py 里的变量名。**不写回文件**，只生成到 _tmp 供人核对后拷贝：
# 候选未经验证（`verify_offsets.py` 要开游戏），自动覆盖源码风险太大。
OFFSET_VARS = {
    'g_BulletManager': 'BM_RVA',
    'g_EnemyManager': 'EM_RVA',
    'items[0]': 'IM_RVA',
    'PLAYER_X': 'PLAYER_X',
    'PLAYER_BASE': 'PLAYER_BASE',
    'CALC_COUNT': 'CALC_COUNT',
    'ITEM_NEXT_IDX': 'ITEM_NEXT_IDX',
}


def generate_offsets(results, src_path, out_path):
    """按定位结果生成新的 offsets.py（写 _tmp，**不覆盖原文件**）

    只替换 `VAR = 0x...` 里的数值，注释、结构、其它常量一律不动。
    同时打印逐项对照，方便人工核对后再拷贝过去。
    """
    import re
    text = open(src_path, encoding='utf-8').read()
    print('=== 生成 offsets.py（写入 _tmp，请核对后再覆盖）===')
    print(f'    {"变量":<20} {"旧值":>12} {"新值":>12}   依据')
    n = 0
    for name, var in OFFSET_VARS.items():
        new = results.get(name)
        if new is None:
            print(f'    {var:<20} {"—":>12} {"(未定位)":>12}   {name}')
            continue
        pat = re.compile(rf'^({var}\s*=\s*)(0x[0-9A-Fa-f]+)', re.M)
        m = pat.search(text)
        if not m:
            print(f'    {var:<20} {"未找到":>12} 0x{new:08X}   源码里没有该变量？')
            continue
        old_val = m.group(2)
        if int(old_val, 16) == new:
            print(f'    {var:<20} {old_val:>12} {old_val:>12}   已一致，跳过')
            continue
        text = pat.sub(lambda mm: f'{mm.group(1)}0x{new:08X}', text, count=1)
        print(f'    {var:<20} {old_val:>12} 0x{new:08X}   {name}')
        n += 1
    # 派生量随基址一起走，这里也要同步（它们由基址算出，不能各写一份）
    if 'PLAYER_X' in results:
        for var, delta in (('PLAYER_Y', 4), ('PLAYER_HITBOX', 28)):
            new = results['PLAYER_X'] + delta
            pat = re.compile(rf'^({var}\s*=\s*)(0x[0-9A-Fa-f]+)', re.M)
            m = pat.search(text)
            if m:
                old_val = m.group(2)
                text = pat.sub(lambda mm: f'{mm.group(1)}0x{new:08X}', text, count=1)
                print(f'    {var:<20} {old_val:>12} 0x{new:08X}   PLAYER_X {delta:+#x}（派生）')
                n += 1
    open(out_path, 'w', encoding='utf-8').write(text)
    print(f'\n    改了 {n} 处 → {out_path}')
    print('    ⚠ 这些都是**静态候选**：先用 verify_offsets.py 开游戏确认，再覆盖 offsets.py。')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--exe', default=None, help='th06nc.exe 路径（默认查 env.py）')
    ap.add_argument('--only', default=None, help='只跑名字含该子串的目标')
    ap.add_argument('--predict', action='store_true',
                    help='只做外推预测的引用检查（不读内存的粗筛）')
    ap.add_argument('--calibrate', action='store_true',
                    help='对前段标量变量逐段标定位移（外推值无人引用时用）')
    ap.add_argument('--refs', default=None,
                    help='反查：列出引用该 RVA 的函数（如 --refs 0xABAE84）')
    ap.add_argument('--apply', action='store_true',
                    help='按定位结果生成新的 offsets.py（写到 _tmp，不覆盖原文件）')
    args = ap.parse_args()

    exe = args.exe
    if exe is None:
        try:
            import env
            exe = os.path.join(env.game_dir(), 'th06nc.exe') \
                if hasattr(env, 'game_dir') else None
        except Exception:
            exe = None
    if not exe or not os.path.exists(exe):
        raise SystemExit('找不到 th06nc.exe，请用 --exe 指定')

    import hashlib
    data = open(exe, 'rb').read()
    md5 = hashlib.md5(data).hexdigest()
    secs = parse_sections(data)
    text = next(s for s in secs if s['name'] == '.text')
    data_sec = next(s for s in secs if s['name'] == '.data')
    data_lo, data_hi = data_sec['vaddr'], data_sec['vaddr'] + data_sec['vsize']
    code = data[text['rawptr']:text['rawptr'] + text['rawsize']]

    print(f'exe   {exe}')
    print(f'MD5   {md5}   （env.KNOWN_MD5 应对齐这个值）')
    print(f'.text RVA 0x{text["vaddr"]:X}  大小 {len(code):,} 字节')
    print(f'.data RVA 0x{data_lo:X}..0x{data_hi:X}\n')

    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
    md.detail = True
    md.skipdata = True

    funcs = parse_pdata(data, secs)
    func_hits = {}
    pdata_shift = data_hi - OLD_DATA_HI      # .data 上界增长量 = 整体位移基准
    print(f'.pdata 解析出 {len(funcs):,} 个函数边界')
    print(f'.data 增长量 {pdata_shift:+#x}（旧上界 0x{OLD_DATA_HI:X} → 新 0x{data_hi:X}）'
          f' —— 外推基准\n')

    if args.predict:
        show_predictions(build_ref_index(md, code, text['vaddr']), pdata_shift)
        return

    if args.calibrate:
        idx = build_ref_index(md, code, text['vaddr'])
        print('=== 逐段标定位移（引用数最多的位移 = 该变量的实际位移）===')
        for name, old in PREDICT_TARGETS:
            calibrate_shift(idx, old, name)
        print()
        return

    if args.refs:
        idx = build_ref_index(md, code, text['vaddr'])
        target = int(args.refs, 0)
        print(f'=== 反查：谁引用了 0x{target:08X} ===')
        who_refs(idx, funcs, target)
        print()
        return

    targets = [f for f in FEATURES
               if not args.only or args.only.lower() in f['name'].lower()]
    results = {}
    for feat in targets:
        kind, imm = feat['anchor']
        print(f'=== {feat["name"]}   旧 RVA 0x{feat["old"]:X} ===')
        print(f'    依据：{feat["why"]}')
        anchors = find_anchors(md, code, text['vaddr'], kind, imm)
        print(f'    锚点命中 {len(anchors)} 处')
        if not anchors:
            print('    ✗ 锚点未命中 —— 该特征在新构建里不成立，需人工核对 MEMMAP\n')
            continue
        # 只在「锚点邻域确实访问了槽内字段」的位置采纳候选 —— 那才是池遍历代码，
        # 不加这道门就会把 4 个目标全指向同一个热门全局（实测 0xBFB2F8）。
        field_off = feat['field']
        want_imm = feat['want'][1] if feat['want'] else None
        direct = feat['anchor'][0] == 'inc_mem'      # direct 类：锚点自带目标地址
        score = {}
        n_pool = 0
        for a_rva, _sz, rel in anchors:
            if direct:
                if rel is not None:
                    s = score.setdefault(rel, [1, 1, []])
                    s[2].append(a_rva)
                continue
            has_want, has_field = probe_near(md, data, secs, a_rva, want_imm, field_off)
            if field_off is not None and not has_field:
                continue
            n_pool += 1
            for t in lea_targets_near(md, data, secs, a_rva, data_lo, data_hi,
                                      only_lea=feat.get('ref', 'lea') == 'lea'):
                s = score.setdefault(t, [0, 0, []])
                s[0] += 1
                s[1] += 1 if has_want else 0
                s[2].append(a_rva)
        if field_off is not None:
            print(f'    同时访问槽内字段 +0x{field_off:X} 的锚点：{n_pool} 处')
        elif direct:
            print(f'    锚点自带目标地址：{len(score)} 个不同目标')
        else:
            print(f'    锚点全部采纳（无槽内字段条件）：{n_pool} 处')
        if not score:
            print('    ✗ 没有锚点同时满足「步长 + 槽内字段」—— 特征需人工核对 MEMMAP\n')
            continue
        ranked = sorted(score.items(), key=lambda kv: (-kv[1][1], -kv[1][0],
                                                       abs(kv[0] - feat['old'])))
        print(f'    {"候选 RVA":>12} {"锚点支持":>8} {"有槽数cmp":>9} {"位移":>10} '
              f'{"偏离参考":>10}')
        for tgt, sc_v in ranked[:6]:
            cnt, wok = sc_v[0], sc_v[1]
            mark = ' ★' if tgt == ranked[0][0] else ''
            shift = tgt - feat['old']
            dev = shift - SHIFT_REF
            flag = '' if abs(dev) <= SHIFT_TOL else '  ✗位移异常'
            # 独立证据：按 .data 增长量外推，与特征候选对比
            predict = feat['old'] + pdata_shift
            gap = abs(tgt - predict)
            pmark = f'  外推差 {gap:>5}' + (' ✓' if gap <= 0x400 else '')
            print(f'      0x{tgt:08X} {cnt:>8} {wok:>9} {shift:>+#10x} '
                  f'{pmark}{flag}{mark}')
        # 采纳「位移正常」的最高分候选（避开热门全局的误命中）
        adopted = None
        for tgt, _sc in ranked:
            if abs((tgt - feat['old']) - SHIFT_REF) <= SHIFT_TOL:
                results[feat['name']] = tgt
                adopted = tgt
                break
        # 锚点落在哪个函数里 —— 用 .pdata 精确回答，顺带给出该函数的新起点
        if adopted is not None and funcs:
            anchor_rvas = score[adopted][2]
            hit = func_of(anchor_rvas[0], funcs)
            if hit:
                fb, fe = hit
                print(f'    锚点函数：0x{fb:08X}..0x{fe:08X}'
                      f'（共 {len(anchor_rvas)} 个锚点落在这里）')
                func_hits.setdefault(fb, [0, 0])
                func_hits[fb][0] += 1
                func_hits[fb][1] = fe
        print()

    # ---- 派生关系交叉验证：MEMMAP 的硬约束，能抓出误命中 ----
    if results:
        print('=== 派生关系交叉验证 ===')
        for d in DERIVED:
            if d['src'] not in results:
                continue
            expect = results[d['src']] + d['delta']
            got = results.get(d['name'])
            if got is None:
                print(f'  {d["name"]:<26} = 0x{results[d["src"]]:08X} '
                      f'{d["delta"]:+#x} → 0x{expect:08X}   （未独立定位，直接采用）')
                results[d['name']] = expect
            elif got == expect:
                print(f'  {d["name"]:<26} 独立 0x{got:08X} = 派生 0x{expect:08X}  ✓ 一致')
            else:
                print(f'  {d["name"]:<26} 独立 0x{got:08X} ≠ 派生 0x{expect:08X}  '
                      f'✗ 至少一个误命中（依据：{d["why"]}）')
        print()

    # ---- 锚点函数汇总：这些函数起点就是 offsets.py 里 FN_* 的新值 ----
    if func_hits:
        print('=== 锚点所在函数（offsets.py 的 FN_* 从这里取）===')
        for fb, (cnt, fe) in sorted(func_hits.items(), key=lambda kv: -kv[1][0]):
            print(f'  0x{fb:08X}..0x{fe:08X}  被 {cnt} 个目标的锚点命中')
        print('\n  对照旧值：FN_ENEMY_SPAWN=0x360D0  FN_ITEM_SPAWN=0x426E0  '
              'FN_SPAWN_LASER=0x105E0\n'
              '            FN_BULLET_UPDATE=0x10870  FN_PLAYER_UPDATE=0x68820  '
              'FN_SPAWN_BULLET=0xF870')

    if args.apply:
        print()
        results.update({k: v for k, v in EXTRA_RESULTS.items() if k not in results})
        src = os.path.join(os.path.dirname(HERE), 'tools', 'offsets.py')
        out = os.path.join(os.path.dirname(HERE), '_tmp', 'offsets_new.py')
        generate_offsets(results, src, out)


if __name__ == '__main__':
    main()
