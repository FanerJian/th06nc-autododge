"""解释当前一帧的躲避决策 —— 只读，不发按键

调参用：为什么这帧选了 down 而不是 ul？软项各占多少？影子轨迹会把自机带到哪？

用法（游戏需在关卡内；暂停态也能读，只是世界被冻结）:
  py tools\\explain_plan.py              当前帧分解 + 150 帧影子轨迹
  py tools\\explain_plan.py --walk 300   影子轨迹跑 300 帧
"""
import argparse
import os
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import th06  # noqa: E402
from dodge import (ATTACK_REACH, ATTACK_STEP, ATTACK_W, CENTER_R, CENTER_W, CLEAR_R,
                   CLEAR_STEP, CLEAR_W, DIRS, EDGE_MARGIN, FALL_VMAX,
                   ITEM_W, ITEM_WAIT, LASER_HORIZON, MARGIN_CAP, MARGIN_W, PLAYER_R,
                   bullet_radii,
                   ENEMY_MARGIN, POC_NORM, POC_TARGET_Y, POC_W_EXTRA, RISK_SOFT, RISK_TOL,
                   STANDOFF,
                   SWITCH_MARGIN, WARN_DIST, WARN_W, EnemyMotion, ItemLineTrip, LaserMotion,
                   attack_cost, bullet_paths, clearance_cost, edge_cost, enemy_gap,
                   fall_frames,
                   item_aim_vals, item_cluster_vals, item_cost, laser_gap, pick_target,
                   read_frame, recenter_cost, warn_radius)  # noqa: E402
from offsets import FIELD_X0, FIELD_X1, FIELD_Y0, FIELD_Y1, ITEM_GRAB_DIST, PLAYER_SPEED  # noqa: E402
from screen import is_running, read_state, screen_of  # noqa: E402
from winmem import module_base  # noqa: E402

DIRV = {n: (a, b) for n, a, b, _ in DIRS}


def item_gap(item, x, y):
    """影子轨迹用：当前在追哪个道具、还有多远、还要几帧才落到自机高度

    「还要几帧」是这次新增时间模型后最该看的一项 —— 大数（几十帧）意味着这块道具
    现在还不该动身，自机会先去做别的事，等它降下来再对齐。
    """
    if item is None or len(item[0]) == 0:
        return '—'
    dls = item[4] if len(item) > 4 else None
    if item_cost(x, y, *item[:4], delays=dls) >= 1.0:
        return '无（没有值得现在动身的道具）'
    ix, iy, vals = item[0], item[1], item[2]
    vys = item[3] if len(item) > 3 else None
    i = int(np.argmin(np.sqrt((x - ix) ** 2 + (y - iy) ** 2) / np.maximum(vals, 1e-6)))
    above = max(y - ITEM_GRAB_DIST - iy[i], 0.0)
    t = float(fall_frames(above, vys[i] if vys is not None else FALL_VMAX)) if above else 0.0
    if dls is not None:
        t += float(dls[i])
    scat = '（散射中，按终点近似）' if dls is not None and dls[i] > 0 else ''
    return (f'追道具 {np.hypot(x - ix[i], y - iy[i]):5.1f}px（价值 {vals[i]:.1f}，'
            f'还要 {t:4.0f} 帧落到自机高度）{scat}')


