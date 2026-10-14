"""死亡黑匣子 —— 按游戏帧逐帧记录完整世界，掉命瞬间自动冻结现场落盘

为什么需要：`watch_live.py` 是 20fps 抽样，且只在**死亡上升沿**打「附近还有哪些弹」。
但游戏是自机撞进判定圈的那一帧判死、`respawnTimer` 走满 8 帧才结算掉命 ——
等到死亡上升沿，真凶早已飞走，现场里剩下的全是路过的无辜弹。
抽样更致命：20fps 对 60fps 的游戏是 3 帧取 1，判定那一帧大概率根本没被采到。

本工具只做一件事：**忠实记原始事实**。
  自机坐标 / 状态 / 死亡窗口 / 低速标志 / 实际输入位图（脚本真按了什么）
  全部子弹（含 exFlags 与加速转向参数，够离线重建 BulletFrame）
  全部激光（判定几何 + 逐帧差分的轴移与转角）/ 全部敌人盒与发弹倒计时
掉命时把前 N 帧一起落盘 → 事后由 `death_report.py` 用**几何真值**定位真凶。
**决策不在这里算**：世界已经录下来了，九向评分由 report 离线复算 —— 那样采集端开销最低，
还能事后换参数重算（「当时 clear_w 若设成 0 会怎么走」）。

两种用法：
  · **独立跑**（本文件的 `main`）：自己读内存，适合「脚本单独跑、黑匣子只旁听」。
  · **挂在躲避主循环上**（控制台勾选「死亡黑匣子」/ `dodge.py --blackbox`）：
    走 `BlackBox.feed()` **复用主循环这一帧已经读到的世界**，只额外读 3 个小量
    （focus / 输入位图 / 火力），不额外占 2MB/帧 的读取带宽 —— 不会把主循环挤到掉帧。

**纯只读**：只 ReadProcessMemory，不 SendInput、不切前台、不改游戏。

独立跑用法:
  py tools\\death_recorder.py                  # 挂着，掉命时自动存 _tmp\\death_<时间>.npz
  py tools\\death_recorder.py --pre 300        # 回看 300 帧（默认 240 ≈ 4 秒）
  py tools\\death_recorder.py --post 40        # 死亡后再录 40 帧（看结算过程）
  py tools\\death_recorder.py --exit-on-death  # 存完就退（专门跑一局用）
  py tools\\death_recorder.py --dump-now       # 缓冲一满就落盘退出（只为采一段试样）
  py tools\\death_recorder.py -v               # 每秒打一行状态
"""
import argparse
import collections
import json
import os
import subprocess
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:                                    # Windows 控制台默认 GBK，中文会乱码
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

import dodge                                                          # noqa: E402
import paths                                                          # noqa: E402
import th06                                                           # noqa: E402
from offsets import (BULLET_STATE_DESPAWNING, CALC_COUNT, E_COLLIDABLE,  # noqa: E402
                     E_INVISIBLE, INPUT, PLAYER_BASE, PLAYER_OFF_FOCUS,
                     POWER)
from read_bullets import read_player_state                            # noqa: E402
from screen import read_state                                         # noqa: E402
from winmem import module_base                                        # noqa: E402

# 变长池：npz 存不下变长数组 → 按组扁平拼接 + 每帧记实体数（`b_n` / `l_n` / `e_n`）。
# 键名带组前缀，report 端按同一张表还原（**单一真源**：report 从这里 import）。
# 子弹字段录全是为离线重建 BulletFrame（`dodge.bullet_paths()` 推加速 / 转向弹要用）。
GROUPS = {
    'b': ('x', 'y', 'vx', 'vy', 'r', 'st', 'exf', 'ang', 'spd', 'tm', 'slot',
          'dcspd', 'hold', 'accx', 'accy', 'trot', 'tint', 'tnum', 'tmax',
          'trate', 'srate'),
    'l': ('x', 'y', 'ang', 'st', 'en', 'ln', 'w', 'spd', 'ph', 'tm', 'tot',
          'slot', 'vx', 'vy', 'om'),
    'e': ('x', 'y', 'hw', 'hh', 'slot', 'fl2', 'siv', 'stm'),
}
# 每帧一个标量（统一 float64 落盘：编码省事，精度对帧数据足够）
SCALARS = ('calc', 'torn', 'missed', 'ms', 'px', 'py', 'pstate', 'respawn',
           'focus', 'key', 'lives', 'bombs', 'deaths', 'dying', 'power',
           'retry', 'scene')


