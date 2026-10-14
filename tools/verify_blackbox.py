"""实机验证死亡黑匣子 —— 真读一帧帧喂进 `BlackBox.feed()`，人为触发一次落盘，再验回来

为什么需要单独一个验证脚本：控制台 / CLI 的 `on_world` 钩子**只在主循环走到
「关卡进行中」时**才被调用，而验证时游戏常停在 Continue / 菜单画面 ——
「喂帧 → 触发 → 落盘 → 能解剖」这条链路不能只靠"接线看起来对"。

本脚本用真实进程读帧、手动喂，到第 `--at` 帧把 `deaths` 人为 +1 触发落盘，
最后跑一遍 `death_report` 的解析。**只读、不发按键、不切前台。**

用法:
  py tools\\verify_blackbox.py               # 读 40 帧，第 30 帧触发
  py tools\\verify_blackbox.py --at 10 --pre 8 --post 3
  py tools\\verify_blackbox.py --keep        # 保留落盘的 npz（默认验证完删掉）
"""
import argparse
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:                                    # Windows 控制台默认 GBK，中文会乱码
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

import death_recorder                                                 # noqa: E402
import death_report                                                   # noqa: E402
import dodge                                                          # noqa: E402
import paths                                                          # noqa: E402
import th06                                                           # noqa: E402
from read_bullets import read_player_state                            # noqa: E402
from screen import read_state                                         # noqa: E402
from winmem import module_base                                        # noqa: E402


def main():
    ap = argparse.ArgumentParser(description='实机验证死亡黑匣子（只读，不按键）')
    ap.add_argument('--at', type=int, default=30, help='第几帧人为触发掉命（默认 30）')
    ap.add_argument('--frames', type=int, default=40, help='最多读多少帧（默认 40）')
    ap.add_argument('--pre', type=int, default=30, help='回看帧数')
    ap.add_argument('--post', type=int, default=2, help='触发后继续录的帧数')
    ap.add_argument('--keep', action='store_true', help='保留落盘的 npz')
    args = ap.parse_args()

    out_dir = os.path.join(paths.app_dir(), '_tmp', 'bbverify')
    p, pid = th06.get_proc()
    mb = module_base(pid, 'th06nc.exe')[0]
    bb = death_recorder.BlackBox(p, mb, pre=args.pre, post=args.post,
                                 out_dir=out_dir, log=print)
    print(f'PID {pid}  基址 0x{mb:X}  pre={args.pre} post={args.post} → {out_dir}')

    motion, enemy_motion = dodge.LaserMotion(), dodge.EnemyMotion()
    path = None
    try:
        for i in range(args.frames):
            w = dodge.read_frame(p, mb, motion=motion, enemy_motion=enemy_motion)
            if w is None:
                print('失败 读帧失败（进程退出？）')
                return 1
            st = read_state(p, mb)
            ps = read_player_state(p, mb)
            if i == args.at:
                st = dict(st)
                st['deaths'] = (st['deaths'] or 0) + 1      # 人为造一次「掉命」
                print(f'  第 {i} 帧：人为把 deaths 改成 {st["deaths"]}')
            got = bb.feed(w, st, ps)
            if i == 5 and bb.buf:                           # 字段体检：一眼看出录全没
                f = bb.buf[-1]
                print(f'  第 5 帧体检：弹 {len(f["b_x"])} 激 {len(f["l_x"])} '
                      f'敌 {len(f["e_x"])}  子弹键 '
                      f'{sum(1 for k in f if k.startswith("b_"))} 个  '
                      f'power={f["power"]:.0f} focus={f["focus"]:.0f} '
                      f'key={f["key"]:.0f}')
            if got:
                path = got
                break
    except KeyboardInterrupt:
        print('\n# 中断')
    finally:
        p.close()

    ok = True
    print(f'\n— 喂了 {bb.n} 帧，落盘 {bb.saves} 例，漏帧 {bb.missed_total}')
    if path is None:
        print('失败 没有触发落盘 —— 链路不通')
        return 1
    d = death_report.Dump(path)
    need = ('px', 'py', 'lives', 'b_n', 'l_n', 'e_n', 'b_slot', 'b_exf', 'b_dcspd',
            'l_ph', 'e_siv')
    miss = [k for k in need if k not in d.__dict__]
    if miss:
        ok = False
        print(f'失败 落盘字段缺失：{miss}')
    else:
        print(f'通过 字段齐：{d.T} 帧，子弹键 {sum(1 for k in d.__dict__ if k.startswith("b_"))} 个')
    print('— 用解剖器验回来：')
    res, parsed = None, True
    try:
        res = death_report.report(d, back=10, scan=10)
    except Exception as ex:                 # 解析崩了才是链路问题
        parsed = False
        import traceback
        traceback.print_exc()               # 别只打一行消息：要看崩在哪一行
        print(f'失败 解剖器解析失败：{type(ex).__name__}: {ex}')
    print(f'\n{"通过 通过" if (ok and parsed) else "失败 失败"}（解剖器'
          + ('找到真凶' if res else '跑完并判「无相交」—— 采样画面里本来就没撞上，属正常')
          + '）')
    if not args.keep:
        shutil.rmtree(out_dir, ignore_errors=True)
        print(f'（已清理 {out_dir}；要留档加 --keep）')
    else:
        print(f'（已保留 {out_dir}）')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
