"""死因解剖 —— 读死亡黑匣子的 npz，用**几何真值**定位真凶并回答「为什么没躲开」

与 `watch_live.py` 的根本区别：这里判死用的是**游戏自己的碰撞几何**
（自机判定圆 vs 弹半径 / 激光线段 / 敌人 AABB），不是脚本的威胁模型 ——
所以能指出「脚本以为安全、其实必死」的漏项，这是脚本自己报不出来的东西。

四步结论：
  ① 真凶：首个几何相交帧的那一帧、那个实体（弹 / 激光 / 敌人），外加它的完整轨迹
  ② 脚本视角：判定帧之前脚本算的九向分数与最优间隙 —— 它是「看见了躲不掉」还是「压根没看见」
  ③ 反事实：从判定帧往前逐帧试九个方向，看最早从哪一帧起还有活路（= 脚本有没有反应时间）
  ④ 结论行：真凶类型 + 脚本是否预警 + 是否有活路

用法:
  py tools\\death_report.py _tmp\\death_20260927-120000.npz
  py tools\\death_report.py <npz> --back 90     # 真凶轨迹回溯 90 帧
  py tools\\death_report.py <npz> --scan 90     # 反事实从判定帧前 90 帧起扫
  py tools\\death_report.py --self-test         # 合成必死场景自测（不需要游戏）
"""
import argparse
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:                                    # Windows 控制台默认 GBK，中文会乱码
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

import dodge                                                          # noqa: E402
from offsets import (BULLET_STATE_DESPAWNING, BULLET_STATE_FIRED, E_BOSS,  # noqa: E402
                     FIELD_X0, FIELD_X1, FIELD_Y0, FIELD_Y1, L_PHASE_FIRE,
                     L_PHASE_WARN, PLAYER_R)
from read_bullets import BulletFrame                                  # noqa: E402
from read_enemies import shoot_countdown                              # noqa: E402
from death_recorder import GROUPS                                     # noqa: E402

VEC = {n: (dx, dy) for n, dx, dy, _ in dodge.DIRS}
DIR_NAMES = [n for n, _, _, _ in dodge.DIRS]
ARROW = {'none': '·', 'up': '↑', 'down': '↓', 'left': '←', 'right': '→',
         'ul': '↖', 'ur': '↗', 'dl': '↙', 'dr': '↘'}
KEYBIT = {0x01: '↑', 0x02: '↓', 0x04: '←', 0x08: '→', 0x10: 'Z', 0x20: 'X',
          0x100: 'Shift'}
EXF_NAME = ((0x001, '加速弹'), (0x010, '加速'), (0x020, '连续转向'),
            (0x040, '定时转向'), (0x080, '**朝自机转向**'), (0x100, '绝对角转向'),
            (0x400, 'X 反弹'), (0x800, 'Y 反弹'))


def keys_of(bits):
    if bits is None or np.isnan(bits):
        return '?'
    b = int(bits)
    return ''.join(v for k, v in KEYBIT.items() if b & k) or '（无）'


def exf_of(v):
    v = int(v)
    if not v:
        return '无'
    return ' | '.join(n for bit, n in EXF_NAME if v & bit) or f'0x{v:03X}'


class Dump:
    """一个黑匣子 npz → 逐帧世界视图"""

    def __init__(self, path):
        z = np.load(path, allow_pickle=False)
        self.path = path
        self.meta = json.loads(z['meta'].item() if z['meta'].shape == ()
                               else str(z['meta']))
        for k in z.files:
            if k != 'meta':
                setattr(self, k, z[k])
        self.T = int(self.px.shape[0])
        self.off = {}
        for g in GROUPS:
            n = getattr(self, g + '_n')
            self.off[g] = np.concatenate([[0], np.cumsum(n)]).astype(int)
        # 旧格式（采集端在线上算过决策）有 dsc/dbest；新格式没有 → 走离线复算
        if not hasattr(self, 'dsc'):
            self.dsc = np.full((self.T, len(DIR_NAMES)), np.nan, dtype=np.float32)
            self.dbest = np.array([''] * self.T, dtype='U12')

    def pool(self, t, g):
        a, b = self.off[g][t], self.off[g][t + 1]
        return {k: getattr(self, f'{g}_{k}')[a:b] for k in GROUPS[g]}

    def pos(self, t):
        return float(self.px[t]), float(self.py[t])


# ---- 离线复算脚本决策：世界取自黑匣子，参数可事后改 ----
def rebuild_bf(d, t):
    """黑匣子一帧 → BulletFrame（`dodge.plan` / `bullet_paths` 的入参）"""
    b = d.pool(t, 'b')
    return BulletFrame(
        b['slot'].astype(np.int64), b['x'], b['y'], b['vx'], b['vy'], b['r'],
        b['exf'].astype(np.int32), b['ang'], b['spd'], b['dcspd'],
        b['tm'].astype(np.int32), b['hold'].astype(np.int32),
        b['accx'], b['accy'], b['trot'],
        b['tint'].astype(np.int32), b['tnum'].astype(np.int32),
        b['tmax'].astype(np.int32), b['trate'], b['srate'],
        b['st'].astype(np.uint16))