def read_calc(p, mb):
    """帧计数（u8，每帧 +1，256 回绕）—— 跟帧 / 算漏帧的唯一依据"""
    d = p.read(mb + CALC_COUNT, 1)
    return d[0] if d else None


def frame_of(p, mb, w, st, ps, calc=None, torn=0.0, missed=0.0, t0=None):
    """一帧世界（`read_frame` 的输出 + 状态）→ 可落盘的 dict

    **两种用法共用本函数**：内嵌主循环（`BlackBox.feed`）与独立跑（`read_world`）从同一条路
    组装字段 —— 免得「脚本里录的」和「单独挂着录的」字段对不上，报告读出来还不一样。
    只额外读 3 个小量（focus / 输入位图 / 火力），每个 1~2 字节。
    """
    px, py = w['px'], w['py']
    # 用**未过滤**的整池：命中自机的那颗弹当帧就转消散，而 `read_frame` 为避弹性能
    # 默认把消散弹滤掉了 —— 用过滤版会让真凶在判定帧凭空消失（实测踩过）。
    bf = w.get('bf_raw') if w.get('bf_raw') is not None else w['bf']
    f = p.read(mb + PLAYER_BASE + PLAYER_OFF_FOCUS, 1)
    k = p.read(mb + INPUT, 2)
    pw = p.read(mb + POWER, 2)
    frame = {
        'calc': float(calc if calc is not None else -1),
        'torn': float(torn),
        'missed': float(missed),
        'px': float(px), 'py': float(py),
        'pstate': float(ps['state']) if ps else np.nan,
        'respawn': float(ps['respawn']) if ps else np.nan,
        'focus': float(f[0]) if f else np.nan,
        'key': float(int.from_bytes(k, 'little')) if k else np.nan,
        'power': float(int.from_bytes(pw, 'little')) if pw else np.nan,
    }
    for name in ('lives', 'bombs', 'deaths', 'dying', 'retry'):
        v = st.get(name)
        frame[name] = float(v) if v is not None else np.nan
    frame['scene'] = float(st['cur_state']) if st.get('cur_state') is not None else np.nan

    # ---- 子弹：几何 + 运动参数（B_OFF_* / EXF_*，见 offsets）----
    frame['b_x'] = np.asarray(bf.xs, dtype=np.float32)
    frame['b_y'] = np.asarray(bf.ys, dtype=np.float32)
    frame['b_vx'] = np.asarray(bf.vxs, dtype=np.float32)
    frame['b_vy'] = np.asarray(bf.vys, dtype=np.float32)
    frame['b_r'] = np.asarray(bf.brs, dtype=np.float32)
    frame['b_st'] = np.asarray(bf.states, dtype=np.float32)
    frame['b_exf'] = np.asarray(bf.exflags, dtype=np.float32)
    frame['b_ang'] = np.asarray(bf.angles, dtype=np.float32)
    frame['b_spd'] = np.asarray(bf.speeds, dtype=np.float32)
    frame['b_tm'] = np.asarray(bf.timers, dtype=np.float32)
    frame['b_slot'] = np.asarray(bf.slots, dtype=np.float32)
    frame['b_dcspd'] = np.asarray(bf.dcspeeds, dtype=np.float32)
    frame['b_hold'] = np.asarray(bf.hold, dtype=np.float32)
    frame['b_accx'] = np.asarray(bf.accel_x, dtype=np.float32)
    frame['b_accy'] = np.asarray(bf.accel_y, dtype=np.float32)
    frame['b_trot'] = np.asarray(bf.turn_rot, dtype=np.float32)
    frame['b_tint'] = np.asarray(bf.turn_int, dtype=np.float32)
    frame['b_tnum'] = np.asarray(bf.turn_num, dtype=np.float32)
    frame['b_tmax'] = np.asarray(bf.turn_max, dtype=np.float32)
    frame['b_trate'] = np.asarray(bf.turn_rate, dtype=np.float32)
    frame['b_srate'] = np.asarray(bf.speed_rate, dtype=np.float32)

    # ---- 激光：判定几何（11 元组含轴移/转角）+ 阶段与槽号 ----
    laser, lfr = w.get('laser'), w.get('lf')
    if laser is not None and lfr is not None and len(lfr.xs):
        for i, k2 in enumerate(('x', 'y', 'ang', 'st', 'en', 'ln', 'w', 'spd',
                                'vx', 'vy', 'om')):
            frame['l_' + k2] = np.asarray(laser[i], dtype=np.float32)
        frame['l_ph'] = np.asarray(lfr.phases, dtype=np.float32)
        frame['l_tm'] = np.asarray(lfr.timers, dtype=np.float32)
        frame['l_tot'] = np.asarray(lfr.totals, dtype=np.float32)
        frame['l_slot'] = np.asarray(lfr.slots, dtype=np.float32)
    else:
        for k2 in GROUPS['l']:
            frame['l_' + k2] = np.zeros(0, dtype=np.float32)

    # ---- 敌人：与 dodge.read_frame 同一判据（可碰撞 且 非隐形）；连槽号一起录 ----
    er = w.get('enemy_raw')
    if er is not None:
        eslots, _exs, _eys, _elife, ehw, ehh, ef2, ef3, iv, tm = er
        keep = ((ef2 & E_COLLIDABLE) != 0) & ((ef3 & E_INVISIBLE) == 0)
        frame['e_x'] = np.asarray(w['enemy'][0], dtype=np.float32)
        frame['e_y'] = np.asarray(w['enemy'][1], dtype=np.float32)
        frame['e_hw'] = np.asarray(ehw[keep], dtype=np.float32)
        frame['e_hh'] = np.asarray(ehh[keep], dtype=np.float32)
        frame['e_slot'] = np.asarray(eslots[keep], dtype=np.float32)
        frame['e_fl2'] = np.asarray(ef2[keep], dtype=np.float32)
        frame['e_siv'] = np.asarray(iv[keep], dtype=np.float32)   # 射击间隔（<=0 = 不射击）
        frame['e_stm'] = np.asarray(tm[keep], dtype=np.float32)   # 已累计帧数 → 发弹倒计时
    else:
        for k2 in GROUPS['e']:
            frame['e_' + k2] = np.zeros(0, dtype=np.float32)

    frame['ms'] = ((time.perf_counter() - t0) * 1000.0 if t0 is not None
                   else np.nan)      # 内嵌模式不单独计时（开销已计在主循环里）
    return frame


