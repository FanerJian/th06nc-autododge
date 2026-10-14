"""plan() 分层决策回归检查 —— 软项不得覆盖安全判断

为什么留着：中心吸引/惯性曾直接加在安全分上，会选中"时间窗内最小间隙为负"
（= 必然中弹）的方向。用例 1 保留了这个缺陷的对照实证，改 `plan()` 后跑一遍。

用法:
  py tools\\check_plan.py            # 纯计算，不需要游戏
"""
import base64
import os
import random
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dodge  # noqa: E402
from dodge import (ATTACK_REACH, ATTACK_STEP, CENTER_R, CLEAR_R, CLEAR_STEP, DIRS,
                   FIELD_CX, FIELD_CY, FIELD_X0, FIELD_X1, FIELD_Y0, FIELD_Y1,
                   ITEM_W, ITEM_WAIT, ITEM_WAIT_IDLE, MARGIN_W, PLAYER_SPEED,
                   POC_COOLDOWN, POC_TARGET_Y, POC_TIMEOUT, REACT_FRAMES, REACT_JITTER,
                   REACT_MIN_COMFORT, SCATTER_AVG, STANDOFF, SWITCH_MARGIN, WARN_DIST,
                   ItemLineTrip, ReactionGate,
                   attack_cost, clearance_cost, edge_cost, item_cluster_vals, item_cost,
                   item_values, pick_target, plan, recenter_cost, threat_present,
                   warn_radius)  # noqa: E402
from read_bullets import BulletFrame  # noqa: E402  # 桩 read_bullet_frame 必须给同一结构
from offsets import EXF_ACCEL, EXF_TURN_AIM, EXF_TURN_REL  # noqa: E402

OK = True
EMPTY = np.array([])


def walk(px, py, enemy, bx, by, vx, vy, frames=240, attack_w=20.0, standoff=STANDOFF,
         edge_w=8.0, inertia=0.2, margin_w=MARGIN_W, switch_margin=SWITCH_MARGIN,
         item=None, item_w=0.0):
    """让虚拟自机按 plan() 逐帧走到停，返回 (末 x, 末 y, 方向序列)"""
    dirv = {n: (a, b) for n, a, b, _ in DIRS}
    prev, seq = 'none', []
    for _ in range(frames):
        tgt = pick_target(px, py, enemy, None)
        best, _ = plan(px, py, bx, by, vx, vy, PLAYER_SPEED, 30, 2.0, edge_w, prev, inertia,
                       enemy, None, 6.0, attack=tgt, attack_w=attack_w, standoff=standoff,
                       margin_w=margin_w, switch_margin=switch_margin,
                       item=item, item_w=item_w)
        seq.append(best)
        dx, dy = dirv[best]
        px = float(np.clip(px + dx * PLAYER_SPEED, FIELD_X0, FIELD_X1))
        py = float(np.clip(py + dy * PLAYER_SPEED, FIELD_Y0, FIELD_Y1))
        prev = best
    return px, py, seq



def old_pick(px, py, scores, center_w, inertia, prev, speed, horizon):
    """旧逻辑：中心/惯性直接加在安全分上（本次修掉的那一版）"""
    best, bestm = None, -1e9
    for name, dx, dy, _ in DIRS:
        xs = min(max(px + dx * speed * horizon, FIELD_X0), FIELD_X1)
        ys = min(max(py + dy * speed * horizon, FIELD_Y0), FIELD_Y1)
        dc = abs(xs - 192.0) / 192.0 + abs(ys - 224.0) / 224.0
        m = scores[name] - center_w * dc + (inertia if name == prev else 0.0)
        if m > bestm:
            best, bestm = name, m
    return best


def check(tag, best, sc, cond, detail=''):
    global OK
    mark = '✓' if cond else '✗'
    print(f'{mark} {tag}: 选 {best}  gap={sc[best]:+.2f}  {detail}')
    if not cond:
        OK = False


def check_val(tag, got, want, detail=''):
    global OK
    mark = '✓' if got == want else '✗'
    print(f'{mark} {tag}: 得到 {got}  期望 {want}  {detail}')
    if got != want:
        OK = False


# 用例 1：贴脸静止弹 + 超强中心吸引。旧逻辑选 none（gap 为负 = 必死）
best, sc = plan(192.0, 224.0, np.array([192.0]), np.array([218.0]),
                np.array([0.0]), np.array([0.0]), PLAYER_SPEED, 30, 2.0,
                edge_w=30.0, prev='none', inertia=0.0, comfort=6.0)
check('危险时软项不参与', best, sc, sc[best] > 0 and sc[best] == max(sc.values()),
      '（贴边权重 30 也拉不回边界）')
old = old_pick(192.0, 224.0, sc, 30.0, 0.0, 'none', PLAYER_SPEED, 30)
check('对照·旧公式在同一场景', old, sc, sc[old] < 0, '← 选中的是必死方向，即本次修掉的问题')

# 用例 2：自机贴左边 + 远处弹 → 够安全时应主动回中
best, sc = plan(30.0, 224.0, np.array([300.0]), np.array([100.0]),
                np.array([0.0]), np.array([0.0]), PLAYER_SPEED, 30, 2.0,
                edge_w=8.0, prev='none', inertia=0.0, comfort=6.0)
check('安全时回中生效', best, sc, best == 'right', '（贴左边应往右）')

# 用例 3：够安全时同向惯性生效
best, sc = plan(192.0, 224.0, np.array([300.0]), np.array([100.0]),
                np.array([0.0]), np.array([0.0]), PLAYER_SPEED, 30, 2.0,
                edge_w=0.0, prev='up', inertia=5.0, comfort=6.0)
check('安全时惯性生效', best, sc, best == 'up', '（prev=up）')

# 用例 4：惯性方向是死路 → 不得因惯性走进去
best, sc = plan(192.0, 224.0, np.array([192.0]), np.array([250.0]),
                np.array([0.0]), np.array([-5.0]), PLAYER_SPEED, 30, 2.0,
                edge_w=0.0, prev='up', inertia=8.0, comfort=6.0)
check('惯性不掩盖死路', best, sc, sc[best] > 0 and best != 'up',
      '（up 方向窗口内会撞，惯性 8 也压不过）')

# 用例 5：安全局面 + 目标在右上方（BOSS）→ 应朝目标移动，而不是回中
ex, ey = np.array([300.0]), np.array([60.0])
best, sc = plan(100.0, 400.0, np.array([]), np.array([]), np.array([]), np.array([]),
                PLAYER_SPEED, 30, 2.0, edge_w=8.0, prev='none', inertia=0.0,
                enemy=(ex, ey, np.array([24.0]), np.array([24.0])), comfort=6.0,
                attack=(300.0, 60.0), attack_w=20.0, standoff=48.0)
check('安全时进攻吸引生效', best, sc, best in ('ur', 'right'),
      '（自机在左下，目标在右上——应向目标靠）')

# 用例 6：进攻目标正上方，但 up 会撞敌人 → 进攻不得把它推成最优
best, sc = plan(192.0, 400.0, np.array([]), np.array([]), np.array([]), np.array([]),
                PLAYER_SPEED, 30, 2.0, edge_w=0.0, prev='none', inertia=0.0,
                enemy=(np.array([192.0]), np.array([330.0]),
                       np.array([40.0]), np.array([40.0])), comfort=6.0,
                attack=(192.0, 100.0), attack_w=20.0, standoff=48.0)
check('进攻不掩盖死路', best, sc, sc[best] > 0 and best != 'up',
      '（目标在正上方，但 up 会撞上敌人）')

# 用例 7：目标选择 —— 只认自机上方的敌人，BOSS 优先
enemy = (np.array([100.0, 300.0, 50.0]), np.array([100.0, 500.0, 200.0]),
         np.zeros(3), np.zeros(3))
check_val('目标选择·BOSS 优先且排除下方', pick_target(200.0, 400.0, enemy,
          np.array([False, False, True])), (50.0, 200.0), '（300,500 在自机下方）')
check_val('目标选择·无 BOSS 取上方最近', pick_target(200.0, 400.0,
          (np.array([100.0, 120.0]), np.array([380.0, 500.0]), np.zeros(2), np.zeros(2)),
          np.array([False, False])), (100.0, 380.0))
check_val('目标选择·全在下方则不打', pick_target(200.0, 400.0,
          (np.array([100.0, 200.0]), np.array([500.0, 450.0]), np.zeros(2), np.zeros(2)),
          np.array([False, False])), None, '（子弹朝上，追下方敌人无意义）')

# ---- 用例 8–11：三个实战现象的护栏（自机贴敌人 / 一路往上 / 打不到敌人 / 无用操作）----

# 用例 8：冲过目标头顶必须受罚。旧式 max(0, (y-ty)-standoff) 在那里恒为 0，
# 与理想位置同分 —— 自机冲上去就不回来，而子弹朝上飞，头顶永远打不到目标。
_ty, _so = 100.0, 48.0
_ideal = attack_cost(192.0, _ty + _so, 192.0, _ty, _so)
_above = attack_cost(192.0, _ty - 80.0, 192.0, _ty, _so)
_far = attack_cost(192.0, _ty + _so + ATTACK_REACH + 80.0, 192.0, _ty, _so)
check_val('过冲受罚·理想点代价最小', round(_ideal, 3), 0.0, '（水平对齐 + 垂直到位 = 0）')
print(f'{"✓" if _above > _ideal and _far > _ideal else "✗"} 过冲受罚·头顶与带外同罚: '
      f'头顶 {_above:.3f} / 带外 {_far:.3f} 都 > 理想 {_ideal:.3f}'
      f'{"  ← 旧式此处全为 0" if _above > 0 else ""}')
OK = OK and _above > _ideal and _far > _ideal

# 用例 9：已在输出带内时，垂直方向不再被进攻项驱动（否则一路贴到敌人脚下）
_en9 = (np.array([192.0]), np.array([80.0]), np.array([28.0]), np.array([28.0]))
best, sc = plan(192.0, 80.0 + STANDOFF + 72.0, EMPTY, EMPTY, EMPTY, EMPTY,
                PLAYER_SPEED, 30, 2.0, edge_w=0.0, prev='none', inertia=0.0,
                enemy=_en9, comfort=6.0, attack=(192.0, 80.0), attack_w=20.0,
                standoff=STANDOFF)
check('输出带内不驱动上行', best, sc, best in ('none', 'down'),
      '（目标下方 120px，仍在带内 —— 进攻项不该再推它往上贴）')

# 用例 10：贴边项只在贴边时非零。旧式全局中心吸引会与进攻项全场对抗，
# 把自机钉在原地（实测水平偏差 53px 打不到目标）。
check_val('贴边项·场地中部为 0', edge_cost(192.0, 224.0), 0.0)
print(f'{"✓" if edge_cost(8.0, 224.0) > 0 and edge_cost(192.0, 224.0) == 0.0 else "✗"} '
      f'贴边项·贴边才扣分: 贴左边 {edge_cost(8.0, 224.0):.3f} / 中部 {edge_cost(192.0, 224.0):.3f}')