def scores_of(px, py, bx, by, vx, vy, enemy, laser, speed, horizon, safe, item=None,
              warn=None, warn_w=0.0, warn_dist=WARN_DIST, item_wait=ITEM_WAIT, br=None,
              clear_r=CLEAR_R, center_r=CENTER_R, clear_step=CLEAR_STEP, enemy_mv=None,
              bf=None):
    """各方向安全分 + 软项分解（与 plan() 同式，见 dodge.plan 的注释）"""
    if enemy is not None and warn is not None and warn_w:      # 与 plan() 同一处放大
        r2 = warn_radius(warn, warn_w, warn_dist) * 2.0
        enemy = (enemy[0], enemy[1], enemy[2] + r2, enemy[3] + r2)
    ts = np.arange(1, horizon + 1, dtype=np.float32)
    ts_laser = np.arange(1, LASER_HORIZON + 1, dtype=np.float32)
    if bf is not None and len(bx):                             # 与 plan() 同一处：吃 bf
        fx, fy = bullet_paths(bf, horizon, px, py)
    else:
        fx = bx[None, :] + vx[None, :] * ts[:, None] if len(bx) else None
        fy = by[None, :] + vy[None, :] * ts[:, None] if len(bx) else None
    threat = PLAYER_R + bullet_radii(br, bx) + safe            # (N,) 逐弹阈值
    out = {}
    for name, dx, dy, _ in DIRS:
        xs = np.clip(px + dx * speed * ts, FIELD_X0, FIELD_X1)
        ys = np.clip(py + dy * speed * ts, FIELD_Y0, FIELD_Y1)
        gaps = []
        if len(bx):
            gaps.append((np.sqrt((xs[:, None] - fx) ** 2 + (ys[:, None] - fy) ** 2)
                         - threat[None, :]).min(axis=1))
        if enemy is not None:
            # 与 plan() 同一处：敌人按速度外推 + 另加 ENEMY_MARGIN
            g = enemy_gap(xs, ys, *enemy,
                          evx=None if enemy_mv is None else enemy_mv[0],
                          evy=None if enemy_mv is None else enemy_mv[1],
                          ts=ts)
            if g is not None:
                gaps.append(g - PLAYER_R - safe - ENEMY_MARGIN)
        if laser is not None:
            # 与 plan() 同一处：激光走独立的长前瞻（LASER_HORIZON）
            lxs = np.clip(px + dx * speed * ts_laser, FIELD_X0, FIELD_X1)
            lys = np.clip(py + dy * speed * ts_laser, FIELD_Y0, FIELD_Y1)
            g = laser_gap(lxs, lys, *laser, ts=ts_laser)
            if g is not None:
                gaps.append(g - PLAYER_R - safe)
        ax = min(max(px + dx * speed * ATTACK_STEP, FIELD_X0), FIELD_X1)
        ay = min(max(py + dy * speed * ATTACK_STEP, FIELD_Y0), FIELD_Y1)
        # 空旷项用自己的前瞻（CLEAR_STEP）：4 帧的落点彼此太近、没有区分度
        clx = min(max(px + dx * speed * clear_step, FIELD_X0), FIELD_X1)
        cly = min(max(py + dy * speed * clear_step, FIELD_Y0), FIELD_Y1)
        out[name] = (float(min(g.min() for g in gaps)) if gaps else 0.0,
                     xs[-1], ys[-1], edge_cost(ax, ay), ax, ay,
                     item_cost(ax, ay, *item[:4], wait=item_wait,
                               delays=item[4] if len(item) > 4 else None)
                     if item is not None else 1.0,
                     clearance_cost(clx, cly, bx, by, clear_r), recenter_cost(ax, ay, free=center_r))
    return out