def pack(frames):
    """帧列表 → 可 savez 的扁平字典（变长池展开 + 计数）"""
    out = {}
    for k in SCALARS:
        out[k] = np.array([f.get(k, np.nan) for f in frames], dtype=np.float64)
    for g, keys in GROUPS.items():
        out[g + '_n'] = np.array([len(f.get(g + '_x', ())) for f in frames],
                                 dtype=np.float64)
        for k in keys:
            name = f'{g}_{k}'
            parts = [f[name] for f in frames if name in f and len(f[name])]
            out[name] = (np.concatenate(parts).astype(np.float32) if parts
                         else np.zeros(0, dtype=np.float32))
    return out


def save_npz(frames, path, meta):
    data = pack(frames)
    data['meta'] = np.array(json.dumps(meta, ensure_ascii=False))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    np.savez_compressed(path, **data)
    return os.path.getsize(path)


class BlackBox:
    """死亡黑匣子：环形缓冲 + 掉命落盘

    两种喂法：
      · `feed(w, st, ps)` —— 挂在躲避主循环上（推荐）：世界是主循环刚读到的，
        本类只补 3 个小量，不额外抢读取带宽。
      · `read_world(p, mb)` + `feed(...)` —— 独立跑：自己读整帧（约 3~6ms）。
    掉命判据三条任一：`deaths` +1 / `Lives` 下降 / 进入 DEAD 状态。
    """

    def __init__(self, p, mb, pre=240, post=24, out_dir=None, log=print,
                 max_saves=8, report=False, verbose=False, params=None):
        self.p, self.mb = p, mb
        self.pre, self.post = max(2, pre), max(0, post)
        self.out_dir = out_dir or os.path.join(paths.app_dir(), '_tmp')
        self.log = log
        self.max_saves = max_saves
        self.report = report
        self.verbose = verbose
        self.params = params          # 当时的运行参数 → 写进 meta（离线复算要用同一套）
        self.buf = collections.deque(maxlen=self.pre)
        self.frozen = None
        self.after = []
        self.post_left = 0
        self.n = 0                  # 已录帧数
        self.saves = 0              # 已落盘例数
        self.paths = []
        self.missed_total = 0
        self.ms_list = []
        self._calc = None
        self._prev = (None, None, None)      # deaths / lives / pstate
        self._why = None                     # 触发原因（落盘在若干帧之后，不能用那时的 hit）
        self._t0 = time.perf_counter()

    # ---- 一帧 ----
    def feed(self, w, st, ps, calc=None, torn=0.0, t0=None):
        """喂一帧 → 触发时落盘，返回落盘路径（否则 None）

        内嵌用法（主循环钩子）只要给 `(w, st, ps)`；帧号/漏帧由本类按 `CALC_COUNT` 自算。
        """
        c = calc if calc is not None else read_calc(self.p, self.mb)
        if c is None:
            return None
        missed = 0 if self._calc is None else (c - self._calc) % 256 - 1
        self._calc = c
        self.missed_total += max(0, missed)
        fr = frame_of(self.p, self.mb, w, st, ps, calc=c, torn=torn, missed=missed,
                      t0=t0)
        self.n += 1
        self.ms_list.append(fr['ms'])
        if len(self.ms_list) > 600:
            del self.ms_list[:300]           # 只留最近一段做均值，别无限涨

        dl, lv, stt = fr['deaths'], fr['lives'], fr['pstate']
        pd, pl, pst = self._prev
        hit = (pd is not None and not np.isnan(dl) and not np.isnan(pd) and dl > pd)
        if not hit and pl is not None and not np.isnan(lv) and not np.isnan(pl) \
                and lv < pl:
            hit = 'Lives 下降'
        if not hit and stt == 2.0 and pst != 2.0:
            hit = '进入 DEAD'
        self._prev = (dl, lv, stt)

        if self.frozen is None:
            self.buf.append(fr)
            if hit:
                why = 'deaths+1' if hit is True else hit
                self._why = why
                self.log(f'死亡黑匣子：掉命（{why}），自机({fr["px"]:.1f},{fr["py"]:.1f})，'
                         f'Lives={lv:.0f}。再录 {self.post} 帧后落盘。')
                self.frozen = list(self.buf)
                self.after = []
                self.post_left = self.post
            elif self.verbose and self.n % 60 == 0:
                self.log(f'  黑匣子 {self.n} 帧　弹 {len(fr["b_x"])}　激光 {len(fr["l_x"])}　'
                         f'敌 {len(fr["e_x"])}　缓冲 {len(self.buf)}/{self.pre}')
            if self.frozen is None:
                return None
        elif self.post_left > 0:
            self.after.append(fr)
            self.post_left -= 1
        if self.frozen is not None and self.post_left <= 0:
            return self._save(self.frozen + self.after, self._why or '掉命', 'death')
        return None

    def save_now(self, why='立即采样'):
        """把当前缓冲直接落盘（不等掉命）→ 路径"""
        return self._save(list(self.buf), why, 'sample')

    def _save(self, frames, why, prefix):
        name = time.strftime(f'{prefix}_%Y%m%d-%H%M%S.npz', time.localtime())
        meta = {
            'saved_at': time.strftime('%Y-%m-%d %H:%M:%S'), 'why': why,
            'pre': self.pre, 'post': self.post, 'n_frames': len(frames),
            'note': '只录原始世界；九向决策由 death_report.py 离线复算',
            'missed_total': self.missed_total,
            'torn': int(sum(1 for f in frames if f['torn'])),
            'ms_avg': float(np.mean(self.ms_list)) if self.ms_list else None,
        }
        if self.params:
            # 参数决定安全分怎么算 —— 不记下来，事后复算只能是猜（实测踩过：
            # 报告用 plan 的默认值算，与实机那套差出 horizon 20/30、attack 125/0）
            meta['params'] = {k: (v if isinstance(v, bool) else float(v))
                              for k, v in self.params.items()
                              if isinstance(v, (bool, int, float))}
        path = os.path.join(self.out_dir, name)
        size = save_npz(frames, path, meta)
        self.saves += 1
        self.paths.append(path)
        self.frozen, self.after, self.post_left = None, [], 0
        self.log(f'死亡黑匣子已保存现场：{path}，{size / 1024:.0f} KB，{len(frames)} 帧。')
        if self.report:
            rep = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               'death_report.py')
            # 用 subprocess 而不是 os.system：路径经 cmd.exe 解析时会被引号/空格坑到
            subprocess.call([sys.executable, rep, path])
        return path

    @property
    def full(self):
        return self.buf.maxlen is not None and len(self.buf) >= self.buf.maxlen