OK = OK and edge_cost(8.0, 224.0) > 0 and edge_cost(192.0, 224.0) == 0.0

# 用例 11：完整走位 —— 站得住、对得齐、不抖。敌人在右上，无弹幕（纯策略验证）。
# 旧逻辑：水平停在半路（偏差 61px，打不到）、且来回切换。
_en11 = (np.array([300.0]), np.array([80.0]), np.array([28.0]), np.array([28.0]))
wx, wy, wseq = walk(100.0, 420.0, _en11, EMPTY, EMPTY, EMPTY, EMPTY)
_sw = sum(1 for i in range(1, len(wseq)) if wseq[i] != wseq[i - 1])
_off = abs(wx - 300.0)
check_val('走位·水平对齐到敌人宽度内', bool(_off < 14.0), True,
          f'（末位置 {wx:.1f},{wy:.1f} 偏差 {_off:.1f}px，敌人半宽 14px → 打得到）')
check_val('走位·不来回抖', bool(_sw <= 8), True, f'（240 帧切换 {_sw} 次；旧逻辑 61px 偏差且未对齐）')
check_val('走位·停在敌人下方（不冲过目标）', bool(wy > 80.0), True,
          f'（末 y={wy:.1f} > 敌人 y=80 —— 冲过目标头顶就永远打不到）')

# 用例 11 对照：同一场景跑「旧软项」（全局中心吸引 + max(0,...) 攻击项 + 纯 soft 池内排序）。
# 它即本次修掉的那一版 —— 断言它确实打不到，证明上面三条护栏抓得住问题。
def walk_old(px, py, enemy, frames=240):
    dirv = {n: (a, b) for n, a, b, _ in DIRS}
    prev = 'none'
    for _ in range(frames):
        tgt = pick_target(px, py, enemy, None)
        soft = {}
        for name, dx, dy, _ in DIRS:
            xe = min(max(px + dx * PLAYER_SPEED * 30, FIELD_X0), FIELD_X1)
            ye = min(max(py + dy * PLAYER_SPEED * 30, FIELD_Y0), FIELD_Y1)
            dc = abs(xe - 192.0) / 192.0 + abs(ye - 224.0) / 224.0
            s = -8.0 * dc + (0.2 if name == prev else 0.0)
            if tgt is not None:
                s -= 20.0 * (0.5 * abs(xe - tgt[0]) / 192.0
                             + max(0.0, (ye - tgt[1]) - 48.0) / 224.0)
            soft[name] = s
        best = max(soft, key=soft.get)
        dx, dy = dirv[best]
        px = float(np.clip(px + dx * PLAYER_SPEED, FIELD_X0, FIELD_X1))
        py = float(np.clip(py + dy * PLAYER_SPEED, FIELD_Y0, FIELD_Y1))
        prev = best
    return px, py


ox, oy = walk_old(100.0, 420.0, _en11)
check_val('对照·旧软项在同一场景打不到', bool(abs(ox - 300.0) >= 14.0), True,
          f'（旧逻辑末位置 {ox:.1f},{oy:.1f} 水平偏差 {abs(ox - 300.0):.1f}px ≥ 半宽 14px）')

# ---- 用例 12–16：道具吸引（捡掉落物）的护栏 ----

# 用例 12：空档期（无弹 / 无敌人 / 无激光）不再呆立 —— 朝掉落道具走。
# 旧逻辑：没有威胁源时 scores 恒为 0 < comfort，软项被整体拦截 → 自机全程 none，
# 掉落物就在眼前也不去捡（开场清完杂兵、BOSS 击破后的空档期全是这种局面）。
# 道具元组 = (xs, ys, vals, vys)：vys 是下落速度，时间模型靠它算「还要几帧落下来」。
_it = (np.array([250.0]), np.array([350.0]), np.array([1.0]), np.array([1.0]))
best, sc = plan(100.0, 350.0, EMPTY, EMPTY, EMPTY, EMPTY, PLAYER_SPEED, 30, 2.0,
                edge_w=0.0, prev='none', inertia=0.0, comfort=6.0, item=_it, item_w=ITEM_W)
check('空档期·朝道具走', best, sc, best == 'right', '（道具在正右方 150px，缓慢下落）')

# 用例 13：走位实证 —— 真的能走进拾取范围（拾取判定 x/y 各 14px，见 offsets）
wx, wy, _ = walk(100.0, 350.0, None, EMPTY, EMPTY, EMPTY, EMPTY, frames=120,
                 attack_w=0.0, edge_w=0.0, inertia=0.0, item=_it, item_w=ITEM_W)
check_val('走位·进入道具拾取范围', bool(abs(wx - 250.0) < 14.0), True,
          f'（末位置 x={wx:.1f}，道具在 250，拾取半宽 14px）')

# 用例 13 对照：道具项沿用 ATTACK_STEP(4 帧) 就够 —— 方向间吸引差 ≫ 切换门槛。
# 别为了「追得更远」把它加长：终点距离模型在够得到的距离上会误判成「冲过头」。
_d_none = item_cost(100.0, 350.0, *_it)
_gap4 = ITEM_W * (_d_none - item_cost(100.0 + PLAYER_SPEED * 4.0, 350.0, *_it))
_gap15 = ITEM_W * (_d_none - item_cost(100.0 + PLAYER_SPEED * 15.0, 350.0, *_it))
check_val('前瞻尺度·ATTACK_STEP 足以越过切换门槛', bool(_gap4 > SWITCH_MARGIN), True,
          f'（4 帧吸引差 {_gap4:.2f} > 门槛 {SWITCH_MARGIN}；15 帧反而 {_gap15:.2f} 更大，'
          f'但那会冲过头）')

# ---- 用例 13b–13e：道具时间模型（用它下落速度外推，治「干等」与「白跑」）----

def _item_plan(items, px=192.0, py=400.0, w=ITEM_W):
    return plan(px, py, EMPTY, EMPTY, EMPTY, EMPTY, PLAYER_SPEED, 30, 2.0,
                edge_w=0.0, prev='none', inertia=0.0, comfort=6.0, item=items, item_w=w)

# 用例 13b：高处道具不追 —— 它还要 ~90 帧才落下来，自机站过去只是干等。
# 旧模型（瞬时距离）此时给满额吸引，自机会一路向上贴到道具下方等它。
_high = (np.array([192.0]), np.array([120.0]), np.array([1.0]), np.array([3.0]))
best, sc = _item_plan(_high)
check_val('道具·高处要等的不追（不干等）', best, 'none',
          '（道具在正上方 280px、3px/帧下落 —— 还要约 89 帧才到自机高度）')

# 用例 13c：赶不上的不追 —— 道具已在下落末端，自机到不了就先出局，别白跑一趟。
_low = (np.array([250.0]), np.array([430.0]), np.array([1.0]), np.array([3.0]))
best, sc = _item_plan(_low, px=100.0)
check_val('道具·赶不上的不追（不白跑）', best, 'none',
          '（道具在右下 150px，只剩约 6 帧就掉出场地，自机要 34 帧）')

# 用例 13d：即将落到自机高度的道具 —— 该做的事是水平对齐，然后等它落到身上。
_near = (np.array([250.0]), np.array([330.0]), np.array([1.0]), np.array([3.0]))
best, sc = _item_plan(_near, px=150.0, py=350.0)
check('道具·快落到自机高度→水平对齐', best, sc, best == 'right',
      '（道具在右上方 150px，约 7 帧后落到自机高度）')

# 用例 13e：道具在自机**上方**时不得向上追 —— 上方的垂直差恒不计入吸引项。
# 自机只做水平对齐，垂直交给道具自己落下来（上追既危险，又会在那里干等）。
_ul = (np.array([100.0]), np.array([330.0]), np.array([1.0]), np.array([3.0]))
best, sc = _item_plan(_ul, px=192.0)
check('道具·在左上方也只水平对齐（不上追）', best, sc, best == 'left',
      '（道具在左上 92px；向左的吸引必须强于向左上）')

# 用例 14：道具吸引不得把自机送进必死方向（贴脸弹 + 正上方道具 + 极端权重）
best, sc = plan(192.0, 224.0, np.array([192.0]), np.array([218.0]),
                np.array([0.0]), np.array([0.0]), PLAYER_SPEED, 30, 2.0,
                edge_w=0.0, prev='none', inertia=0.0, comfort=6.0,
                item=(np.array([192.0]), np.array([60.0]), np.array([1.0])), item_w=500.0)
check('道具吸引不掩盖死路', best, sc, sc[best] > 0 and sc[best] == max(sc.values()),
      '（道具在正上方，但 up 会撞弹；权重 500 也压不过安全分）')

# 用例 15：价值排序 —— 火力未满时 Power 优先（补火力 = 提输出 + 清弹），满火力后蓝点更值钱
_t = np.array([0, 1, 2], dtype=np.int8)      # 小P / 蓝点 / 大P
_v_low, _v_full = item_values(_t, power=4), item_values(_t, power=128)
check_val('道具价值·火力未满 Power 加成', bool(_v_low[0] > _v_low[1]), True,
          f'（小P {_v_low[0]:.2f} > 蓝点 {_v_low[1]:.2f}）')
check_val('道具价值·满火力蓝点更值', bool(_v_full[0] < _v_full[1]), True,
          f'（小P {_v_full[0]:.2f} < 蓝点 {_v_full[1]:.2f}）')

# 用例 16：--item 0 是硬开关（关掉后掉落物再近也不追）
best, sc = plan(100.0, 400.0, EMPTY, EMPTY, EMPTY, EMPTY, PLAYER_SPEED, 30, 2.0,
                edge_w=0.0, prev='none', inertia=0.0, comfort=6.0, item=_it, item_w=0.0)
check_val('道具吸引·权重 0 时关闭', best, 'none', '（--item 0）')

# 用例 16b–16d：空档期放宽「愿意等」的上限（主动捡，但不外溢到有威胁时）
# 没有中弹风险时，「先走到落点下方等它落下来」不是干等而是主动 —— 沿用 item_wait
# 会把「走过去 + 等」整体判成干等而放弃，自机只会干等道具降到近处才动。
_hi_far = (np.array([280.0]), np.array([140.0]), np.array([1.0]), np.array([3.0]))
best, sc = _item_plan(_hi_far, px=120.0)
check('空档期·高处道具也主动走到落点下方等', best, sc, best == 'right',
      '（道具高 246px、水平偏 160px：无威胁源，走过去等它落下来是对的）')

_c45 = item_cost(120.0, 400.0, *_hi_far, wait=ITEM_WAIT)
_c600 = item_cost(120.0, 400.0, *_hi_far, wait=ITEM_WAIT_IDLE)
check_val('空档期·等待上限确实被放宽', bool(_c600 < _c45), True,
          f'（同一颗道具：item_wait {ITEM_WAIT:.0f} 帧 → 等效距离 {_c45:.2f}；'
          f'空档期 {ITEM_WAIT_IDLE:.0f} 帧 → {_c600:.2f}）')

_bx1 = np.array([120.0])
_by1 = np.array([380.0])
_b0 = np.array([0.0])
best_plain, _ = plan(120.0, 400.0, _bx1, _by1, _b0, _b0, PLAYER_SPEED, 30, 2.0,
                     edge_w=0.0, prev='none', inertia=0.0, comfort=6.0)
