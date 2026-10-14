"""run_session 的自动射击与进攻跟随回归检查（全部桩化，不碰游戏）

真机在关卡里才能验的路径：Z 是否只在关卡中按住、退出时是否松开、
进攻项是否真的把自机往目标方向推。

用法:
  py tools\\check_autofire.py
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dodge  # noqa: E402
import th06  # noqa: E402
from offsets import (PLAYER_STATE_ALIVE, PLAYER_STATE_DEAD,  # noqa: E402
                     PLAYER_STATE_INVULNERABLE)
from read_lasers import LaserFrame  # noqa: E402  # 桩 read_lasers 必须给同一结构
from read_bullets import empty_frame as empty_bullet_frame  # noqa: E402
from screen import screen_of as real_screen_of  # noqa: E402  # 残机 0 用例要钉真实判据

REAL_READ_FRAME = dodge.read_frame   # 各用例都会替换 dodge.read_frame，阶段过滤要钉真实实现

OK = True


class FakeWatch:
    """玩家让位的桩 —— 测试里绝不能真装键盘钩子（运行者自己的按键会污染结果）"""

    error = None

    def __init__(self):
        self.y = False            # 是否让位
        self.phys = set()         # 玩家物理按住的键
        self.started = False
        self.stopped = False

    def start(self, timeout=1.5):
        self.started = True
        return True

    def stop(self):
        self.stopped = True

    def yielding(self, idle=2.0):
        return self.y

    def physical(self):
        return set(self.phys)


def check(tag, cond, detail=''):
    global OK
    print(f'{"通过" if cond else "失败"} {tag}  {detail}')
    OK = OK and cond


def run(dry, stop_after=40):
    """跑一小段主循环，返回 (发出的按键序列, 每帧选中的方向)"""
    sent, dirs = [], []
    n = [0]
    fc = [0]

    th06.key_down = lambda k: sent.append(('down', k))
    th06.key_up = lambda k: sent.append(('up', k))
    th06.tap = lambda *a, **k: None
    dodge.HumanWatch = FakeWatch
    dodge.foreground = lambda: 0x1234
    dodge.set_foreground = lambda h: None
    dodge.read_lives = lambda p, mb: 3
    # 灵击判据也要桩掉：run_session 每帧都读它（存活态 = state 0 / respawn 8）
    dodge.read_player_state = lambda p, mb: dict(state=0, respawn=8, bomb_in_use=0, bombs=3)

    def fake_state(p, mb):
        fc[0] += 1
        return {'calc_count': fc[0], 'retry': 0, 'lives': 3, 'dying': 0}

    dodge.read_state = fake_state

    def fake_screen(st, running=None):
        return ('IN_GAME', '关卡进行中', True) if n[0] < stop_after else ('RESULT', '结算画面', False)

    dodge.screen_of = fake_screen

    def fake_frame(p, mb, use_enemy=True, use_laser=True, use_item=True, motion=None, enemy_motion=None):
        n[0] += 1
        return dict(bx=np.array([]), by=np.array([]), vx=np.array([]), vy=np.array([]),
                    px=100.0, py=400.0, n_enemy=1, n_laser=0, n_item=0, item=None,
                    warn=None, power=0.0, poc_val=0.0, poc_cx=None,
                    enemy=(np.array([300.0]), np.array([60.0]),   # 目标敌人本体
                           np.array([24.0]), np.array([24.0])),
                    laser=None, target=(300.0, 60.0))

    dodge.read_frame = fake_frame

    real_plan = dodge.plan

    def spy(px, py, *a, **kw):
        best, sc = real_plan(px, py, *a, **kw)
        dirs.append(best)
        return best, sc

    dodge.plan = spy
    cfg = dict(dry=dry, frames=0, period=0.001, unpause=False, restore=False,
               autofire=True, attack=20.0, standoff=48.0)
    dodge.run_session(None, None, 0x1234, cfg, log=lambda m: None)
    dodge.plan = real_plan
    dodge.read_frame = None
    return sent, dirs


sent, dirs = run(dry=False)
check('实跑：进入关卡后按住 Z 射击', ('down', 'z') in sent, f'发出 {sent}')
check('实跑：只在退出时松开 Z（不多次抖动）',
      sum(1 for s in sent if s == ('down', 'z')) == 1 and sent[-1] == ('up', 'z'),
      f'末次 = {sent[-1]}')
check('实跑：方向朝目标（右上）', all(d in ('ur', 'right') for d in dirs),
      f'方向序列 {sorted(set(dirs))}')

sent2, dirs2 = run(dry=True)
check('dry：一个键都不发', sent2 == [], f'发出 {sent2}')

cfg_off = dict(dry=False, frames=0, period=0.001, unpause=False, restore=False,
               autofire=False, attack=20.0, standoff=48.0)
fc2 = [0]


def fake_state2(p, mb):
    fc2[0] += 1
    return {'calc_count': fc2[0], 'retry': 0, 'lives': 3, 'dying': 0}


dodge.read_frame = lambda p, mb, ue=True, ul=True, ui=True, motion=None, enemy_motion=None: dict(
    bx=np.array([]), by=np.array([]), vx=np.array([]), vy=np.array([]),
    px=100.0, py=400.0, n_enemy=1, n_laser=0, n_item=0, item=None, warn=None,
    power=0.0, poc_val=0.0, poc_cx=None,
    laser=None, target=(300.0, 60.0),
    enemy=(np.array([300.0]), np.array([60.0]), np.array([24.0]), np.array([24.0])))
dodge.screen_of = lambda st, running=None: ('IN_GAME', '', True)
dodge.read_lives = lambda p, mb: 3
dodge.read_state = fake_state2
dodge.read_player_state = lambda p, mb: dict(state=0, respawn=8, bomb_in_use=0, bombs=3)
sent3 = []
th06.key_down = lambda k: sent3.append(('down', k))
th06.key_up = lambda k: sent3.append(('up', k))
dodge.run_session(None, None, 0x1234, dict(cfg_off, frames=20), log=lambda m: None)
check('关闭自动射击：不发 Z', not any(k == 'z' for _, k in sent3), f'发出 {sent3}')


# ---- 自动灵击（BombGuard 接进 run_session）----
# 「被打中」在真机上是撞运气的一次性事件，离线护栏钉住的是：什么时候该按 X、
# 什么时候绝不能按（没炸弹 / 无敌中 / 关掉了 / 窗口已过）。


def frame_alive():
    return dict(bx=np.array([]), by=np.array([]), vx=np.array([]), vy=np.array([]),
                px=100.0, py=400.0, n_enemy=0, n_laser=0, n_item=0, item=None,
                warn=None, power=0.0, poc_val=0.0, poc_cx=None,
                enemy=None, laser=None, target=None)


def frame_doomed():
    """九颗子弹正好压在自机九个方向外推 1 帧的落点上 —— 怎么走都重叠"""
    xs = np.array([100.0 + dx * 4.39 for _, dx, dy, _ in dodge.DIRS])
    ys = np.array([400.0 + dy * 4.39 for _, dx, dy, _ in dodge.DIRS])
    return dict(bx=xs, by=ys, vx=np.zeros(9), vy=np.zeros(9),
                px=100.0, py=400.0, n_enemy=0, n_laser=0, n_item=0, item=None,
                warn=None, power=0.0, poc_val=0.0, poc_cx=None,
                enemy=None, laser=None, target=None)


def run_bomb(ps, frame, frames=6, code='IN_GAME', extra=None, switch_after=None):
    """把玩家状态与场面都桩掉，跑几帧 run_session，返回发出的按键序列

    `switch_after`：先跑几帧 IN_GAME 再切到 `code` —— 真实的「被打中」发生在主循环
    运行期间，而不是开场预备接管时（那时窗口早过了）。
    """
    sent, fc = [], [0]
    th06.key_down = lambda k: sent.append(('down', k))
    th06.key_up = lambda k: sent.append(('up', k))
    th06.tap = lambda *a, **k: None
    dodge.HumanWatch = FakeWatch
    dodge.foreground = lambda: 0x1234
    dodge.set_foreground = lambda h: None
    dodge.read_lives = lambda p, mb: 3

    def fake_state(p, mb):
        fc[0] += 1
        return {'calc_count': fc[0], 'retry': 0, 'lives': 3,
                'dying': 1 if ps['state'] == PLAYER_STATE_DEAD else 0}

    def fake_screen(st, running=None):
        if switch_after is not None and fc[0] >= switch_after:
            return (code, '桩', False)
        return ('IN_GAME', '桩', True)

    dodge.read_state = fake_state
    dodge.screen_of = fake_screen
    dodge.read_frame = lambda p, mb, ue=True, ul=True, ui=True, motion=None, enemy_motion=None: frame()
    dodge.read_player_state = lambda p, mb: dict(ps)
    cfg = dict(dry=False, frames=frames, period=0.001, unpause=False, restore=False,
               autofire=False, attack=0.0, bomb=True)
    cfg.update(extra or {})
    dodge.run_session(None, None, 0x1234, cfg, log=lambda m: None)
    return sent


ALIVE_PS = dict(state=PLAYER_STATE_ALIVE, respawn=8, bomb_in_use=0, bombs=3)

s = run_bomb(dict(state=PLAYER_STATE_DEAD, respawn=7, bomb_in_use=0, bombs=3),
             frame_alive, code='DYING', switch_after=2)
check('灵击·死亡窗口内按 X 抢救', ('down', 'x') in s, f'发出 {s}')
check('灵击·按下沿只发一次（跨帧按住，不是同帧 down+up）',
      s.count(('down', 'x')) == 1, f'发出 {s}')

s = run_bomb(dict(state=PLAYER_STATE_DEAD, respawn=7, bomb_in_use=0, bombs=0),
             frame_alive, code='DYING', switch_after=2)
check('灵击·没炸弹时不按 X', not any(k == 'x' for _, k in s), f'发出 {s}')

s = run_bomb(dict(state=PLAYER_STATE_DEAD, respawn=0, bomb_in_use=0, bombs=3),
             frame_alive, code='DYING', switch_after=2)
check('灵击·窗口已过（respawn=0）不按 X，直接退出',
      not any(k == 'x' for _, k in s), f'发出 {s}')

s = run_bomb(ALIVE_PS, frame_doomed)
check('灵击·九向必死时提前炸', ('down', 'x') in s, f'发出 {s}')

s = run_bomb(dict(state=PLAYER_STATE_INVULNERABLE, respawn=8, bomb_in_use=0, bombs=3),
             frame_doomed)
check('灵击·无敌中不预判炸（本来就死不了，炸了是浪费）',
      not any(k == 'x' for _, k in s), f'发出 {s}')

s = run_bomb(dict(state=PLAYER_STATE_DEAD, respawn=7, bomb_in_use=0, bombs=3),
             frame_alive, code='DYING', switch_after=2, extra=dict(bomb=False))
check('灵击·关掉后一个 X 都不发', not any(k == 'x' for _, k in s), f'发出 {s}')

s = run_bomb(ALIVE_PS, frame_alive)
check('灵击·安全时不乱炸', not any(k == 'x' for _, k in s), f'发出 {s}')


# ---- 激光阶段：预警阶段没有伤害判定，不许触发必死预判 ----
# 依据（反汇编 `BulletManager__OnUpdate` 的激光循环）：只有 flags == 1（发射）会调
# `Player__CalcLaserHitbox`，预警 / 消散阶段打不到人。旧版把**所有**活跃激光都喂给必死判据 ——
# 于是激光预警线刚出、自机恰好在线上，就先白扔一颗炸弹。
# 字段与阶段语义 → `项目文档/02-内存布局/相关-游戏内存映射-MEMMAP.md` §7。

def frame_laser(armed):
    """一条宽激光压在自机身上：九个方向外推 1 帧都还在它里面

    几何 = `pos + 方向 × [start, end]`（这里是 pos=(100,384) 向右 0→100px、宽 100）。
    """
    lz = (np.array([100.0]), np.array([384.0]), np.array([0.0]),
          np.array([0.0]), np.array([100.0]), np.array([100.0]),
          np.array([100.0]), np.array([0.0]))
    f = frame_alive()
    f['laser'] = lz
    f['laser_armed'] = lz if armed else None
    return f


s = run_bomb(ALIVE_PS, lambda: frame_laser(armed=False))
check('激光·还在预警（无判定）时不预判炸', not any(k == 'x' for _, k in s), f'发出 {s}')
s = run_bomb(ALIVE_PS, lambda: frame_laser(armed=True))
check('激光·真正发射（有判定）时才预判炸', ('down', 'x') in s, f'发出 {s}')


def lasers_of(phases):
    """桩掉内存读取，单验 `read_frame` 的阶段过滤：armed 只留 L_PHASE_FIRE"""
    n = len(phases)
    idx = np.arange(n, dtype=np.float32)      # 拿下标当 x：留下来的具体是哪几条一眼可见
    z = np.zeros(n, dtype=np.float32)
    dodge.read_bullet_frame = lambda p, mb: empty_bullet_frame()
    dodge.read_player = lambda p, mb: (100.0, 400.0)
    dodge.read_enemies = lambda p, mb: None
    dodge.read_items = lambda p, mb: None
    dodge.read_lasers = lambda p, mb: LaserFrame(
        np.arange(n), idx, z, z, z,                      # slots / xs / ys / angles / widths
        z, np.full(n, 200.0, dtype=np.float32),          # starts / ends（起点到 200px 处）
        np.full(n, 200.0, dtype=np.float32), z,          # lens / speeds
        np.array(phases, dtype=np.int32),
        np.zeros(n, dtype=np.int32),
        np.full(n, 60, dtype=np.int32))
    return REAL_READ_FRAME(None, None)


w = lasers_of([0, 1, 2, 3])
check('激光阶段·躲避仍纳入全部阶段（预警线也要让开）',
      w['laser'] is not None and len(w['laser'][0]) == 4,
      f'激光集 {None if w["laser"] is None else len(w["laser"][0])} 条')
check('激光阶段·必死判据只留发射中的那条',
      w['laser_armed'] is not None and list(w['laser_armed'][0]) == [1.0],
      f'保留 {None if w["laser_armed"] is None else list(w["laser_armed"][0])}')
w = lasers_of([0, 2])
check('激光阶段·全是预警 / 消散时必死判据看不到激光', w['laser_armed'] is None,
      f'{w["laser_armed"]}')


# ---- 智能道具线（ItemLineTrip 接进 run_session）----
# 满火力 + 可转化价值 ≥ poc_min → 主循环给 plan() 传冲线目标（y=POC_TARGET_Y）、
# 方向朝上；火力不满则全程不传（收集线只在满火力时存在，冲了也白冲）。

def run_poc(power, frames=10):
    """桩一个「满屏普通掉落」的场面跑主循环，返回 (plan 输出方向序列, 收到的 poc 序列)"""
    dirs, pocs = [], []
    fc = [0]
    th06.key_down = lambda k: None
    th06.key_up = lambda k: None
    th06.tap = lambda *a, **k: None
    dodge.HumanWatch = FakeWatch
    dodge.foreground = lambda: 0x1234
    dodge.set_foreground = lambda h: None
    dodge.read_lives = lambda p, mb: 3
    dodge.read_player_state = lambda p, mb: dict(ALIVE_PS)

    def fake_state(p, mb):
        fc[0] += 1
        return {'calc_count': fc[0], 'retry': 0, 'lives': 3, 'dying': 0}

    dodge.read_state = fake_state
    dodge.screen_of = lambda st, running=None: ('IN_GAME', '桩', True)
    it = (np.array([160.0, 176.0, 208.0, 224.0]), np.array([350.0] * 4),
          np.ones(4, dtype=np.float32), np.full(4, 3.0, dtype=np.float32),
          np.zeros(4, dtype=np.float32))
    dodge.read_frame = lambda p, mb, ue=True, ul=True, ui=True, motion=None, enemy_motion=None: dict(
        frame_alive(), px=192.0, n_item=4, item=it,
        power=power, poc_val=4.0, poc_cx=192.0)
    real_plan = dodge.plan

    def spy(px, py, *a, **kw):
        pocs.append(kw.get('poc'))
        best, sc = real_plan(px, py, *a, **kw)
        dirs.append(best)
        return best, sc

    dodge.plan = spy
    dodge.run_session(None, None, 0x1234,
                      dict(dry=False, frames=frames, period=0.001, unpause=False,
                           restore=False, autofire=False), log=lambda m: None)
    dodge.plan = real_plan
    return dirs, pocs


dirs_p, pocs_p = run_poc(128)
check('道具线·满火力触发并传冲线目标',
      all(p is not None and abs(p[1] - dodge.POC_TARGET_Y) < 1e-6 for p in pocs_p),
      f'poc 序列前 3 帧 {pocs_p[:3]}')
check('道具线·方向朝上', all(d in ('up', 'ul', 'ur') for d in dirs_p),
      f'方向序列 {sorted(set(dirs_p))}')
dirs_q, pocs_q = run_poc(100)
check('道具线·火力不满全程不冲', all(p is None for p in pocs_q),
      f'poc 序列前 3 帧 {pocs_q[:3]}')

# ---- 自动进下一关（关卡过渡不退出 + 开场对话轻点 Z）----
# 真机上要打穿一关才能验一次过渡、对话又只在关卡开头出现，所以用桩化的画面序列钉住：
# 哪个画面绝不能退出、什么条件下才允许轻点 Z、有威胁源时绝不许轻点。

def _stub_common(watch):
    dodge.HumanWatch = lambda: watch
    dodge.foreground = lambda: 0x1234
    dodge.set_foreground = lambda h: None
    dodge.read_lives = lambda p, mb: 3
    dodge.read_player_state = lambda p, mb: dict(state=0, respawn=8, bomb_in_use=0, bombs=3)


def run_flow(codes, advance=True, threats=False):
    """按给定画面序列跑主循环；返回 (帧数, 结束原因, 发送序列, 轻点序列)

    `codes` 第 k 项 = 主循环第 k 帧看到的画面；开场检查那一次另算（恒为 IN_GAME）。
    """
    seq = ['IN_GAME'] + list(codes)
    sent, tapped, idx = [], [], [0]
    _stub_common(FakeWatch())
    th06.key_down = lambda k: sent.append(('down', k))
    th06.key_up = lambda k: sent.append(('up', k))
    th06.tap = lambda k, ms=60: tapped.append(k)

    def fake_state(p, mb):
        return {'calc_count': idx[0] + 1, 'retry': 0, 'lives': 3, 'dying': 0}

    def fake_screen(st, running=None):
        c = seq[min(idx[0], len(seq) - 1)]
        idx[0] += 1
        return (c, '桩', c == 'IN_GAME')

    dodge.read_state = fake_state
    dodge.screen_of = fake_screen

    def fake_frame(p, mb, ue=True, ul=True, ui=True, motion=None, enemy_motion=None):
        bx = np.array([100.0]) if threats else np.array([])
        return dict(bx=bx, by=bx, vx=np.zeros(len(bx)), vy=np.zeros(len(bx)),
                    px=100.0, py=400.0, n_enemy=0, n_laser=0, n_item=0, item=None,
                    warn=None, power=0.0, poc_val=0.0, poc_cx=None,
                    enemy=None, laser=None, target=None)

    dodge.read_frame = fake_frame
    frames, _, reason = dodge.run_session(
        None, None, 0x1234,
        dict(dry=False, frames=len(codes), period=0.001, unpause=False, restore=False,
             autofire=False, advance=advance), log=lambda m: None)
    return frames, reason, sent, tapped


frames, reason, sent, tapped = run_flow(['IN_GAME'] * 2 + ['STAGE_SWITCH'] * 3 + ['IN_GAME'] * 2)
check('进关·关卡过渡不退出（旧版在这里就停了）', reason == '到达帧数上限', f'结束原因 {reason}')
check('进关·过渡期间不发任何按键（过场不需要按键）', sent == [], f'发出 {sent}')
check('进关·过渡后回到关卡继续跑满', frames == 7, f'跑了 {frames} 帧')

frames, reason, sent, tapped = run_flow(['IN_GAME', 'STAGE_SWITCH', 'STAGE_SWITCH'], advance=False)
check('进关·关掉「自动进下一关」后仍按旧行为退出', reason == '画面 STAGE_SWITCH',
      f'结束原因 {reason}')

frames, reason, sent, tapped = run_flow(['IN_GAME'] * 4)
check('对话推进·无威胁源时轻点 Z（按住连射推不动对话）', tapped == ['z'], f'轻点 {tapped}')
frames, reason, sent, tapped = run_flow(['IN_GAME'] * 4, threats=True)
check('对话推进·有威胁源时不轻点（那会松开正在连射的 Z）', tapped == [], f'轻点 {tapped}')


# ---- 残机 0 = 最后一条命，继续避弹（旧版在这里直接退出）----
# 残机是**备用命**：0 只表示没有后备，这一局还在打。旧版把 lives==0 当退出条件，
# 于是每到最后一条命脚本就停手站桩送死 —— 这里同时钉住 screen.py 的判据与 dodge.py 的分支。

ALIVE0 = dict(lives=0, dying=0, retry=0)
CONTINUE_ST = dict(lives=0, dying=0, retry=0xFF)


def st_of(**kw):
    s = dict(cur_state=2, wanted_state=2, calc_count=0, lives=3, bombs=3, retry=0,
             deaths=0, dying=0)
    s.update(kw)
    return s


c, _, ok = real_screen_of(st_of(lives=0))
check('残机 0·判据：仍可发方向键（旧版在这里退出）', c == 'NO_LIVES' and ok is True, f'{c}/{ok}')
c, _, ok = real_screen_of(st_of(lives=0, dying=1))
check('残机 0·判据：死亡中仍判 DYING —— 死亡炸弹窗口不被吃掉', c == 'DYING', f'{c}')
c, _, ok = real_screen_of(st_of(lives=0, retry=0xFF))
check('残机 0·判据：Continue 画面仍禁止按键', c == 'CONTINUE' and ok is False, f'{c}/{ok}')
c, _, ok = real_screen_of(st_of(lives=0), running=False)
check('残机 0·判据：暂停优先（暂停态不发键）', c == 'PAUSED', f'{c}')
c, _, ok = real_screen_of(st_of(lives=3))
check('残机 3·判据：原样 IN_GAME', c == 'IN_GAME' and ok is True, f'{c}/{ok}')


def frame_target():
    f = frame_alive()
    f.update(n_enemy=1, target=(300.0, 60.0),
             enemy=(np.array([300.0]), np.array([60.0]),
                    np.array([24.0]), np.array([24.0])))
    return f


def run_lives0(seq, play=None, frame=None, keep_going=True):
    """残机 0 的主循环：screen_of 用**真实**判据，read_state 只喂内存值

    `seq` 第 k 项 = 第 k 次 read_state 看到的 {lives, dying, retry}（读完重复最后一项）；
    `play` 给 dict 则每帧相同，给 list 则与 seq 同下标（用来模拟「运行中被打中」）。
    返回 (结束帧数, 结束原因, [(状态下标, 动作, 键)])。
    """
    sent, idx, cur = [], [0], [0]
    _stub_common(FakeWatch())
    th06.key_down = lambda k: sent.append((cur[0], 'down', k))
    th06.key_up = lambda k: sent.append((cur[0], 'up', k))
    th06.tap = lambda *a, **k: None
    dodge.screen_of = real_screen_of
    alive_ps = dict(state=PLAYER_STATE_ALIVE, respawn=8, bomb_in_use=0, bombs=3)

    def ps_of():
        if isinstance(play, list):
            return dict(play[min(cur[0], len(play) - 1)])
        return dict(play or alive_ps)

    dodge.read_player_state = lambda p, mb: ps_of()

    def fake_state(p, mb):
        i = min(idx[0], len(seq) - 1)
        idx[0] += 1
        cur[0] = i
        return dict(cur_state=2, calc_count=idx[0], **seq[i])   # 关卡中（curState=2）

    dodge.read_state = fake_state
    dodge.read_lives = lambda p, mb: seq[cur[0]]['lives']
    dodge.read_frame = lambda p, mb, ue=True, ul=True, ui=True, motion=None, enemy_motion=None: (frame or frame_alive)()
    n, _, reason = dodge.run_session(
        None, None, 0x1234,
        dict(dry=False, frames=len(seq), period=0.001, unpause=False, restore=False,
             autofire=False, attack=20.0, keep_going_on_death=keep_going),
        log=lambda m: None)
    dodge.screen_of = real_screen_of      # 留在真实判据上，别把桩漏给后面的用例
    return n, reason, sent


n, reason, sent = run_lives0([ALIVE0] * 8, frame=frame_target)
check('残机 0·关卡中不退出、照常发方向键',
      reason == '到达帧数上限' and n == 8
      and any(a == 'down' and k in ('right', 'ur') for _, a, k in sent),
      f'{n} 帧 / {reason} / 前几次 {sent[:4]}')

# 「被打中」得发生在主循环里：开场就是 DYING 时启动检查本就该拒绝接管（那是另一条路径）
ALIVE_PS0 = dict(state=PLAYER_STATE_ALIVE, respawn=8, bomb_in_use=0, bombs=3)
DYING_ST = dict(lives=0, dying=1, retry=0)

n, reason, sent = run_lives0([ALIVE0] * 2 + [DYING_ST] * 4,
                             play=[ALIVE_PS0, ALIVE_PS0] + [dict(
                                 state=PLAYER_STATE_DEAD, respawn=7,
                                 bomb_in_use=0, bombs=3)] * 4)
check('残机 0·被打中照走死亡炸弹抢救（窗口没被残机 0 吃掉）',
      reason == '到达帧数上限' and any(a == 'down' and k == 'x' for _, a, k in sent),
      f'{n} 帧 / {reason} / {sent}')

n, reason, sent = run_lives0([ALIVE0] * 2 + [DYING_ST] * 4,
                             play=[ALIVE_PS0, ALIVE_PS0] + [dict(
                                 state=PLAYER_STATE_DEAD, respawn=0,
                                 bomb_in_use=0, bombs=3)] * 4)
check('残机 0·死亡结算完就退出（赶在 Continue 画面之前松键，也不再按 X）',
      reason == '画面 DYING' and not any(a == 'down' and k == 'x' for _, a, k in sent),
      f'{n} 帧 / {reason} / {sent}')

n, reason, sent = run_lives0([ALIVE0] * 3 + [CONTINUE_ST] * 3, frame=frame_target)
check('残机 0·进 Continue 画面立即退出', reason == '画面 CONTINUE', f'{n} 帧 / {reason}')
check('残机 0·Continue 期间一个键都不发（方向键会把「是」拨到「否」）',
      not any(i >= 3 and a == 'down' for i, a, _ in sent), f'{sent}')

n, reason, sent = run_lives0([dict(lives=1, dying=0, retry=0)] * 2 + [ALIVE0] * 4,
                             frame=frame_target, keep_going=False)
check('掉命即退·关掉「掉命后继续」时仍按旧行为（掉到 0 那次也不接）',
      reason == '掉命', f'{n} 帧 / {reason}')


# ---- 玩家让位（人一上手，脚本停手）----

def run_yield(yield_from=None, yield_to=None, phys=(), enabled=True):
    """让位时序：第 yield_from 帧起让位、第 yield_to 帧起恢复

    返回 (带帧号的发送序列, watch —— 用它看钩子有没有被装/卸)。
    `phys` = 玩家此刻物理按住的键（让位时不许抬它们）。
    """
    sent, idx, w = [], [0], FakeWatch()
    _stub_common(w)
    th06.key_down = lambda k: sent.append((idx[0], 'down', k))
    th06.key_up = lambda k: sent.append((idx[0], 'up', k))
    th06.tap = lambda *a, **k: None

    def fake_state(p, mb):
        return {'calc_count': idx[0] + 1, 'retry': 0, 'lives': 3, 'dying': 0}

    def fake_screen(st, running=None):
        idx[0] += 1
        return ('IN_GAME', '桩', True)

    dodge.read_state = fake_state
    dodge.screen_of = fake_screen

    def fake_frame(p, mb, ue=True, ul=True, ui=True, motion=None, enemy_motion=None):
        w.y = (yield_from is not None and yield_from <= idx[0]
               and (yield_to is None or idx[0] < yield_to))
        w.phys = set(phys) if w.y else set()
        return dict(bx=np.array([]), by=np.array([]), vx=np.array([]), vy=np.array([]),
                    px=100.0, py=400.0, n_enemy=1, n_laser=0, n_item=0, item=None,
                    warn=None, power=0.0, poc_val=0.0, poc_cx=None,
                    enemy=(np.array([300.0]), np.array([60.0]),
                           np.array([24.0]), np.array([24.0])),
                    laser=None, target=(300.0, 60.0))

    dodge.read_frame = fake_frame
    dodge.run_session(None, None, 0x1234,
                      dict(dry=False, frames=8, period=0.001, unpause=False, restore=False,
                           autofire=False, human_yield=enabled, react=0.0), log=lambda m: None)
    return sent, w


sent, w = run_yield(yield_from=3, yield_to=5)
check('让位·钩子在跑之前装好、跑完卸掉', w.started and w.stopped, f'{w.started}/{w.stopped}')
check('让位·让位期间一个键都不发',
      not any(f >= 3 and f < 5 and a == 'down' for f, a, _ in sent), f'发出 {sent}')
check('让位·开始时就松开脚本按着的方向键',
      any(f == 3 and a == 'up' for f, a, _ in sent), f'第 3 帧 {[x for x in sent if x[0] == 3]}')
check('让位·人停手后重新接管按键',
      any(f >= 5 and a == 'down' for f, a, _ in sent), f'发出 {sent}')

sent, w = run_yield(yield_from=3, yield_to=5, phys=('right',))
lifted = [k for f, a, k in sent if f == 3 and a == 'up']
check('让位·玩家正按着的键不抬（硬抬会把人家按住的右方向顶掉）',
      'right' not in lifted and 'up' in lifted, f'第 3 帧抬起 {lifted}')

sent, w = run_yield(yield_from=1, enabled=False)
check('让位·关掉后不装钩子、照常发键',
      not w.started and any(a == 'down' for _, a, _ in sent), f'装={w.started} 发出 {sent}')

# ---- 低速模式（focus：只在「原地不动就够安全」时半速走）----
# 依据：反汇编 `Player__OnUpdate`（输入位图 bit2 = TH_BUTTON_SLOW，命中后速度字段从
# `+0x7864` 取）+ 实机读结构常量（4.0 / 2.0，斜向 2.82843 / 1.41421 = 精确半速）。
# 判据是「**原地不动**的间隙」（`scores['none']`），不是「最优方向的间隙」——
# 后者一片太平就成立，会让自机常年半速。这里钉住：只需微调时按 Shift、
# 站着不动都险时绝不按、门槛滑条真的在接管判据、冲线期强制高速。


def frame_roomy():
    """一颗远处的静止子弹：确实有威胁源，但站着不动都极宽裕（≈432px）"""
    return dict(bx=np.array([400.0]), by=np.array([80.0]), vx=np.zeros(1), vy=np.zeros(1),
                px=100.0, py=400.0, n_enemy=0, n_laser=0, n_item=0, item=None,
                warn=None, power=0.0, poc_val=0.0, poc_cx=None,
                enemy=None, laser=None, target=None)


def frame_tight():
    """八向 14px 各一颗静止子弹：原地只有 14 − (1.25+3.0+2.0) = 7.75px，够不到门槛

    被围住时最优解本就是不动（`best == 'none'`）—— 按 Shift 也换不来任何东西。
    """
    ds = dodge.DIRS[1:]
    return dict(bx=np.array([100.0 + dx * 14.0 for _, dx, dy, _ in ds]),
                by=np.array([400.0 + dy * 14.0 for _, dx, dy, _ in ds]),
                vx=np.zeros(8), vy=np.zeros(8),
                px=100.0, py=400.0, n_enemy=0, n_laser=0, n_item=0, item=None,
                warn=None, power=0.0, poc_val=0.0, poc_cx=None,
                enemy=None, laser=None, target=None)


def frame_under_fire():
    """正上方 10px 一颗静止子弹：原地只有 3.75px —— 在分数线以下，必须躲

    这是「真的要移动」的样子：原地不动会撞，`none` 连候选池都进不去。
    """
    return dict(bx=np.array([100.0]), by=np.array([290.0]), vx=np.zeros(1), vy=np.zeros(1),
                px=100.0, py=300.0, n_enemy=0, n_laser=0, n_item=0, item=None,
                warn=None, power=0.0, poc_val=0.0, poc_cx=None,
                enemy=None, laser=None, target=None)


def frame_near_miss():
    """正下方 20px 一颗静止子弹 + 正上方一个输出目标：原地 13.75px

    够活（正数、在分数线之上），但够不到默认门槛（分数线 6 + 余量 12 = 18）——
    正是「要不要放宽门槛」的临界面。
    """
    return dict(bx=np.array([100.0]), by=np.array([320.0]), vx=np.zeros(1), vy=np.zeros(1),
                px=100.0, py=300.0, n_enemy=1, n_laser=0, n_item=0, item=None,
                warn=None, power=0.0, poc_val=0.0, poc_cx=None,
                enemy=None, laser=None, target=(100.0, 60.0))


def run_focus(frame, enabled=True, extra=None, frames=6):
    """跑几帧主循环，返回发出的键序列（bomb 关掉，免得按 X 混进判据）"""
    sent, idx = [], [0]
    _stub_common(FakeWatch())
    th06.key_down = lambda k: sent.append(('down', k))
    th06.key_up = lambda k: sent.append(('up', k))
    th06.tap = lambda *a, **k: None
    dodge.screen_of = lambda st, running=None: ('IN_GAME', '桩', True)

    def fake_state(p, mb):
        idx[0] += 1
        return {'calc_count': idx[0], 'retry': 0, 'lives': 3, 'dying': 0}

    dodge.read_state = fake_state
    dodge.read_frame = lambda p, mb, ue=True, ul=True, ui=True, motion=None, enemy_motion=None: frame()
    cfg = dict(dry=False, frames=frames, period=0.001, unpause=False, restore=False,
               autofire=False, attack=0.0, bomb=False, react=0.0, focus=enabled)
    cfg.update(extra or {})
    dodge.run_session(None, None, 0x1234, cfg, log=lambda m: None)
    return sent


sent = run_focus(frame_roomy)
check('低速·只需微调（原地不动就极宽裕）时按住 Shift 半速走',
      ('down', 'shift') in sent, f'发出 {sent}')
check('低速·退出时松开 Shift（不留按下的修饰键）', ('up', 'shift') in sent, f'发出 {sent}')

sent = run_focus(frame_tight)
check('低速·被围住（原地都不够安全）时不用低速',
      not any(k == 'shift' for _, k in sent), f'发出 {sent}')

sent = run_focus(frame_under_fire)
check('低速·必须躲（原地会撞）时绝不用低速 —— 那正是要靠速度拉开距离的时刻',
      not any(k == 'shift' for _, k in sent), f'发出 {sent}')

sent = run_focus(frame_near_miss, extra=dict(attack=30.0))
check('低速·够活但不够宽裕（原地 13.75px < 门槛 18）时不用低速',
      not any(k == 'shift' for _, k in sent), f'发出 {sent}')

sent = run_focus(frame_near_miss, extra=dict(attack=30.0, focus_slack=0.0))
check('低速·门槛滑条真的接管判据（调 0 后同一局面改用低速）',
      ('down', 'shift') in sent, f'发出 {sent}')

sent = run_focus(frame_roomy, enabled=False)
check('低速·关掉开关后永不按 Shift（退回全高速）',
      not any(k == 'shift' for _, k in sent), f'发出 {sent}')

dash_frame = frame_roomy()
dash_frame.update(power=128.0, poc_val=5.0, poc_cx=100.0)
sent = run_focus(lambda: dash_frame, extra=dict(poc=True, poc_min=0.0, item=50.0))
check('低速·冲线期强制高速（那件事的本质就是快点冲上去）',
      not any(k == 'shift' for _, k in sent), f'发出 {sent}')


# ---- 逐弹判定半径（grazeSize）----
# 依据 MEMMAP §3：r弹 = min(grazeSize.x, grazeSize.y) × 0.5，**逐弹不同**。
# 本机实测两档：小玉 4×4 → 2.0（占多数）、普通弹 6×6 → 3.0；原版分档最大到 32×32 → 16.0。
# 旧实现对所有弹一律 3.0：大玉少算 13px —— 算出来「安全」的位置其实必死。
# 这里钉住：半径真的进了安全分，且大玉能翻掉小玉的安全判断。

def _gap_at(br, dy=12.0):
    """正上方 dy 处一颗静止子弹：「原地不动」方向的间隙（safe=0，算式看得清）"""
    _b, sc = dodge.plan(192.0, 400.0, np.array([192.0]), np.array([400.0 - dy]),
                        np.zeros(1), np.zeros(1), dodge.PLAYER_SPEED, 30, 0.0,
                        br=None if br is None else np.array([br], dtype=np.float32))
    return sc['none']


_g_small, _g_norm = _gap_at(2.0), _gap_at(3.0)
_g_big, _g_none = _gap_at(16.0), _gap_at(None)
check('判定半径·小玉(4×4, r=2.0)：12px 处间隙 = 12 − 3.25 = 8.75px',
      abs(_g_small - 8.75) < 1e-3, f'得到 {_g_small:.2f}')
check('判定半径·普通弹(6×6, r=3.0)：同一位置 = 12 − 4.25 = 7.75px',
      abs(_g_norm - 7.75) < 1e-3, f'得到 {_g_norm:.2f}')
check('判定半径·大玉(32×32, r=16.0)：同一位置 −5.25px（必死）—— 旧的一律 3.0 会算成 7.75',
      abs(_g_big + 5.25) < 1e-3, f'得到 {_g_big:.2f}')
check('判定半径·br 缺失时回落 BULLET_R（与逐弹改造前逐字一致）',
      abs(_g_none - _g_norm) < 1e-6, f'{_g_none:.2f} vs {_g_norm:.2f}')
check('判定半径·大玉把「小玉够安全」的位置翻成必死（判定真的进入了决策）',
      _g_small > 0.0 > _g_big, f'小玉 {_g_small:+.2f} → 大玉 {_g_big:+.2f}')


print('\n全部通过' if OK else '\n有失败项')
sys.exit(0 if OK else 1)