def read_world(p, mb, motion, enemy_motion):
    """独立跑用：自己读一整帧 → (w, st, ps, calc, torn)

    内嵌模式不走这里（主循环已经把世界读好了）。`torn` = 读世界期间游戏又走了一帧，
    这一帧的世界是跨帧拼的 —— 上面的「相交」可能是假的，报告里要能据此打折。
    """
    c0 = read_calc(p, mb)
    t0 = time.perf_counter()
    w = dodge.read_frame(p, mb, use_enemy=True, use_laser=True, use_item=False,
                         motion=motion, enemy_motion=enemy_motion)
    if w is None:
        return None
    st = read_state(p, mb)
    ps = read_player_state(p, mb)
    c1 = read_calc(p, mb)
    torn = 1.0 if (c0 is not None and c1 is not None and c1 != c0) else 0.0
    return w, st, ps, c0, torn, t0


def main():
    ap = argparse.ArgumentParser(description='死亡黑匣子（独立跑，只读不按键）')
    ap.add_argument('--pre', type=int, default=240, help='掉命时回看的帧数（默认 240 ≈ 4 秒）')
    ap.add_argument('--post', type=int, default=24, help='掉命后继续录的帧数（默认 24）')
    ap.add_argument('--out', default=None, help='输出目录（默认 _tmp/）')
    ap.add_argument('--exit-on-death', action='store_true', help='存完一例就退出')
    ap.add_argument('--max-saves', type=int, default=8, help='最多存几例（默认 8）')
    ap.add_argument('--seconds', type=float, default=0.0, help='0 = 一直跑')
    ap.add_argument('--dump-now', action='store_true',
                    help='缓冲区一满就立刻落盘退出（不为等掉命，只为采一段真实世界试样）')
    ap.add_argument('-v', '--verbose', action='store_true', help='每秒打一行状态')
    ap.add_argument('--report', action='store_true', help='存完自动跑 death_report.py')
    args = ap.parse_args()

    p, pid = th06.get_proc()
    mb = module_base(pid, 'th06nc.exe')[0]
    # 实机那套参数（出厂默认 + 控制台保存值）一并记进 meta：独立跑时躲避脚本不在场，
    # 不记就只剩猜（复算要用同一套，见 death_report.live_params）
    live = dodge.default_params()
    live.update(dodge.load_saved()[0])
    bb = BlackBox(p, mb, pre=args.pre, post=args.post, out_dir=args.out,
                  max_saves=args.max_saves, report=args.report, verbose=args.verbose,
                  params=live)
    print(f'# 死亡黑匣子  PID {pid}  基址 0x{mb:X}  回看 {args.pre} 帧 + 后录 {args.post} 帧')
    print(f'# 只读，不发按键；输出 → {bb.out_dir}')
    print('# 等游戏走帧…（暂停 / 非关卡时帧计数不动，这里会静等）')
    print('# 提示：控制台（dodge_gui.py）勾「死亡黑匣子」可在躲避脚本内启用，'
          '那时复用主循环的读取、更快')

    motion = dodge.LaserMotion()
    enemy_motion = dodge.EnemyMotion()
    last_calc = None
    t0 = time.perf_counter()
    try:
        while True:
            now = time.perf_counter()
            if args.seconds and now - t0 > args.seconds:
                print('# 到时退出')
                break
            c = read_calc(p, mb)
            if c is None:
                print('! 帧计数读取失败（进程退出？）')
                break
            if c == last_calc:
                time.sleep(0.0005)          # 0.5ms，别空转烧 CPU
                continue
            got = read_world(p, mb, motion, enemy_motion)
            if got is None:
                print('! 读世界失败（进程退出？）')
                break
            w, st, ps, calc, torn, t_read = got
            path = bb.feed(w, st, ps, calc=calc, torn=torn, t0=t_read)
            if path:
                if args.exit_on_death or bb.saves >= bb.max_saves:
                    break
            elif args.dump_now and bb.full:
                print(f'[{now - t0:8.2f}s] 立即采样：缓冲已满 {len(bb.buf)} 帧 → 落盘退出')
                bb.save_now('立即采样（--dump-now）')
                break
            last_calc = calc
    except KeyboardInterrupt:
        print('\n# 中断')
    finally:
        el = time.perf_counter() - t0
        avg = float(np.mean(bb.ms_list)) if bb.ms_list else 0.0
        print(f'# 结束：{el:.1f}s / {bb.n} 帧 / 漏帧 {bb.missed_total} 帧 / '
              f'单帧读取 {avg:.2f}ms（{avg / 16.67 * 100:.0f}% 帧预算）/ 存了 {bb.saves} 例')
        if bb.n and not bb.saves:
            print('# 本段没有掉命 —— 没落盘。要收一例：挂着它，然后正常玩到掉命')
        p.close()


if __name__ == '__main__':
    main()