best_item, _ = plan(120.0, 400.0, _bx1, _by1, _b0, _b0, PLAYER_SPEED, 30, 2.0,
                    edge_w=0.0, prev='none', inertia=0.0, comfort=6.0,
                    item=_hi_far, item_w=ITEM_W)
check_val('有威胁时·道具项不改变选择（放宽不外溢）', best_item, best_plain,
          '（场上有弹 → 仍按 item_wait 拦，不为道具站桩）')

# ---- 用例 17–18：弹幕预警（预测下一波什么时候来，不预测形状）----

# 用例 17：warn_radius 的三段行为 —— 窗口外 0 / 不射击(-1) 0 / 发弹瞬间最大
check_val('预警半径·窗口外为 0', float(warn_radius(np.array([25]), 20.0, 60.0)[0]), 0.0)
check_val('预警半径·不射击(-1)为 0', float(warn_radius(np.array([-1]), 20.0, 60.0)[0]), 0.0)
check_val('预警半径·发弹瞬间最大', float(warn_radius(np.array([0]), 20.0, 60.0)[0]), 60.0)

# 用例 18：预警必须真的压低安全分 —— 自机在敌人下方，敌人 3 帧后发弹时
# 该敌人方向的安全分要显著低于「不预警」时，自机才会提前让开。
_en18 = (np.array([192.0]), np.array([100.0]), np.array([24.0]), np.array([24.0]))
_args = (192.0, 220.0, EMPTY, EMPTY, EMPTY, EMPTY, PLAYER_SPEED, 30, 2.0)
_g_off = plan(*_args, edge_w=0.0, prev='none', inertia=0.0, enemy=_en18,
              comfort=6.0, attack_w=0.0)[1]['none']
_g_on = plan(*_args, edge_w=0.0, prev='none', inertia=0.0, enemy=_en18, comfort=6.0,
             attack_w=0.0, warn=np.array([3]), warn_w=20.0, warn_dist=WARN_DIST)[1]['none']
print(f'{"✓" if _g_on < _g_off else "✗"} 预警压低安全分: 不预警 {_g_off:.1f}px → '
      f'预警后 {_g_on:.1f}px（敌人 3 帧后发弹）')
OK = OK and _g_on < _g_off

# ---- 用例 19–23：人类化反应延迟（局面宽裕慢半拍，危险时零延迟）----
# 为什么留着：延迟漏进危险侧就是送命，延迟无界就永远不执行 —— 这两条是
# 「动作像人」与「不出事」的分界。改 ReactionGate 后跑一遍。

# 用例 19：react = 0 必须与旧行为完全一致（逐帧即时响应），不留隐性差异
check_val('反应延迟·0 = 关闭', ReactionGate(random.Random(1)).update(
    'right', 'none', {'none': 30.0, 'right': 40.0}, 6.0, 0.0), 'right')

# 用例 20：局面宽裕时必须真的等，且延迟有界（不超过抖动上限）
_g20, _n20 = ReactionGate(random.Random(7)), 0
for _ in range(40):
    _n20 += 1
    if _g20.update('right', 'none', {'none': 30.0, 'right': 40.0}, 6.0, REACT_FRAMES) == 'right':
        break
_hi20 = int(np.ceil(REACT_FRAMES * REACT_JITTER[1]))
check_val('反应延迟·安全时确实慢半拍', bool(2 <= _n20 <= _hi20), True,
          f'（等了 {_n20} 帧才转 right，抖动上限 {_hi20} 帧）')

# 用例 21：危险侧不得出现任何等待 —— 网格覆盖「当前方向不安全」与「最优方向不宽裕」
# 两个前提（comfort=6、REACT_SLACK=8）的 9 种违反组合，全部必须当帧执行。
_g21, _bad21 = ReactionGate(random.Random(1)), []
for _c in (0.0, 3.0, 5.9):
    for _b in (6.0, 9.0, 13.9):
        if _g21.update('right', 'none', {'none': _c, 'right': _b}, 6.0, REACT_FRAMES) != 'right':
            _bad21.append((_c, _b))
check_val('反应延迟·危险侧零延迟', _bad21, [],
          '（当前方向 < 6px 或最优 < 14px 的 9 种组合全部立即执行）')
check_val('反应延迟·边界正好达标则允许等', ReactionGate(random.Random(1)).update(
    'right', 'none', {'none': 6.0, 'right': 14.0}, 6.0, REACT_FRAMES), 'none',
    '（6 / 14 正好压在门槛上 —— 达标即从容）')

# 用例 22：目标方向每帧反复变时，延迟必须仍有界（软项拉锯不能让它永远不执行）
_g22, _n22 = ReactionGate(random.Random(5)), 0
for _i in range(40):
    _n22 += 1
    if _g22.update('right' if _i % 2 == 0 else 'left', 'none',
                   {'none': 30.0, 'right': 40.0, 'left': 40.0}, 6.0, REACT_FRAMES) != 'none':
        break
check_val('反应延迟·目标反复变也不卡死', bool(_n22 <= _hi20), True,
          f'（第 {_n22} 帧已执行，上限 {_hi20} 帧）')

# 用例 23：空档期（无威胁源）允许从容 + 威胁源判据与 plan() 同一句
check_val('反应延迟·空档期允许从容', ReactionGate(random.Random(3)).update(
    'right', 'none', {'none': 0.0, 'right': 0.0}, 6.0, REACT_FRAMES, threat=False), 'none',
    '（无威胁源：所有方向绝对安全，等得起）')
check_val('威胁源判据·空数组敌人也算威胁源',
          threat_present(EMPTY, (EMPTY, EMPTY, EMPTY, EMPTY), None), True,
          '（与 plan() 的 has_threat 同一句，别在两处各写一遍）')
check_val('威胁源判据·全空 = 空档期', threat_present(EMPTY, None, None), False)

# 用例 24：安全分数线被调低时，延迟闸门不得跟着放松（底线与分数线解耦）。
# 为什么留着：分数线同时是软项的闸门，把它调到 1px 是合法的调参（想让更多软项参与排序），
# 但那不该顺带把「可以慢半拍」的范围也放大 —— 延迟漏进危险侧就是拿命换像人。
# 实测背景：用户曾把分数线设到 1，瞬间把延迟判据从 6px 拉到 1px。
_g24, _bad24 = ReactionGate(random.Random(1)), []
for _c in (0.0, 1.0, 3.0, 5.9):
    for _b in (1.0, 4.0, 9.0, 13.9):
        if _g24.update('right', 'none', {'none': _c, 'right': _b}, 1.0, REACT_FRAMES) != 'right':
            _bad24.append((_c, _b))
check_val('反应延迟·分数线调低不放宽延迟', _bad24, [],
          f'（分数线 1px 时仍按 {REACT_MIN_COMFORT:.0f}px 底线判：16 种组合全部立即执行）')
check_val('反应延迟·分数线调高时从严', ReactionGate(random.Random(1)).update(
    'right', 'none', {'none': 10.0, 'right': 40.0}, 20.0, REACT_FRAMES), 'right',
    '（分数线 20px > 底线 6px：当前方向 10px 不够，立即执行）')

# ---- 用例 25–28：紧张档同等安全（boss 战不再只躲不打）+ 顺路捡 ----

# 用例 25：弹幕密到没有方向达到分数线时，旧逻辑直接返回纯安全分 → boss 战全程只躲不打
# （boss 战几乎从不满足分数线）。现在只允许「与最优方向相差 ≤ risk 且间隙 ≥ 0」的方向
# 让软项决胜负。场景（搜索得到，见 _tmp/try_risk.py）：三颗弹逼住右侧与上方 ——
# risk=0 选 dl（纯躲），risk=1 选 left：两者间隙只差 0.7px（远在外推误差内），
# 但 left 更接近目标的水平位置，打得到 BOSS。
_rk_bx = np.array([187.6, 277.1, 197.8])
_rk_by = np.array([179.5, 231.7, 344.1])
_rk_vx = np.array([-1.5, 1.5, -1.5])
_rk_vy = np.array([1.0, -1.0, 2.0])


def _risk_plan(risk):
    return plan(192.0, 350.0, _rk_bx, _rk_by, _rk_vx, _rk_vy, PLAYER_SPEED, 30, 2.0, 8.0,
                'none', 0.2, None, None, 6.0, attack=(100.0, 150.0), attack_w=20.0,
                standoff=STANDOFF, margin_w=MARGIN_W, switch_margin=SWITCH_MARGIN,
                item=None, item_w=0.0, risk=risk)


_b25o, _s25o = _risk_plan(0.0)
_b25n, _s25n = _risk_plan(1.0)
check('紧张档·risk=0 退回纯躲', _b25o, _s25o, _b25o == max(_s25o, key=_s25o.get),
      '（旧行为：只比安全分，取间隙最大的 dl）')
check('紧张档·risk=1 在同档内偏输出', _b25n, _s25n,
      _b25n != _b25o and _b25n == 'left' and _s25n[_b25n] >= max(_s25n.values()) - 1.0,
      '（left 只比最优少 0.7px，但更接近目标水平位置 → 一边躲一边对齐输出）')
check_val('紧张档·入选方向的间隙不为负', bool(_s25n[_b25n] >= 0.0), True,
          f'（left 间隙 {_s25n[_b25n]:+.2f}px）')

# 用例 26：全部方向间隙为负（必死局面）时，risk 再大也拉不进「会中弹」的方向 ——
# 候选的硬底线是间隙 ≥ 0，安全判断永不被偏好覆盖。
_b26, _s26 = plan(192.0, 224.0, np.array([192.0, 150.0]), np.array([224.0, 200.0]),
                  np.array([0.0, 0.0]), np.array([0.0, 0.0]), PLAYER_SPEED, 30, 2.0, 8.0,
                  'none', 0.2, None, None, 6.0, attack=(190.0, 60.0), attack_w=400.0,
                  risk=5.0)
check('紧张档·必死局面仍选最大间隙', _b26, _s26,
      _s26[_b26] == max(_s26.values()) and _s26[_b26] < 0,
      f'（最优间隙 {_s26[_b26]:+.2f}px < 0：risk 5px 也不改变「只比安全分」）')

# 用例 48：九向全负**且当前已侵入判定圈**时改按「第几帧脱出判定圈」排（ESCAPE_RANK）——
# 实测（death_20260927-113717）：48 条辐射激光同时预警、每条都带 LASER_MARGIN 的余量坑，
# 九向全负；旧排序让「间隙恒定、不靠近别的威胁」的 none 胜出，自机于是在一条即将开火的
# 激光判定圈里站了 59 帧 —— 而它只要右移 5.95px / 2 帧就能出圈（那里余量仍是负的，min 看不见）。
# 场景：三条竖直激光（判定带 x∈[178.75,201.25] / [218.75,241.25] / [158.75,181.25]），
# 自机 (192,224) 站在第一条带里：右 = 3 帧出带，左 = 一头扎进第三条带，上下 = x 不变、永远出不去。
_LZ48 = (np.array([190.0, 230.0, 170.0]), np.zeros(3), np.full(3, np.pi / 2),
         np.zeros(3), np.full(3, 440.0), np.full(3, 440.0), np.full(3, 20.0),
         np.zeros(3), np.zeros(3), np.zeros(3), np.zeros(3))