def enemy_motion_of(d, t):
    """敌人逐帧位移（池里没有速度字段，只能按槽位回上一帧做差分）"""
    e, e0 = d.pool(t, 'e'), (d.pool(t - 1, 'e') if t > 0 else None)
    if e0 is None or not len(e['x']) or not len(e0['x']):
        return None
    vx = np.zeros(len(e['x']), dtype=np.float32)
    vy = np.zeros(len(e['x']), dtype=np.float32)
    for i, s in enumerate(e['slot']):
        j = np.nonzero(e0['slot'] == s)[0]
        if len(j):
            vx[i] = e['x'][i] - e0['x'][int(j[0])]
            vy[i] = e['y'][i] - e0['y'][int(j[0])]
    return vx, vy


def live_params(d=None):
    """复算该用哪套参数 —— 三级优先，**别用 `plan()` 的函数默认值**

    ① 黑匣子 meta 里的 `params`（记录时就在用的那一套，最准）
    ② 实机参数 = 出厂默认 + 控制台保存值（`dodge_params.json`）
    ③ 出厂默认

    为什么较真：`plan()` 的函数默认值是给调用方兜底的（comfort=1.0、edge_w=24.0、
    attack_w=0.0），与 GUI 跑的那套差出 horizon 20/30、attack 125/0 这种量级 ——
    拿它复算出来的「脚本视角」不是脚本当时算的分数（实测踩过）。
    """
    meta = getattr(d, 'meta', None) or {}
    p = dict(dodge.default_params())
    saved, _, _ = dodge.load_saved()
    p.update(saved)
    for k, v in (meta.get('params') or {}).items():
        if k in p:
            p[k] = v
    return p


def replan(d, t, horizon=None, safe=None, speed=None, params=None, cfg=None,
           px=None, py=None, prev='none', safe_armed=None):
    """离线复算第 t 帧的九向决策 → (best, scores)

    与躲避脚本走同一个 `dodge.plan()`、同一套派生量（敌人运动 / 发弹倒计时 / 预警矩形）、
    同一套参数（见 `live_params`）；差别只在于世界来自记录、参数可事后覆盖（`params`）
    —— 用来试「换个参数会不会活」。

    `px`/`py` 给「自机不在记录位置」的场合（闭环回放：世界取自记录，自机自己走）。
    `prev` 是上一帧**实际执行**的方向（惯性项吃它）：闭环回放必须自己维护，
    单帧复算保持 'none'（无状态）。
    """
    c = live_params(d) if cfg is None else dict(cfg)
    if params:
        c.update(params)
    hz = int(c['horizon'] if horizon is None else horizon)
    sf = float(c['safe'] if safe is None else safe)
    sp = float(c['speed'] if speed is None else speed)
    bf = rebuild_bf(d, t)
    e, lf = d.pool(t, 'e'), d.pool(t, 'l')
    enemy = (e['x'], e['y'], e['hw'], e['hh']) if len(e['x']) else None
    laser = ((lf['x'], lf['y'], lf['ang'], lf['st'], lf['en'], lf['ln'], lf['w'],
              lf['spd'], lf['vx'], lf['vy'], lf['om']) if len(lf['x']) else None)
    # 安全分认不认预警线跟随实机开关（`dodge.LASER_SAFE_ARMED`），保证复算 ≡ 实机；
    # `safe_armed` 显式覆盖，用来做「只认已开火」的对照试算
    use_armed = dodge.LASER_SAFE_ARMED if safe_armed is None else safe_armed
    keep = (lf['ph'] == L_PHASE_FIRE) if len(lf['x']) else None
    armed = tuple(a[keep] for a in laser) if (keep is not None and keep.any()) else None
    kw = dict(br=bf.brs, enemy=enemy, laser=laser,
              laser_armed=(armed if use_armed else dodge._AUTO), bf=bf,
              edge_w=c['edge'], prev=prev, inertia=c['inertia'],
              laser_rect=((lf['ph'] == L_PHASE_WARN) if len(lf['x']) else None),
              enemy_mv=enemy_motion_of(d, t),
              comfort=c['comfort'], attack_w=c['attack'], standoff=c['standoff'],
              margin_w=c['margin'], switch_margin=c['switch'], risk=c['risk'],
              warn_w=c['warn'], warn_dist=c['warn_dist'],
              clear_w=c['clear'], clear_r=c['clear_r'],
              center_w=c['center'], center_r=c['center_r'], center_y=c.get('center_y'),
              # 这三个不在 `default_params()` 里（是 plan 的调参口，不是界面滑条），
              # 所以必须给 `plan()` 的默认值而不是 None —— 传 None 会把软项静默关掉。
              laser_margin=c.get('laser_margin'),
              warn_rect_w=c.get('warn_rect_w', dodge.WARN_RECT_W))
    if 'warn_pool' in c:
        # 这里**不给默认值**：默认值放两处就会与 `plan()` 的默认脱节
        # （改 `warn_pool` 默认为关之后，这里写死的 True 让复算报出了改前的两倍效果）
        kw['warn_pool'] = c['warn_pool']
    if enemy is not None:
        kw['warn'] = shoot_countdown(e['siv'], e['stm'])
        boss = (e['fl2'].astype(np.int32) & E_BOSS) != 0
        kw['attack'] = dodge.pick_target(d.px[t] if px is None else px,
                                         d.py[t] if py is None else py, enemy, boss)
    if params:
        kw.update(params)
    return dodge.plan(d.px[t] if px is None else px, d.py[t] if py is None else py,
                      bf.xs, bf.ys, bf.vxs, bf.vys, sp, hz, sf, **kw)