def decide(sc, edge_w, inertia, prev, attack, attack_w, standoff, comfort, margin_w,
           switch_margin, item_w=0.0, has_threat=True, risk=RISK_TOL, poc=None, poc_w=0.0,
           clear_w=0.0, center_w=0.0):
    soft = {}
    for name in sc:
        gap, _, _, ec, ax, ay, ic, cc, rc = sc[name]
        s = -edge_w * ec + (inertia if name == prev else 0.0)
        if clear_w:
            s -= clear_w * cc
        if center_w:
            s -= center_w * rc
        if poc is not None and poc_w:
            # 与 plan() 同式：冲线期进攻/道具吸引让位给冲线吸引（不是叠加）
            s += poc_w * (1.0 - np.hypot(ax - poc[0], ay - poc[1]) / POC_NORM)
        else:
            if attack is not None and attack_w:
                s -= attack_w * attack_cost(ax, ay, attack[0], attack[1], standoff)
            if item_w:
                s += item_w * (1.0 - ic)
        soft[name] = s
    top = max(v[0] for v in sc.values())
    if has_threat and top < comfort:
        # 紧张档：与 plan() 同一句 —— 只在「与最优同样安全」的方向间让软项决胜负
        pool = ([n for n, v in sc.items() if v[0] >= max(top - risk, 0.0)] if risk > 0 else [])
        if len(pool) <= 1:
            return max(sc, key=lambda n: sc[n][0]), soft, '紧张：只比安全分（纯躲）'
        base, scale = top, RISK_SOFT
        note = f'紧张：同等安全内偏输出（容差 {risk:g}px）'
    else:
        pool = [n for n, v in sc.items() if v[0] >= comfort] if has_threat else list(sc)
        base, scale = comfort, 1.0
        note = '软项参与排序' if has_threat else '无威胁源：软项直接决胜负'
    if len(pool) <= 1:     # 与 plan() 同款保护：没方向达门槛时只比安全分（别 max() 空序列）
        return max(sc, key=lambda n: sc[n][0]), soft, f'{note}（可用方向不足，只比安全分）'
    merit = {n: scale * soft[n] + margin_w * min(sc[n][0] - base, MARGIN_CAP) / MARGIN_CAP
             for n in pool}
    best = max(pool, key=lambda n: merit[n])
    if prev in merit and merit[best] - merit[prev] < switch_margin:
        return prev, soft, f'{note}（切换门槛粘住 {prev}：{best} 只领先 {merit[best] - merit[prev]:.2f} < {switch_margin}）'
    return best, soft, note


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--walk', type=int, default=150, help='影子轨迹帧数，0 = 只看当前帧')
    ap.add_argument('--speed', type=float, default=PLAYER_SPEED)
    ap.add_argument('--horizon', type=int, default=30)
    ap.add_argument('--safe', type=float, default=2.0)
    ap.add_argument('--edge', type=float, default=8.0)
    ap.add_argument('--inertia', type=float, default=0.2)
    ap.add_argument('--attack', type=float, default=ATTACK_W)
    ap.add_argument('--standoff', type=float, default=STANDOFF)
    ap.add_argument('--item', type=float, default=ITEM_W, help='捡道具权重，0 = 不捡')
    ap.add_argument('--item-wait', type=float, default=ITEM_WAIT,
                    help='愿意为道具等的帧数：道具还要更久才落到自机高度就不追')
    ap.add_argument('--risk', type=float, default=RISK_TOL,
                    help='紧张档同等安全容差(px)：0 = 紧张时纯躲（旧行为）')
    ap.add_argument('--warn', type=float, default=WARN_W, help='弹幕预警窗口(帧)，0 = 关闭')
    ap.add_argument('--warn-dist', type=float, default=WARN_DIST, help='预警最大额外危险半径(px)')
    ap.add_argument('--comfort', type=float, default=6.0)
    ap.add_argument('--margin', type=float, default=MARGIN_W)
    ap.add_argument('--clear', type=float, default=CLEAR_W, help='空旷区吸引权重，0 = 关闭')
    ap.add_argument('--clear-r', type=float, default=CLEAR_R, help='空旷度评价半径(px)')
    ap.add_argument('--clear-step', type=float, default=CLEAR_STEP,
                    help='空旷项的独立前瞻(帧)：落点彼此够远才有区分度')
    ap.add_argument('--center', type=float, default=CENTER_W, help='自动回中权重，0 = 关闭')
    ap.add_argument('--center-r', type=float, default=CENTER_R, help='回中自由半径(px)')
    ap.add_argument('--switch', type=float, default=SWITCH_MARGIN)
    a = ap.parse_args()

    p, pid = th06.get_proc()
    mb = module_base(pid, 'th06nc.exe')[0]
    # 连读两帧：横扫的激光与移动的敌人**都没有可读的速度字段**（都得逐帧差分）。
    # 只读一帧等于按「激光不横扫 + 敌人静止」评估，与实机 plan 不同式。
    # 帧没推进时差分为 0，自动退化成单帧行为，无害。
    lm, em = LaserMotion(), EnemyMotion()
    # 先确认在关卡里：不在关卡时玩家/敌人结构是**没初始化的堆内存**（实测自机 (0,0)、
    # life 与 hitbox 是垃圾值），照常算会打印一屏无意义的数字，或让候选池为空直接崩。
    st = read_state(p, mb)
    scr = screen_of(st, is_running(p, mb))
    if scr[0] not in ('IN_GAME', 'NO_LIVES', 'PAUSED', 'DYING'):
        print(f'游戏当前在 {scr[0]}（{scr[1]}），不在关卡里 —— 内存还没初始化，'
              f'读出来的是垃圾值。\n先进关卡再跑本工具。')
        return
    if scr[0] == 'PAUSED':
        print(f'（{scr[1]}：世界冻结，差分出来的激光/敌人速度会是 0，评分只反映静止几何）')
    read_frame(p, mb, motion=lm, enemy_motion=em)      # 第一帧只用来建立差分基线
    time.sleep(0.02)                                   # 等游戏推进一步（60fps ≈ 16.7ms）
    w = read_frame(p, mb, motion=lm, enemy_motion=em)
    px, py = w['px'], w['py']
    bx, by, vx, vy = w['bx'], w['by'], w['vx'], w['vy']
    br = w['br']                       # 逐弹判定半径（MEMMAP §3）
    enemy, laser, target, item = w['enemy'], w['laser'], w['target'], w['item']
    warn = w['warn']
    # 与 plan() 同式、同序：集群加成（一趟能捡最多）→ 顺路折扣（离目标对齐线越远越不值）
    if item is not None:
        v = item_cluster_vals(px, py, item[0], item[1], item[2],
                              item[3] if len(item) > 3 else None,
                              item[4] if len(item) > 4 else None)
        v = item_aim_vals(item[0], v, target[0] if target is not None else None)
        item = (item[0], item[1], v,
                item[3] if len(item) > 3 else None,
                item[4] if len(item) > 4 else None)
    # 与 run_session 同式：评估一次道具线状态（只读显示，不影响真机的状态机）
    trip = ItemLineTrip()
    dashing = trip.update(py, w.get('power', 0.0), w.get('poc_val', 0.0), enabled=True)
    poc = None
    poc_w = 0.0
    if dashing:
        poc = (w.get('poc_cx') if w.get('poc_cx') is not None else px, POC_TARGET_Y)
        poc_w = a.attack + a.item + POC_W_EXTRA
    has_threat = len(bx) > 0 or enemy is not None or laser is not None
    print(f'自机 ({px:.1f},{py:.1f})  弹 {len(bx)}  敌 {w["n_enemy"]}  激 {w["n_laser"]}  '
          f'道具 {w["n_item"]}  目标 {target}  火力 {w.get("power", 0):.0f}  '
          f'可转化价值 {w.get("poc_val", 0.0):.1f}'
          + (f'  冲线中 → ({poc[0]:.0f},{poc[1]:.0f})' if dashing else ''))
    if warn is not None and len(warn):
        cd = [int(c) for c in warn]
        soon = [c for c in cd if 0 <= c <= a.warn]
        print(f'发弹倒计时 {cd}（-1 = 不射击）'
              + (f'  {len(soon)} 个敌人进入预警窗口 {a.warn:.0f} 帧：{soon}' if soon
                 else f'  （窗口 {a.warn:.0f} 帧内无敌人发弹）'))
    print(f'参数 edge={a.edge} margin={a.margin} switch={a.switch} attack={a.attack} '
          f'standoff={a.standoff}（输出带 {a.standoff:.0f}..{a.standoff + ATTACK_REACH:.0f}px）'
          f'  item={a.item}/{a.item_wait:.0f}帧  risk={a.risk:g}px  '
          f'warn={a.warn:.0f}帧/{a.warn_dist:.0f}px  贴边距离 {EDGE_MARGIN:.0f}px')
    print(f'      空旷区 clear={a.clear}/{a.clear_r:.0f}px  回中 center={a.center}/'
          f'自由半径 {a.center_r:.0f}px')

    sc = scores_of(px, py, bx, by, vx, vy, enemy, laser, a.speed, a.horizon, a.safe, item,
                   warn, a.warn, a.warn_dist, a.item_wait, br, a.clear_r, a.center_r,
                   a.clear_step, enemy_mv=w.get('enemy_mv'), bf=w.get('bf'))
    best, soft, note = decide(sc, a.edge, a.inertia, 'none', target, a.attack, a.standoff,
                              a.comfort, a.margin, a.switch, a.item, has_threat, a.risk,
                              poc=poc, poc_w=poc_w, clear_w=a.clear, center_w=a.center)
    if dashing:
        note = f'冲线中（poc_w={poc_w:.0f}：进攻/道具项已让位）· ' + note
    print(f'\n{"方向":<6}{"安全分":>9}{"贴边项":>9}{"惯性":>7}{"进攻项":>9}{"道具/冲线":>9}'
          f'{"空旷项":>9}{"回中项":>9}{"soft":>8}   外推终点(horizon)')
    for name in sc:
        gap, xe, ye, ec, ax, ay, ic, cc, rc = sc[name]
        iner = a.inertia if name == 'none' else 0.0
        atk = itm = 0.0
        if poc is not None and poc_w:
            itm = poc_w * (1.0 - np.hypot(ax - poc[0], ay - poc[1]) / POC_NORM)
        else:
            if target is not None and a.attack:
                atk = -a.attack * attack_cost(ax, ay, target[0], target[1], a.standoff)
            if a.item:
                itm = a.item * (1.0 - ic)
        mark = ' ←' if name == best else ''
        print(f'{name:<6}{gap:9.2f}{-a.edge * ec:9.2f}{iner:7.2f}{atk:9.2f}{itm:9.2f}'
              f'{-a.clear * cc:9.2f}{-a.center * rc:9.2f}'
              f'{soft[name]:8.2f}   ({xe:.0f},{ye:.0f}){mark}')
    print(f'\n决策 = {best}（{note}）')

    if a.walk <= 0:
        p.close()
        return
    print(f'\n=== 影子轨迹（世界冻结 {a.walk} 帧）===')
    sx, sy, prev = px, py, 'none'
    for f in range(a.walk):
        tgt = pick_target(sx, sy, enemy, None)
        # 影子轨迹里倒计时随帧推进递减（发过弹后归 -1）——否则预警会被当成永恒状态
        wf = None if warn is None else np.where(warn >= f, warn - f, -1)
        sc = scores_of(sx, sy, bx, by, vx, vy, enemy, laser, a.speed, a.horizon, a.safe, item,
                       wf, a.warn, a.warn_dist, a.item_wait, br, a.clear_r, a.center_r,
                       enemy_mv=w.get('enemy_mv'), bf=w.get('bf'))
        best, _, _ = decide(sc, a.edge, a.inertia, prev, tgt, a.attack, a.standoff,
                            a.comfort, a.margin, a.switch, a.item, has_threat, a.risk,
                            poc=poc, poc_w=poc_w, clear_w=a.clear, center_w=a.center)
        r = item_gap(item, sx, sy)
        dx, dy = DIRV[best]
        sx = float(np.clip(sx + dx * a.speed, FIELD_X0, FIELD_X1))
        sy = float(np.clip(sy + dy * a.speed, FIELD_Y0, FIELD_Y1))
        prev = best
        if f % 15 == 0 or f == a.walk - 1:
            off = '—' if tgt is None else f'水平差 {abs(sx - tgt[0]):5.1f}px'
            print(f'  帧{f:4d}  自机({sx:6.1f},{sy:6.1f})  {best:<5} 目标 {tgt}  {off}'
                  f'   道具 {r}')
    p.close()


if __name__ == '__main__':
    main()