def _escape_plan(rank):
    save = dodge.ESCAPE_RANK
    dodge.ESCAPE_RANK = rank
    try:
        return dodge.plan(192.0, 224.0, EMPTY, EMPTY, EMPTY, EMPTY,
                          PLAYER_SPEED, 30, 2.0, 8.0, 'none', 0.2, None, _LZ48, 6.0)
    finally:
        dodge.ESCAPE_RANK = save


_b48_off, _s48_off = _escape_plan(False)
_b48_on, _s48_on = _escape_plan(True)
check('全负脱出·旧排序选中「永远出不去」的方向（对照）', _b48_off, _s48_off,
      _b48_off == 'down',
      f'（down {_s48_off["down"]:+.2f}px：x 不变 → 一直在判定带里）')
check('全负脱出·已侵入判定圈时改选最快出圈的方向', _b48_on, _s48_on,
      _b48_on == 'right' and _s48_on[_b48_on] < 0,
      f'（right {_s48_on["right"]:+.2f}px 仍为负：出圈只要 3 帧，但走满 30 帧会撞第二条带）')
check_val('全负脱出·安全分逐字不变（换的只是排序键）',
          bool(all(abs(_s48_off[k] - _s48_on[k]) < 1e-9 for k in _s48_off)), True,
          '（scores 两种模式下完全一致；软项依旧不参与）')

# 用例 49：horizon 从控制台 / `dodge_params.json` 来是**浮点**（实测存的是 `"horizon": 20.0`）——
# `np.arange` 容忍浮点（所以老代码没暴露），但 `np.full` / 切片要 int，混用会直接抛
# `TypeError: expected a sequence of integers or a single integer, got '20.0'`（实机踩过）。
def _hz_plan(hz):
    return dodge.plan(192.0, 224.0, np.array([192.0]), np.array([150.0]),
                      np.array([0.0]), np.array([3.0]), PLAYER_SPEED, hz, 2.0, 8.0,
                      'none', 0.2, None, _LZ48, 6.0)


try:
    _b49f, _s49f = _hz_plan(20.0)
    _hz_ok = True
except TypeError as _e:
    _b49f, _s49f, _hz_ok = None, {}, False
check_val('horizon·浮点（控制台存盘格式）不崩', _hz_ok, True,
          '（`np.full` 与激光切片都要求 int）')
_b49i, _s49i = _hz_plan(20)
check_val('horizon·浮点与整数结果一致',
          bool(_hz_ok and _b49f == _b49i
               and all(abs(_s49f[k] - _s49i[k]) < 1e-9 for k in _s49i)), True,
          f'（都选 {_b49i}）')

# 用例 50：九向全负时「最小间隙」会把**唯一在纯判定几何上全程安全**的方向埋没。
# 实测（death_20260927-121323）：自机离最近的 FIRE 激光表面 15px（真实安全，PLAYER_R 才
# 1.25），只因 LASER_MARGIN=16 的余量被扣成 -4.69；而唯一能躲开下一帧大玉的 down，
# 因 20 帧后会撞上一条已开火的激光被判 -29.35 → 旧排序选「不动」，一帧后被那颗大玉打死。
# 场景：两条竖直激光夹住左右（各距自机 25px = 真实 15px 余量）+ 一条 22.5° 斜激光
# （离自机 100px，沿 down 每帧靠近 4.06px → **第 23 帧**才进判定圈：scores 的 40 帧窗口
# 看得见，纯判定几何的 20 帧窗口看不见）+ 一颗朝自机下落的大玉（决定 raw0['none'] < 0）。
_A50 = np.radians(22.5)
_LZ50 = (np.array([174.9, 224.9, 199.9 - 100.0 * np.sin(_A50)]),
         np.array([0.0, 0.0, 266.4 + 100.0 * np.cos(_A50)]),
         np.array([np.pi / 2, np.pi / 2, _A50]),
         np.zeros(3), np.full(3, 440.0), np.full(3, 440.0), np.full(3, 20.0),
         np.zeros(3), np.zeros(3), np.zeros(3), np.zeros(3))
_BX50, _BY50 = np.array([188.7]), np.array([252.2])
_VY50, _BR50 = np.array([2.4]), np.array([16.0])


def _rank50(rank):
    save = dodge.ESCAPE_RANK
    dodge.ESCAPE_RANK = rank
    try:
        return dodge.plan(199.9, 266.4, _BX50, _BY50, np.zeros(1), _VY50,
                          PLAYER_SPEED, 20, 2.0, 8.0, 'none', 0.2, None, _LZ50,
                          1.0, br=_BR50)
    finally:
        dodge.ESCAPE_RANK = save


_b50_off, _s50_off = _rank50(False)
_b50_on, _s50_on = _rank50(True)
check('全负脱出·最小间隙把唯一安全的方向埋没（对照）', _b50_off, _s50_off,
      _b50_off == 'up' and max(_s50_off.values()) < 0,
      f'（up {_s50_off["up"]:+.2f}px 只比 none 的 {_s50_off["none"]:+.2f}px 高 0.02，'
      f'而 down 被判 {_s50_off["down"]:+.2f}px）')
check('全负脱出·改选纯判定几何全程安全的方向', _b50_on, _s50_on,
      _b50_on == 'down',
      f'（down 的 scores 仍是 {_s50_on["down"]:+.2f}px：20 帧窗口内它一步都没进判定圈，'
      f'只有 40 帧窗口的远端会撞上那条斜激光）')
check_val('全负脱出·换排序键不影响安全分',
          bool(all(abs(_s50_off[k] - _s50_on[k]) < 1e-9 for k in _s50_off)), True,
          '（scores 两种模式完全一致；软项依旧不参与）')

# 用例 27：顺路 —— 有可打目标时，离目标对齐线太远的道具会被打到追不动（不为它把输出走丢）；
# 同一个道具在没有目标时会被捡。这是「捡掉落物压过输出 → 打不到 BOSS → 不掉新道具」
# 那条恶性循环的护栏。
_far = (np.array([300.0]), np.array([400.0]), np.array([1.0]), np.array([1.0]))
_b27f, _s27f = plan(192.0, 400.0, EMPTY, EMPTY, EMPTY, EMPTY, PLAYER_SPEED, 30, 2.0, 0.0,
                    'none', 0.0, None, None, 6.0, item=_far, item_w=ITEM_W)
check('顺路·无目标时去捡远处的道具', _b27f, _s27f, _b27f == 'right',
      '（空档期：没有输出可做，全力捡）')
_b27a, _s27a = plan(192.0, 250.0, EMPTY, EMPTY, EMPTY, EMPTY, PLAYER_SPEED, 30, 2.0, 0.0,
                    'none', 0.0, None, None, 6.0, attack=(192.0, 150.0), attack_w=20.0,
                    standoff=STANDOFF, item=_far, item_w=ITEM_W)
check_val('顺路·有目标时不为远处道具离开输出位', _b27a, 'none',
          '（道具偏离目标对齐线 108px：顺路折扣把它打到等效距离上限之外 → 留在输出带里打）')

# 用例 28：顺路带内的道具照捡 —— 够得着又不破坏对齐的，不该放过。
_near28 = (np.array([215.0]), np.array([250.0]), np.array([1.0]), np.array([1.0]))
_b28, _s28 = plan(192.0, 250.0, EMPTY, EMPTY, EMPTY, EMPTY, PLAYER_SPEED, 30, 2.0, 0.0,
                  'none', 0.0, None, None, 6.0, attack=(192.0, 150.0), attack_w=20.0,
                  standoff=STANDOFF, item=_near28, item_w=ITEM_W)
check('顺路·带内道具照捡', _b28, _s28, _b28 == 'right',
      '（道具离对齐线 23px ≤ 40 → 不打折；捡的同时人还在输出带里）')

# ---- 用例 29–30：道具集群（「一趟能捡最多」压过「单块最值钱/最近」）----

# 用例 29：集群抬价改变方向选择。近侧 1 块蓝点（val 1.5）在右 48px；
# 远侧 3 块小P（各 val 1.0）挤在左 40±20px（水平窗 56 内、同时到达）。
# 无集群时近的赢（right）；集群后远侧每块 val = 1.0 + 2×邻居 → 合计 9 倍票 → left。
_xs29 = np.array([240.0, 132.0, 152.0, 172.0])
_ys29 = np.array([350.0, 350.0, 350.0, 350.0])
_vs29 = np.array([1.5, 1.0, 1.0, 1.0])
_vy29 = np.array([3.0, 3.0, 3.0, 3.0])
_v29c = item_cluster_vals(192.0, 400.0, _xs29, _ys29, _vs29, _vy29)
check_val('集群·挤在一起的互相抬价',
          bool(_v29c[1] > _vs29[1] and _v29c[0] == _vs29[0]), True,
          f'（集群块 {_v29c[1]:.2f} > 原价 1.0；孤立蓝点 {_v29c[0]:.1f} 不变）')
_b29, _ = plan(192.0, 400.0, EMPTY, EMPTY, EMPTY, EMPTY, PLAYER_SPEED, 30, 2.0,
               edge_w=0.0, prev='none', inertia=0.0, comfort=6.0,
               item=(_xs29, _ys29, _vs29, _vy29), item_w=ITEM_W)
check_val('集群·一趟能捡最多压过单块更近', _b29, 'left',
          '（3 块小P 挤在左侧 → 集群抬价后往左走，而不是捡右侧更近的蓝点）')

# 用例 30：集群判据边界 —— 水平窗 / 时间窗 / 邻居可捡（快出场缩水）三件 + w=0 关闭
_v30f = item_cluster_vals(192.0, 400.0, np.array([100.0, 200.0]),
                          np.array([350.0, 350.0]), np.array([1.0, 1.0]),
                          np.array([3.0, 3.0]))
check_val('集群·水平窗外不算邻居', bool((_v30f == 1.0).all()), True,
          '（相距 100px > 窗 56 → 互不抬价）')
_v30t = item_cluster_vals(192.0, 400.0, np.array([150.0, 160.0]),
                          np.array([350.0, 100.0]), np.array([1.0, 1.0]),
                          np.array([3.0, 3.0]))
check_val('集群·时间窗外不算邻居', bool((_v30t == 1.0).all()), True,
          '（一块还要 12 帧、另一块 95 帧 → 差 83 > 窗 60，一趟收不了）')
_v30d = item_cluster_vals(192.0, 400.0, np.array([150.0, 160.0]),
                          np.array([350.0, 410.0]), np.array([1.0, 1.0]),
                          np.array([3.0, 3.0]))
check_val('集群·快出场的邻居缩水', bool(_v30d[0] < _v30d[1]), True,
          f'（410px 那块只剩约 7 帧出场：抬价 {_v30d[0]:.2f} < 反向 {_v30d[1]:.2f}）')