def collisions(d, t, px, py, tol=0.0):
    """自机在 (px, py) 时与第 t 帧世界的几何相交 → [(类型, 序号, 净余量, 参数 dict)]

    净余量 < 0 = 已侵入判定圈。判据与游戏一致：
      弹   = min(grazeSize) × 0.5 + 自机半径        （仅 FIRED 阶段判死）
      激光 = 到线段表面距离 ≤ 自机半径              （仅 FIRE 阶段判死）
      敌人 = 到 AABB 表面距离 ≤ 自机半径
    `tol` 放宽判定半径（px）：实机复盘时最小余量常在 **+0.3 上下**就死了 ——
    自机半径 / grazeSize 的取值与游戏内部判定次序都有亚像素误差，
    严格 `<= 0` 会把真凶漏掉（见 `--tol`）。
    """
    out = []
    b = d.pool(t, 'b')
    if len(b['x']):
        m = b['st'] == BULLET_STATE_FIRED
        if m.any():
            dd = np.hypot(b['x'][m] - px, b['y'][m] - py) - (b['r'][m] + PLAYER_R)
            for j in np.nonzero(dd <= tol)[0]:
                i = np.nonzero(m)[0][j]
                out.append(('bullet', int(i), float(dd[j]), {
                    'slot': b['slot'][i], 'x': b['x'][i], 'y': b['y'][i],
                    'vx': b['vx'][i], 'vy': b['vy'][i], 'r': b['r'][i],
                    'exf': b['exf'][i], 'ang': b['ang'][i], 'spd': b['spd'][i],
                    'tm': b['tm'][i]}))
    lf = d.pool(t, 'l')
    if len(lf['x']):
        m = lf['ph'] == L_PHASE_FIRE
        if m.any():
            g = dodge.laser_gap(np.array([px], dtype=np.float32),
                                np.array([py], dtype=np.float32),
                                lf['x'][m], lf['y'][m], lf['ang'][m], lf['st'][m],
                                lf['en'][m], lf['ln'][m], lf['w'][m], lf['spd'][m],
                                lf['vx'][m], lf['vy'][m], lf['om'][m])
            dd = g - PLAYER_R
            for j in np.nonzero(dd <= tol)[0]:
                i = np.nonzero(m)[0][j]
                out.append(('laser', int(i), float(dd[j]), {
                    'slot': lf['slot'][i], 'x': lf['x'][i], 'y': lf['y'][i],
                    'ang': lf['ang'][i], 'w': lf['w'][i], 'st': lf['st'][i],
                    'en': lf['en'][i], 'ln': lf['ln'][i], 'vx': lf['vx'][i],
                    'vy': lf['vy'][i], 'om': lf['om'][i], 'tm': lf['tm'][i]}))
    en = d.pool(t, 'e')
    if len(en['x']):
        g = dodge.enemy_gap(np.array([px], dtype=np.float32),
                            np.array([py], dtype=np.float32),
                            en['x'], en['y'], en['hw'], en['hh'])
        dd = g - PLAYER_R
        for j in np.nonzero(dd <= tol)[0]:
            out.append(('enemy', int(j), float(dd[j]), {
                'slot': en['slot'][j], 'x': en['x'][j], 'y': en['y'][j],
                'hw': en['hw'][j], 'hh': en['hh'][j]}))
    out.sort(key=lambda r: r[2])
    return out


def closest(d, t, px=None, py=None):
    """第 t 帧最接近自机的威胁 → (净余量, 类型, 参数 dict)；场上没威胁返回 (nan, None, None)

    **不管进没进圈都给值** —— 实机复盘里最有用的一行常是「差 0.27px」：
    严格判据说没相交，可自机确实死了，那个 0.27 就是答案（判定常数有亚像素误差）。
    取一个足够大的 tol 让 `collisions` 把全部实体都交出来，再挑最小的那个。
    """
    if px is None:
        px, py = d.pos(t)
    hit = collisions(d, t, px, py, tol=1e9)
    if not hit:
        return float('nan'), None, None
    g, kind, p = min(((r[2], r[0], r[3]) for r in hit), key=lambda r: r[0])
    return g, kind, p


def first_hit(d, tol=0.0):
    """首个判定帧 → (帧号, 命中列表, (最接近帧, 最小余量))

    没有相交时 `t_hit` 为 None，但第三个返回值仍给出最接近的那一帧 ——
    实机复盘里差 0.3px 就是死，报告不能因为严格判据说「没相交」就闭嘴。
    """
    near_t, near_g = None, np.inf
    for t in range(d.T):
        hit = collisions(d, t, *d.pos(t), tol=tol)
        if hit:
            return t, hit, (near_t, near_g)
        g = closest(d, t)[0]
        if g == g and g < near_g:
            near_t, near_g = t, g
    return None, [], (near_t, near_g)


def hit_ahead(d, t, tol=0.0):
    """把第 t 帧的弹按原版机制**推进 1 帧**，看会不会撞上自机 → 命中列表

    为什么需要：**命中自机的弹在命中那一帧就转入消散阶段**，而记录的池里没有消散弹
    （`read_frame` 为避弹性能过滤掉了）。于是判定帧上真凶凭空消失，严格判定只会说
    「没相交」。但它在**上一帧**还在、速度也已知 —— 推进一帧正好落在命中位置上。
    推进用 `dodge.bullet_paths`（含加速弹 / 转向弹，与避弹同一套机制）。
    """
    bf = rebuild_bf(d, t)
    keep = bf.states != BULLET_STATE_DESPAWNING
    if not keep.all():
        bf = bf._replace(**{f: getattr(bf, f)[keep] for f in bf._fields})
    if not len(bf.xs):
        return []
    px, py = d.pos(t)
    fx, fy = dodge.bullet_paths(bf, 1, px, py)
    dd = np.hypot(fx[0] - px, fy[0] - py) - (bf.brs + PLAYER_R)
    out = []
    for j in np.nonzero(dd <= tol)[0]:
        out.append(('bullet', int(j), float(dd[j]), {
            'slot': bf.slots[j], 'x': bf.xs[j], 'y': bf.ys[j], 'vx': bf.vxs[j],
            'vy': bf.vys[j], 'r': bf.brs[j], 'exf': bf.exflags[j],
            'ang': bf.angles[j], 'spd': bf.speeds[j], 'tm': bf.timers[j],
            'ahead': True}))
    out.sort(key=lambda r: r[2])
    return out