_v30z = item_cluster_vals(192.0, 400.0, _xs29, _ys29, _vs29, _vy29, w=0.0)
check_val('集群·w=0 原样返回', bool((_v30z == _vs29).all()), True, '（关闭开关）')

# ---- 用例 31–33：智能道具线冲刺（PoC）----

# 用例 31：状态机 —— 满火力+价值够才冲；越线即成功；超时放弃进冷却；火力掉了放弃
_t31 = ItemLineTrip(poc_min=4.0)   # 用例自带阈值：钉「阈值确实在拦」，不跟出厂默认走
check_val('冲线·满火力+价值够→触发',
          bool(_t31.update(400.0, 128, 5.0) and _t31.event == 'start'), True)
check_val('冲线·越线即成功',
          bool(_t31.update(120.0, 128, 5.0) is None
               and _t31.event == 'trip' and _t31.trips == 1), True)
check_val('冲线·火力不满不触发', _t31.update(400.0, 64, 99.0), None,
          '（收集线只在满火力时存在，火力不足冲线毫无收益）')
check_val('冲线·价值不足不触发', _t31.update(400.0, 128, 3.0), None,
          '（3.0 < 用例阈值 4.0 —— 不值得为一两块专门冲）')
_t31b = ItemLineTrip()
_t31b.update(400.0, 128, 5.0)
_ev31 = None
for _ in range(POC_TIMEOUT + 2):
    _t31b.update(400.0, 128, 5.0)
    if _t31b.event == 'giveup':
        _ev31 = 'giveup'
        break
check_val('冲线·超时放弃进冷却', _ev31, 'giveup', f'（{POC_TIMEOUT} 帧冲不过线就放弃，不硬闯）')
_cd31 = 0
for _ in range(POC_COOLDOWN + 2):
    _cd31 += 1
    if _t31b.update(400.0, 128, 5.0) and _t31b.state == 'charging':
        break
check_val('冲线·冷却期间不触发', _cd31, POC_COOLDOWN + 1,
          f'（冷却 {POC_COOLDOWN} 帧内一直 suppress，第 {_cd31} 次才重新冲）')
_t31c = ItemLineTrip()
_t31c.update(400.0, 128, 5.0)
_t31c.update(400.0, 100, 5.0)
check_val('冲线·中途掉火力→放弃', _t31c.event, 'giveup',
          '（掉命/掉火力后收集线不存在了，立刻放弃）')

# 用例 32：冲线吸引 —— 空档期朝收集线走；贴脸弹时压不过安全分
_b32, _s32 = plan(192.0, 400.0, EMPTY, EMPTY, EMPTY, EMPTY, PLAYER_SPEED, 30, 2.0,
                  edge_w=0.0, prev='none', inertia=0.0, comfort=6.0,
                  poc=(192.0, POC_TARGET_Y), poc_w=44.0)
check_val('冲线·空档期朝上冲', _b32, 'up', f'（目标 y={POC_TARGET_Y:.0f} 在正上方）')
_b32b, _s32b = plan(192.0, 224.0, np.array([192.0]), np.array([218.0]),
                    np.array([0.0]), np.array([0.0]), PLAYER_SPEED, 30, 2.0,
                    edge_w=0.0, prev='none', inertia=0.0, comfort=6.0,
                    poc=(192.0, POC_TARGET_Y), poc_w=500.0)
check('冲线·吸引不掩盖死路', _b32b, _s32b, _s32b[_b32b] >= 0.0 and _b32b != 'up',
      '（冲线权重 500 也拉不进会中弹的 up —— 上方被弹幕堵死就冲不上去）')

# 用例 33：冲线期**替代**攻击项（不是叠加）—— 自机已高过输出带（过冲区），
# 若攻击项还在生效，×2 过冲惩罚会把自机拉回带内；冲线替代后仍朝上冲。
# 敌人放远处，只留 attack 目标在近处，隔离出「过冲惩罚」这一个变量。
_en33 = (np.array([300.0]), np.array([150.0]), np.array([24.0]), np.array([24.0]))
_b33a, _ = plan(192.0, 190.0, EMPTY, EMPTY, EMPTY, EMPTY, PLAYER_SPEED, 30, 2.0,
                edge_w=0.0, prev='up', inertia=0.0, comfort=6.0, enemy=_en33,
                attack=(192.0, 150.0), attack_w=20.0, standoff=STANDOFF)
check_val('对照·过冲区攻击项拉回', _b33a, 'down',
          '（无冲线：自机在 standoff 带上方 8px，攻击项把它拉回输出带）')
_b33, _ = plan(192.0, 190.0, EMPTY, EMPTY, EMPTY, EMPTY, PLAYER_SPEED, 30, 2.0,
               edge_w=0.0, prev='up', inertia=0.0, comfort=6.0, enemy=_en33,
               attack=(192.0, 150.0), attack_w=20.0, standoff=STANDOFF,
               poc=(192.0, POC_TARGET_Y), poc_w=44.0)
check_val('冲线·过冲区仍朝上（攻击项已让位）', _b33, 'up',
          '（若攻击项没让位，×2 过冲惩罚会拦住最后一段 —— 冲线永远差几像素）')

# 用例 34：read_frame 道具三态分拣（桩化读内存；纯逻辑不开游戏）——
# state-1 剔除出吸引集；state-2 用终点近似 + vy=0 + 延迟；poc_val 只算 state-0；
# poc_cx = 非追踪（0+2）价值加权质心，散射物用终点参与。
_orig34 = (dodge.read_bullet_frame, dodge.read_player, dodge.read_items, dodge.read_power)
_Z = EMPTY
dodge.read_bullet_frame = lambda p, mb: BulletFrame(
    _Z, _Z, _Z, _Z, _Z, _Z, _Z.astype(np.int32), _Z, _Z, _Z, _Z.astype(np.int32),
    _Z.astype(np.int32), _Z, _Z, _Z, _Z.astype(np.int32), _Z.astype(np.int32),
    _Z.astype(np.int32), _Z, _Z, _Z.astype(np.uint16))
dodge.read_player = lambda p, mb: (192.0, 400.0)
_sl34 = np.array([0, 1, 2])
_xs34 = np.array([100.0, 200.0, 300.0])
_ys34 = np.array([350.0, 350.0, 80.0])
_vy34 = np.array([3.0, 3.0, -123.0])            # state-2 的 vy 字段是垃圾值
_tp34 = np.array([0, 0, 1], dtype=np.int8)       # 小P / 小P / 蓝点
_st34 = np.array([0, 1, 2], dtype=np.int8)       # 普通 / 追踪 / 散射
_tx34 = np.array([0.0, 0.0, 320.0])
_ty34 = np.array([0.0, 0.0, 90.0])
dodge.read_items = lambda p, mb: (_sl34, _xs34, _ys34, _vy34, _tp34, _st34,
                                  _tx34, _ty34)
dodge.read_power = lambda p, mb: 128
_w34 = dodge.read_frame(None, None, use_enemy=False, use_laser=False, use_item=True)
(dodge.read_bullet_frame, dodge.read_player, dodge.read_items, dodge.read_power) = _orig34
_it34 = _w34['item']
check_val('分拣·追踪中道具剔除出吸引集', len(_it34[0]), 2,
          '（state-1 8px/帧 自投罗网，不必吸引，模型也不适用）')
check_val('分拣·散射道具用终点近似',
          (round(float(_it34[0][1]), 1), round(float(_it34[1][1]), 1)), (320.0, 90.0),
          '（位置 = targetPosition，不是插值中的位置；vy 垃圾值不带入）')
check_val('分拣·散射 vy=0 + 延迟',
          (float(_it34[3][1]), float(_it34[4][1])), (0.0, SCATTER_AVG),
          f'（散射结束后从静止开始落，+{SCATTER_AVG:.0f} 帧平均剩余）')
check_val('分拣·可转化价值只算 state-0', _w34['poc_val'], 1.0,
          '（1 块小P；追踪中/散射都不算 —— 它们不会被收集线转化）')
check_val('分拣·冲线目标 x = 非追踪质心', round(_w34['poc_cx'], 1), 232.0,
          '（(100×1.0 + 320×1.5)/2.5 —— 散射物用终点参与质心）')
check_val('分拣·火力值传出', _w34['power'], 128)

# 用例 35：散射延迟 —— delays 把到达/出局时刻整体后移（散射物到终点前不下落）
_it35 = (np.array([192.0]), np.array([300.0]), np.array([1.0]), np.array([3.0]))
_c35a = item_cost(192.0, 400.0, *_it35)
_c35b = item_cost(192.0, 400.0, *_it35, delays=np.array([60.0]))
check_val('散射延迟·未延迟可捡', bool(_c35a < 1.0), True, f'（等效距离 {_c35a:.2f}）')
check_val('散射延迟·+60 帧判成干等', bool(_c35b >= 1.0), True,
          f'（同一块 +60 帧 → 等效距离 {_c35b:.2f}：到终点前不追，不干等）')

# ---- 用例 36：激光额外安全余量（LASER_MARGIN）----
# 激光不动、一道能挂几十帧。只按「别撞上」算的话，间隙刚过 comfort 就算安全，
# 软项立刻把自机拉回激光边上输出 —— 惯性 / 反应延迟一推就滑进去（实测报的「撞激光上」）。
# 场景：一条竖激光在自机左边 10px（表面距 6px），进攻吸引把自机往上拉。

def laser_case(margin):
    lz = (np.array([100.0]), np.array([0.0]), np.array([np.pi / 2]),
          np.array([0.0]), np.array([500.0]), np.array([500.0]),
          np.array([8.0]), np.array([0.0]))
    save = dodge.LASER_MARGIN
    dodge.LASER_MARGIN = margin
    try:
        return dodge.plan(110.0, 384.0, np.array([]), np.array([]),
                          np.array([]), np.array([]), 4.39, 5, 0.0,
                          24.0, 'none', 0.7, None, lz, 1.0,
                          (110.0, 200.0), 30.0)
    finally:
        dodge.LASER_MARGIN = save


_best_on, _sc_on = laser_case(dodge.LASER_MARGIN)
_best_off, _sc_off = laser_case(0.0)
check_val('激光余量·贴边的方向被压成不安全', bool(_sc_on['none'] < 0.0), True,
          f'（none 方向 {_sc_on["none"]:.1f}px）')
check_val('激光余量·关掉余量时贴边仍算「安全」（旧行为对照）',
          bool(_sc_off['none'] > 0.0), True, f'（none 方向 {_sc_off["none"]:.1f}px）')
check_val('激光余量·远离激光的方向分数更高', bool(_sc_on['right'] > _sc_on['none']), True,
          f'（right {_sc_on["right"]:.1f} > none {_sc_on["none"]:.1f}）')

# ---- 用例 37：横扫过来的激光必须带时间维（拿当前几何算未来落点 = 刻舟求剑）----
# 实测症状（Laevatein）：自机站在一条正扫过来的激光路径上，脚本判成安全不动 → 撞上。
# 依据：`endOffset += speed`（offsets.L_OFF_ENDOFF），线段整体沿 angle 平移。
# 场景：一条向右扫的水平激光，当前线段 [−200, 0]、宽 8、6px/帧；自机 (200, 384)。
# 34 帧后它扫过自机 —— 只看当前几何完全看不到这件事。
_SWEEP = (np.array([-200.0]), np.array([384.0]), np.array([0.0]),
          np.array([0.0]), np.array([200.0]), np.array([200.0]),
          np.array([8.0]), np.array([6.0]))
_TS40 = np.arange(1, 41, dtype=np.float32)
_g_moving = float(dodge.laser_gap(np.array([200.0]), np.array([384.0]),
                                  *_SWEEP, ts=_TS40).min())
_g_static = float(dodge.laser_gap(np.array([200.0]), np.array([384.0]),
                                  *_SWEEP).min())
check_val('横扫激光·带 ts 时预判出「40 帧内会被扫到」', bool(_g_moving < 0.0), True,
          f'（窗内最小间隙 {_g_moving:.1f}px）')
check_val('横扫激光·只看当前几何会误判为安全（旧行为对照）', bool(_g_static > 0.0), True,
          f'（当前线段离自机 {_g_static:.1f}px）')
_best_sw, _sc_sw = dodge.plan(200.0, 384.0, np.array([]), np.array([]),
                              np.array([]), np.array([]), 4.39, 40, 0.0,
                              24.0, 'none', 0.7, None, _SWEEP)
check_val('横扫激光·原地不动被判成会撞上（不再站着挨打）',
          bool(_sc_sw['none'] < 0.0), True, f'（none 方向 {_sc_sw["none"]:.1f}px）')

# 生长阶段：偏移先伸长到长度上限，之后起点才跟着走。
# 少了这一条，刚生成 10px 的激光会被当成一条已经平移出去的长条，让自机提前跑开。
_GROW = (np.array([0.0]), np.array([0.0]), np.array([0.0]),
         np.array([0.0]), np.array([10.0]), np.array([200.0]),
         np.array([10.0]), np.array([6.0]))
_g_grow = float(dodge.laser_gap(np.array([30.0]), np.array([0.0]), *_GROW,
                                ts=np.array([10.0], dtype=np.float32)).min())
check_val('横扫激光·生长阶段起点不动（10 帧后 [0,70] 仍覆盖 x=30）',
          bool(_g_grow < 0.0), True, f'（间隙 {_g_grow:.1f}px）')

# ---- 用例 38：激光**轴原点**平移也要预判（Laevatein 横扫的真实机制）----
# 实测（`_tmp/laser_trace` 落盘 42716 条激光样本，Laevatein 符卡）：
#   · 槽里的 speed 字段恒为 0 —— 它只描述 offset 前进，不是移动；
#   · 移动发生在 **pos** 上：+6px/帧，比自机 4.39px/帧还快，从后面追上自机；
#   · 被击中那几帧 gap 只有 0~3px，自机一直在激光右边缘勉力维持 → 必然被追死。
# 场景：竖直激光在自机左侧 36px，以 +6px/帧 右移 → 第 7 帧压到自机身上。
_SIDE = (np.array([150.0]), np.array([40.0]), np.array([np.pi / 2]),
         np.array([0.0]), np.array([400.0]), np.array([400.0]),
         np.array([12.0]), np.array([0.0]))
_TS20 = np.arange(1, 21, dtype=np.float32)
_SIDE_PX, _SIDE_PY = 192.0, 300.0
_g_still = float(dodge.laser_gap(np.array([_SIDE_PX]), np.array([_SIDE_PY]),
                                 *_SIDE, ts=_TS20).min())
_g_move = float(dodge.laser_gap(np.array([_SIDE_PX]), np.array([_SIDE_PY]),
                                *_SIDE, lvx=np.array([6.0]), lvy=np.array([0.0]),
                                ts=_TS20).min())
check_val('轴原点平移·按静止算会误判为一直安全（旧行为对照）',
          bool(_g_still > 0.0), True, f'（20 帧内最小间隙 {_g_still:.1f}px）')
check_val('轴原点平移·带上速度就预判出会被压到', bool(_g_move < 0.0), True,
          f'（20 帧内最小间隙 {_g_move:.1f}px）')
check_val('轴原点平移·选的方向不是「站在原地挨压」',
          bool(dodge.plan(_SIDE_PX, _SIDE_PY, np.array([]), np.array([]),
                          np.array([]), np.array([]), 4.39, 12, 0.0, 24.0, 'none',
                          0.7, None,
                          (_SIDE[0], _SIDE[1], _SIDE[2], _SIDE[3], _SIDE[4],
                           _SIDE[5], _SIDE[6], _SIDE[7],
                           np.array([6.0]), np.array([0.0])))[1]['none'] < 0.0), True,
          '（none 方向被压成负间隙）')

# ---- 用例 39：LaserMotion 差分（横扫速度槽里读不到，只能这么拿）----
class _FakeLF:
    """够用的 LaserFrame 替身：只带 LaserMotion 要读的字段"""

    def __init__(self, slots, xs, ys, angle=None, phase=0, timer=0):
        n = len(slots)
        self.slots, self.xs, self.ys = slots, xs, ys
        self.angles = (np.full(n, np.pi / 2, dtype=np.float32) if angle is None
                       else np.asarray(angle, dtype=np.float32))
        self.starts = np.zeros(n, dtype=np.float32)
        self.ends = np.full(n, 400.0, dtype=np.float32)
        self.phases = np.full(n, phase, dtype=np.int32)
        self.timers = np.full(n, timer, dtype=np.int32)


_mo = dodge.LaserMotion()
_mo.speeds(_FakeLF(np.array([0, 1]), np.array([100.0, 300.0]), np.array([40.0, 40.0])))
_vx, _vy, _om = _mo.speeds(_FakeLF(np.array([0, 1]), np.array([106.0, 290.0]),
                                   np.array([40.0, 40.0])))
check_val('差分·同槽右移 6px/帧 读成 +6', float(_vx[0]), 6.0)
check_val('差分·同槽左移 10px/帧 读成 −10', float(_vx[1]), -10.0)
check_val('差分·纵移读进 vy', float(_vy[1]), 0.0)
_vx3, _, _ = _mo.speeds(_FakeLF(np.array([0]), np.array([300.0]), np.array([40.0])))
check_val('差分·槽复用（位移超阈值）速度记 0，不伪造', float(_vx3[0]), 0.0)

# ---- 用例 44：旋转激光（angle 逐帧变，实测 2.25°/帧）----
# 旧实现「angle 一变就判槽复用、速度记 0」，旋转激光等于完全没有运动预测。
# 实测样本：同一槽连续 19 帧 pos / speed / 线段全不动，只有 angle 每帧 +2.25°。
_rot = dodge.LaserMotion()
_rot.speeds(_FakeLF(np.array([0]), np.array([192.0]), np.array([80.0]),
                    angle=np.array([np.pi]), phase=0, timer=10))
_vr, _yr, _omr = _rot.speeds(_FakeLF(np.array([0]), np.array([192.0]), np.array([80.0]),
                                     angle=np.array([np.pi + 0.0393]), phase=0, timer=11))
check_val('旋转激光·角速度差分出来（pos 不动也认）', round(float(_omr[0]), 4), 0.0393,
          '（2.25°/帧 = 0.0393 rad/帧；旧实现这里记 0）')
check_val('旋转激光·pos 不动时线速度仍是 0', (float(_vr[0]), float(_yr[0])), (0.0, 0.0))
_reuse = dodge.LaserMotion()
_reuse.speeds(_FakeLF(np.array([0]), np.array([192.0]), np.array([80.0]),
                      angle=np.array([np.pi]), phase=1, timer=20))
_vx4, _, _om4 = _reuse.speeds(_FakeLF(np.array([0]), np.array([192.0]), np.array([80.0]),
                                      angle=np.array([np.pi]), phase=0, timer=0))
check_val('槽复用·阶段倒退（发射→预警）速度与角速度都记 0',
          (float(_vx4[0]), float(_om4[0])), (0.0, 0.0))
# 旋转外推：竖线以 0.0393 rad/帧 转 20 帧 ≈ 45°，自机在它的扫描侧
_ROT_L = (np.array([192.0]), np.array([80.0]), np.array([np.pi / 2]),
          np.array([0.0]), np.array([400.0]), np.array([400.0]),
          np.array([12.0]), np.array([0.0]))
_ts20 = np.arange(1, 21, dtype=np.float32)
_G_NOROT = float(dodge.laser_gap(np.array([260.0]), np.array([380.0]), *_ROT_L,
                                 lom=np.array([0.0]), ts=_ts20).min())
_G_ROT = float(dodge.laser_gap(np.array([260.0]), np.array([380.0]), *_ROT_L,
                               lom=np.array([-0.0393]), ts=_ts20).min())
check_val('旋转外推·不带角速度算成一直安全（旧行为对照）',
          bool(_G_NOROT > 0.0), True, f'（20 帧最小间隙 {_G_NOROT:.1f}px）')
check_val('旋转外推·带上角速度预判出会被扫到',
          bool(_G_ROT < _G_NOROT - 20.0), True,
          f'（{_G_NOROT:.1f} → {_G_ROT:.1f}px：线段 20 帧转过 45°）')

# ---- 用例 45：子弹的加速 / 转向外推（bullet_paths）----
# 只按当前 vx/vy 匀速外推时：加速弹偏近、转向弹在转向帧之后整段错。
def _bf1(x, y, vx, vy, exf=0, angle=0.0, speed=0.0, timer=0, hold=0,
         ax=0.0, ay=0.0, rot=0.0, ivl=0, num=0, maxn=0, rate=0.0, srate=0.0,
         dcs=0.0, state=1):
    """单颗弹的 BulletFrame（默认值 = 普通弹）"""
    f1 = lambda v: np.array([v], dtype=np.float32)      # noqa: E731
    i1 = lambda v: np.array([v], dtype=np.int32)        # noqa: E731
    return BulletFrame(np.array([0]), f1(x), f1(y), f1(vx), f1(vy), f1(3.0),
                       i1(exf), f1(angle), f1(speed), f1(dcs), i1(timer), i1(hold),
                       f1(ax), f1(ay), f1(rot), i1(ivl), i1(num), i1(maxn),
                       f1(rate), f1(srate), np.array([state], dtype=np.uint16))


_fx_a, _fy_a = dodge.bullet_paths(
    _bf1(100.0, 100.0, 0.0, 4.0, exf=EXF_ACCEL, speed=4.0, ay=0.5, hold=60), 10, 192.0, 384.0)
check_val('加速弹·10 帧按抛物线推进（不是匀速直线）',
          round(float(_fy_a[-1, 0]), 1), 167.5,
          '（Σ(4+0.5k) = 67.5；匀速外推只有 140 —— 差 27.5px）')
_fx_a0, _fy_a0 = dodge.bullet_paths(
    _bf1(100.0, 100.0, 0.0, 4.0, exf=EXF_ACCEL, speed=4.0, ay=0.5, hold=3), 10, 192.0, 384.0)
check_val('加速弹·计时到 hold 就停（之后匀速）',
          round(float(_fy_a0[-1, 0]), 1), 100.0 + (4.5 + 5.0 + 5.5) + 5.5 * 7,
          '（前 3 帧加速，之后 v=5.5 匀速）')