def trace(d, t_hit, kind, slot, back):
    """真凶轨迹：从判定帧往前按槽位回溯（位置跳变 > 100px 视为槽被复用，停）"""
    rows = []
    for t in range(t_hit, max(-1, t_hit - back) - 1, -1):
        p = d.pool(t, 'b' if kind == 'bullet' else
                   ('l' if kind == 'laser' else 'e'))
        if not len(p['x']):
            if rows:
                break
            continue
        m = np.nonzero(p['slot'] == slot)[0]
        if not len(m):
            if rows:
                break
            continue
        i = int(m[0])
        x, y = float(p['x'][i]), float(p['y'][i])
        if rows and np.hypot(x - rows[-1][1], y - rows[-1][2]) > 100:
            break
        rows.append((t, x, y, p))
    rows.reverse()
    return [(t, x, y) for t, x, y, _ in rows], rows


def survive(d, i0, i1, name, speed, tol=0.0):
    """从 i0 帧起改走 name 方向，能否活到 i1 —— 世界用记录的真实历史（近似）

    **近似点（必须诚实标注）**：世界里瞄准自机的弹（`EXF_TURN_AIM`）与瞄准激光
    会因为自机换了位置而改道，所以「能活」在含瞄准弹的局面下是乐观估计。
    反过来，固定弹幕 / 已发射的激光不受影响，结论可靠。
    """
    dx, dy = VEC[name]
    x, y = d.pos(i0)
    for t in range(i0 + 1, i1 + 1):
        x = min(max(x + dx * speed, FIELD_X0), FIELD_X1)
        y = min(max(y + dy * speed, FIELD_Y0), FIELD_Y1)
        if collisions(d, t, x, y, tol):
            return False
    return True


def fill_scores(d, lo, hi, horizon=None, safe=None, speed=None, params=None):
    """把 [lo, hi] 区间的九向分数离线复算进 `d.dsc` / `d.dbest` → (成功帧数, 首个错误)

    已有记录的帧跳过（旧格式 npz 里采集端算过），没记录的就地补算 ——
    于是同一段世界可以用不同参数反复重算（`params`）。
    错误不吞：复算全失败时，报告里要能看见是字段缺了还是 plan 报的错。
    """
    n, err = 0, None
    for t in range(lo, hi + 1):
        if not np.all(np.isnan(d.dsc[t])):
            n += 1
            continue
        try:
            best, sc = replan(d, t, horizon=horizon, safe=safe, speed=speed,
                              params=params)
        except Exception as ex:
            if err is None:
                err = f'第 {t} 帧 {type(ex).__name__}: {ex}'
            continue
        d.dsc[t] = np.array([float(sc.get(k, 0.0)) for k in DIR_NAMES],
                            dtype=np.float32)
        d.dbest[t] = best
        n += 1
    return n, err