_fx_t, _fy_t = dodge.bullet_paths(
    _bf1(100.0, 100.0, 0.0, 4.0, exf=EXF_TURN_REL, angle=np.pi / 2, speed=4.0,
         ivl=5, rot=-np.pi / 2, maxn=2, dcs=4.0), 8, 192.0, 384.0)
check_val('转向弹·转向前的速度插值（5 帧只走 12px 而不是 20px）',
          round(float(_fy_t[4, 0]), 1), 112.0,
          '（原版间隔内 bulletSpeed 从 speed 线性衰减到 0）')
check_val('转向弹·转向帧换成新方向（−90° → 朝 +x 走）',
          (round(float(_fx_t[5, 0]), 1), round(float(_fy_t[5, 0]), 1)), (104.0, 112.0))
_fx_m, _fy_m = dodge.bullet_paths(
    _bf1(100.0, 100.0, 0.0, 4.0, exf=EXF_TURN_AIM, angle=np.pi / 2, speed=4.0,
         ivl=1, rot=0.0, maxn=1, dcs=4.0), 4, 300.0, 100.0)
check_val('转向弹·EXF_TURN_AIM 转向后朝自机飞',
          (round(float(_fx_m[1, 0]), 1), round(float(_fy_m[1, 0]), 1)), (104.0, 103.9),
          '（转向角 = 朝自机角；第 1 帧弹已下移 4px 到 y=104，自机在 y=100 → 略朝上）')
_fx_p, _fy_p = dodge.bullet_paths(
    _bf1(100.0, 100.0, 0.0, 4.0, exf=0, speed=4.0), 5, 192.0, 384.0)
check_val('普通弹·仍走原来的直线（快路径逐位一致）',
          (round(float(_fx_p[-1, 0]), 3), round(float(_fy_p[-1, 0]), 3)), (100.0, 120.0))

# ---- 用例 46：消散阶段的弹不进威胁（read_frame 过滤 state 5）----
_orig43 = (dodge.read_bullet_frame, dodge.read_player)
dodge.read_bullet_frame = lambda p, mb: _bf1(192.0, 380.0, 0.0, 4.0, state=5)
dodge.read_player = lambda p, mb: (192.0, 400.0)
_w43 = dodge.read_frame(None, None, use_enemy=False, use_laser=False, use_item=False)
check_val('消散弹·无判定，不进威胁集', len(_w43['bx']), 0,
          '（原版只有 FIRED 判死，躲消散弹是纯浪费移动）')
dodge.read_bullet_frame = lambda p, mb: _bf1(192.0, 380.0, 0.0, 4.0, state=3)
_w43b = dodge.read_frame(None, None, use_enemy=False, use_laser=False, use_item=False)
check_val('生成中弹·照旧进威胁集（它马上就判死）', len(_w43b['bx']), 1)
(dodge.read_bullet_frame, dodge.read_player) = _orig43

# ---- 用例 47：plan() 真的吃下了 bf（对照：不给就是直线）----
_PX44, _PY44 = 192.0, 300.0
_BX44, _BY44 = np.array([192.0]), np.array([200.0])
_VX44, _VY44 = np.array([0.0]), np.array([4.0])
_b44_line, _sc44_line = plan(_PX44, _PY44, _BX44, _BY44, _VX44, _VY44,
                             PLAYER_SPEED, 10, 0.0)
_b44_acc, _sc44_acc = plan(_PX44, _PY44, _BX44, _BY44, _VX44, _VY44,
                           PLAYER_SPEED, 10, 0.0,
                           bf=_bf1(192.0, 200.0, 0.0, 4.0, exf=EXF_ACCEL,
                                   speed=4.0, ay=0.4, hold=60))
check_val('plan·给了 bf 就按加速弹算（同一局面间隙更小）',
          bool(_sc44_acc['none'] < _sc44_line['none']), True,
          f'（none 方向 {_sc44_line["none"]:.1f} → {_sc44_acc["none"]:.1f}px）')

# ---- 用例 40：激光的独立长前瞻（LASER_HORIZON）----
# 「激光要出了还在打敌人」的机制：16 帧窗口（≈96px）**之外**判成安全 → 进攻吸引
# 把自机按在输出位上；等激光进窗口，自机已来不及垂直逃出 368px 长的覆盖带。
# 场景：一条横扫激光在自机右侧 140px 外，以 6px/帧 从右往左压过来。
#   · 16 帧窗口：它只走 96px，还差 44px 才碰到 → 判安全（旧行为）
#   · 40 帧窗口：它走 240px，早已压过自机 → 判危险
_SWEEP2 = (np.array([332.0]), np.array([40.0]), np.array([np.pi / 2]),
           np.array([0.0]), np.array([400.0]), np.array([400.0]),
           np.array([12.0]), np.array([0.0]))
_LVX, _LVY = np.array([-6.0]), np.array([0.0])
_PX2, _PY2 = 192.0, 300.0
_g16 = float(dodge.laser_gap(np.array([_PX2]), np.array([_PY2]), *_SWEEP2,
                             lvx=_LVX, lvy=_LVY,
                             ts=np.arange(1, 17, dtype=np.float32)).min())
_g40 = float(dodge.laser_gap(np.array([_PX2]), np.array([_PY2]), *_SWEEP2,
                             lvx=_LVX, lvy=_LVY,
                             ts=np.arange(1, 41, dtype=np.float32)).min())
check_val('激光长前瞻·16 帧窗口看不见远处压过来的激光（旧行为对照）',
          bool(_g16 > 0.0), True, f'（窗内最小间隙 {_g16:.1f}px）')
check_val('激光长前瞻·40 帧窗口提前发现它', bool(_g40 < 0.0), True,
          f'（窗内最小间隙 {_g40:.1f}px）')
_sc_l = dodge.plan(_PX2, _PY2, np.array([]), np.array([]), np.array([]), np.array([]),
                   4.39, 16, 0.0, 24.0, 'none', 0.7, None,
                   (_SWEEP2[0], _SWEEP2[1], _SWEEP2[2], _SWEEP2[3], _SWEEP2[4],
                    _SWEEP2[5], _SWEEP2[6], _SWEEP2[7], _LVX, _LVY))[1]
check_val('激光长前瞻·horizon=16 时 plan 仍按 40 帧评激光（不再被按在输出位）',
          bool(_sc_l['none'] < 0.0), True, f'（none 方向 {_sc_l["none"]:.1f}px）')

# ---- 用例 41：预警激光的矩形避让是**软项**（横向逃不掉，得沿轴线出去）----
# 场景直接取自实测（Laevatein frame 3590）：预警线在屏幕最左，自机在右侧 49px。
#   · 只看真实几何：横向 37px 余量 → 判「安全」→ 进攻吸引把自机按在输出位继续打
#   · 矩形软项：人在轴线区间里 → 越靠中点代价越高 → 请自机沿轴线往外走
# **必须是软项**：这里算的是「逃出区间还需多少」，与碰撞间隙不同量纲 ——
# 混进安全分会把「撞敌人 −10」这种真威胁盖掉（实测症状：自机为了躲激光径直撞进 BOSS）。
_WARN_LZ = (np.array([0.0]), np.array([40.0]), np.array([np.pi / 2]),
            np.array([32.0]), np.array([400.0]), np.array([368.0]),
            np.array([24.0]), np.array([0.0]),
            np.array([0.0]), np.array([0.0]))
_RECT = np.array([True])
_g_plain = float(dodge.laser_gap(np.array([49.2]), np.array([209.5]), *_WARN_LZ).min())
check_val('预警矩形·只看真实几何判成安全（横向还有 37px 余量）', bool(_g_plain > 0.0),
          True, f'（间隙 {_g_plain:.1f}px）')
_c_mid = float(dodge.warn_rect_cost(49.2, 256.0, *_WARN_LZ[:5], _RECT))
_c_edge = float(dodge.warn_rect_cost(49.2, 78.0, *_WARN_LZ[:5], _RECT))
_c_out = float(dodge.warn_rect_cost(49.2, 20.0, *_WARN_LZ[:5], _RECT))
check_val('预警矩形·区间中点代价最高', bool(_c_mid > 0.9), True, f'（代价 {_c_mid:.3f}）')
check_val('预警矩形·贴近端点代价很低', bool(_c_edge < 0.1), True, f'（代价 {_c_edge:.3f}）')
check_val('预警矩形·已出区间代价为 0', _c_out, 0.0, '（y=20 在轴线区间 [72, 440] 之外）')
_b_on, _sc_on2 = dodge.plan(49.2, 209.5, np.array([]), np.array([]), np.array([]),
                            np.array([]), 4.39, 16, 2.0, edge_w=42.0, prev='none',
                            inertia=1.1, laser=_WARN_LZ, comfort=1.0, margin_w=8.0,
                            switch_margin=0.4, risk=1.0, laser_rect=_RECT)
# 斜向也算数：`ur` 同样在沿轴线往外走，而且横向离激光更远、安全分更高（安全永远优先）
check_val('预警矩形·plan 从输出位改选沿轴线往外走', _b_on in ('up', 'ur', 'ul'), True,
          f'（选 {_b_on}，up {_sc_on2["up"]:.1f}px，none {_sc_on2["none"]:.1f}px）')

# ---- 用例 42：敌人也要预判（池里没有速度字段，只能逐帧差分）----
# 实测症状「撞到敌人身上死亡」的机制：前瞻窗口里子弹（vx/vy）和激光（laser_gap 的 ts）
# 都有速度外推，**唯独敌人被当成静止的** —— 而 BOSS 会移动（Laevatein 实测蕾米莉亚
# 本体逐帧位移，AABB 56×56）。16 帧的误差全算在自机头上。撞敌人必死，这条威胁却是
# 唯一没做运动预测的。
_em = dodge.EnemyMotion()
_v0 = _em.speeds(np.array([3]), np.array([100.0]), np.array([200.0]), np.array([500]))
check_val('敌人差分·首帧无基线记 0', (float(_v0[0][0]), float(_v0[1][0])), (0.0, 0.0))
_v1 = _em.speeds(np.array([3]), np.array([106.0]), np.array([198.0]), np.array([499]))
check_val('敌人差分·同槽移动读成速度', (float(_v1[0][0]), float(_v1[1][0])), (6.0, -2.0))
_v2 = _em.speeds(np.array([3]), np.array([400.0]), np.array([198.0]), np.array([600]))
check_val('敌人差分·life 变大（槽被新敌人接管）速度记 0', float(_v2[0][0]), 0.0)
_v3 = _em.speeds(np.array([3]), np.array([500.0]), np.array([198.0]), np.array([599]))
check_val('敌人差分·位移超阈值不伪造速度', float(_v3[0][0]), 0.0)

_ts16 = np.arange(1, 17, dtype=np.float32)
_exs = np.full(16, 200.0, dtype=np.float32)
_eys = (300.0 - 4.39 * _ts16).astype(np.float32)
_e_fix = (np.array([200.0]), np.array([100.0]), np.array([56.0]), np.array([56.0]))
_g_s = float(dodge.enemy_gap(_exs, _eys, *_e_fix, ts=_ts16).min())
_g_m = float(dodge.enemy_gap(_exs, _eys, *_e_fix, evx=np.array([0.0]),
                             evy=np.array([4.0]), ts=_ts16).min())
check_val('敌人外推·静止敌人的间隙与旧行为一致', bool(_g_s > 100.0), True, f'（{_g_s:.1f}px）')
check_val('敌人外推·迎面下压的敌人把间隙从 102px 压到 38px',
          bool(abs(_g_m - 37.76) < 1.0), True, f'（外推后 {_g_m:.1f}px）')

# 端到端：敌人朝自机冲下来，外推与否决定「这一格安全吗」
_e_dive = (np.array([200.0]), np.array([100.0]), np.array([56.0]), np.array([56.0]))
_kw = dict(edge_w=0.0, prev='none', inertia=0.0, enemy=_e_dive, comfort=1.0, margin_w=8.0)
_b_no, _sc_no = dodge.plan(200.0, 300.0, np.array([]), np.array([]), np.array([]),
                           np.array([]), 4.39, 16, 2.0, **_kw)
_b_mv, _sc_mv = dodge.plan(200.0, 300.0, np.array([]), np.array([]), np.array([]),
                           np.array([]), 4.39, 16, 2.0,
                           enemy_mv=(np.array([0.0]), np.array([12.0])), **_kw)
check_val('敌人外推·不外推时原地被算成安全', bool(_sc_no['none'] > 0.0), True,
          f'（none {_sc_no["none"]:+.1f}px，敌人被当成静止）')
check_val('敌人外推·外推后同一格算成必死', bool(_sc_mv['none'] < 0.0), True,
          f'（none {_sc_mv["none"]:+.1f}px）')

# ---- 用例 43：敌人余量（撞敌人与擦子弹不能同一个定价）----
# `comfort = 1px` 是用户拍板的手感基准（软项的闸门），于是池内「间隙 1px」与「间隙 25px」
# 的余量分差只有 `margin_w`（8 分，且被 MARGIN_CAP 截断），而进攻吸引 55 / 矩形避让 80
# 都是几十上百 —— 自机会为了软项收益主动选「擦着敌人 1px 过去」。
# 子弹擦过去是常态，**敌人擦过去是死亡**：给它单独一截余量（同 LASER_MARGIN 的手法）。
check_val('敌人余量·默认值', dodge.ENEMY_MARGIN, 48.0)
_b_far, _sc_far = dodge.plan(192.0, 200.0, np.array([]), np.array([]), np.array([]),
                             np.array([]), 4.39, 16, 2.0, **_kw)
# 自机 (192,200)：敌人 AABB 下边缘 128 → 原始间隙 72px，扣掉 PLAYER_R+safe+余量后仍为正
check_val('敌人余量·输出位（离 72px）仍然可用', bool(_sc_far['none'] > 0.0), True,
          f'（none {_sc_far["none"]:+.1f}px = 72 − 4 − 48）')
_b_close, _sc_close = dodge.plan(192.0, 170.0, np.array([]), np.array([]), np.array([]),
                                 np.array([]), 4.39, 16, 2.0, **_kw)
# 自机 (192,170)：原始间隙 42px。不加余量是 +38（「够安全」），加了才是 −10（不许去）
check_val('敌人余量·贴到 42px 被算成负（48px 内不算安全）',
          bool(_sc_close['none'] < 0.0), True,
          f'（none {_sc_close["none"]:+.1f}px —— 不加余量会是 +38.0px）')
check_val('敌人余量·plan 不选往上撞敌人的方向', _b_close not in ('up', 'ul', 'ur'), True,
          f'（选 {_b_close}）')

# ---- 空旷区吸引 / 自动回中（软项，只在够安全的方向间决胜负）----
# 素材：一帧**真实**密集弹幕（FINAL STAGE 符卡实战采样，48 颗）固化在这里 ——
# 护栏不依赖游戏也能复现。断言的是**不变量**，不是某个具体方向。
_SNAP = base64.b64decode(
    "EKlTQ6wkhz9MsKtDLs2bQ8rxtkOU5KVDsjakQ2Yxs0MqKINDf0fBQ24MpkPrXpZDJlmNQ0PSsEOcdpZD7KdVQ/0mkkMwlIBD"
    "2vSCQ7A7rkPcxEJD5oZgQyw5ckOw6alDQGhQQ7jNMEM5U41DccKEQ5DKfEMutwJDytRXQ2LI8kLS9flClKTlQm77fkNtGoBD"
    "TIPkQqlIl0IrK9lBqmPKQsrFa0P4gVVDWs5VQrRSo0HtTnpBOAIAQvi1YUKqfFZCWnHfQwCgukOblIBD/iZIQ2S2c0I2BvFC"
    "FOFKQjazyEKE+FZDuyBIQlzMmkMP2J9DI4hGQ8alKEP+X2VDjnaiQwt4kUMX8dtD/7LfQ7HD2ENiy7RDkEbiQ3lC10O8e61D"
    "4gG+Qxvxp0Ox/X9DCFtFQ4hPnUOMdYFDFGLRQ/dM2kOnabVDIEy+Q2pEukN087tDkwXAQ3KSj0Pqk3xDq0NeQzj4WUPJi05D"
    "yjvVQ64/x0PYIdxD99bCQ8qmzkNSCMBD9LPlPZvPS7/kVc0/+9CnP+Hq5z/5pb8/SKPKP9DU8D+Ismw/3F8KQN1Qzz9M1LU/"
    "ztScP5oc/z/iFbY/+cT0Pl8kqj/bB5Y//CqePwskGUDrY5k+sfQmP7WhXD9IKwFAFCDsPuifsT27oKs/n6WRP1iwfD+/Leu+"
    "u54xP7BNOL+pHhW/Gik3v1g+jz+xS5E/pw05v744nb+XeO6/atJkv5seXj/AgxM/G5b8vzJAIsCscSfAw6MVwHUb9r8lN/y/"
    "umvIP7jOsD+9IbA/N6FZPxFV3r65Y+w9pA0SvzEMnL2wYIg/uM4Tv/SBAECsnxJAp9J6P1EHKD9PI6g/e0AWQK1r/T9l+41A"
    "dzKRQHZDi0CIS0BAr6KCQGWQdEDnNDVAT0ROQJvNLEDVcOA/AYSHP/WtHEB04eQ/u96UQONpnUBZd1VAGlpkQGeZXUC/a2BA"
    "pD1nQH0RFkB/OfI/MXC/Pxo+uD9YGqU/u1CtQAsYnkAD07RAkEuZQLwmpkBbPZZAAABAQAAAQEAAAEBAAABAQAAAQEAAAEBA"
    "AABAQAAAQEAAAEBAAABAQAAAQEAAAEBAAABAQAAAQEAAAEBAAABAQAAAQEAAAABBAAAAQQAAAEEAAEBAAABAQAAAQEAAAEBA"
    "AABAQAAAQEAAAEBAAABAQAAAQEAAAEBAAAAAQQAAAEEAAEBAAABAQAAAQEAAAEBAAABAQAAAQEAAAEBAAABAQAAAQEAAAEBA"
    "AAAAQQAAAEEAAABBAAAAQQAAAEEAAABB")
_SBX, _SBY, _SVX, _SVY, _SBR = (np.frombuffer(_SNAP[i * 192:(i + 1) * 192], dtype=np.float32)
                                for i in range(5))
_SPX, _SPY = 156.9, 337.6
_DIRV = {n: (a, b) for n, a, b, _ in DIRS}


def _soft_pos(px, py, name, step):
    """候选方向在 step 帧后的落点（与 plan() 同式，含场地裁剪）"""
    dx, dy = _DIRV[name]
    return (min(max(px + dx * PLAYER_SPEED * step, FIELD_X0), FIELD_X1),
            min(max(py + dy * PLAYER_SPEED * step, FIELD_Y0), FIELD_Y1))


def _snap_plan(**kw):
    """在固化帧上跑 plan()；comfort 取负无穷 → 强制走「软项全额参与」那条路"""
    return plan(_SPX, _SPY, _SBX, _SBY, _SVX, _SVY, PLAYER_SPEED, 100, 0.1, 32.0,
                'none', 0.8, None, None, -1e9, margin_w=0.0, switch_margin=0.0, **kw)


_E = np.array([], dtype=np.float32)
check_val('空旷度·无弹时为 0', bool(clearance_cost(192.0, 300.0, _E, _E) == 0.0), True, '')
check_val('空旷度·弹越近越大',
          bool(clearance_cost(192.0, 300.0, np.array([192.0]), np.array([300.0]))
               > clearance_cost(192.0, 300.0, np.array([192.0]), np.array([380.0]))),
          True, '（正中 > 距 80px）')
check_val('空旷度·超出评价半径不计',
          bool(clearance_cost(192.0, 300.0, np.array([192.0]),
                              np.array([300.0 + CLEAR_R + 5.0])) == 0.0), True, '')
check_val('回中·场地中心为 0', bool(recenter_cost(FIELD_CX, FIELD_CY) == 0.0), True, '')
check_val('回中·自由半径处仍为 0（带内不干预）',
          bool(recenter_cost(FIELD_CX + CENTER_R, FIELD_CY) == 0.0), True,
          f'（自由半径 {CENTER_R:g}px）')
check_val('回中·带外单调增',
          bool(recenter_cost(FIELD_CX + CENTER_R + 100.0, FIELD_CY)
               > recenter_cost(FIELD_CX + CENTER_R + 50.0, FIELD_CY)), True, '')

_cc = {n: clearance_cost(*_soft_pos(_SPX, _SPY, n, CLEAR_STEP), _SBX, _SBY, CLEAR_R)
       for n in _DIRV}
_rc = {n: recenter_cost(*_soft_pos(_SPX, _SPY, n, ATTACK_STEP)) for n in _DIRV}
_b1, _s1 = _snap_plan(clear_w=1e6)
_b2, _s2 = _snap_plan(center_w=1e6)
check_val('空旷项·权重极大时选中该帧最空旷的方向',
          bool(abs(_cc[_b1] - min(_cc.values())) < 1e-6), True,
          f'（{_b1} 空旷度 {_cc[_b1]:.3f}，九向 {min(_cc.values()):.3f}..{max(_cc.values()):.3f}）')
check_val('回中项·权重极大时选中离场地中心最近的方向',
          bool(abs(_rc[_b2] - min(_rc.values())) < 1e-6), True,
          f'（{_b2} 回中代价 {_rc[_b2]:.3f}）')
# DO_NOT_REVERT 的核心不变量：软项再大也不许把自机送进会中弹的方向
check_val('两个新软项·权重极大也不会选中会中弹的方向',
          bool(_s1[_b1] >= 0.0 and _s2[_b2] >= 0.0), True,
          f'（间隙 {_s1[_b1]:.1f} / {_s2[_b2]:.1f}px；该帧 ul/dr 方向是负的）')

print('\n全部通过' if OK else '\n有失败项')
sys.exit(0 if OK else 1)