def report(d, back=60, scan=60, horizon=None, safe=None, speed=None,
           params=None, tol=0.5, auto_near=2.0, out=print):
    m = d.meta
    offline = bool(np.all(np.isnan(d.dsc)))
    c = live_params(d)
    if params:
        c.update(params)
    hz = c['horizon'] if horizon is None else horizon
    sf = c['safe'] if safe is None else safe
    sp = c['speed'] if speed is None else speed
    src = '黑匣子 meta' if (m.get('params') or {}).get('horizon') is not None \
        else '实机 dodge_params.json'
    out('=' * 78)
    out(f'死亡解剖  {os.path.basename(d.path)}')
    out(f'  触发：{m.get("why")}   落盘 {m.get("saved_at")}   '
        f'缓冲 {m.get("n_frames")} 帧（前 {m.get("pre")} + 后 {m.get("post")}）')
    ms = m.get('ms_avg')
    mst = f'{ms:.2f}ms' if isinstance(ms, (int, float)) and ms == ms else '内嵌未单独计时'
    out(f'  记录：单帧读取 {mst}  漏帧 {m.get("missed_total")}   '
        f'撕裂帧 {m.get("torn")}')
    out('  决策：' + (f'离线复算（世界取自记录；参数取自{src}）' if offline
                      else '采集端在线记录'))
    if offline:
        out(f'        参数 horizon={hz:g} safe={sf:g} speed={sp:g} '
            f'edge={c["edge"]:g} attack={c["attack"]:g} comfort={c["comfort"]:g} '
            f'clear={c["clear"]:g} center={c["center"]:g} risk={c["risk"]:g}')
    out(f'  注意：{m.get("note")}')
    out('=' * 78)

    if d.T < 3:
        out('! 帧数太少，无法分析')
        return None
    # 死亡信号帧：deaths 增加优先；符卡练习里重开符卡不结算，deaths 可能全程不增，
    # 那就退到「进入 DEAD」的第一帧 —— 否则它会落到缓冲末尾，差值毫无意义。
    dl = d.deaths
    up = np.nonzero(np.diff(dl) > 0)[0]
    if len(up):
        t_death = int(up[-1] + 1)
    else:
        dz = np.nonzero(d.pstate == 2)[0]
        t_death = int(dz[0]) if dz.size else d.T - 1

    # 四级找真凶，**顺序要紧**：
    #   ① 严格当帧相交（余量 ≤ 0）—— 无争议
    #   ② 「当帧已消散」的凶手：上一帧弹道外推一帧 → 侵入。**必须排在容差之前**：
    #      容差会把「擦过但没死」的帧（余量 +0.1）误判成判定帧，而真正杀死自机的
    #      那颗弹在命中帧已消散、只能靠外推抓（实测踩过：先容差后外推，报错了凶手）
    #   ③ 容差内的当帧擦边（余量 ≤ tol）
    #   ④ 都没有 → 最小余量帧推定
    t_hit, hits, (near_t, near_g) = first_hit(d, tol=0.0)
    inferred = ahead = False
    if t_hit is None:
        for t in range(max(0, t_death - 1), max(-1, t_death - 24), -1):
            h = hit_ahead(d, t, tol=0.0)
            if h:
                t_hit, hits, ahead = t, h, True
                break
    if t_hit is None:
        t_hit, hits, (near_t, near_g) = first_hit(d, tol=tol)
        inferred = t_hit is not None
    if t_hit is None and near_t is not None and near_g <= auto_near:
        t_hit, inferred = near_t, True
        hits = collisions(d, t_hit, *d.pos(t_hit), tol=near_g + 0.2)

    out('')
    if ahead:
        out('【一】真凶（几何真值层；命中自机的弹**当帧就转消散**，按上一帧外推一帧定位）')
        out('    消散弹不在记录的池里（避弹要滤掉它才不浪费移动）—— 真凶因此会在判定帧')
        out('    凭空消失，直接扫当帧永远只会说「没相交」。')
    elif inferred:
        out('【一】真凶（几何真值层；严格判定无相交，按最小余量推定）')
        out(f'  ★ 最接近的一刻 = 第 {near_t} 帧，净余量 **{near_g:+.2f}px** ——'
            f' 差这一点就进判定圈')
        out(f'    该量级落在判定常数误差内，按它算；要更严 `--tol 0`，'
            f'要更松 `--tol {near_g + 0.5:.1f}`。')
    else:
        out(f'【一】真凶（几何真值层：用游戏自己的碰撞判定扫全部帧，容差 {tol:g}px）')
    if t_hit is None:
        out(f'  ✗ 没有一帧相交，也没有任何威胁接近到 {auto_near:g}px 以内 ——')
        out('    致死威胁不在「弹 / 激光 / 敌人」这三类里，或发生在前 %d 帧之外'
            '（加大 --pre 重录）。' % m.get('pre', 0))
        out('    这一条本身就是结论：两边用的是同一套几何，谁都没找到凶手 → '
            '去查别的死法。')
        out('    下面仍列出脚本视角与反事实 —— 它们不依赖「有没有找到真凶」。')
    else:
        tag = '（外推定位）' if ahead else ('（推定）' if inferred else '')
        out(f'  判定帧 = 缓冲第 {t_hit} 帧{tag}；死亡信号帧 {t_death}，'
            f'相差 {t_death - t_hit} 帧 ≈ {(t_death - t_hit) / 60:.2f}s')
        if t_death - t_hit < 0:
            out('  ! 判定发生在死亡信号之后 —— 次序反常，检查是否混进了别的事件')
        elif t_death - t_hit > 15:
            out(f'  ! 判定与死亡信号差了 {t_death - t_hit} 帧（正常应 ≈8 帧 = respawnTimer）'
                f' —— 缓冲里可能混了不止一次事件，或中途漏帧')
        out(f'  自机 ({d.px[t_hit]:.1f},{d.py[t_hit]:.1f})  '
            f'{"⇩低速" if d.focus[t_hit] == 1 else "高速"}  '
            f'按键 {keys_of(d.key[t_hit])}')
    # 缓冲是否跨了场景重载（符卡重开 / 加载）：后半段其实是另一个场景，
    # 拿它算「当时有没有活路」会把两个场景混在一起。
    jumps = np.nonzero(((np.diff(d.calc.astype(int)) % 256) - 1) > 5)[0]
    if jumps.size and t_hit is not None:
        after = int((jumps > t_hit).sum())
        if after:
            out(f'  注：判定帧之后有 {after} 处场景重载（帧计数大跳）——'
                f' 那是死亡后的重开，不影响上面的判定')
    # 没找到真凶时也要有"参考帧"给后面两段用：取缓冲末尾（死亡就发生在那里）。
    # 不这么做的话，【二】【三】【四】会因为没有 t_hit 直接崩掉 ——
    # 而「找不到凶手」本身正是最需要看脚本视角的情形。
    no_hit = t_hit is None
    if no_hit:
        t_hit = d.T - 1
    for kind, i, gap, p in hits[:4]:
        cn = {'bullet': '子弹', 'laser': '激光', 'enemy': '敌人'}[kind]
        out(f'  ★ 真凶 = {cn}  槽 {int(p["slot"])}   侵入判定 {gap:+.2f}px（负 = 已进圈）')
        if kind == 'bullet':
            out(f'      pos=({p["x"]:.2f},{p["y"]:.2f})  v=({p["vx"]:.2f},{p["vy"]:.2f})  '
                f'r={p["r"]:.2f}  |v|={p["spd"]:.2f}  角度={np.degrees(p["ang"]):.1f}°  '
                f'计时={int(p["tm"])}')
            out(f'      运动标志：{exf_of(p["exf"])}')
            if p.get('ahead'):
                out(f'      ↑ 这是它在**上一帧**的位置；推进一帧后侵入 {gap:+.2f}px。'
                    f'命中帧它已转消散、不在记录里')
        elif kind == 'laser':
            out(f'      pos=({p["x"]:.1f},{p["y"]:.1f})  角度={np.degrees(p["ang"]):.1f}°  '
                f'半宽={p["w"] / 2:.1f}  线段=[{p["st"]:.1f},{p["en"]:.1f}]  长={p["ln"]:.1f}')
            out(f'      轴移=({p["vx"]:.2f},{p["vy"]:.2f})/帧  转角={np.degrees(p["om"]):.2f}°/帧  '
                f'阶段已过 {int(p["tm"])} 帧')
        else:
            out(f'      AABB {p["hw"]:.0f}×{p["hh"]:.0f} 中心 ({p["x"]:.1f},{p["y"]:.1f})')

    # ---- 真凶轨迹 ----
    # 没找到真凶时用空壳占位：`trace()` 找不到槽就返回空，下面的打印自然跳过
    kind, i, _, p = hits[0] if hits else ('none', -1, 0.0, {})
    slot = p.get('slot', -1)
    if kind != 'enemy':
        tr, rows = trace(d, t_hit, kind, slot, back)
        if len(tr) > 1:
            out('')
            out(f'  真凶轨迹（判死前 {len(tr)} 帧，槽 {int(slot)}）：')
            step = max(1, len(tr) // 8)
            picks = list(range(0, len(tr), step))
            if picks[-1] != len(tr) - 1:
                picks.append(len(tr) - 1)          # 判定帧本身必打
            for k in picks:
                t, x, y = tr[k]
                extra = ''
                if kind == 'bullet':
                    pp = d.pool(t, 'b')
                    j = np.nonzero(pp['slot'] == slot)[0]
                    if len(j):
                        j = int(j[0])
                        extra = (f'  v=({pp["vx"][j]:6.2f},{pp["vy"][j]:6.2f}) '
                                 f'|v|={pp["spd"][j]:5.2f} '
                                 f'角={np.degrees(pp["ang"][j]):6.1f}° '
                                 f'exF=0x{int(pp["exf"][j]):03X}')
                out(f'    第 {t:>4} 帧  ({x:7.2f},{y:7.2f})  距自机 '
                    f'{np.hypot(x - d.px[t], y - d.py[t]):6.2f}px{extra}')
            if kind == 'bullet':
                pp = d.pool(t_hit, 'b')
                j = np.nonzero(pp['slot'] == slot)[0]
                if len(j):
                    e0 = int(pp['exf'][int(j[0])])
                    if e0 & 0x1C0:
                        out('  ⚠ 真凶带**定时转向位**：脚本若只按当前速度外推，'
                            '转向那一刻整段落点作废。')

    # ---- 脚本视角 ----
    seen, gap_min = 'unknown', float('nan')
    out('')
    out('【二】脚本视角（判定帧之前，它算的九向分数）'
        + ('　※ 没找到判定帧，这里取缓冲末尾 30 帧' if no_hit else ''))
    lo = max(0, t_hit - 30)
    got, err = fill_scores(d, lo, t_hit, horizon=horizon, safe=safe, speed=speed,
                           params=params)
    if got == 0:
        out(f'  （九向分数全为空：{err or "世界字段缺失"}）')
    else:
        dirs = m.get('dirs') or DIR_NAMES
        out('     帧   自机位置        脚本选中  最优间隙   九向分数（越大越安全）')
        for t in range(lo, t_hit + 1):
            # 近 12 帧逐帧打（决策链关键段），更早的每 5 帧一行 —— 否则 30 行 × 9 个数刷屏
            if t < t_hit - 12 and (t - lo) % 5:
                continue
            sc = d.dsc[t]
            if np.all(np.isnan(sc)):
                continue
            order = ' '.join(f'{ARROW.get(n, n)}{sc[k]:6.1f}' for k, n in enumerate(dirs))
            mark = ' ←判死' if t == t_hit else ''
            out(f'  {t:>5}  ({d.px[t]:6.1f},{d.py[t]:6.1f})  '
                f'{ARROW.get(str(d.dbest[t]), str(d.dbest[t])):^6}  '
                f'{float(np.nanmax(sc)):7.2f}   {order}{mark}')
        g = np.nanmax(d.dsc[lo:t_hit + 1], axis=1)
        g = g[~np.isnan(g)]
        if len(g):
            warned = np.nonzero(g < 0)[0]
            if len(warned):
                out(f'  → 脚本在判定前第 {t_hit - lo - int(warned[0])} 帧就已在算「无路可走」'
                    f'（最优间隙转负）—— 它是**看见了但躲不掉**。')
                seen = 'warned'
            else:
                out(f'  → 全程最优间隙 ≥ {g.min():.1f}px（脚本认为一直有路）'
                    f' —— 它是**没看见这个威胁**：真凶属于模型的漏项。')
                seen = 'blind'
            gap_min = float(g.min())
        else:
            out('  → 九向分数全为空（plan 复算失败），看不了脚本视角。')
            seen, gap_min = 'unknown', float('nan')

    # ---- 反事实 ----
    # 只能从**判定帧之前**起步：判定帧当场已经撞上了，那一步不存在「还能活」。
    out('')
    out('【三】反事实（从判定帧之前逐帧起步，试九个方向还有没有活路）')
    out('  世界取记录的真实轨迹 + 假设自机走位；含瞄准弹时结论偏乐观（弹会改道跟人）')
    n_aim = int(np.sum((d.b_exf.astype(np.int32) & 0x80) != 0))
    if n_aim:
        out(f'  ⚠ 本段出现 {n_aim} 个「朝自机转向」弹样本 —— 按乐观读')
    i1 = min(d.T - 1, t_hit + 10)
    lo = max(0, t_hit - scan)
    best_i0 = None
    for i0 in range(lo, t_hit):                 # 从最早往近扫，第一个命中的就是最早活路
        al = [n for n in DIR_NAMES if survive(d, i0, i1, n, sp, tol)]
        if al:
            best_i0 = (i0, al)
            break
    if best_i0 is None:
        out(f'  ✗ 判定帧前这 {t_hit - lo} 帧里，任何一帧起步走任何方向都活不到判死 —— '
            f'**必死局面**（脚本无责）')
    else:
        i0, al = best_i0
        lead = t_hit - i0
        out(f'  最早有活路的一帧 = 判死前第 {lead} 帧（{lead / 60:.2f}s）：'
            + '、'.join(f'{ARROW[n]} {n}' for n in al))
        if i0 == 0 and t_hit > 0:
            out('  （已到缓冲开头，实际可能更早 —— 加大 --pre 重录再看）')
        elif i0 == lo:
            out(f'  （已到 --scan {scan} 帧的上限，实际可能更早 —— 加大 --scan 再看）')
        if lead >= 20:
            out(f'  → 有 {lead / 60:.2f}s 的反应时间，不是必死局 —— '
                f'是**当时的决策 / 执行没走到那条路**。')
        else:
            out(f'  → 只有 {lead / 60:.2f}s（{lead} 帧），接近脚本 `react` 延迟 —— '
                f'属于**突发**，不该算脚本的账。')
    # ---- 结论 ----
    out('')
    out('【四】结论')
    if not hits:
        out('  真凶：**未定位**（见【一】—— 三类威胁都没接近，去查非三类死法）')
        if seen == 'blind':
            out('  脚本：**没看见**任何威胁 —— 与「找不到真凶」一致，'
                '说明致死机制不在脚本的威胁模型里')
        elif seen == 'warned':
            out('  脚本：看见了（最优间隙已转负）—— 威胁确实在模型内，'
                '只是判定帧没落在缓冲里（加大 --pre 重录）')
        if best_i0 is None:
            out(f'  活路：以缓冲末尾为基准的前 {scan} 帧内都没有活路可试')
        return {'t_hit': None, 't_death': t_death, 'hits': [], 'earliest': best_i0,
                'seen': seen}
    kind0, _, _, p0 = hits[0]
    cn = {'bullet': '子弹', 'laser': '激光', 'enemy': '敌人'}[kind0]
    turny = kind0 == 'bullet' and (int(p0['exf']) & 0x1C0)
    out(f'  真凶：{cn}（槽 {int(p0["slot"])}）'
        + ('，**带定时转向** —— 只按当前速度外推会漏' if turny else '，直线运动'))
    if seen == 'blind':
        out(f'  脚本：**没看见**（判死前最优间隙一路 ≥ {gap_min:.1f}px）'
            f'→ 模型的漏项，该补威胁建模而不是调参')
    elif seen == 'warned':
        out('  脚本：看见了（最优间隙已转负）→ 躲不掉，查速度不足还是判据太乐观')
    else:
        out('  脚本：本次没记决策，补不上这一栏（重录去掉 --no-plan）')
    if best_i0 is None:
        out('  活路：无 —— 必死局面，不算脚本的账')
    else:
        i0, al = best_i0
        out(f'  活路：判死前 {t_hit - i0} 帧起走 '
            + '/'.join(ARROW[n] for n in al) + ' 可避 → 有反应时间，值得改')
    out('')
    out('  对号入座：')
    out('    · 没看见 + 直线弹  → 安全分漏了这类威胁（查 plan 的哪一项没进安全分）')
    out('    · 没看见 + 转向弹  → bullet_paths 的外推没覆盖该 exFlags 位')
    out('    · 看见了          → 速度 / 门槛问题（focus 半速跑不掉、comfort 门槛太松）')
    out('    · 必死局面        → 无解，留档即可')
    return {'t_hit': t_hit, 't_death': t_death, 'hits': hits, 'earliest': best_i0,
            'seen': seen}


# ---- 离线自测：合成一段「一颗弹直线撞死站着不动的自机」的黑匣子 ----
def self_test(out=print):
    """不需要游戏：造 npz → 跑完整分析管线 → 断言真凶定位正确"""
    import tempfile
    T = 120
    b = {'x': [], 'y': [], 'vx': [], 'vy': [], 'r': [], 'st': [], 'exf': [],
         'ang': [], 'spd': [], 'tm': [], 'slot': []}
    px = np.full(T, 192.0, dtype=np.float64)
    py = np.full(T, 300.0, dtype=np.float64)
    bx, by = 192.0, 120.0
    for t in range(T):
        by += 6.0                       # vy = 6px/帧 直线下落
        b['x'].append(bx), b['y'].append(by)
        b['vx'].append(0.0), b['vy'].append(6.0)
        b['r'].append(2.0), b['st'].append(float(BULLET_STATE_FIRED))
        b['exf'].append(0.0), b['ang'].append(float(np.pi / 2))
        b['spd'].append(6.0), b['tm'].append(float(t)), b['slot'].append(7.0)
    for k in GROUPS['b']:
        b.setdefault(k, [0.0] * T)      # 没构造的运动参数一律 0（= 直线弹）
    data = {
        'px': px, 'py': py,
        'pstate': np.full(T, 2.0), 'respawn': np.full(T, 8.0),
        'focus': np.zeros(T), 'key': np.zeros(T),
        'lives': np.concatenate([np.full(T - 3, 2.0), np.full(3, 1.0)]),
        'bombs': np.full(T, 3.0),
        'deaths': np.concatenate([np.zeros(T - 3), np.ones(3)]),
        'dying': np.zeros(T), 'power': np.full(T, 128.0), 'retry': np.zeros(T),
        'scene': np.full(T, 2.0), 'calc': np.arange(T) % 256.0,
        'torn': np.zeros(T), 'missed': np.zeros(T), 'ms': np.full(T, 1.0),
        'b_n': np.ones(T), 'l_n': np.zeros(T), 'e_n': np.zeros(T),
    }
    # 不写 dsc / dbest：自测要走**离线复算**那条路（那才是采集端现在的行为）
    for k, v in b.items():
        data['b_' + k] = np.array(v, dtype=np.float32)
    for k in GROUPS['l']:
        data['l_' + k] = np.zeros(0, dtype=np.float32)
    for k in GROUPS['e']:
        data['e_' + k] = np.zeros(0, dtype=np.float32)
    data['meta'] = np.array(json.dumps({
        'why': '自测合成', 'note': '合成场景：弹 vy=6 直线下落，自机静止', 'pre': T,
        'post': 0, 'n_frames': T, 'dirs': DIR_NAMES, 'missed_total': 0, 'torn': 0,
        'ms_avg': 1.0, 'saved_at': '自测'}, ensure_ascii=False))
    fd, path = tempfile.mkstemp(suffix='.npz')
    os.close(fd)
    np.savez_compressed(path, **data)
    out('### 自测：合成「弹 vy=6 直线下落撞静止自机」')
    d = Dump(path)
    res = report(d, out=out)
    ok = bool(res and res['hits'] and res['hits'][0][0] == 'bullet'
              and abs(res['hits'][0][3]['slot'] - 7) < 0.5)
    if ok:
        # 判定帧的定义就是「首次侵入」：本帧侵入、前一帧不侵入
        t = res['t_hit']
        cur = collisions(d, t, *d.pos(t))
        prev = collisions(d, t - 1, *d.pos(t - 1)) if t else []
        ok = bool(cur) and not prev and cur[0][2] <= 0
        out(f'  断言：判定帧 {t} 侵入={bool(cur)}  前一帧侵入={bool(prev)}'
            f'（须前者真、后者假）')
    os.unlink(path)
    out('')
    out(f'### 自测结果：{"通过 ✓" if ok else "失败 ✗"}')
    return 0 if ok else 1


def parse_params(items):
    """`--param key=value` → dict（值按 bool / int / float 自动转，转不动就留字符串）"""
    out = {}
    for it in items:
        k, sep, v = it.partition('=')
        if not sep:
            raise SystemExit(f'--param 要 key=value 形式：{it}')
        vl = v.strip().lower()
        if vl in ('true', 'false'):
            out[k.strip()] = (vl == 'true')
            continue
        for cast in (int, float):
            try:
                out[k.strip()] = cast(v)
                break
            except ValueError:
                continue
        else:
            out[k.strip()] = v
    return out


def main():
    ap = argparse.ArgumentParser(description='死亡黑匣子解剖（只读）')
    ap.add_argument('npz', nargs='?', help='death_recorder.py 落盘的 npz')
    ap.add_argument('--back', type=int, default=60, help='真凶轨迹回溯帧数')
    ap.add_argument('--scan', type=int, default=60, help='反事实扫描起点范围')
    ap.add_argument('--horizon', type=int, default=None,
                    help='决策复算的前瞻帧数（默认取实机参数；plan() 兜底值是 30）')
    ap.add_argument('--safe', type=float, default=None,
                    help='决策复算的安全分（默认取实机参数；plan() 兜底值是 2.0）')
    ap.add_argument('--speed', type=float, default=None,
                    help='决策复算的自机速度（默认取实机参数）')
    ap.add_argument('--param', action='append', default=[], metavar='K=V',
                    help='覆盖 plan() 的任意参数做试算，可重复（如 --param clear_w=0）')
    ap.add_argument('--tol', type=float, default=0.5,
                    help='判定容差(px)：实机复盘最小余量常在 +0.3 上下就死了，'
                         '严格 0 会漏掉真凶（默认 0.5）')
    ap.add_argument('--self-test', action='store_true', help='合成场景自测（不需要游戏）')
    args = ap.parse_args()
    if args.self_test:
        sys.exit(self_test())
    if not args.npz:
        ap.error('要么给 npz 路径，要么 --self-test')
    report(Dump(args.npz), back=args.back, scan=args.scan, horizon=args.horizon,
           safe=args.safe, speed=args.speed, tol=args.tol,
           params=parse_params(args.param) or None)


if __name__ == '__main__':
    main()
