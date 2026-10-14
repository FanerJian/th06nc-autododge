"""th06nc 自动躲避 + 自动攻击 + 自动捡道具 + 自动灵击 —— 读内存 → 轨迹外推评分 → SendInput

四个输出：
  方向：9 个候选方向各把自机与子弹外推 horizon 帧，取"整个时间窗内最小间隙"最大者。
        局面宽裕（有方向间隙 ≥ comfort）时，才让贴边惩罚 / 惯性 / 进攻吸引 / 道具吸引 /
        空旷区吸引 / 自动回中在够安全的方向间决胜负；紧张时它们只允许在「与最优方向同样
        安全」（相差 ≤ risk 且间隙 ≥ 0）的方向间决胜负 —— 安全判断永不被"想打谁"覆盖，
        但也不至于 boss 战弹幕一密就全程只躲不打。
        其中**空旷区吸引**管的是「别逐帧钻缝」：局部间隙最大的方向常只是弹与弹之间的
        一条缝，钻进去越走越窄；同等安全时优先退向弹少的一带。**自动回中**管的是
        「别在角落与顶部恋战」：离场地中心超出自由半径才牵引，带内完全自由。
        最后过一层「人类化闸门」：局面宽裕时慢半拍再动、危险时零延迟（`ReactionGate`）。
  射击：进关卡后一直按住 Z 连射（tap 只出零星几发）。每帧只发一次按键。
  捡道具：掉落道具（P 点 / 蓝点 / Bomb / 1UP …）是软吸引项，但带时间模型 ——
        用下落速度外推，只在「快落到自机高度」时做水平对齐；不追还在高处的（干等）、
        不追赶不上的（白跑）；有可打目标时还必须「顺路」，不为捡道具把输出对齐走丢。
        场上没有威胁源时放宽等待上限：先走到落点下方等它掉下来（主动捡，不是干等）。
        道具价值带集群加成：挤在同一落点附近的一片道具互相抬价，方向选择于是比
        「一趟能捡最多」而不是「单块最值钱/最近」（item_cluster_vals）。
  冲道具线：满火力且场上可转化掉落价值够高时，冲上收集线（y<128）一次 ——
        游戏把全屏普通掉落强制转成追踪（8px/帧 飞向自机，不可能漏捡），然后回位
        正常输出（ItemLineTrip：限时冲不过就放弃冷却，安全分永远压过冲线吸引）。
  灵击：被打中时放技能保命（`BombGuard`）。被击中有 8 帧死亡炸弹窗口，来得及按 X 取消死亡；
        九向外推全部重叠（必死）时提前炸 —— 那两种情况不炸必死，所以不会浪费技能。
  进关卡：关卡之间的过渡（curState=3）不退出、不按键，等游戏自己载入下一关；关卡开场的
        对话只认**按下沿**（原版 Gui.cpp:577），按住 Z 连射推不动它 —— 场上没有威胁源时
        周期性轻点一次 Z 把对话推过去，于是打穿一关能自动接上下一关（`StageFlow`）。
  让位：检测到**真人按键**（低级键盘钩子的非注入事件，`human_watch`）就停手 —— 松键、
        一个键都不发，人停手若干秒后自动接管回来。跑图期间想自己上手随时可以。

用法:
  py tools\\dodge.py --dry            只决策不按键（可在暂停态观察逻辑）
  py tools\\dodge.py --unpause        实跑（自动切前台 + 解除暂停 + 自动射击）
  py tools\\dodge.py --frames 300     跑 300 帧后退出
  py tools\\dodge.py --attack 0       关掉进攻吸引（只躲不打）
  py tools\\dodge.py --item 0         关掉道具吸引（不捡掉落物）
  py tools\\dodge.py --no-poc         关掉道具线冲刺（默认满火力且掉落够多时冲线全屏吸）
  py tools\\dodge.py --no-bomb        关掉自动灵击（对照用）
  py tools\\dodge.py --no-advance     关卡切换即退出（对照：不自动进下一关）
  py tools\\dodge.py --no-yield       玩家按键盘时不让位（对照用）
  py tools\\dodge.py --risk 0         紧张时纯躲（退回旧行为，对照用）
  py tools\\dodge.py --clear 0        关掉空旷区吸引（对照用）
  py tools\\dodge.py --center 0       关掉自动回中（对照用）
速度标定 → `tools\\calib_speed.py`（唯一标定处；别再用 sleep 计时估速度）
"""
import argparse
import ctypes
import json
import os
import random
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import paths
import th06
from human_watch import HumanWatch
from offsets import (BULLET_R, BULLET_STATE_DESPAWNING, E_BOSS, E_COLLIDABLE, E_INVISIBLE,
                     EXF_ACCEL, EXF_TURN_ABS, EXF_TURN_AIM, EXF_TURN_ANY, EXF_TURN_CONT,
                     EXF_TURN_REL, FIELD_CX, FIELD_CY, FIELD_X0, FIELD_X1, FIELD_Y0,
                     FIELD_Y1, I_BOMB, I_FULL_POWER, I_LIFE, I_POINT, I_POWER_BIG,
                     I_POWER_SMALL, ITEM_GRAB_DIST, L_PHASE_FIRE, L_PHASE_WARN,
                     POC_LINE_Y, POC_TARGET_Y, PLAYER_R, PLAYER_SPEED, PLAYER_STATE_ALIVE,
                     PLAYER_STATE_DEAD)
from read_bullets import (read_bullet_frame, read_lives, read_player,
                          read_player_state)
from read_enemies import read_enemies, shoot_countdown
from read_items import read_items, read_power
from read_lasers import read_lasers
from screen import read_state, screen_of
from winmem import module_base, find_windows, set_foreground

user32 = ctypes.WinDLL('user32', use_last_error=True)

# ---- 场地与判定常量集中在 offsets.py（依据 MEMMAP.md）----

# 方向: (名称, dx, dy, 按键)
DIRS = [
    ('none', 0.0, 0.0, ()),
    ('up', 0.0, -1.0, ('up',)),
    ('down', 0.0, 1.0, ('down',)),
    ('left', -1.0, 0.0, ('left',)),
    ('right', 1.0, 0.0, ('right',)),
    ('ul', -0.70711, -0.70711, ('up', 'left')),
    ('ur', 0.70711, -0.70711, ('up', 'right')),
    ('dl', -0.70711, 0.70711, ('down', 'left')),
    ('dr', 0.70711, 0.70711, ('down', 'right')),
]
DIR_KEYS = {n: k for n, _, _, k in DIRS}

FIRE_KEY = 'z'               # 射击键；按住才连射，退出前必须松开
ATTACK_W = 30.0              # 进攻吸引默认权重（0 = 不追敌人）
STANDOFF = 99.0              # 停在目标下方多远输出（px）
ATTACK_STEP = 4              # 进攻项前瞻帧数(×speed = px)。短前瞻才能精细对齐：
                             # 用 horizon(30 帧=120px) 评估时，水平位移远大于对齐所需，
                             # 自机停在「外推刚好对齐」处、精度差几十像素（实测 27px 打不到）。
ATTACK_REACH = 80.0          # 理想驻留带的宽度(px)：允许停在目标下方 standoff..standoff+reach 之间。
                             # 这个带里垂直方向不受进攻项驱动 —— 自机该在「打得到目标的带」里躲，
                             # 而不是一路贴到敌人脚下。带越宽越保守。
OVERSHOOT_W = 2.0            # 冲过目标头顶的惩罚倍率（自机子弹朝上飞，头顶打不到）
EDGE_MARGIN = 60.0           # 贴边惩罚的作用距离(px)：离边界这么近才扣分，场地中部完全自由
MARGIN_W = 8.0               # 安全余量权重：候选池内间隙越大越优先，治"刚够安全就贴上去"
MARGIN_CAP = 24.0            # 安全余量归一化上限(px)，超过按 1 计

# ---- 敌人余量（撞上必死，而且它会动）----
# 与 LASER_MARGIN 同款手法，对象是**敌人本体**：BOSS 的 AABB 有 56×56（实测），
# 会逐帧移动，而敌人池里**没有速度字段**（速度靠 `EnemyMotion` 差分）。
# 为什么必须单独留一截：`comfort = 1px` 是用户拍板的手感基准（软项的闸门），
# 于是池内「间隙 1px」与「间隙 25px」的余量分差只有 `margin_w`（8 分，且被 MARGIN_CAP
# 截断），而进攻吸引 55 / 矩形避让 80 都是几十上百 —— 自机会为了软项收益主动选
# 「擦着敌人 1px 过去」。子弹擦过去是常态，**敌人擦过去是死亡**，两者不能同一个定价。
ENEMY_MARGIN = 48.0          # px；调大 = 离敌人更远（从 AABB 边缘算起的自机中心距离）
SWITCH_MARGIN = 0.4          # 方向切换门槛：新方向优势不足此值就维持原方向。
                             # 别调大：>0.5 会把「贴着边界该往右脱出」也粘住，也会让自机
                             # 停在半路不对齐目标（实测 0.3→对齐 0.8px，1.5→停在中途 139px）。
                             # 抖动的主因已由 attack_cost 死区与 edge_cost 局部化消除。

# ---- 失败菜单（isInRetryMenu=0xFF）----
# 普通关卡的 Continue 与符卡练习失败后的 "Failed..." 共用这一位（screen.py）。
# 脚本在菜单里只做一件事：松键等一会儿，然后按一次 Z。符卡练习的「重试」是默认项，
# 所以这一按就是重开符卡；普通关卡下它是续关（要按得先开 --resume）。
MENU_WAIT = 1.2              # 进菜单后等多久才按 Z（秒）：动画没走完时按键会被吃掉
MENU_TIMEOUT = 15.0          # 菜单停留上限（秒）：按了 Z 还出不去就松手退出
RELOAD_TIMEOUT = 15.0        # 场景重载（curState=12）等待上限（秒）：正常只持续 1~2 帧

# ---- 空旷区吸引（往弹少的地方退，而不是逐帧钻缝）----
# 逐帧挑「当前间隙最大」只是局部最优：密集弹幕里那个方向常常只是弹与弹之间的一条缝，
# 越钻越窄，几秒后前后左右都压到判定线上（实测第六关就是这样被磨死的：
# 21px 余量 → 3 秒后 1.7px，最终九向全负）。
# 本项问的不是「最近那颗会不会撞上」（那是安全分），而是「这一带弹多不多」——
# 同等安全的方向里优先退向开阔处，等于用位置换后续的机动空间。
# **是软项**：只在安全分数线之上（或紧张档的同等安全内）决胜负，永不覆盖安全判断。
CLEAR_W = 25.0               # 空旷区吸引默认权重（0 = 关闭）
CLEAR_R = 110.0              # 空旷度评价半径(px)：落点周围这么大范围里的弹密度
CLEAR_STEP = 12.0            # 空旷项的**独立**前瞻(帧) ≈ 53px
                             # 为什么不用统一的 ATTACK_STEP(4 帧=18px)：9 个方向的落点只差
                             # 几十像素，而评价半径是 110px → 各落点的空旷度高度相关，
                             # 实测同帧极差只有 0.20（软项几乎没有区分度，差异率 1.2%）。
                             # 本机密集快照实测（120 帧）：
                             #   4 帧 极差 0.20 / 8 帧 0.51 / 12 帧 0.85 / 16 帧 0.98
                             # 前瞻越远区分度越好，但「最空方向贴边」的比例也涨：
                             #   12 帧 2% → 16 帧 12% → 20 帧 38% → 25 帧 78%
                             # 取 12 帧：区分度够（0.85）且几乎不会把自机往边界赶。
CLEAR_REF = 32.0             # 软化计数的归一化参考：达到它算「挤满」
                             # 本机实测（FINAL STAGE 符卡，241 帧 × 9 方向）：
                             #   半径 110px 的计数 p50≈17、max≈31 → 取 32 保证最密的场面
                             #   也不饱和（饱和 = 所有方向同为 1、软项失去区分度）。

# ---- 自动回中（别在角落与顶部恋战）----
# 与贴边惩罚的分工：贴边管的是「离边界 60px 内」（那里丧失机动空间），管不到**顶部中间**——
# 那儿离左右边界很远、离顶边也可以超过 60px，贴边项给 0 分；但上方弹幕刚生成、
# 留给自机的反应距离最短，实战是最不该久留的位置。本项补这一块：离中心太远就往回拉。
# **带内恒 0**：旧版「全局中心吸引」与进攻吸引全场对抗，把自机钉在场地中央、
# 水平偏差 53px 打不到敌人（→ DO_NOT_REVERT）。只有跑出自由半径才牵引。
CENTER_W = 15.0              # 回中默认权重（0 = 关闭）
CENTER_R = 110.0             # 自由半径(px)：离中心这么近完全不干预，软项自由发挥
CENTER_SPAN = 200.0          # 归一化尺度(px)：从自由半径再远这么多就扣满

# ---- 道具吸引（软项，与进攻吸引同层）----
# 时间模型：道具自己在下落，自机只在「它快落到我高度」时做水平对齐 ——
# 不追还在高处的（那是干等）、不追赶不上的（那是白跑）、不追在自机上方更远的（上追危险且打不到人）。
ITEM_W = 50.0                # 道具吸引默认权重（0 = 不捡掉落物，等价 --no-item）
ITEM_CAP = 180.0             # 等效距离上限(px)：超过它就不值得专门去追
ITEM_WAIT = 60.0             # 愿意等的帧数：道具还要更久才落到自机高度 → 现在不追
ITEM_WAIT_IDLE = 600.0       # 空档期（场上没有威胁源）的愿意等待帧数。没有中弹风险时
                             # 「先走到落点下方等它掉下来」不是干等，是主动捡 —— 此时
                             # 若仍按 item_wait 拦，自机只会等道具降到近处才动，白白放过。
                             # 有威胁源时仍按 item_wait（不为道具站桩）。
ITEM_MISS_FADE = 80.0        # 已经落到自机下方的道具：越远越不值，超过它就完全不追（别一路向下）
ITEM_DOWN_REACH = 20.0       # 下方最多牵引自机下移这么多(px)：更远的属于「已经错过」，
                             # 不为它改垂直位置。仿真实测（_tmp/sim_items.py 多种子）：
                             # 0 → 收集 50%，20 → 55%，30 → 48% —— 20 附近是折中，
                             # 再大就会为了追下方道具上下游走、离开输出带。
ITEM_AIM_TOL = 40.0          # 顺路带宽(px)：为捡道具把输出对齐偏差推过它就开始打折
ITEM_AIM_FADE = 96.0         # 顺路衰减宽度(px)：偏差超过 tol+fade 就完全不捡（专心输出）
ITEM_FULL_POWER = 128        # 满火力阈值：之后 Power 道具只转分数，不再值得优先补
ITEM_POWER_BONUS = 1.8       # 火力未满时 Power 类道具的价值倍率（优先补火力）
ITEM_VALUE = {               # 基础价值（相对值，只决定「多个道具同时在场时先追哪个」）
    I_POINT: 1.5,            # 蓝点：LUNATIC 单颗 15 万～20 万分，满火力后最值钱
    I_FULL_POWER: 2.0,
    I_BOMB: 2.5,
    I_LIFE: 3.0,             # 1UP 最稀有
}

# ---- 道具集群（「一趟能捡最多」的近似）----
# 一块道具的有效价值 += 邻居价值：多块道具挤在同一落点附近时，朝那里走一趟能全收，
# 等效于单块价值翻倍 —— 方向选择于是从「最近/最值钱的一块」变成「一趟能捡最多的一片」。
# 邻居判据 = 水平近 + 到达自机高度的时间近 + 邻居自身可捡（存活久、不用干等、没错过）。
ITEM_CLUSTER_WIN = 56.0      # 水平窗口(px)：相邻两次拾取之间自机能横扫的距离量级
ITEM_CLUSTER_T = 60.0        # 时间窗(帧)：到达时间差内的才算「同一趟能收」
ITEM_CLUSTER_W = 1.0         # 邻居价值计入倍率
ITEM_SURV_REF = 60.0         # 邻居存活参考(帧)：快掉出场的邻居（t_die 小）加成按比例缩水

# ---- 智能道具线冲刺（PoC；机制见 offsets.POC_LINE_Y 的反汇编依据）----
# 满火力 + 场上可转化（state-0 普通掉落）价值 ≥ poc_min 时，冲上收集线一次：
# 游戏把全屏普通道具强制转为追踪（8px/帧 飞向自机、不可能再漏捡），然后回到正常
# 躲避/输出，道具自己飞过来。EoSD 的收集线只在满火力时存在 —— 火力不足冲线毫无收益。
# 冲线吸引走软项通道（= 进攻 + 道具 + 8），安全分永远压过它：上方路被弹幕堵死时
# 冲不上去，限时一到放弃并冷却，绝不硬闯。state-2 散射物不参与转化（原版同构），
# 但冲线路过上部时顺路身体接，目标 x 取非追踪道具的价值加权质心。
POC_MIN = 0.0                # 触发价值：可转化道具总价值 ≥ 它才值得冲（0 = 满火力且有普通掉落就冲）
POC_TIMEOUT = 300            # 冲线限时(帧)：5 秒内跨不过线就放弃
POC_COOLDOWN = 240           # 放弃后的冷却(帧)：别顶着弹幕反复撞
POC_W_EXTRA = 8.0            # 冲线吸引 = attack_w + item_w + 它（压过同层软项，仍不敌安全分）
SCATTER_AVG = 30.0           # state-2 散射的平均剩余帧数（实际 0..60 未知，取中值）
POC_NORM = float(np.hypot(FIELD_X1 - FIELD_X0, FIELD_Y1 - FIELD_Y0))
                             # 冲线吸引的归一化尺度(px) = 场地对角线：自机与冲线
                             # 目标都在场内 → 距离 ≤ 它，吸引项自然落在 [0, poc_w]。

# ---- 道具下落规律（原版 ItemManager::OnUpdate：vy 每帧 +0.03，上限 3.0）----
# 生成时 vy = −2.2（先向上飞，约 73 帧后转下落）；y ≥ 448 消失且倒扣 rank —— 漏捡有代价。
FALL_ACC = 0.03
FALL_VMAX = 3.0

# ---- 紧张档（弹幕密、最优方向间隙 < 安全分数线）的软项参与 ----
RISK_TOL = 1.0               # 同等安全容差(px)：只在与最优方向相差 ≤ 它的方向之间让软项决胜负
RISK_SOFT = 0.5              # 紧张档软项折扣：紧张时偏好只做微调，不主导走位

# ---- 全负兜底（九向都会进余量圈时的排序键）----
# 安全分只留 min 会丢掉「第几帧脱出」：−24（现已侵入判定圈、且不动就出不去）与 −29
# （26 帧后才被扫到）被抹成同一量级，`none` 反而因为「间隙恒定、不靠近别的威胁」胜出。
# 实测（death_20260927-113717）：48 条辐射激光同时进入预警，每条都带 LASER_MARGIN 的
# 余量坑 → 全场没有一格是正的；选出的 `none` 恰好停在一条即将开火的激光判定圈里 59 帧 ——
# 而它只要右移 5.95px / 2 帧就能出圈（那里的余量仍是负的，所以 min 看不见）。
# 兜底因此改看「纯判定几何」：True = 全负时按「第几帧脱出判定圈」排；
# False = 旧行为（按最小间隙排）。两者都不看软项。
ESCAPE_RANK = True

# ---- 弹幕预警（改的是安全分本身，不是软项）----
# 不做弹幕形状预测，只预测「下一波什么时候来」：敌人的 shootInterval / shootIntervalTimer
# 就在内存里（MEMMAP §10，反汇编 0x28A8A 段确证）。即将发弹的敌人，危险半径按倒计时放大，
# 给自机留出「跑出弹幕覆盖区」的时间 —— 反应式躲避缺的正是这段时间。
WARN_W = 10.0                # 预警窗口(帧)：还有这么多帧就发弹时开始避险；0 = 关闭
WARN_DIST = 10.0             # 发弹瞬间的最大额外危险半径(px)

# ---- 人类化：安全时的反应延迟（让动作像人，而不是每帧即时响应）----
# 真人的反应时间随紧张程度变化：危险时高手是零延迟的即时反应，安全时动作从容、
# 一次动作走一段而不每帧改主意。延迟只加在安全侧 —— 加在危险侧只会送命。
REACT_FRAMES = 7.0           # 安全时的反应延迟(帧)；0 = 关闭，退回逐帧即时响应。
                             # 仿真拐点是 4 帧（humanize_sweep），7 是用户实机沿用值。
REACT_SLACK = 8.0            # 允许延迟所需的额外安全余量(px)：最优方向间隙 ≥ 底线+它 才敢慢半拍
REACT_MIN_COMFORT = 6.0      # 延迟的安全底线(px)：与「安全分数线」取**大者**。
                             # 分数线同时是软项的闸门 —— 为「让更多软项参与」把它调低到 1px 是合法的，
                             # 但延迟不该跟着放松：延迟漏进危险侧就是拿命换像人。
REACT_JITTER = (0.7, 1.3)    # 延迟长度的抖动倍数：真人的反应时间不是固定值，固定帧数本身就是机械特征

# ---- 自动灵击（被打中时放技能）----
# 依据：反汇编 `Player__OnUpdate` 0x689A8..0x68B20 + 原版 `BombData.cpp`（→ MEMMAP §11）
#   · bomb 是**按下沿**触发：输入位图 bit1 本帧按下、且与上帧不同 —— 一直按着只算第一帧。
#   · 触发还要求 `respawnTimer != 0`。存活时它恒为 8；被击中进 DEAD 后逐帧递减，
#     到 0 才结算掉命（deaths++ / 掉道具 / 扣 power）。**这段窗口就是死亡炸弹窗口**：
#     窗口内按 X 会执行角色 bomb 的 calc，把 playerState 改成 INVULNERABLE，死亡被取消。
BOMB_KEY = 'x'               # 灵击键（TH_BUTTON_BOMB = 输入位图 bit1）
BOMB_HOLD = 3                # 按住帧数：按下沿要跨帧才收得到，同帧 down+up 会被轮询漏掉
BOMB_COOLDOWN = 10           # 一次灵击后的静默帧数：灵击生效中不必再按，也防连发
BOMB_PRE = 1                 # 必死预判前瞻(帧)：0 = 只在被击中后抢救（不预判）

# ---- 激光额外安全余量 + 独立长前瞻 ----
# 激光是**长条**（一道 368~388px，几乎贯穿全屏高度），而且新典里还会**整体横扫**
# （轴原点 +6px/帧，见 MEMMAP §7.1）。躲避只问「窗口内会不会撞上」：
#   · 余量（LASER_MARGIN）：间隙刚过 `comfort` 就算安全，软项（进攻/道具）立刻把自机
#     拉回激光边上输出，惯性 / 反应延迟一推就滑进去（实测报的「撞激光上」）。
#   · 前瞻（LASER_HORIZON）：**这是「来不及躲」的真正原因** —— 自机从输出位垂直逃出
#     激光覆盖带要跑 40+ 帧，而 `horizon` 只有 16 帧（≈96px）：激光还在窗口外时
#     间隙很大 → 判成安全 → 进攻吸引把自机按在输出位，等它进窗口已经来不及。
#     用户实测原话：「激光要出了还在打敌人，而不是立即远离」。
# 两者**只加在躲避的安全分上**：必死预判要的是真实几何（判据是「不炸必死」），不能虚高。
LASER_MARGIN = 16.0          # px；调大 = 更早让开、更不肯贴着激光输出
LASER_HORIZON = 40           # 帧；激光专用的接近趋势窗口（≈0.67s，自机可跑 176px）
# ---- 安全分认不认预警阶段的激光 ----
# 关（默认）：**全部活跃激光**都进安全分 —— 预警线是「马上要开火的位置」，不让开就是
#     开火即死（实测 113717：`none` 停在一条即将开火的激光判定圈里 59 帧）。
# 开：安全分只认 `L_PHASE_FIRE`（有伤害判定的），预警线只走 `warn_rect_cost` 软项。
#     2026-09-27 实机 17 例复盘一度认为是它，**回放证伪了**：摘掉后自机不再站桩，
#     但因为预警线不再有安全分的否决权，它会走进「即将开火」的区域 —— 232 帧激光
#     一转发射就被打死（`_tmp/replay_plan.py`，五种参数组合全死在那一帧）。
#     真正的病灶是 `LASER_MARGIN` 在 48 条预警激光上**叠加**（每条都扣 16px）→ 全场判负
#     → `ESCAPE_RANK` 兜底（作者在 218 行已记录同一现象）→ 排序键丢掉余量、选错方向。
#     → 该试的是 `laser_margin`，不是这个开关。
LASER_SAFE_ARMED = False
# 为什么不干脆把全局 `horizon` 调大：子弹的窗口一长，「朝目标走一步」就会被当成
# 「一路走到目标怀里」，水平对齐立刻变差（软项前瞻踩过的同款坑，见 CLEAR_STEP 的注释）。
# 激光要的是「提前让开整片区域」，与子弹要的「这一步落哪」不是一回事，所以各留一个。
WARN_RECT_W = 80.0           # 软项权重：预警激光的「轴线区间」避让（横向逃不掉，得往外走）
# 为什么预警期要特殊处理：实测（Laevatein）预警期 `pos` 静止、`speed = 0`，
# **开火后才 +6px/帧横扫** —— 「会不会扫、往哪扫」在预警期**没有任何信号**。
# 几何（CSV 实测 angle = 90°）：这是**竖线**，沿 y 铺满场地高度（y ∈ [80,448]）。
# 横扫 = 竖线在水平方向平移 → 水平跑不掉（6 > 自机 4.39），唯一出口是**上下出端点**。
# **上方出口正是 BOSS**（实测 AABB 56×56、y ∈ [52,108]）：本项只看激光、不知敌人在哪，
# 必须留在软项里，由安全分否决「撞 BOSS 那一步」——做成硬约束就会径直撞进 BOSS。
# **必须做成软项，不能进安全分**：这里算的是「逃出区间还需多少」，与碰撞间隙不同量纲 ——
# 混进 `min()` 后它那个 −150 会把「撞敌人 −10」这种真威胁盖掉
# （实测症状：自机为了躲激光径直撞进 BOSS）。
# 默认 80 > 进攻吸引 55：压得过它才请得动自机。调大 = 更早退开、更保守。
WARN_RECT_ON = True          # 关掉做对照/排查用
WARN_RECT_STEP = 24.0        # 帧；矩形避让的**独立前瞻**（≈105px）
# 必须独立：用 `ATTACK_STEP`（4 帧）评「该不该离开激光区间」等于没生效 ——
# 四个方向的落点彼此只差十几像素，而区间长 368px，代价几乎一样
# （实测：开 / 关的决策差异只有「right → ur」这么一点）。
# 同款坑见 `CLEAR_STEP`（软项前瞻一刀切）。24 帧 ≈ 跑过区间的一半，方向差异才分得开；
# 再大就会把「一步之遥」也算成「已经跑到那儿了」。

# ---- 低速模式（focus / 按住 Shift）----
# 机制（反汇编 `Player__OnUpdate` + 实机读结构常量，→ MEMMAP §1 §12）：
#   输入位图 bit2 = TH_BUTTON_SLOW；命中时速度字段从 `+0x7864` 取，否则 `+0x7860`。
#   本机实测 4.0 / 2.0（斜向 2.82843 / 1.41421）→ **低速 = 精确半速，斜向同样归一化**。
#   focus 还会切换射击函数（`Player+0x7720` / `+0x7728` 每帧二选一）—— 慢不只是慢。
# 策略：**只在「原地不动就够安全」时用低速** —— 那说明这一步不是为了活命，只是微调
#   （对齐输出位 / 捡近处道具 / 离开边界）；站着不动都险时绝不慢，那正是要靠速度
#   拉开距离的时刻。
#   1. 每帧对快 / 慢两个速度各规划一次。**必须重规划**：plan() 的间隙按 speed 外推轨迹，
#      拿高速轨迹去执行低速 = 以为走得到、实际少走一半。
#   2. 判据看的是 `scores['none']`（**原地不动**的间隙），不是「最优方向的间隙」：
#      后者一片太平就成立，会让自机常年半速（实测就是这个问题）。
#      `none` 的间隙与速度无关（不动就没有外推），所以查高速那次的结果就够。
#   3. 已在低速时门槛打折（FOCUS_EXIT），否则会在门槛上下逐帧横跳。
#   4. 冲线期（dashing）强制高速：那件事的本质就是「快点到上面去」。
FOCUS_KEY = 'shift'
FOCUS_RATIO = 0.5            # 低速 / 高速 速度比（结构常量确证，别当成可调项）
FOCUS_SLACK = 12.0           # px；原地不动的间隙要比安全分数线高出这么多，才敢低速
FOCUS_EXIT = 0.5             # 已在低速时的门槛折扣：门槛 = 分数线 + slack×它（防抖）

# ---- 自动进下一关（关卡之间的过场 + 开场对话）----
# 关卡结束 → 下一关**不需要按键**：原版 Gui.cpp 的 MSG_OPCODE_STAGEEND 把 curState 置为
# SUPERVISOR_STATE_GAMEMANAGER_REINIT(3)，GameManager::AddedCallback 里 currentStage++ 后
# 自动载入下一关。脚本唯一要做的是「别在这时退出、也别按键」（旧版把 SCENE_3 当普通
# 非关卡画面直接退出，于是每打完一关就停）。
# 真正需要按键的是关卡**开场对话**：原版对话的 WAIT 指令只认按下沿
# （Gui.cpp:577 `WAS_PRESSED(TH_BUTTON_SHOOT)`）、两次之间还要隔 ≥8 帧，而自动射击是
# **按住** Z 的 —— 对话推不动，脚本就卡在第一句上。对策：场上没有威胁源
# （对话与开场飞行段本来就没有弹幕/敌人/激光）时周期性轻点一次 Z。
ADVANCE_TAP_S = 0.6          # 无威胁源时轻点 Z 的间隔(秒)：>8 帧的按下沿间隔要求
ADVANCE_TAP_MS = 60          # 轻点的按住时长(ms)
ADVANCE_TIMEOUT_S = 120.0    # 关卡切换等待上限(秒)：超时说明卡在某个画面，松键退出

# ---- 玩家让位（人一上手，脚本停手）----
# 判据来自 human_watch 的低级键盘钩子：只认**非注入**按键，所以脚本自己发的键不会误触发。
# 让位期间一个键都不发（含 Z 射击与灵击），并松掉脚本自己按下的键 —— 但**跳过玩家此刻
# 正按着的键**：SendInput 的抬键会改系统键状态表，硬松会把人家按住的右方向顶掉。
# 只看「最近 N 秒有没有按键」不够：人一直按着方向键时，时间窗一过脚本就会把手柄抢回来。
HUMAN_IDLE = 2.0             # 人最后一次按键后，脚本再静默这么多秒才接管回来


# ---- 控制台保存的默认值（「保存为默认值」写到 SAVED_PATH；CLI 不读，只用出厂默认 + 显式参数）----
# 路径由 paths.py 给：源码 = 项目根，打包 = exe 旁（打包后 __file__ 在只读解包目录里）
SAVED_PATH = paths.outside('dodge_params.json')


def default_params():
    """出厂默认参数 —— 唯一真源（GUI 滑条与勾选框、保存文件的键集合都由它决定）

    数值 = 用户实机调校并固化的一组（逐项含义见 `项目文档/04-调参/相关-参数速查-TUNING.md`）；
    用户在控制台再调出来的值走 `save_saved()` 存文件。改这里等于改出厂默认。

    **CLI 也读这里**（`--xxx` 的 argparse 默认值取自本函数）、**不读 `SAVED_PATH`** ——
    所以「控制台里调出来的值」与「命令行不带参数跑出来的值」本来是两套；
    要两边一致，就得把值写进本函数（这里就是那个落点）。
    """
    return dict(horizon=15.0, speed=PLAYER_SPEED, safe=2.0, edge=1000.0, attack=0.0,
                standoff=60.0, item=300.0, item_wait=20.0, risk=0.0,
                warn=20.0, warn_dist=30.0,
                inertia=1.5, comfort=0.0, margin=MARGIN_W, switch=SWITCH_MARGIN,
                clear=100.0, clear_r=50.0, center=1.0, center_r=5.0, center_y=FIELD_CY,
                react=6.0, bomb_pre=8.0,
                focus=False, focus_slack=0.0,
                poc=True, poc_min=1.0,
                advance=True, human_yield=True, human_idle=1.0,
                autofire=True, use_enemy=True, use_laser=True, use_item=True,
                bomb=True, unpause=True, keep_going_on_death=True,
                blackbox=False)      # 死亡黑匣子：勾上才录，掉命时存现场（只读，见 death_recorder.py）


def load_saved(path=SAVED_PATH):
    """读控制台保存的默认值；文件缺失 / 损坏 / 键非法一律忽略（静默退回出厂默认）

    返回 (参数 dict, 采用了几项, 出错原因或 None)。只认 `default_params()` 里已有的键与类型，
    手改文件塞进未知键不会带进运行参数。
    """
    try:
        with open(path, encoding='utf-8') as f:
            raw = json.load(f)
    except FileNotFoundError:
        return {}, 0, None
    except (OSError, ValueError) as e:
        return {}, 0, f'无法读取 {os.path.basename(path)}：{e}'
    if not isinstance(raw, dict):
        return {}, 0, f'{os.path.basename(path)} 的内容不是键值表'
    base, out = default_params(), {}
    for k, v in raw.items():
        if k not in base or isinstance(v, bool) != isinstance(base[k], bool):
            continue
        try:
            out[k] = bool(v) if isinstance(base[k], bool) else float(v)
        except (TypeError, ValueError):
            continue
    return out, len(out), None


def save_saved(params, path=SAVED_PATH):
    """把当前参数写为默认值；返回 (是否成功, 说明)

    只写 `default_params()` 认得的键 —— 存的是「一组默认值」而不是整个 cfg（cfg 里还有
    dry/frames/period 这类运行时状态，不该被固化）。
    """
    base = default_params()
    data = {k: params[k] for k in base if k in params}
    try:
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2, sort_keys=True)
            f.write('\n')
    except OSError as e:
        return False, f'无法写入 {os.path.basename(path)}：{e}'
    return True, f'已保存 {len(data)} 项至 {os.path.basename(path)}'


def clear_saved(path=SAVED_PATH):
    """删掉保存的默认值，回到出厂默认；返回 (是否成功, 说明)"""
    try:
        os.remove(path)
    except FileNotFoundError:
        return True, '此前未保存过默认值'
    except OSError as e:
        return False, f'无法删除 {os.path.basename(path)}：{e}'
    return True, '已恢复为出厂默认值'


def foreground():
    return user32.GetForegroundWindow()


def threat_present(bx, enemy, laser):
    """场上是否存在威胁源（弹 / 敌人本体 / 激光）—— 唯一判据，plan() 与 ReactionGate 共用

    无威胁源时所有方向绝对安全，安全分恒为 0；任何"按分数判安全"的逻辑都必须先问这一句，
    否则空档期会被当成"永不安全"（`plan()` 曾因此在清完杂兵后全程不动）。
    """
    return len(bx) > 0 or enemy is not None or laser is not None


def warn_radius(countdown, window, dist):
    """每个敌人的额外危险半径(px)：倒计时越小越大，窗口之外为 0

    倒计时 = interval - timer（`read_enemies.shoot_countdown()`）；< 0 = 当前不射击。
    线性放大即可 —— 目的是「提前让开」，不是精确预测弹幕形状（那需要解析 bulletProps）。
    """
    if window <= 0 or len(countdown) == 0:
        return np.zeros(0, dtype=np.float32)
    c = np.asarray(countdown, dtype=np.float32)
    t = np.clip(1.0 - c / window, 0.0, 1.0)
    return np.where(c < 0, 0.0, t * dist).astype(np.float32)


def enemy_gap(xs, ys, ex, ey, ehw, ehh, evx=None, evy=None, ts=None):
    """轨迹点到所有敌人 AABB 的最小间隙（负 = 已侵入）

    ehw / ehh 是**含预警放大的**盒尺寸（见 warn_radius），调用方负责叠加。

    给 `ts` + `evx`/`evy` 时按第 t 帧外推敌人位置。**为什么必须外推**：前瞻窗口里
    子弹和激光都有速度（`vx`/`vy`、`laser_gap` 的 ts），唯独敌人被当成静止的 ——
    而 BOSS 会移动（Laevatein 实测蕾米莉亚本体逐帧位移），`horizon` 16 帧就是 16 次
    误差累积：自机算「这个方向离它 80px，安全」，走到时它已经挪到路上。
    速度来自 `EnemyMotion`（池里没有这个字段，只能逐帧差分）。
    """
    if len(ex) == 0:
        return None
    if ts is not None and (evx is not None or evy is not None):
        tt = np.asarray(ts, dtype=np.float32)[:, None]                  # (H, 1)
        cx = ex[None, :] + (0.0 if evx is None
                            else np.asarray(evx, dtype=np.float32)[None, :] * tt)
        cy = ey[None, :] + (0.0 if evy is None
                            else np.asarray(evy, dtype=np.float32)[None, :] * tt)
    else:
        cx, cy = ex[None, :], ey[None, :]
    dx = np.maximum(np.abs(xs[:, None] - cx) - ehw[None, :] * 0.5, 0.0)
    dy = np.maximum(np.abs(ys[:, None] - cy) - ehh[None, :] * 0.5, 0.0)
    return np.sqrt(dx * dx + dy * dy).min(axis=1)




# ---- 子弹运动预测：加速弹与转向弹（反汇编 BulletManager__OnUpdate 确证）----
# 只按当前 vx/vy 匀速外推不够用：新典保留了原版整套 exFlags 机制 ——
#   EXF_ACCEL      每帧 `velocity += accel`（原版 731 行）
#   EXF_TURN_CONT  每帧 `angle += rate`、`speed += srate`（743-747 行）
#   EXF_TURN_REL/ABS/AIM  定时把**速度矢量整体改向**（761 / 787 / 813 行），
#                 其中 AIM 直接朝自机转 —— 转向那一刻落点整段作废。
# `read_bullet_frame()` 给出这些字段，下面按同一套机制逐帧推进。
BULLET_SKIP_DESPAWN = True    # 消散阶段(state 5)不做碰撞判定，躲它是纯浪费移动
_EXF_MOTION = EXF_ACCEL | EXF_TURN_CONT | EXF_TURN_ANY


def bullet_paths(bf, horizon, px, py):
    """按原版机制逐帧推进子弹 → `(H, N)` 的 `(fx, fy)`

    `bf` 是 `read_bullet_frame()` 的 `BulletFrame`。普通弹走一次向量化直线（与旧实现
    逐位一致），只有带 exFlags 运动位的弹走逐帧推进 —— 实测 300 颗弹里 200 颗是特殊弹时
    horizon=16 也只要 1.0ms（帧预算的 8%）。

    `EXF_TURN_AIM` 的转向角按**当前**自机位置算（原版每帧取最新自机位置）：
    窗口内自机最多再走 horizon×4.39px，用它当近似比忽略好得多。
    """
    n = len(bf.xs)
    H = max(1, int(horizon))
    ts = np.arange(1, H + 1, dtype=np.float32)
    if n == 0:
        return np.zeros((H, 0), dtype=np.float32), np.zeros((H, 0), dtype=np.float32)
    fx = bf.xs[None, :] + bf.vxs[None, :] * ts[:, None]      # 普通弹：一次直线
    fy = bf.ys[None, :] + bf.vys[None, :] * ts[:, None]
    idx = np.nonzero(bf.exflags.astype(np.int32) & _EXF_MOTION)[0]
    if len(idx) == 0:
        return fx, fy
    sub = bf._replace(**{f: getattr(bf, f)[idx] for f in bf._fields})
    sx, sy = _advance(sub, H, px, py)
    fx[:, idx] = sx                                           # 只有特殊弹逐帧推进
    fy[:, idx] = sy
    return fx, fy


def _advance(bf, H, px, py):
    """逐帧推进一池**全是特殊弹**的子弹 → `(H, N)`；机制见 `bullet_paths`"""
    n = len(bf.xs)
    exf = bf.exflags.astype(np.int32)
    x = bf.xs.astype(np.float64).copy()
    y = bf.ys.astype(np.float64).copy()
    vx = bf.vxs.astype(np.float64).copy()
    vy = bf.vys.astype(np.float64).copy()
    ang = bf.angles.astype(np.float64).copy()
    spd = bf.speeds.astype(np.float64).copy()
    dcs = bf.dcspeeds.astype(np.float64)
    timer = bf.timers.astype(np.int64).copy()
    hold = bf.hold.astype(np.int64)
    ax, ay = bf.accel_x.astype(np.float64), bf.accel_y.astype(np.float64)
    rot = bf.turn_rot.astype(np.float64)
    ivl = bf.turn_int.astype(np.int64)
    num = bf.turn_num.astype(np.int64).copy()
    maxn = bf.turn_max.astype(np.int64)
    rate = bf.turn_rate.astype(np.float64)
    srate = bf.speed_rate.astype(np.float64)

    acc_on = (exf & EXF_ACCEL) != 0
    cont_on = (exf & EXF_TURN_CONT) != 0
    turn_on = (exf & EXF_TURN_ANY) != 0
    rel_on = (exf & EXF_TURN_REL) != 0
    abs_on = (exf & EXF_TURN_ABS) != 0
    aim_on = (exf & EXF_TURN_AIM) != 0
    # 某一类弹不存在时整段跳过（掩码只会被 &= 变少，不会凭空出现）
    has_acc, has_cont, has_turn = acc_on.any(), cont_on.any(), turn_on.any()

    fx = np.empty((H, n), dtype=np.float32)
    fy = np.empty((H, n), dtype=np.float32)
    for t in range(H):
        if has_acc:
            # 加速：计时到 hold 停（原版 timer >= ex5Int0 → 清位，此后不再加速）
            act = acc_on & (timer < hold)
            if act.any():
                vx[act] += ax[act]
                vy[act] += ay[act]
                ang[act] = np.arctan2(vy[act], vx[act])
            acc_on &= ~(acc_on & (timer >= hold))
        if has_cont:
            # 连续转向：每帧转一点、加速一点
            act = cont_on & (timer < hold)
            if act.any():
                ang[act] += rate[act]
                spd[act] += srate[act]
                vx[act] = np.cos(ang[act]) * spd[act]
                vy[act] = np.sin(ang[act]) * spd[act]
            cont_on &= ~(cont_on & (timer >= hold))
        if has_turn:
            # 定时转向：`timer >= interval*(num+1)` 的那一帧换方向与速度
            tt = timer - ivl * num
            fire = turn_on & (ivl > 0) & (tt >= ivl)
            if fire.any():
                num[fire] += 1
                turn_on &= ~(fire & (num >= maxn))       # 次数到顶清位，但这一帧照转
                m = fire & rel_on
                ang[m] = ang[m] + rot[m]
                m = fire & abs_on
                ang[m] = rot[m]
                m = fire & aim_on
                if m.any():
                    ang[m] = np.arctan2(py - y[m], px - x[m]) + rot[m]
                spd[fire] = dcs[fire]
                vx[fire] = np.cos(ang[fire]) * spd[fire]
                vy[fire] = np.sin(ang[fire]) * spd[fire]
            # 非事件帧：速度线性衰减到 0（原版 767-771 的 bulletSpeed 插值）
            itp = turn_on & ~fire & (ivl > 0)
            if itp.any():
                s2 = spd[itp] * (1.0 - tt[itp] / ivl[itp])
                vx[itp] = np.cos(ang[itp]) * s2
                vy[itp] = np.sin(ang[itp]) * s2
        x += vx
        y += vy
        fx[t] = x
        fy[t] = y
        timer += 1
    return fx, fy


class LaserMotion:
    """激光「轴原点平移」与「角度旋转」的逐帧差分

    为什么不能读槽里的 `speed`：那是 **offset 前进速度**（线段沿自身方向伸长）。
    实测横扫的激光 `speed` 恒为 0，移动发生在 `pos` 上（Laevatein 实测 **+6px/帧**，
    比自机 4.39px/帧还快 —— 贴着它跑必被从后面追上）。这个量没有字段能直接读，
    只能逐帧差分。

    **角度同样会变**：反汇编里引擎只读 angle，但采样实测（`_tmp/laser_trace`）
    同一槽连续 19 帧 `pos`/`speed`/线段全不动、angle 每帧 +2.25° —— 旋转激光真实存在。
    所以角速度一并差分，交给 `laser_gap()` 按**第 t 帧的朝向**算线段。

    槽复用（旧激光消失、新激光占同一个槽）会伪造出巨大位移与整圈角度跳变，判据三条：
      · 阶段或阶段计时倒退（新激光从预警重新开始）
      · 位移超过 `MAX_STEP`（真实横扫实测 ≤6px/帧）
      · 角度跳变超过 `MAX_TURN`（真实旋转实测 0.039 rad/帧 = 2.25°/帧）
    任一命中 → 该槽这一帧的速度与角速度都记 0（当它静止，保守）。
    """

    MAX_STEP = 48.0            # px/帧；真实横扫实测 6，槽复用跳变实测 30~65
    MAX_TURN = 0.5             # rad/帧(≈28.6°)；真实旋转 0.039，槽复用常整圈跳变

    def __init__(self):
        self.prev = {}

    def speeds(self, lf):
        """→ `(vx, vy, omega)`，与 `lf` 的各数组同长；首次出现 / 槽复用的都记 0"""
        n = len(lf.slots)
        vx = np.zeros(n, dtype=np.float32)
        vy = np.zeros(n, dtype=np.float32)
        om = np.zeros(n, dtype=np.float32)
        for i in range(n):
            p = self.prev.get(int(lf.slots[i]))
            if p is None:
                continue
            dx = float(lf.xs[i]) - p[0]
            dy = float(lf.ys[i]) - p[1]
            dang = float(lf.angles[i]) - p[2]
            dang = (dang + np.pi) % (2.0 * np.pi) - np.pi      # 归一化到 [-π, π]
            if (int(lf.phases[i]) < p[3]
                    or (int(lf.phases[i]) == p[3] and int(lf.timers[i]) < p[4])
                    or abs(dx) > self.MAX_STEP or abs(dy) > self.MAX_STEP
                    or abs(dang) > self.MAX_TURN):
                continue
            vx[i], vy[i], om[i] = dx, dy, dang
        self.prev = {int(lf.slots[i]): (float(lf.xs[i]), float(lf.ys[i]),
                                        float(lf.angles[i]), int(lf.phases[i]),
                                        int(lf.timers[i])) for i in range(n)}
        return vx, vy, om


class EnemyMotion:
    """敌人位置的逐帧差分 —— 敌人池里**没有速度字段**（MEMMAP §6）

    为什么需要：前瞻窗口里子弹和激光都有速度外推，唯独敌人被当成静止的。而 BOSS
    会移动，`horizon` 16 帧就是 16 次误差累积 —— 自机算「这个方向离它 80px，安全」，
    走过去时它已经在路上。**撞敌人必死，这条威胁却是唯一没做运动预测的。**

    槽复用（敌人被销毁、新敌人占同一槽）会伪造出巨大位移，所以用
    「`life` 只减不增 + 位移不超过 `MAX_STEP`」双重判据否掉，速度记 0（当它不动，保守）。
    """

    MAX_STEP = 24.0            # px/帧；超过按「这个槽换了另一个敌人」处理

    def __init__(self):
        self.prev = {}

    def speeds(self, slots, xs, ys, lifes):
        """→ `(vx, vy)`，与传入数组同长；首次出现 / 槽被接管的速度记 0"""
        n = len(slots)
        vx = np.zeros(n, dtype=np.float32)
        vy = np.zeros(n, dtype=np.float32)
        for i in range(n):
            p = self.prev.get(int(slots[i]))
            if p is None:
                continue
            dx = float(xs[i]) - p[0]
            dy = float(ys[i]) - p[1]
            if float(lifes[i]) > p[2] or abs(dx) > self.MAX_STEP or abs(dy) > self.MAX_STEP:
                continue
            vx[i], vy[i] = dx, dy
        self.prev = {int(slots[i]): (float(xs[i]), float(ys[i]), float(lifes[i]))
                     for i in range(n)}
        return vx, vy


def laser_segments(lf, keep=None, motion=None):
    """`read_lasers()` 的 LaserFrame → 判定几何元组（供 `laser_gap` 直接展开）

    返回 `(xs, ys, angles, starts, ends, lens, widths, speeds, vx, vy, omega)`：
    第 i 条激光在第 t 帧的线段 =
        `(pos + v·t) + 方向(angle + ω·t) × [starts + speeds·t, ends + speeds·t]`
    （前一项是**轴原点平移**，中间是**朝向旋转**，后一项是**沿自身方向伸长**，
    三回事，见 `laser_gap`）。

    `lens` 是长度上限。字段全空的槽（少数激光靠 ANM 画长度）退化成静止的 500px 长条 ——
    宁可当它是长激光，也别当它不存在。

    `motion` 是 `LaserMotion.speeds()` 给的 `(vx, vy, omega)`。不给就只能假设激光静止，
    拿当前几何算未来落点 —— 横扫的激光会跑到自机身上、旋转的激光会扫过来。

    预警阶段的额外避让**不在这里**（那是 `warn_rect_cost()` 软项的输入）——
    它的量纲与碰撞间隙不同，不能混进安全分。
    """
    idx = slice(None) if keep is None else keep
    starts, ends = lf.starts[idx], lf.ends[idx]
    seg, lens = ends - starts, lf.lens[idx]
    empty = (lens <= 0) & (seg <= 0)
    if motion is None:
        vx = vy = om = np.zeros(len(lf.xs[idx]), dtype=np.float32)
    else:
        vx = np.asarray(motion[0][idx], dtype=np.float32)
        vy = np.asarray(motion[1][idx], dtype=np.float32)
        om = np.asarray(motion[2][idx], dtype=np.float32)
    return (lf.xs[idx], lf.ys[idx], lf.angles[idx],
            np.where(empty, np.float32(0.0), starts).astype(np.float32),
            np.where(empty, np.float32(500.0), ends).astype(np.float32),
            np.where(empty, np.float32(500.0), np.maximum(lens, seg)).astype(np.float32),
            lf.widths[idx], lf.speeds[idx], vx, vy, om)


def laser_gap(xs, ys, lx, ly, lang, lstart, lend, llen, lw, lspeed=None,
              lvx=None, lvy=None, lom=None, ts=None):
    """轨迹点（H 个时刻）到激光线段（N 条）的最小间隙 → (H,)

    几何（`Player__CalcLaserHitbox` 入参，反汇编 0x1161D..0x11883 确证）：
    **线段 = pos + 方向(angle) × [startOffset, endOffset]**，半宽 = width/2。
    `pos` 是轴原点、**不是线段起点** —— 旧版按 `[pos, pos + startLength]` 算，
    静止的激光恰好错得不多，横向扫过来的则整条错位。

    给 `ts`（H 个帧序号）时按原版逐帧外推第 t 帧，四件事各算各的：
        · 轴原点平移  `posₜ = pos + v·t`（`lvx`/`lvy`：槽里没有这个量，靠逐帧差分）
        · **朝向旋转** `angleₜ = angle + ω·t`（`lom`：同上，靠逐帧差分）
        · 终点偏移    `endₜ = end + speed·t`
        · 起点偏移    `startₜ = max(start, endₜ − len)` ← 生长阶段起点不动
    少了「生长」那句，刚生成的短激光会被当成一条已经在平移的长条，提前让出整片区域；
    少了「轴原点平移」，横扫的激光会被当成静止的，自机就站在它的必经之路上不动
    （Laevatein 实测：激光 +6px/帧 > 自机 4.39px/帧，贴边跑必被从后面追上）；
    少了「朝向旋转」，旋转激光的落点会停在**当前**朝向不动 ——
    实测一条 388px 长的激光以 2.25°/帧 扫过，40 帧前瞻能转过 90°。

    **预警阶段的额外避让不在这里**：那是 `warn_rect_cost()`（软项）的活 ——
    它的量纲是「逃出轴线区间还需多少」而不是碰撞间隙，混进安全分会把真实威胁盖掉。
    """
    if len(lx) == 0:
        return None
    if ts is not None:
        tt = np.asarray(ts, dtype=np.float32)[:, None]            # (H, 1)，H 个帧序号
        if lom is not None:
            a = np.asarray(lang, dtype=np.float32)[None, :] + \
                np.asarray(lom, dtype=np.float32)[None, :] * tt
            ca, sa = np.cos(a), np.sin(a)
        else:
            ca, sa = np.cos(lang)[None, :], np.sin(lang)[None, :]
        ox, oy = lx[None, :], ly[None, :]
        if lvx is not None:
            ox = ox + np.asarray(lvx, dtype=np.float32)[None, :] * tt
        if lvy is not None:
            oy = oy + np.asarray(lvy, dtype=np.float32)[None, :] * tt
        if lspeed is not None:
            e = lend[None, :] + np.asarray(lspeed, dtype=np.float32)[None, :] * tt
            s = np.maximum(lstart[None, :],
                           e - np.maximum(llen, lend - lstart)[None, :])
        else:
            s, e = lstart[None, :], lend[None, :]
    else:
        ca, sa = np.cos(lang)[None, :], np.sin(lang)[None, :]
        ox, oy = lx[None, :], ly[None, :]
        s, e = lstart[None, :], lend[None, :]
    dx, dy = xs[:, None] - ox, ys[:, None] - oy
    t = np.clip(dx * ca + dy * sa, s, e)
    d = np.sqrt((dx - t * ca) ** 2 + (dy - t * sa) ** 2)
    return (d - lw[None, :] * 0.5).min(axis=1)


def warn_rect_cost(x, y, lx, ly, lang, lstart, lend, rect):
    """落点有多「深」地待在预警激光的轴线区间里 → [0, 1]（1 = 正中间，最该离开）

    为什么预警激光要按**矩形**看：实测预警期 `pos` 静止、`speed = 0`，
    「它会不会扫、往哪扫」在预警期没有任何信号；而它一开火就 +6px/帧横扫
    （> 自机 4.39px/帧），**水平方向永远跑不掉**，只有沿轴（上下）跑出线段端点才安全。
    **注意出口**：对 angle = 90° 的竖线，上方出口正是 BOSS 所在（见 `WARN_RECT_W`）——
    所以这只是一条软项，安全分（`ENEMY_MARGIN`）随时能否决它。

    **必须是软项，不能进安全分**：这里的量纲是「逃出区间还需多少 px」，
    与碰撞间隙不是一回事 —— 混进 `min()` 后它那个 −150 会把「撞敌人 −10」
    这种真正致命的威胁盖掉（实测症状：自机为了躲激光径直撞进 BOSS）。
    软项只在安全分数线之上决胜负，真实威胁永远优先。
    """
    if rect is None or not np.any(rect):
        return 0.0
    ca, sa = np.cos(lang), np.sin(lang)
    t = (x - lx) * ca + (y - ly) * sa
    inside = rect & (t > lstart) & (t < lend)
    if not inside.any():
        return 0.0
    esc = np.minimum(np.abs(t - lstart), np.abs(t - lend))
    half = np.maximum((lend - lstart) * 0.5, 1e-6)
    # 越靠区间中点代价越高（= 越该往外走）；贴到端点附近几乎为 0
    return float(np.max(np.where(inside, np.clip(esc / half, 0.0, 1.0), 0.0)))


def bullet_radii(br, bx):
    """逐弹判定半径数组(px)；缺失或长度不符时回落 BULLET_R

    回落而不是报错：grazeSize 读值异常只影响精度，不该让整帧躲避失效。
    """
    if br is None or len(br) != len(bx):
        return np.full(len(bx), BULLET_R, dtype=np.float32)
    return np.asarray(br, dtype=np.float32)


def doomed_gap(px, py, bx, by, enemy, laser, safe=0.0, speed=PLAYER_SPEED, pre=BOMB_PRE,
               br=None):
    """9 个方向各外推 pre 帧，返回「最好的方向」的最小净间隙；< 0 = 怎么走都中弹

    与 `plan()` 的安全分同几何、不同问法：`plan()` 问「哪个方向最优」，这里问
    「有没有一条活路」。所以取九个方向里的最大值 —— 只要还有一条路不重叠，就不是必死。
    用途是灵击的必死预判：**判据为负 ⇒ 不炸必死，所以这一炸不会浪费。**

    `laser` 必须是**有伤害判定的**那一组（`read_frame` 的 `laser_armed`，只含 `L_PHASE_FIRE`）：
    预警 / 消散阶段的激光打不到人，混进来会让「不炸必死」失真 —— 激光还没释放就先炸了。
    """
    if pre <= 0 or not (len(bx) or enemy is not None or laser is not None):
        return 1e9
    ts = np.arange(1, pre + 1, dtype=np.float32)
    # 逐弹判定阈值：小玉 3.25px、普通弹 4.25px、大玉可到 17.25px（MEMMAP §3）
    bthr = (PLAYER_R + bullet_radii(br, bx) + safe) if len(bx) else None
    best = -1e9
    for _name, dx, dy, _keys in DIRS:
        xs = np.clip(px + dx * speed * ts, FIELD_X0, FIELD_X1)
        ys = np.clip(py + dy * speed * ts, FIELD_Y0, FIELD_Y1)
        gaps = []
        if len(bx):
            d = np.sqrt((xs[:, None] - bx[None, :]) ** 2 + (ys[:, None] - by[None, :]) ** 2)
            gaps.append(float((d - bthr[None, :]).min()))
        if enemy is not None:
            g = enemy_gap(xs, ys, *enemy)
            if g is not None:
                gaps.append(float(g.min()) - PLAYER_R - safe)
        if laser is not None:
            g = laser_gap(xs, ys, *laser, ts=ts)
            if g is not None:
                gaps.append(float(g.min()) - PLAYER_R - safe)
        best = max(best, min(gaps) if gaps else 1e9)
    return best


# 空旷度的面积采样点：单位圆内均匀、固定种子 —— 同一坐标永远给同一占比，不引入抖动
_CLEAR_N = 512
_clear_rng = np.random.default_rng(20260924)
_clear_rad = np.sqrt(_clear_rng.random(_CLEAR_N))
_clear_ang = _clear_rng.random(_CLEAR_N) * 2.0 * np.pi
_CLEAR_UX = _clear_rad * np.cos(_clear_ang)
_CLEAR_UY = _clear_rad * np.sin(_clear_ang)


def clear_area_frac(x, y, radius):
    """半径 radius 的圆落在场地内的面积占比 ∈ (0,1]

    边角处这个圆有一小半在场地外（实测左下角 40px 内只有 0.54）——
    空间本来就被边界切掉了，那里「弹少」是假象。密度拿可用面积当分母，
    边角才按真实拥挤度计价，空旷项不会把自机往角落里带。
    """
    xs = x + _CLEAR_UX * radius
    ys = y + _CLEAR_UY * radius
    return float(((xs >= FIELD_X0) & (xs <= FIELD_X1)
                  & (ys >= FIELD_Y0) & (ys <= FIELD_Y1)).mean())


def clearance_cost(x, y, bx, by, radius=CLEAR_R, ref=CLEAR_REF):
    """落点周围的开阔度 → [0,1]；0 = 空旷，1 = 挤到参考值以上

    软化计数（线性核）：每颗弹按「离落点多近」加权，正中算 1、半径边缘算 0。
    用它而不是硬计数 —— 硬计数是台阶函数，同分方向一多就会逐帧横跳。
    只用位置、不看速度：要的是「这一带现在多挤」，弹道预测已由安全分负责。
    密度按**场地内的可用面积**归一（`clear_area_frac`）——否则边角弹少会被读成空旷。
    """
    if len(bx) == 0 or ref <= 0.0:
        return 0.0
    r2 = radius * radius
    d2 = (bx - x) ** 2 + (by - y) ** 2
    near = d2 < r2
    if not near.any():
        return 0.0
    frac = max(clear_area_frac(x, y, radius), 0.05)
    return float(min(float((1.0 - d2[near] / r2).sum()) / (ref * frac), 1.0))


def recenter_cost(x, y, cx=FIELD_CX, cy=FIELD_CY, free=CENTER_R, span=CENTER_SPAN):
    """离待机锚点超出 free 的部分 → [0,1]；带内恒 0

    带内恒 0 是本项与前代「全局中心吸引」的全部区别：场地中部完全自由，
    只有跑远了才被拉回来。目的 = 「别在角落与顶部恋战」，不是「常驻正中心」。
    """
    d = float(np.hypot(x - cx, y - cy))
    return min(max(d - free, 0.0) / max(span, 1e-3), 1.0)


def edge_cost(x, y, margin=EDGE_MARGIN):
    """离场地边界不足 margin 的部分（归一化）；场地中部为 0

    旧的「中心吸引」写成了全局吸引（永远朝正中心），与进攻吸引在全场持续对抗，
    实测把自机钉在原地、水平偏差 53px 打不到目标。贴边才扣分即恢复原意 ——
    避免贴边丧失机动空间，而不是常驻中心。
    """
    return ((max(0.0, margin - (x - FIELD_X0)) + max(0.0, margin - (FIELD_X1 - x))) / FIELD_CX
            + (max(0.0, margin - (y - FIELD_Y0)) + max(0.0, margin - (FIELD_Y1 - y))) / FIELD_CY)


def attack_cost(x, y, tx, ty, standoff, reach=ATTACK_REACH):
    """到「目标下方 standoff〜standoff+reach 这条输出带」的归一化偏差；越小越该走

    水平项权重加倍：自机子弹朝正上方直飞，水平对齐才打得到。
    垂直项是分段死区：
      太远（在输出带下方）→ 驱动靠近；
      带内 → 0，不驱动，自机在带里躲，不是一路贴上去；
      冲过目标头顶 → 按 OVERSHOOT_W 惩罚，那里子弹朝上飞，永远打不到目标。
    旧式 max(0, (y-ty)-standoff) 在冲过目标后恒为 0，与理想位置同分 ——
    实测自机在目标上方 80px 时 none/up/down 三项全为 0，进攻项不再纠偏。
    """
    dy = y - (ty + standoff)
    if dy > reach:
        vert = (dy - reach) / FIELD_CY
    elif dy < 0.0:
        vert = -dy / FIELD_CY * OVERSHOOT_W
    else:
        vert = 0.0
    return 0.5 * abs(x - tx) / FIELD_CX + vert


def fall_frames(dist, vy, acc=FALL_ACC, vmax=FALL_VMAX):
    """道具下落 dist 距离需要多少帧（vy 每帧 +acc，到 vmax 后匀速）

    vy 可为负：道具刚生成时向上飞（SpawnItem 里 startPosition.y = −2.2），
    这段「还得先落回来」的时间必须算进去 —— 否则刚出现的道具会被当成马上到手。
    """
    dist = np.maximum(np.asarray(dist, dtype=np.float32), 0.0)
    vy = np.asarray(vy, dtype=np.float32)
    t_cap = np.maximum((vmax - vy) / acc, 0.0)               # 加速到上限的时刻
    d_cap = vy * t_cap + 0.5 * acc * t_cap ** 2              # 那时已下落的距离
    t1 = (-vy + np.sqrt(np.maximum(vy ** 2 + 2.0 * acc * dist, 0.0))) / acc
    return np.where(dist <= d_cap, t1, t_cap + (dist - d_cap) / vmax)


def item_cost(x, y, ix, iy, vals, vys=None, cap=ITEM_CAP, wait=ITEM_WAIT,
              speed=PLAYER_SPEED, grab=ITEM_GRAB_DIST, fade=ITEM_MISS_FADE,
              down_reach=ITEM_DOWN_REACH, delays=None):
    """此刻值得为道具动身吗 —— 最值得捡那个的等效距离，归一化到 [0,1]；1 = 不值得

    等效距离 = 需要移动的距离 ÷ (时效 × 价值 × 错过程度)。时间模型三项：
      · 时效 = 1 − 到位后还要空等的帧数 / wait：要站在下面仰头等的不追（修掉「干等」）；
      · 赶不上：自机到位所需帧数 > 道具落出场地前剩余帧数 → 出局（修掉「白跑」）；
      · 错过：已经落到自机下方越远越不值（`fade` 外归零）—— 追它意味着离开输出位
        一路向下，而掉落物多半还会再掉。
    垂直方向只在**下方**计入（向下接）；上方的垂直差恒不计 ——
    上方的道具靠下落倒计时处理，自机水平对齐后等它落到身上即可，绝不向上追。
    delays：每块道具的额外延迟帧（state-2 散射物到终点前不下落）—— 只把到达/出局
    两个时刻整体后移，不改变模型；None = 全零（既有调用不受影响）。
    """
    if len(ix) == 0:
        return 1.0
    ix = np.asarray(ix, dtype=np.float32)
    iy = np.asarray(iy, dtype=np.float32)
    vals = np.asarray(vals, dtype=np.float32)
    vy = (np.full(len(ix), FALL_VMAX, dtype=np.float32) if vys is None
          else np.asarray(vys, dtype=np.float32))
    dl = (np.zeros(len(ix), dtype=np.float32) if delays is None
          else np.asarray(delays, dtype=np.float32))

    above = np.maximum(y - grab - iy, 0.0)                    # 在自机高度带之上多远
    t_arr = np.where(above > 0.0, fall_frames(above, vy), 0.0) + dl
    sp = max(speed, 1e-3)
    t_go = np.abs(x - ix) / sp                                # 水平对齐需要几帧
    # 「干等」= 自机到位后还要空等的帧数（不是总时长）：太久的现在不追，
    # 等道具降到近处再来对齐 —— 期间自机可以去输出，而不是站在下面仰头等。
    idle = np.maximum(t_arr - t_go, 0.0)
    fresh = np.clip(1.0 - idle / max(wait, 1e-3), 0.0, 1.0)
    # 赶不上的直接出局：自机到位所需帧数 > 道具落出场地前剩余帧数。
    # ⚠ 这个剩余时间只由**道具**决定（`FIELD_Y1 - iy`），不能写成 `FIELD_Y1 - y`：
    # 那样「自机越高、预算越大」，道具项就会自己驱动自机向上跑（实测选 ur 而不是 right）。
    t_die = fall_frames(FIELD_Y1 - iy, vy) + dl
    miss = np.maximum(iy - y - grab, 0.0)                     # 已经错过（落到自机下方）多远
    # 垂直只牵引 `down_reach` 以内（顺手接）；更远的不改垂直位置，免得为捡道具上下游走
    need = np.hypot(np.abs(x - ix), np.minimum(miss, down_reach))
    pen = np.clip(1.0 - miss / max(fade, 1e-3), 0.0, 1.0)
    ok = (need / sp <= t_die) & (fresh > 0.0) & (pen > 0.0)
    equiv = np.where(ok, need / np.maximum(fresh * vals * pen, 1e-3), 1e9)
    return min(1.0, float(equiv.min()) / cap)


def item_values(types, power, power_bonus=ITEM_POWER_BONUS, full=ITEM_FULL_POWER):
    """每种道具的「值得程度」—— 只决定多个道具同时在追谁，不控总开关（那是 --item）"""
    if len(types) == 0:
        return np.empty(0, dtype=np.float32)
    vals = np.array([ITEM_VALUE.get(int(t), 1.0) for t in types], dtype=np.float32)
    if power < full:
        vals = np.where((types == I_POWER_SMALL) | (types == I_POWER_BIG),
                        vals * power_bonus, vals)
    return vals.astype(np.float32)


def item_aim_vals(ixs, vals, aim_x, tol=ITEM_AIM_TOL, fade=ITEM_AIM_FADE):
    """顺路衰减后的道具价值：水平位置离「目标对齐线」越远越不值，超 tol+fade 归零

    唯一实现处（`plan()` 与 `tools/explain_plan.py` 共用）—— 输出对齐优先于绕路捡：
    打得到才杀得掉，杀得掉才继续掉道具。aim_x = None（没有可打目标）时不衰减。
    """
    if aim_x is None or len(ixs) == 0:
        return vals
    off = np.abs(np.asarray(ixs, dtype=np.float32) - aim_x)
    return vals * np.clip(1.0 - (off - tol) / fade, 0.0, 1.0)


def item_cluster_vals(x, y, ix, iy, vals, vys=None, delays=None,
                      win=ITEM_CLUSTER_WIN, twin=ITEM_CLUSTER_T, w=ITEM_CLUSTER_W,
                      surv_ref=ITEM_SURV_REF, grab=ITEM_GRAB_DIST):
    """集群价值：每块道具的有效价值 += 邻居价值 —— 「一趟能捡最多」的近似

    一片道具挤在同一落点附近时，朝那里走一趟能全收，等效于单块价值翻倍；
    于是「往哪走」从「最近/最值钱的一块」变成「一趟能捡最多的一片」。
    只改 vals（等效距离的分母变大），不动 item_cost 的几何 —— 集群是价值层面的
    加成，不是新的吸引模型；干等/白跑/错过的过滤仍由 item_cost 自己做。
    邻居判据三件：
      · 水平近：|Δx| ≤ win（道具只竖直下落，x 不变，当前位置的 x 即落点）
      · 时间近：到达自机高度的时刻差 ≤ twin（一趟能顺路收完）
      · 邻居可捡：仍在自机高度带上方（没错过），且掉出场前活得够久
        （t_die 按 surv_ref 缩水 —— 快出场的邻居救不回来，别为它抬价）
    """
    if len(ix) < 2 or w <= 0.0:
        return vals
    ix = np.asarray(ix, dtype=np.float32)
    iy = np.asarray(iy, dtype=np.float32)
    vals = np.asarray(vals, dtype=np.float32)
    vy = (np.full(len(ix), FALL_VMAX, dtype=np.float32) if vys is None
          else np.asarray(vys, dtype=np.float32))
    dl = (np.zeros(len(ix), dtype=np.float32) if delays is None
          else np.asarray(delays, dtype=np.float32))
    above = np.maximum(y - grab - iy, 0.0)
    t_arr = np.where(above > 0.0, fall_frames(above, vy), 0.0) + dl
    t_die = fall_frames(FIELD_Y1 - iy, vy) + dl
    near = ((np.abs(ix[:, None] - ix[None, :]) <= win)          # 水平近
            & (np.abs(t_arr[:, None] - t_arr[None, :]) <= twin)  # 时间近
            & (iy[None, :] <= y + grab))                         # 邻居没错过（仍在上方）
    np.fill_diagonal(near, False)
    surv = np.clip(t_die / max(surv_ref, 1e-3), 0.0, 1.0)        # 快出场的邻居缩水
    boost = near * (vals * surv)[None, :]
    return (vals + w * boost.sum(axis=1)).astype(np.float32)


def pick_target(px, py, enemy, boss=None):
    """选攻击目标，返回 (x, y)；无可打目标返回 None

    只认自机上方的敌人：子弹朝上飞，追屏幕下方的敌人既打不着也更危险。
    BOSS 优先（多个时取最近的），否则取自机上方最近的敌人。
    """
    if enemy is None or len(enemy[0]) == 0:
        return None
    exs, eys = enemy[0], enemy[1]
    upper = eys <= py + 8.0
    if not upper.any():
        return None
    cand = np.nonzero(upper & boss)[0] if boss is not None and (upper & boss).any() \
        else np.nonzero(upper)[0]
    d = (exs[cand] - px) ** 2 + (eys[cand] - py) ** 2
    i = cand[int(np.argmin(d))]
    return float(exs[i]), float(eys[i])


# 「没给这个参数」的哨兵 —— 与「给了 None（当前场上没有这类激光）」是两回事。
# 用 None 兼表两义会踩坑：没有 FIRE 激光时 armed=None，就会静默回落成全阶段激光，
# 于是「只认有伤害判定的激光」这一改进在最需要它的时刻（还没开火）失效。
_AUTO = object()


def plan(px, py, bx, by, vx, vy, speed, horizon, safe, edge_w=24.0,
         prev='none', inertia=0.7, enemy=None, laser=None, comfort=1.0,
         attack=None, attack_w=0.0, standoff=STANDOFF,
         margin_w=MARGIN_W, switch_margin=SWITCH_MARGIN, item=None, item_w=0.0,
         warn=None, warn_w=0.0, warn_dist=WARN_DIST,
         item_wait=ITEM_WAIT, risk=RISK_TOL, poc=None, poc_w=0.0, br=None,
         clear_w=0.0, clear_r=CLEAR_R, center_w=0.0, center_r=CENTER_R, center_y=None,
         clear_step=CLEAR_STEP, laser_rect=None, warn_rect_w=WARN_RECT_W,
         enemy_mv=None, bf=None, laser_armed=_AUTO, laser_margin=None, warn_pool=False):
    """返回 (最佳方向名, {方向: 安全分})；安全分 = 时间窗内最小间隙（px），负 = 必然中弹

    safe    : 额外安全裕度(px)，加到判定半径外，越大越保守
    br      : 逐弹判定半径(px)，`read_bullets()` 给出；None = 全按 BULLET_R 兜底
    edge_w  : 贴边惩罚权重。软项之一，只在离边界 EDGE_MARGIN 内扣分，
              场地中部完全自由 —— 不再与进攻吸引全场对抗。
    inertia : 与上一帧同向的奖励，抑制按键抖动
    comfort : 安全分数线(px)。有方向达到它 = 局面不紧张，此时才让贴边/惯性/进攻/道具
              参与排序；否则只比安全分。**软项永不覆盖安全判断。**
    enemy   : (ex, ey, ehw, ehh) 敌人 AABB；
              laser: (lx, ly, lang, start, end, len, w, speed)，见 `laser_segments()`。
               **全部活跃激光**（含预警）—— 用于威胁判定与预警矩形软项。
    laser_armed: 只含 `L_PHASE_FIRE` 的那一组，**安全分只认它**；不给 = 回落 `laser`（旧行为）。
              传 `None` = 「场上当前没有已开火的激光」→ 安全分不含激光（**与「不给」不同**）。
              **默认关**（`LASER_SAFE_ARMED`）：单独摘掉预警线会让自机走进「即将开火」的区域、
              开火即死 —— 病灶在 `laser_margin` 的叠加，不在「进不进安全分」。
    laser_margin: 激光的额外余量(px)，默认 `LASER_MARGIN`。调 0 = 安全分只认纯判定几何。
              **注意它对排序无能为力**：48 条激光覆盖全场时每条对九个方向同等扣分，
              调它只是整体平移分数（实测 16→0 时九向排序逐字不变）。
    warn_pool: 九向全负**且场上有预警线**时，把候选池下限从 0 放宽到 `top - risk`，
              好让软项（尤其 `warn_rect_cost`）参与 —— 否则候选池为空、软项被整体旁路，
              自机在预警激光阵里选 none 站桩。
              **默认关：2026-09-27 实机证伪。** 放开后自机确实不再站桩（帧 177 起移动 8 帧），
              但方向**朝 BOSS** —— `warn_rect_cost` 找的「最近出口」在几何上就是上方
              （自机 y=233：到上端点 y<80 只有 153px，到下端点 y>448 要 215px），
              而上方正是 BOSS。设计者本意是「软项提议往上、**安全分否决撞 BOSS 那一步**」
              （见 `WARN_RECT_W` 那段注释），可**九向全负时安全分的否决机制本来就失效了** ——
              站桩（不放宽）与冲 BOSS（放宽）是同一个缺陷的两面，不是放开就能解决的。
              试过并无效：`center_w=0` / `attack_w=55` / `risk=20`（wide 分支不吃 `risk`）
              / 关掉余量项；**唯一能让自机往下走的是关掉 `warn_rect_cost` 本身**。
              正路是让出口选择避开敌人，不是放开 pool —— 那需要把敌人位置喂给 `warn_rect_cost`。
              分开的理由：预警阶段的激光打不到人，却会带着 `LASER_MARGIN` 的余量把整场判负 ——
              Laevatein 开局 48 条光柱同时生成，九向瞬间全负 → 自机站桩 3.7 秒被打死
              （实机 17 例复盘见 CONTEXT §3.25）。预警线仍走 `warn_rect_cost` 软项：
              它问的是「这一带马上要变危险」，不是「现在就必死」—— 量纲不同，
              混进安全分会盖掉真实威胁（`read_frame` 的 `laser_armed` 即此参数）。
    enemy_mv: (evx, evy) 敌人的逐帧位移（`EnemyMotion` 差分），None = 当它静止。
              敌人池里没有速度字段，不外推就会把「会移动的 BOSS」算成静止的。
              余量另加 `ENEMY_MARGIN`：撞敌人与擦子弹不是同一个定价。
              激光会沿自身方向平移（`end += speed` / 生长完起点跟着走），
              所以每个轨迹点按**那一帧**的线段算间隙（`laser_gap` 的 ts）。
    warn    : 每个敌人的发弹倒计时(帧)，`read_enemies.shoot_countdown()` 给出；None = 不预警
    warn_w  : 弹幕预警窗口(帧)，0 = 关闭。**改的是安全分本身**：即将发弹的敌人
              危险半径按倒计时放大（`warn_radius()`），提前把自机挤出弹幕覆盖区。
    attack  : 攻击目标 (tx, ty)（`pick_target()` 给出），None = 不打谁
    attack_w: 进攻吸引权重，0 = 关闭；值越大越主动朝目标的输出带走
    margin_w: 安全余量权重。池内排序 = 软项 + margin_w×归一化余量，
              间隙越大越优先；余量项单调递增于间隙，不会把间隙 < comfort 的方向
              拉进池子。治「刚够安全就贴到敌人边上」。
    clear_w : 空旷区吸引权重，0 = 关闭。落点周围（半径 clear_r）的弹密度越低分越高。
              与安全分的分工：安全分问「最近那颗会不会撞上」，本项问「这一带弹多不多」。
              治「逐帧钻缝」—— 密集弹幕里局部间隙最大的方向常只是弹与弹之间的一条缝，
              钻进去就越走越窄。同为软项，永不覆盖安全判断。
    clear_r : 空旷度评价半径(px)。
    clear_step: 空旷项的**独立前瞻**(帧)，不跟 ATTACK_STEP。
              理由：4 帧的落点彼此只差几十像素，而评价半径是 110px —— 各方向的空旷度
              高度相关，软项几乎没有区分度（实测同帧极差仅 0.20，决策差异率 1.2%）。
              取 12 帧后极差 0.85；再远区分度提升有限，但「最空方向贴着边界」的比例
              从 2% 涨到 12%(16 帧) / 38%(20 帧)，会把自机往边界赶。
    center_w: 自动回中权重，0 = 关闭。离**待机锚点**超出 center_r 才牵引，带内完全自由。
              补贴边项够不到的地方（主要是**顶部中间**：离四周都不近，贴边项给 0 分，
              但上方弹幕刚生成、反应距离最短）。目的 = 「别在角落与顶部恋战」。
    center_r: 回中自由半径(px)。
    center_y: 待机锚点的 y（默认场地中心 `FIELD_CY`）。调大 = 锚点下移 = 偏好往下待着。
              用途是「下避」：激光阵里上下两个出口不等价，上方端点挨着 BOSS，
              而 `warn_rect_cost` 只按距离挑最近出口（实测挑了上方 → 停 BOSS 正下方被打死）。
              **注意只下移锚点可能不够**：自由带 = 锚点 ± `center_r`，锚点还在带内时毫无效果
              （实测 `center_r=10` 时自机 y=233 恰好卡在自由带边缘）。下移要同时保证
              自机落在带外，否则得到的是「带内随便站」。
    switch_margin: 方向切换门槛。上一帧方向仍安全、且领先不足此值时维持原方向，
              治逐帧原地横跳（每帧都在按键但净位移为 0）。
    item    : (ixs, iys, vals, vys[, delays]) 掉落道具的坐标、价值、下落速度、散射
              延迟，None = 不捡。vals 先过集群加成（item_cluster_vals：一片道具
              互相抬价，比「一趟能捡最多」），再过顺路折扣。
    item_w  : 道具吸引权重，0 = 关闭。与进攻吸引同层的软项 —— 场上没有威胁源时
              （无弹 / 无敌人 / 无激光）软项仍然生效，否则空档期会呆立不动。
    item_wait: 愿意为道具等的帧数（`item_cost()` 的时效尺度）：道具还要更久才落到
              自机高度 → 现在不追。**空档期**（场上无威胁源）改用 `ITEM_WAIT_IDLE`：
              没有中弹风险时先走到落点下方等，是主动捡而不是干等。
              **顺路**：有可打目标时，离目标对齐线太远的道具
              价值被打折（`item_aim_vals()`）—— 输出优先，不为捡道具把对齐走丢。
    risk    : 紧张档的「同等安全容差」(px)。最优方向间隙 < comfort 时，只允许安全分与
              它相差 ≤ risk 的方向让软项决胜负 —— 既不会为输出走进实质更危险的方向，
              也不会像旧逻辑那样一紧张就完全不追 BOSS（boss 战弹幕密，旧逻辑全程纯躲）。
              risk = 0 退回旧行为；候选始终要求间隙 ≥ 0（外推下会中弹的方向永不入选）。
    poc     : 冲线目标 (tx, ty)（ItemLineTrip 处于 charging 时给出），None = 不冲。
              冲线期**替代**进攻与道具吸引（不是叠加）：attack_cost 的「冲过头顶」
              惩罚专治输出位，冲线时往上冲正是目的，留着它会把自机按在线下磨蹭。
    poc_w   : 冲线吸引权重 = attack_w + item_w + POC_W_EXTRA（借走两者的权柄再加码）。
              与其他软项同层 —— 安全分永远压过它：上方被弹幕堵死时自然冲不上去。
    bf      : `read_bullet_frame()` 的 `BulletFrame`，必须与 bx/by/vx/vy **同源同序**。
              给了就按 exFlags 逐帧推进（加速弹的抛物线、转向弹定时器到点后换向）；
              不给只能按当前速度匀速外推 —— 加速弹偏近、转向弹在转向帧之后整段错。
    """
    # 预警半径在循环外算一次：它只依赖敌人自身状态，与候选方向无关
    if enemy is not None and warn is not None and warn_w:
        r2 = warn_radius(warn, warn_w, warn_dist) * 2.0     # 半径 → 盒边长
        enemy = (enemy[0], enemy[1], enemy[2] + r2, enemy[3] + r2)
    has_threat = threat_present(bx, enemy, laser)
    # 安全分只认有伤害判定的激光（见 `laser_armed` 的说明）；预警线照旧只走软项。
    # 威胁判定（上一句）与软项仍看全部活跃激光 —— 只改「会不会中」这一问，不改「要不要让」。
    lasafe = laser if laser_armed is _AUTO else laser_armed
    # 默认值在**运行时**取常量：写成签名默认值会在定义时求值，测试里 monkey-patch
    # `LASER_MARGIN` 的用例就失效了（check_plan「激光余量」那组踩过）。
    lmargin = LASER_MARGIN if laser_margin is None else laser_margin
    if not has_threat and item is None and poc is None:
        return 'none', {n: 0.0 for n, _, _, _ in DIRS}
    # 道具吸引：拆出 vys / delays 给时间模型；集群加成让「往哪走」比的是一趟能
    # 捡最多的一片（item_cluster_vals）；有可打目标时再按「顺路」打折 ——
    # 输出对齐（打得到 → 敌人才会死 → 才继续掉道具）优先于绕路捡。
    # 冲线期（poc 非空）道具与进攻吸引整体让位给冲线吸引（见循环内 poc 分支）。
    item_arg = None
    if item is not None and item_w and poc is None:
        ixs, iys, vals = item[0], item[1], item[2]
        vys = item[3] if len(item) > 3 else None
        delays = item[4] if len(item) > 4 else None
        vals = item_cluster_vals(px, py, ixs, iys, vals, vys, delays)
        vals = item_aim_vals(ixs, vals, attack[0] if attack is not None else None)
        item_arg = (ixs, iys, vals, vys, delays)
    # 空档期（场上没有威胁源）没有中弹风险：「先走到落点下方等它掉下来」不算干等，
    # 放宽等待上限才是**主动**捡；有威胁源时仍按 item_wait（不为道具站桩）。
    wait_eff = item_wait if has_threat else max(item_wait, ITEM_WAIT_IDLE)
    # 帧数必须是 int：`dodge_params.json` / 控制台存的是浮点（实测 `"horizon": 20.0`），
    # 而 `np.full` 与切片都不接受浮点 shape（`np.arange` 容忍，所以这个坑一直没暴露）。
    horizon = int(horizon)
    ts = np.arange(1, horizon + 1, dtype=np.float32)
    ts_laser = np.arange(1, LASER_HORIZON + 1, dtype=np.float32)
    if bf is not None:
        # 加速弹 / 转向弹按原版机制逐帧推进（bf 与 bx/by/vx/vy 同源同序）
        fx, fy = bullet_paths(bf, horizon, px, py)
    else:
        fx = bx[None, :] + vx[None, :] * ts[:, None]      # 子弹外推 (H, N)
        fy = by[None, :] + vy[None, :] * ts[:, None]
    # 逐弹判定阈值 (N,)：必须先各减各的再取 min —— 用统一常数会把大玉当小玉躲
    threat = PLAYER_R + bullet_radii(br, bx) + safe

    scores, soft, rank, raw0 = {}, {}, {}, {}
    for name, dx, dy, _ in DIRS:
        xs = np.clip(px + dx * speed * ts, FIELD_X0, FIELD_X1)
        ys = np.clip(py + dy * speed * ts, FIELD_Y0, FIELD_Y1)
        gaps = []
        # 逐帧对齐的三类间隙（长度 = horizon）：各类威胁各算各的 min 会丢掉时间信息，
        # 而全负时唯一有区分度的恰恰是「第几帧脱出真实判定圈」（见 ESCAPE_RANK）。
        # 三个数组分开留是为了反推「不含余量」的纯判定几何 —— 各类的余量坑不同
        # （子弹只多 safe，敌人另加 ENEMY_MARGIN，激光另加 LASER_MARGIN）。
        pb = pe = pl = None
        if len(bx):
            g = (np.sqrt((xs[:, None] - fx) ** 2
                         + (ys[:, None] - fy) ** 2) - threat[None, :]).min(axis=1)
            gaps.append(g)
            pb = g + safe                          # threat 里含 safe，减回去
        if enemy is not None:
            # 敌人会动（BOSS 实测逐帧位移），速度靠 `EnemyMotion` 差分 —— 不外推等于
            # 把唯一「撞上必死」的威胁当成静止的。余量另加 ENEMY_MARGIN。
            g = enemy_gap(xs, ys, *enemy,
                          evx=None if enemy_mv is None else enemy_mv[0],
                          evy=None if enemy_mv is None else enemy_mv[1],
                          ts=ts)
            if g is not None:
                g = g - PLAYER_R - safe - ENEMY_MARGIN
                gaps.append(g)
                pe = g + safe + ENEMY_MARGIN
        if lasafe is not None:
            # 激光走**自己的长前瞻**（LASER_HORIZON）：横扫过来的激光在 16 帧窗口外
            # 时判成安全，进攻吸引就把自机按在输出位上，等它进窗口已经来不及
            # ——「激光要出了还在打敌人」就是这么来的（用户实测）。
            lxs = np.clip(px + dx * speed * ts_laser, FIELD_X0, FIELD_X1)
            lys = np.clip(py + dy * speed * ts_laser, FIELD_Y0, FIELD_Y1)
            g = laser_gap(lxs, lys, *lasafe, ts=ts_laser)
            if g is not None:
                # 激光另留一截余量（`laser_margin`）：不留的话自机会贴着它输出，一拉就进去。
                # **它是「别贴着输出」的偏好，不是判定几何** —— 48 条同时在场时每条的余量
                # 叠加，会把整场判负（实测 ESCAPE_RANK 就是为这个现象加的，见 218 行）。
                g = g - PLAYER_R - safe - lmargin
                gaps.append(g)
                pl = (g + safe + lmargin)[:horizon]   # 激光窗口更长，截前段对齐
        scores[name] = float(min(g.min() for g in gaps)) if gaps else 0.0
        # 逐帧取三类威胁的**纯判定几何**（自机中心到判定圈边缘的净距离）：三类的余量
        # 坑各不相同（子弹只多 safe，敌人另加 ENEMY_MARGIN，激光另加 LASER_MARGIN），
        # 各自减回去再取逐帧最小 —— 用它判「会不会真被命中」，不含任何余量偏好。
        raw = np.full(horizon, np.inf, dtype=np.float32)
        for arr in (pb, pe, pl):
            if arr is not None:
                raw = np.minimum(raw, arr)
        # 九向全负时 scores 已无区分度（激光余量能把整场判负），改按「窗口内还有几帧
        # 不在判定圈里」排：已经踩进去的，出圈越早剩下的安全帧越多；还没踩进去的，
        # 越晚被踩进来安全帧越多 —— 一个量覆盖两种局面，中途被命中的帧也不计白不计。
        # 实测 121323：站着不动只被激光余量扣 4.69（真实间隙 15px，根本没碰着），
        # 而唯一能躲开下一帧子弹的 down 因 20 帧后会撞上一条已开火的激光被判 -29.35
        # —— 旧排序（只看最小间隙）于是选「不动」，一帧后被那颗大玉打死。
        rank[name] = int((raw >= 0.0).sum())
        raw0[name] = float(raw[0])
        # 软项统一用 ATTACK_STEP 前瞻位置。别用 horizon 外推终点：那会把
        # 「朝边界走一步」当成「一路走到边界」（实测自机要右移 30px 对齐目标，
        # 却因外推 120px 撞边界被劝退，水平偏差 30px 打不到），
        # 也会把「朝目标走一步」当成「撞进目标怀里」。
        ax = min(max(px + dx * speed * ATTACK_STEP, FIELD_X0), FIELD_X1)
        ay = min(max(py + dy * speed * ATTACK_STEP, FIELD_Y0), FIELD_Y1)
        soft[name] = -edge_w * edge_cost(ax, ay) + (inertia if name == prev else 0.0)
        # 位置质量两项（空旷区 / 回中）：都只看前瞻落点，不看 horizon 终点
        # （→ DO_NOT_REVERT「别把软项的前瞻改回 horizon」）
        if clear_w:
            # 空旷项另用自己的前瞻（见 CLEAR_STEP）：4 帧的落点彼此太近、没有区分度
            clx = min(max(px + dx * speed * clear_step, FIELD_X0), FIELD_X1)
            cly = min(max(py + dy * speed * clear_step, FIELD_Y0), FIELD_Y1)
            soft[name] -= clear_w * clearance_cost(clx, cly, bx, by, clear_r)
        if center_w:
            # 待机锚点可下移（`center_y`）：激光阵里上下两个出口不等价 —— 上方端点挨着 BOSS，
            # 往下才是活路，而 `warn_rect_cost` 只按距离挑「最近出口」（实测 135407 挑了上方
            # → 停在 BOSS 正下方被打死）。把锚点下移 = 用回中项给出「往下待着」的偏好。
            soft[name] -= center_w * recenter_cost(
                ax, ay, cy=(FIELD_CY if center_y is None else center_y), free=center_r)
        if laser_rect is not None and laser is not None and warn_rect_w:
            # 预警激光的轴线区间：横向逃不掉（它一开火就横扫），请自机沿轴线出去。
            # **软项**：安全分永远是真实几何，这道「往外走」的偏好只在够安全时说话 ——
            # 否则会为了躲激光撞进敌人（见 WARN_RECT_W）。
            # 前瞻用**自己的**（WARN_RECT_STEP）：4 帧的落点分不出「在区间里」的深浅。
            wx = min(max(px + dx * speed * WARN_RECT_STEP, FIELD_X0), FIELD_X1)
            wy = min(max(py + dy * speed * WARN_RECT_STEP, FIELD_Y0), FIELD_Y1)
            soft[name] -= warn_rect_w * warn_rect_cost(wx, wy, *laser[:5], laser_rect)
        if poc is not None and poc_w:
            # 冲线期：进攻/道具吸引让位（不是叠加）—— attack_cost 的「冲过头顶」
            # 惩罚专治输出位，冲线时往上冲正是目的，留着它会把自机按在线下磨蹭。
            # 距冲线目标越近分越高；两点都在场内 → 距离 ≤ 对角线，项自然落在 [0, poc_w]。
            soft[name] += poc_w * (1.0 - np.hypot(ax - poc[0], ay - poc[1]) / POC_NORM)
        else:
            if attack is not None and attack_w:
                soft[name] -= attack_w * attack_cost(ax, ay, attack[0], attack[1], standoff)
            if item_arg is not None:
                soft[name] += item_w * (1.0 - item_cost(ax, ay, *item_arg[:4],
                                                        wait=wait_eff,
                                                        delays=item_arg[4]))

    top = max(scores.values())
    if has_threat and top < comfort:
        # 紧张档：旧逻辑一紧张就把软项全拦掉 → boss 战（弹幕密，几乎从不满足分数线）
        # 全程只躲不打。改为只在「与最优方向同样安全」的方向之间让软项决胜负，
        # 且候选必须间隙 ≥ 0 —— 外推下会中弹的方向永不入选，安全判断仍不被偏好覆盖。
        # 九向全负**且场上有预警线**时，直接放开候选池（安全分已无区分度：全负就是
        # 「怎么走都在余量圈里」，此时唯一还能分辨的信息是软项 —— 而
        # 「预警激光马上要开火、得沿轴线往外走」**只有软项知道**（`warn_rect_cost`）。
        # 原来的 `max(top - risk, 0.0)` 在这种帧会把池清空 → 只剩 `max(scores)` →
        # 自机选 none 站桩，等激光一转发射就被打死（实机 131730：静止 25 帧）。
        # 只放宽 `risk` 不够：这里九向的分布是 none 一枝独秀、其余挤在 -29（差 11px），
        # risk 得调到 11 才圈得进移动方向 —— 那是滥用「同等安全容差」的语义。
        # **必须限定「场上有预警线」**：没有预警线时软项没有「该往外走」的输入，
        # 放开只会把自机推向下边界死角（实测 121449 就是这么更早死的，它那帧激光数是 0）。
        # **已侵入判定圈的场合留给下面的 `ESCAPE_RANK`**：那时「马上挪窝」比「往外走」
        # 更急，而 ESCAPE_RANK 按「第几帧脱出」排正是为它写的。放宽若抢在它前面，
        # 会把这个兜底短路掉（实测 113717 反向：选不动 1 → 10 帧）。
        wide = (warn_pool and top < 0.0 and laser_rect is not None
                and laser_rect.any() and raw0.get('none', 0.0) >= 0.0)
        if wide:
            pool = list(scores)
            # 余量项在**全负**时是纯惩罚（`scores - top ≤ 0` → 归一化后为负）：
            # 实测 `down` 被判 −5.29，刚放开的软项根本翻不过它 → 自机停在原地
            # （135407 帧 185 之后停 39 帧、帧 238 被垂直落下的加速弹打死）。
            # 安全分此时已无区分度（全负 = 怎么走都在余量圈里），胜负该交给软项
            # ——「预警激光马上要开火、得沿轴线往外走」只有 `warn_rect_cost` 知道。
            base, scale, margin_w = top, RISK_SOFT, 0.0
        elif risk > 0.0:
            pool = [n for n, s in scores.items() if s >= max(top - risk, 0.0)]
        else:
            pool = []
        if len(pool) <= 1:
            # 只在「九向全负」**且**「当前这一步已经踩进判定圈」时改排序：
            # 前者说明最小间隙已无区分度，后者才是「必须马上挪窝」的判据。
            # 当前没侵入时不启用 —— 实测（121449）那时改排序会把自机一路推到下边界
            # 卡进死角，反而比原来的「挑最宽处待着」更早死。
            if ESCAPE_RANK and top < 0.0 and raw0.get('none', 0.0) < 0.0:
                # 这里**不能**让软项参与打破 rank 并列：项目有意规定「已侵入判定圈时按最快
                # 出圈排、不看偏好」（`check_plan` 两条护栏用例守住这一点）。试过一版
                # 「rank 并列时用 soft 决胜」，当场被那两条用例挡下 —— 包括实机案例
                # 需要的 `up`，也不是软项能改的（帧 177 的 rank 唯一最高）。
                # 「下避」要在这里生效，得让 rank 的几何本身知道 BOSS 在哪个方位。
                return max(scores, key=lambda n: (rank[n], scores[n])), scores
            return max(scores, key=scores.get), scores
        base, scale = top, RISK_SOFT
    else:
        # 无威胁源时 scores 恒为 0、必低于 comfort，若照旧拦截就永远不动（捡不了道具）。
        # 此时所有方向都绝对安全，直接让软项决胜负；余量项对每个方向同值，不影响排序。
        pool = [n for n, s in scores.items() if s >= comfort] if has_threat else list(scores)
        base, scale = comfort, 1.0
    # 余量项按「池的基准」量度：宽裕档基准是分数线，紧张档基准是最优方向本身 ——
    # 紧张档若仍按分数线算，gap < comfort 会让它变成大额负分（正比于与分数线的差距），
    # 反过来盖过软项，把「同等安全内偏输出」又压回纯躲。
    merit = {n: scale * soft[n] + margin_w * min(scores[n] - base, MARGIN_CAP) / MARGIN_CAP
             for n in pool}
    best = max(pool, key=lambda n: merit[n])
    if prev in merit and merit[best] - merit[prev] < switch_margin:
        return prev, scores
    return best, scores


class ReactionGate:
    """安全时的反应延迟 —— 局面宽裕就慢半拍再动，紧起来立刻执行

    为什么只在安全时：人的反应时间随紧张程度变化。危险时高手是零延迟的即时反应；
    安全时动作从容 —— 一次动作走一段，不每帧改主意。延迟加在危险侧只会送命。

    允许延迟的三个前提（`update()` 里的判据，任一不满足即当帧执行）：
      1. 当前方向间隙 ≥ comfort —— **延迟期间走的就是这条路**。`plan()` 的间隙已覆盖
         horizon 帧的外推轨迹，远长于这几帧延迟，所以慢半拍仍在已确认安全的轨迹上。
      2. 最优方向间隙 ≥ comfort + slack —— 还有宽裕的替代方案，等得起。
      3. 无威胁源（空档期）—— 所有方向绝对安全，直接允许延迟。

    延迟长度逐次抖动（`REACT_JITTER`）：固定的帧数节奏本身就是机械特征。
    目标方向可变、已等帧数不重置 —— 保证最坏情况下延迟仍有界，不会因软项反复
    拉锯而永远不执行。
    """

    def __init__(self, rng=None):
        self.rng = rng or random.Random()
        self.target = 'none'
        self.waited = 0
        self.limit = 0

    def reset(self):
        self.target, self.waited, self.limit = 'none', 0, 0

    def update(self, best, cur, scores, comfort, react, threat=True, slack=REACT_SLACK,
               min_comfort=REACT_MIN_COMFORT):
        """返回本帧实际执行的方向；react <= 0 = 关闭，原样返回 best（旧行为）"""
        if react <= 0:
            self.reset()
            return best
        if threat:
            # 底线与「安全分数线」解耦：分数线是软项的闸门，调低它是为了多参与排序，
            # 不该连带把延迟闸门一起放松 —— 取大者，调高时从严、调低时不放松。
            line = max(comfort, min_comfort)
            if scores.get(cur, 0.0) < line or scores.get(best, 0.0) < line + slack:
                self.reset()
                return best
        if best == cur:
            self.reset()
            return cur
        if self.waited == 0:                        # 新计划：掷出本次要等几帧
            self.limit = max(1, round(react * self.rng.uniform(*REACT_JITTER)))
        self.target = best
        self.waited += 1
        if self.waited >= self.limit:
            self.reset()
            return best
        return cur


class BombGuard:
    """自动灵击 —— 被打中时放技能保命，躲不过时提前炸

    两级判据（依据 → MEMMAP §11，全部由 `Player__OnUpdate` 反汇编 + 实机读值确证）：

      1. **死亡炸弹**：`state == DEAD 且 respawn > 0`。被击中的那一刻起 respawnTimer 从 8
         逐帧递减，到 0 才结算掉命；这段窗口里按 X，角色 bomb 的 calc 会把 playerState
         改成 INVULNERABLE —— **死亡就此取消**。这是真人高手最标志性的操作。
      2. **必死预判**：9 个方向外推 pre 帧全都与威胁重叠（`doomed_gap() < 0`）。判据为负
         意味着「不炸必死」，所以这一炸不会浪费；它抢在碰撞判定之前生效，比死亡炸弹更稳。

    两个「不浪费」的前提：`bombs > 0`，且当前没有灵击正在生效（`bomb_in_use`）。
    只在 `state == ALIVE` 时做必死预判 —— 无敌 / 复活中本来就不会死，炸了纯浪费。

    按住 `hold` 帧再松开：游戏的按下沿检测要求按键**跨帧存在**，同帧 down+up 会被漏掉。
    """

    def __init__(self, key=BOMB_KEY, hold=BOMB_HOLD, cooldown=BOMB_COOLDOWN):
        self.key = key
        self.hold_frames = max(1, int(hold))
        self.cooldown = max(0, int(cooldown))
        self.hold = 0
        self.cool = 0
        self.rescues = 0        # 死亡炸弹次数
        self.preempts = 0       # 必死预判次数
        self.event = None       # 本帧触发的原因（'rescue' / 'preempt'），仅供日志

    def reset(self):
        self.hold = 0
        self.cool = 0
        self.event = None

    def update(self, st, doomed, enabled=True):
        """返回本帧是否按住灵击键；`st` 来自 `read_bullets.read_player_state()`"""
        self.event = None
        if self.hold > 0:
            self.hold -= 1
            if self.hold == 0:
                self.cool = self.cooldown
            return True
        if self.cool > 0:
            self.cool -= 1
            return False
        if not enabled or st is None:
            return False
        if st['bombs'] <= 0 or st['bomb_in_use']:
            return False
        if st['state'] == PLAYER_STATE_DEAD and st['respawn'] > 0:
            self.hold = self.hold_frames - 1
            self.rescues += 1
            self.event = 'rescue'
            return True
        if doomed and st['state'] == PLAYER_STATE_ALIVE:
            self.hold = self.hold_frames - 1
            self.preempts += 1
            self.event = 'preempt'
            return True
        return False


class ItemLineTrip:
    """智能道具线冲刺（PoC）—— 满火力且场上可转化价值够高时，冲上收集线一次

    EoSD 的收集线只在满火力时存在（ItemManager::OnUpdate 0x42980：state≠2 且
    power ≥ 128 且自机 y < 128 → 全屏 state-0 道具强制转追踪，8px/帧 飞向自机，
    不可能再漏捡）。火力不满冲线毫无收益，所以满火力是触发条件之一；
    state-2 散射物永远不参与转化（转化判据在 state≠2 分支里，原版如此），
    但它们会照常落到屏幕下部 —— 回位路上顺路身体接。

    状态机：
      idle --(满火力 & 可转化价值 ≥ poc_min & 自机在线下)--> charging
      charging --(y < POC_LINE_Y 越线)--> idle        转化已发生，道具自己飞来
      charging --(限时到 / 价值见底 / 火力掉了 / 被关)--> cooldown --(到时)--> idle
    冲线吸引走 plan() 的软项通道（poc_w = attack + item + extra）并**替代**进攻/
    道具吸引；安全分永远压过它 —— 上方被弹幕堵死时自然冲不上去，限时一到放弃
    冷却，绝不硬闯。冲线目标 x = 非追踪道具的价值加权质心（read_frame 给出）。
    """

    def __init__(self, poc_min=POC_MIN, timeout=POC_TIMEOUT, cooldown=POC_COOLDOWN):
        self.poc_min = max(0.0, float(poc_min))
        self.timeout = max(1, int(timeout))
        self.cooldown = max(0, int(cooldown))
        self.state = 'idle'    # idle | charging | cooldown
        self.t = 0             # 当前状态已停留帧数
        self.trips = 0         # 成功冲线次数
        self.gives = 0         # 放弃次数
        self.event = None      # 本帧事件（'start' / 'trip' / 'giveup'），仅供日志

    def reset(self):
        self.state, self.t, self.event = 'idle', 0, None

    def update(self, py, power, poc_val, enabled=True):
        """每帧调用；返回 True = 正在冲线（调用方据此给 plan() 传冲线目标）

        py      : 自机当前 y（越线即成功 —— 判据与游戏一致取严格小于）
        power   : 火力（0..128；收集线只在满火力时存在）
        poc_val : 场上 state-0 可转化道具的总价值（read_frame 给出）
        enabled : 总开关（道具吸引关了 / 控制台没勾就不冲；冲到一半被关也放弃）
        """
        self.event = None
        if self.state == 'cooldown':
            self.t += 1
            if self.t >= self.cooldown:
                self.state, self.t = 'idle', 0
            return None
        if self.state == 'idle':
            if (not enabled or power < ITEM_FULL_POWER or py < POC_LINE_Y
                    or poc_val <= 0.0 or poc_val < self.poc_min):
                return None
            self.state, self.t = 'charging', 0
            self.event = 'start'
        # charging：越线即成功；限时 / 价值见底 / 火力掉了 / 被关掉 → 放弃进冷却
        self.t += 1
        if py < POC_LINE_Y:
            self.trips += 1
            self.event = 'trip'
            self.state, self.t = 'idle', 0
            return None
        if (self.t >= self.timeout or poc_val <= 0.0 or power < ITEM_FULL_POWER
                or not enabled):
            self.gives += 1
            self.event = 'giveup'
            self.state, self.t = 'cooldown', 0
            return None
        return True


class StageFlow:
    """关卡之间的推进：过渡态不退出、开场对话自动按 Z 前进

    依据（原版 `Gui.cpp` 的 msg 虚拟机，新典同构）：
      · 关卡结束 → `MSG_OPCODE_STAGEEND` 把 curState 置成 3（GAMEMANAGER_REINIT），
        `GameManager::AddedCallback` 里 `currentStage++` 后自动载入下一关 —— **不用按键**。
      · 关卡开场的对话是 `MSG_OPCODE_WAIT`：只认 `WAS_PRESSED(TH_BUTTON_SHOOT)`，
        两次按下沿还要隔 ≥8 帧 —— 按住 Z 连射永远推不动它。

    所以这里只做两件事：过渡态计时（超时才算卡死）、无威胁源时按节奏轻点 Z。
    「无威胁源」是敢轻点的前提：对话与开场飞行段本来就没有弹幕/敌人/激光，此时 Z 只有
    射击一个作用；有威胁源时绝不轻点 —— 那会松开正在连射的 Z。
    """

    def __init__(self, tap_s=ADVANCE_TAP_S, timeout_s=ADVANCE_TIMEOUT_S):
        self.tap_s = tap_s
        self.timeout_s = timeout_s
        self.t_switch = None      # 进入关卡切换态的时刻（None = 不在切换中）
        self.t_tap = 0.0          # 上次轻点 Z 的时刻
        self.switches = 0         # 跨过的关卡过渡次数
        self.taps = 0             # 累计轻点次数（收尾日志用）

    def switching(self, now):
        """登记一次「处在关卡切换态」，返回 (已等待秒数, 是否刚进入)"""
        first = self.t_switch is None
        if first:
            self.t_switch = now
            self.switches += 1
        return now - self.t_switch, first

    def back_in_game(self):
        """回到关卡中 —— 清掉过渡计时"""
        self.t_switch = None

    def tap_due(self, now, quiet):
        """该轻点一次 Z 了吗（quiet = 场上没有威胁源）"""
        if not quiet or now - self.t_tap < self.tap_s:
            return False
        self.t_tap = now
        self.taps += 1
        return True


def apply_keys(held, want):
    want = set(want)
    for k in held - want:
        th06.key_up(k)
    for k in want - held:
        th06.key_down(k)
    held.clear()
    held.update(want)


def release_all(held, skip=()):
    """松开脚本按下的所有键

    `skip` = 玩家此刻物理按着的键：对它们只从 held 里划掉、**不发抬键** ——
    SendInput 的抬键同样会改系统键状态表，硬松会把人家按住的右方向顶掉。
    """
    for k in list(held):
        if k not in skip:
            th06.key_up(k)
    held.clear()


def apply_fire(firing, want):
    """自动射击：按住 Z 才连射（反复 tap 只出零星几发，射速全靠按住状态）

    返回新的按键状态。只在状态变化时发一次 SendInput。
    """
    if want and not firing:
        th06.key_down(FIRE_KEY)
        return True
    if not want and firing:
        th06.key_up(FIRE_KEY)
        return False
    return firing


def read_frame(p, mb, use_enemy=True, use_laser=True, use_item=True, motion=None,
               enemy_motion=None):
    """读一帧世界状态；返回 dict，读取失败返回 None

    主循环与「预备接管」共用，避免两处各写一遍筛选逻辑。
    `motion` = `LaserMotion`：给激光补上「轴原点每帧位移」，只有**连续逐帧调用**才有
    意义（主循环传；单帧诊断工具不传 → 按静止处理）。
    """
    bf = read_bullet_frame(p, mb)
    if bf is None:
        return None
    bf_raw = bf            # 未过滤的整池：黑匣子取证要用 —— 命中自机的弹**当帧就转消散**，
    if BULLET_SKIP_DESPAWN:  # 只留过滤后的版本会让真凶在判定帧凭空消失
        # 消散阶段不做碰撞判定（原版只有 FIRED 判死），躲它是纯浪费移动。
        # 生成阶段(2/3/4)不过滤：那些弹就停在生成点上，几帧后就进入判死状态。
        keep = np.nonzero(bf.states != BULLET_STATE_DESPAWNING)[0]
        if len(keep) != len(bf.states):
            bf = bf._replace(**{f: getattr(bf, f)[keep] for f in bf._fields})
    bx, by, vx, vy, br = bf.xs, bf.ys, bf.vxs, bf.vys, bf.brs
    px, py = read_player(p, mb)
    enemy = laser = target = item = None
    er = lf = None                     # 原始池（黑匣子取证要：敌人槽号/标志/发弹倒计时、激光阶段）
    enemy_mv = None                    # 敌人逐帧位移（池里没有速度字段 → EnemyMotion 差分）
    armed = None                       # 真正有伤害判定的激光（必死预判只能看它）
    laser_rect = None                  # 预警阶段的激光（矩形避让软项的输入，见 WARN_RECT_W）
    warn = None
    n_enemy = n_laser = n_item = 0
    if use_enemy:
        er = read_enemies(p, mb)
        if er is not None:
            eslots, exs, eys, elife, ehw, ehh, ef2, ef3, iv, tm = er
            keep = ((ef2 & E_COLLIDABLE) != 0) & ((ef3 & E_INVISIBLE) == 0)  # 可碰撞 且 非隐形
            enemy = (exs[keep], eys[keep], ehw[keep], ehh[keep])
            # 敌人也要有速度（池里读不到，逐帧差分）：不外推 = 把会移动的 BOSS
            # 当成静止的，前瞻 16 帧的误差全算在自机头上 —— 撞上必死（Laevatein 实测）。
            if enemy_motion is not None:
                enemy_mv = enemy_motion.speeds(eslots[keep], exs[keep], eys[keep],
                                               elife[keep])
            warn = shoot_countdown(iv, tm)[keep]      # 每个敌人的发弹倒计时（-1 = 不射击）
            n_enemy = int(keep.sum())
            target = pick_target(px, py, enemy, ((ef2 & E_BOSS) != 0)[keep])
    if use_laser:
        lf = read_lasers(p, mb)
        if lf is not None:
            # 躲避用**全部活跃激光**（预警线就是马上要开火的位置，必须让开 ——
            # 而它自己也在平移，所以带时间维预测，见 laser_gap）；
            # 必死预判只认 `L_PHASE_FIRE` —— 预警阶段打不到人，拿它当「不炸必死」
            # 就会在激光还没释放时白扔炸弹（实测踩过）。
            # 两种速度各管一段：`speeds`（offset 前进，槽里能读）与
            # `mv`（轴原点平移，槽里读不到 → LaserMotion 逐帧差分）。
            mv = motion.speeds(lf) if motion is not None else None
            # 预警线 = 「这一带马上要变危险」（它会不会横扫在预警期没有信号，见 WARN_RECT_W）：
            # 单独交给软项，不进安全分 —— 量纲不同，混进去会盖掉真实威胁。
            laser_rect = (lf.phases == L_PHASE_WARN) if WARN_RECT_ON else None
            laser = laser_segments(lf, motion=mv) if len(lf.xs) else None
            keep = lf.phases == L_PHASE_FIRE
            armed = laser_segments(lf, keep, mv) if keep.any() else None
            n_laser = len(lf.xs)
    power = 0.0
    poc_val, poc_cx = 0.0, None
    if use_item:
        ir = read_items(p, mb)
        if ir is not None:
            # 三态分拣（MEMMAP §9 / ItemManager::OnUpdate）：
            #   0=普通下落（vy 走 +0.03 规律）；1=已被吸引（8px/帧追自机，自投罗网，
            #     不必吸引，vy 字段也已被改写、模型不适用）→ 从吸引集里剔除；
            #   2=散射（60 帧插值到 target；期间 vy 字段是出生点 y = 垃圾值，
            #     且散射结束时 vy 清零、state 永不转 0 → 永不参与收集线转化）
            #     → 位置用散射终点近似，vy=0（结束后从静止开始落），
            #     加平均剩余帧延迟（delays 平移到达/出局时刻，模型本身不变）。
            _, ixs0, iys0, ivys0, itypes, istates, itxs, itys = ir
            power = read_power(p, mb)
            vals = item_values(itypes, power)
            # 冲线可转化价值：收集线只把 state-0 强制转追踪 —— 只有它们算数
            conv = istates == 0
            poc_val = float(vals[conv].sum()) if len(itypes) else 0.0
            # 冲线目标 x：非追踪道具（state 0 + 2）的价值加权质心；state-2 用终点
            nt = istates != 1
            if nt.any() and float(vals[nt].sum()) > 0.0:
                cx = np.where(istates == 2, itxs, ixs0)
                poc_cx = float(np.dot(cx[nt], vals[nt]) / vals[nt].sum())
            scat = istates[nt] == 2
            ixs = np.where(scat, itxs[nt], ixs0[nt])
            iys = np.where(scat, itys[nt], iys0[nt])
            ivys = np.where(scat, 0.0, ivys0[nt]).astype(np.float32)
            delays = np.where(scat, SCATTER_AVG, 0.0).astype(np.float32)
            item = (ixs, iys, vals[nt], ivys, delays)
            n_item = int(nt.sum())
    return dict(bx=bx, by=by, vx=vx, vy=vy, br=br, px=px, py=py, bf=bf, bf_raw=bf_raw,
                enemy=enemy, enemy_mv=enemy_mv, enemy_raw=er, lf=lf,
                laser=laser, laser_armed=armed, laser_rect=laser_rect,
                n_enemy=n_enemy, n_laser=n_laser, target=target,
                item=item, n_item=n_item, warn=warn,
                power=power, poc_val=poc_val, poc_cx=poc_cx)


def run_session(p, mb, hwnd, cfg, on_frame=None, on_world=None, stop_flag=None,
                log=print):
    """躲避主循环 —— CLI 与 GUI 共用，安全闸只此一处

    cfg 键: dry / frames / horizon / speed / safe / inertia / edge / period /
            use_enemy / use_laser / use_item / unpause / resume / restore /
            keep_going_on_death / autofire / attack / standoff / item / react /
            poc / poc_min / advance / human_yield / human_idle
    on_frame: 每帧回调，收 state dict；返回 False 则停止
    on_world: 每帧回调，收 (w, st, ps) —— `read_frame` 的原始世界（黑匣子取证用）。
              单独一个钩子是为了**复用这一帧已经读到的内存**：另起进程录会多抢一份
              2MB/帧的读取带宽，把主循环挤到掉帧。
    stop_flag: threading.Event，置位后停止
    返回 (frame, elapsed, reason)，不关闭进程句柄
    """
    dry = cfg.get('dry', False)
    limit = cfg.get('frames', 0)
    use_enemy = cfg.get('use_enemy', True)
    use_laser = cfg.get('use_laser', True)
    use_item = cfg.get('use_item', True)
    orig_fg = cfg.get('orig_fg') or foreground()
    held = set()
    firing = False
    guard = BombGuard()         # 自动灵击：死亡炸弹 + 必死预判（放 try 外，收尾日志要读它的计数）
    trip = ItemLineTrip()       # 智能道具线：满火力冲收集线全屏吸道具（收尾日志读计数）
    flow = StageFlow()          # 关卡推进：过渡态等待 + 开场对话轻点 Z（收尾日志读计数）
    motion = LaserMotion()      # 激光轴原点的逐帧差分（槽里读不到的横扫速度）
    enemy_motion = EnemyMotion()  # 敌人的逐帧差分（敌人池里同样没有速度字段）
    watch = None                # 玩家让位：真人按键监听（装不上就让位失效，躲避照跑）
    was_yielding = False
    no_lives_said = False       # 「残机 0 仍照常避弹」只提示一次（收尾日志会读）
    frame = 0
    reason = '正常结束'
    t_start = time.perf_counter()
    start_dir = 'none'         # 预备接管已按住的方向 —— 主循环的 prev 必须从它接上
    try:
        if cfg.get('human_yield', True) and not dry:
            watch = HumanWatch()
            if not watch.start():
                log(f'键盘钩子未能安装（err={watch.error}）：玩家让位不可用，其余功能照常。')
                watch = None
        if not dry:
            set_foreground(hwnd)
            time.sleep(0.4)
            if foreground() != hwnd:
                log('游戏未取得前台焦点，退出，以免按键发送至其他程序。')
                return 0, 0.0, '焦点未获取'
            st = read_state(p, mb)
            code, desc, ok = screen_of(st)
            if code == 'CONTINUE' and not cfg.get('resume', False):
                log('停在失败菜单（Continue 或符卡失败）：不发送任何按键，退出。')
                log('  如需脚本自行按 Z 继续（符卡练习等于重试），请启用「续关」。')
                return 0, 0.0, 'Continue 画面'
            if not ok and code != 'CONTINUE' and not (code == 'STAGE_SWITCH'
                                                      and cfg.get('advance', True)):
                log(f'当前画面 {code}：{desc}')
                log('  发送方向键不安全，退出，不发送任何按键。')
                return 0, 0.0, f'画面 {code}'
            # 预备接管只在**已经在关卡中**时做：Continue 画面发方向键会把「是」拨到「否」
            # （PITFALLS 里那个坑），关卡过渡里发方向键也没有意义 —— 那两种交给主循环。
            # 先按住方向再解除暂停：暂停时方向键无效，但键状态会被游戏轮询到，
            # 解除暂停的第一帧自机就已在移动 —— 消除「恢复后裸奔」的致命窗口
            if code in ('IN_GAME', 'NO_LIVES'):
                pre = read_frame(p, mb, use_enemy, use_laser, use_item,
                                 enemy_motion=enemy_motion)
                if pre is not None:
                    # 预备接管也评估一次冲线：开局就在「满火力 + 满屏掉落」的场面时，
                    # 第一帧就该朝上冲，而不是等主循环跑起来才开始（ItemLineTrip）。
                    dash0 = trip.update(pre['py'], pre.get('power', 0.0),
                                        pre.get('poc_val', 0.0),
                                        enabled=use_item and cfg.get('poc', True))
                    poc0 = None
                    poc_w0 = 0.0
                    if dash0:
                        cx0 = pre.get('poc_cx')
                        poc0 = (cx0 if cx0 is not None else pre['px'], POC_TARGET_Y)
                        poc_w0 = (cfg.get('attack', ATTACK_W) + cfg.get('item', ITEM_W)
                                  + POC_W_EXTRA)
                    b0, sc0 = plan(pre['px'], pre['py'], pre['bx'], pre['by'],
                                   pre['vx'], pre['vy'],
                                   cfg.get('speed', PLAYER_SPEED), cfg.get('horizon', 30),
                                   cfg.get('safe', 2.0), cfg.get('edge', 8.0),
                                   'none', cfg.get('inertia', 0.2), pre['enemy'], pre['laser'],
                                   cfg.get('comfort', 6.0),
                                   attack=pre['target'], attack_w=cfg.get('attack', ATTACK_W),
                                   standoff=cfg.get('standoff', STANDOFF),
                                   margin_w=cfg.get('margin', MARGIN_W),
                                   switch_margin=cfg.get('switch', SWITCH_MARGIN),
                                   item=pre['item'], item_w=cfg.get('item', ITEM_W),
                                   item_wait=cfg.get('item_wait', ITEM_WAIT),
                                   risk=cfg.get('risk', RISK_TOL),
                                   warn=pre['warn'], warn_w=cfg.get('warn', WARN_W),
                                   warn_dist=cfg.get('warn_dist', WARN_DIST),
                                   poc=poc0, poc_w=poc_w0, br=pre.get('br'),
                                   clear_w=cfg.get('clear', CLEAR_W),
                                   clear_r=cfg.get('clear_r', CLEAR_R),
                                   center_w=cfg.get('center', CENTER_W),
                                   center_r=cfg.get('center_r', CENTER_R),
                                   laser_rect=pre.get('laser_rect'),
                                   enemy_mv=pre.get('enemy_mv'))
                    apply_keys(held, DIR_KEYS[b0])
                    start_dir = b0
                    gap = sc0.get(b0, 0.0)
                    warn = '  注意：最优方向间隙已为负，恢复瞬间极可能中弹。' if gap < 0 else ''
                    log(f'  预备接管：先按住 {b0}（弹 {len(pre["bx"])} 敌 {pre["n_enemy"]} '
                        f'激光 {pre["n_laser"]} 道具 {pre["n_item"]}，间隙 {gap:.1f}px）{warn}')
            # 关卡过渡期间一个键都不按：载入中发键没有意义，等主循环把它等过去
            if code != 'STAGE_SWITCH' and cfg.get('unpause', True):
                th06.tap('z', 60)
                time.sleep(0.4)
                if cfg.get('resume', False):
                    time.sleep(0.6)
                    c2, d2, _ = screen_of(read_state(p, mb))
                    log(f'  续关尝试后：{c2}（{d2}） Lives={read_lives(p, mb)}')

        if cfg.get('focus', True):
            log(f'  低速模式：原地不动的间隙不低于分数线加 '
                f'{cfg.get("focus_slack", FOCUS_SLACK):g}px（即只是微调）时按住 '
                f'{FOCUS_KEY.upper()} 半速移动；必须躲避时立即回高速。')
        prev = start_dir        # 上一帧**实际执行**的方向（延迟后的），不是 plan() 的原始输出
        gate = ReactionGate()
        focus_was = False       # 上一帧是否按住低速（门槛折扣用，防在门槛上下横跳）
        still = 0
        last_pos = None
        last_lives = None
        last_fc = None
        stall = 0
        menu_t = None           # 停在失败菜单的起始时刻（None = 不在菜单里）
        menu_pressed = False    # 本次进菜单是否已按过 Z
        reload_t = None         # 场景重载（curState=12）的起始时刻
        period = cfg.get('period', 1.0 / 60.0)
        while True:
            if stop_flag is not None and stop_flag.is_set():
                reason = '已停止'
                break
            t0 = time.perf_counter()
            st = read_state(p, mb)
            code, desc, ok = screen_of(st)
            ps = read_player_state(p, mb)
            # 灵击的死亡炸弹窗口：自机已进入死亡状态，但掉命结算还没到 —— 这段窗口里按 X
            # 仍能取消死亡。**必须在画面判据之前处理**：screen_of() 见到自机死亡会直接
            # 退出主循环，那就再没有机会抢救了。
            # `salvaged`：仍值得继续跑的死亡相关画面 —— 窗口还没走完（respawn > 0），
            # 或者已经被灵击救回（state 不再是 DEAD，此时 dying 标志可能还滞后着）。
            salvaged = (code == 'DYING' and ps is not None
                        and not (ps['state'] == PLAYER_STATE_DEAD and ps['respawn'] <= 0))
            # 关卡之间的过渡（curState=3）：原版自己会载入下一关（GameManager::AddedCallback
            # 里 currentStage++），脚本只要「不退出、不按键」。这里就是「自动进下一关」的落点 ——
            # 旧版把非关卡画面一律当退出条件，于是每打完一关就停。
            if code == 'STAGE_SWITCH' and cfg.get('advance', True):
                waited, first = flow.switching(t0)
                if first:
                    log(f'第 {flow.switches} 次关卡过渡：等待游戏载入下一关，过场不需要按键。')
                if waited > flow.timeout_s:
                    log(f'关卡切换已等待 {waited:.0f}s 仍未回到关卡，松开按键退出。')
                    reason = '关卡切换超时'
                    break
                if not dry:
                    release_all(held, skip=watch.physical() if watch else ())
                    firing = apply_fire(firing, False)
                frame += 1
                if on_frame is None and frame % 60 == 0:
                    log(f'  等待载入中（{waited:.0f}s / {flow.timeout_s:.0f}s）。')
                dt = time.perf_counter() - t0
                if dt < period:
                    time.sleep(period - dt)
                continue
            if code in ('IN_GAME', 'NO_LIVES') and flow.t_switch is not None:
                log(f'已进入下一关场景（第 {flow.switches} 次过渡），恢复避弹。')
                flow.back_in_game()
            if code == 'NO_LIVES' and not no_lives_said:
                log('残机 0（最后一条命）：仍照常避弹；被打中会在 Continue 出现前松开按键退出。')
                no_lives_said = True
            # NO_LIVES 与 IN_GAME 同一条路：残机是备用命，0 不代表这一局结束。
            # 真正该停的两种仍会停：死亡结算完（salvaged 转假）与 Continue 画面（判据在 screen.py）。
            if code == 'CONTINUE':
                # 失败菜单（普通关卡的 Continue，与符卡练习失败后的 "Failed..."）：
                # 两个都是 isInRetryMenu=0xFF（screen.py）。**菜单里一个方向键都不能发** ——
                # Continue 画面会把「是」拨到「否」，符卡失败菜单会把光标拨走。
                # 只按 Z：符卡练习默认停在「重试」上，普通关卡那是续关（要不要续由 --resume 决定）。
                if not cfg.get('resume', False):
                    log(f'画面变为 {code}：{desc}，松开按键退出（如需自动按 Z 继续，请启用「续关」）。')
                    reason = f'画面 {code}'
                    break
                if menu_t is None:
                    menu_t, menu_pressed = t0, False
                    log(f'停在失败菜单（{desc}）：松开全部按键，等待。')
                if not dry:
                    release_all(held, skip=watch.physical() if watch else ())
                    firing = apply_fire(firing, False)
                if not menu_pressed and t0 - menu_t >= cfg.get('menu_wait', MENU_WAIT):
                    if not dry:
                        th06.tap(FIRE_KEY, 60)
                    menu_pressed = True
                    log('  已按一次 Z（符卡练习等于重试）。')
                if t0 - menu_t > cfg.get('menu_timeout', MENU_TIMEOUT):
                    log(f'失败菜单停留已超过 {cfg.get("menu_timeout", MENU_TIMEOUT):g}s，退出。')
                    reason = '失败菜单超时'
                    break
                frame += 1
                dt = time.perf_counter() - t0
                if dt < period:
                    time.sleep(period - dt)
                continue
            if menu_t is not None:
                log('已离开失败菜单，恢复避弹。')
                menu_t, menu_pressed = None, False
            if code == 'RELOAD':
                # 场景重载（curState=12，新典自加的过渡态）：按 Z 重开一张符卡时出现 1~2 帧。
                # 期间同样一个键都不发，等它自己回到 2 —— 判成未知场景会让脚本每重试一次就退出。
                if reload_t is None:
                    reload_t = t0
                    log('场景重载中（重开符卡或载入）：等待。')
                if not dry:
                    release_all(held, skip=watch.physical() if watch else ())
                    firing = apply_fire(firing, False)
                if t0 - reload_t > cfg.get('reload_timeout', RELOAD_TIMEOUT):
                    log(f'场景重载已等待 {t0 - reload_t:.0f}s 仍无进展，退出。')
                    reason = '场景重载超时'
                    break
                frame += 1
                dt = time.perf_counter() - t0
                if dt < period:
                    time.sleep(period - dt)
                continue
            reload_t = None
            if code not in ('IN_GAME', 'NO_LIVES') and not salvaged:
                log(f'画面变为 {code}：{desc}，松开按键退出。')
                reason = f'画面 {code}'
                break
            if st['calc_count'] == last_fc:
                stall += 1
                if stall > 45:
                    log('帧计数 0.75s 未变化（游戏已暂停），松开按键退出。')
                    reason = '游戏暂停'
                    break
            else:
                stall, last_fc = 0, st['calc_count']
            w = read_frame(p, mb, use_enemy, use_laser, use_item, motion=motion,
                           enemy_motion=enemy_motion)
            if w is None:
                log('读取失败，退出。')
                reason = '读取失败'
                break
            if on_world is not None:
                on_world(w, st, ps)            # 黑匣子：复用本帧已读到的世界，不重读内存
            bx, by, vx, vy = w['bx'], w['by'], w['vx'], w['vy']
            br = w.get('br')                   # 逐弹判定半径（MEMMAP §3）；None = 全按 BULLET_R
            px, py = w['px'], w['py']
            enemy, laser = w['enemy'], w['laser']
            armed = w.get('laser_armed')       # 必死预判只看有判定的激光（见 doom 段）
            n_enemy, n_laser = w['n_enemy'], w['n_laser']
            target, item, n_item = w['target'], w['item'], w['n_item']
            warn = w['warn']
            # 智能道具线：满火力 + 可转化价值达标 → 冲上收集线一次（ItemLineTrip）。
            # dashing 时给 plan() 传冲线目标（x=非追踪道具质心，y=POC_TARGET_Y），
            # 权重 = 进攻 + 道具 + extra 并替代两者 —— 安全分仍然永远压过它。
            dashing = trip.update(py, w.get('power', 0.0), w.get('poc_val', 0.0),
                                  enabled=use_item and cfg.get('poc', True))
            if trip.event == 'start':
                log(f'  冲线开始：可转化价值 {w["poc_val"]:.1f} 不低于 '
                    f'{cfg.get("poc_min", POC_MIN):.1f}，目标 y={POC_TARGET_Y:.0f}。')
            elif trip.event == 'trip':
                log('  冲线成功：已越过收集线，全屏普通掉落转为追踪。')
            elif trip.event == 'giveup':
                log(f'  冲线放弃（可转化价值 {w["poc_val"]:.1f}），冷却 {POC_COOLDOWN} 帧。')
            poc = None
            poc_w = 0.0
            if dashing:
                cx = w.get('poc_cx')
                poc = (cx if cx is not None else px, POC_TARGET_Y)
                poc_w = cfg.get('attack', ATTACK_W) + cfg.get('item', ITEM_W) + POC_W_EXTRA
            lv = read_lives(p, mb)
            if last_lives is None:
                last_lives = lv
            elif lv != last_lives:
                log(f'   Lives {last_lives} 变为 {lv}。')
                dropped = lv < last_lives
                last_lives = lv
                if dropped and not cfg.get('keep_going_on_death', False):
                    log('掉命：立即松开按键退出'
                        '（Continue 画面的 Scene 仍为 2，继续发送按键会点掉续关）。')
                    reason = '掉命'
                    break

            # 低速模式：同一帧按快 / 慢两个速度各规划一次，慢着走也宽裕才切慢（见 FOCUS_*）。
            sp_fast = cfg.get('speed', PLAYER_SPEED)
            hz, safe = cfg.get('horizon', 30), cfg.get('safe', 2.0)
            kw = dict(comfort=cfg.get('comfort', 6.0),
                      attack=target, attack_w=cfg.get('attack', ATTACK_W),
                      standoff=cfg.get('standoff', STANDOFF),
                      margin_w=cfg.get('margin', MARGIN_W),
                      switch_margin=cfg.get('switch', SWITCH_MARGIN),
                      item=item, item_w=cfg.get('item', ITEM_W),
                      item_wait=cfg.get('item_wait', ITEM_WAIT),
                      risk=cfg.get('risk', RISK_TOL),
                      warn=warn, warn_w=cfg.get('warn', WARN_W),
                      warn_dist=cfg.get('warn_dist', WARN_DIST),
                      poc=poc, poc_w=poc_w, br=br,
                      clear_w=cfg.get('clear', CLEAR_W), clear_r=cfg.get('clear_r', CLEAR_R),
                      center_w=cfg.get('center', CENTER_W),
                      center_r=cfg.get('center_r', CENTER_R),
                      center_y=cfg.get('center_y', FIELD_CY),
                      laser_rect=w.get('laser_rect'),
                      laser_armed=armed if LASER_SAFE_ARMED else _AUTO,
                      enemy_mv=w.get('enemy_mv'), bf=w.get('bf'))
            best, scores = plan(px, py, bx, by, vx, vy, sp_fast, hz, safe,
                                cfg.get('edge', 8.0), prev, cfg.get('inertia', 0.2),
                                enemy, laser, **kw)
            sp_exec, focus_on = sp_fast, False
            if cfg.get('focus', True) and not dashing:
                line = (kw['comfort'] + cfg.get('focus_slack', FOCUS_SLACK)
                        * (FOCUS_EXIT if focus_was else 1.0))
                # 微量移动判据：**原地不动就够安全** → 这一步不是躲命，只是微调。
                # 站着不动都险时绝不慢：那正是要靠速度拉开距离的时刻。
                # `none` 的间隙与速度无关（不动就没有外推），查高速那次的结果就够。
                if scores.get('none', 0.0) >= line:
                    sp_slow = sp_fast * FOCUS_RATIO
                    b_slow, s_slow = plan(px, py, bx, by, vx, vy, sp_slow, hz, safe,
                                          cfg.get('edge', 8.0), prev,
                                          cfg.get('inertia', 0.2), enemy, laser, **kw)
                    if s_slow[b_slow] >= line:
                        best, scores, sp_exec, focus_on = b_slow, s_slow, sp_slow, True
            focus_was = focus_on
            # 人类化：局面宽裕就慢半拍再动，紧起来零延迟（ReactionGate）。
            # prev 传「实际执行」而非 plan 原始输出 —— 惯性/切换门槛必须看见真实按键，
            # 否则延迟期间 plan 会以为自己已经在走新方向，迟滞基于错误前提。
            exec_dir = gate.update(best, prev, scores, cfg.get('comfort', 6.0),
                                   cfg.get('react', REACT_FRAMES),
                                   threat=threat_present(bx, enemy, laser))
            prev = exec_dir

            # 灵击：被击中（死亡炸弹窗口）优先，否则看是不是「怎么走都躲不掉」。
            # 两个判据都要求 bombs > 0 且当前没有灵击在生效 —— 不浪费技能。
            # 必死预判用**当前实际速度**：低速下能走的路只有一半，判据必须跟着走。
            dg = doomed_gap(px, py, bx, by, enemy, armed, safe, sp_exec,
                            int(cfg.get('bomb_pre', BOMB_PRE)), br=br)
            bomb_now = guard.update(ps, dg < 0.0, enabled=cfg.get('bomb', True))
            if guard.event == 'rescue':
                log(f'死亡炸弹：已被击中（死亡窗口剩 {ps["respawn"]} 帧），按 '
                    f'{BOMB_KEY.upper()} 保命（bombs={ps["bombs"]}）。')
            elif guard.event == 'preempt':
                log(f'必死预判：九向无路（最优间隙 {max(scores.values()):.1f}px），按 '
                    f'{BOMB_KEY.upper()} 保命（bombs={ps["bombs"]}）。')

            # 玩家接管：检测到真人按键（低级键盘钩子的非注入事件）就停手 —— 强制不动，
            # 且下面的发键段一个键都不发。判据包含「此刻仍按着键」：只看时间窗的话，
            # 人一直按着方向键时脚本会在几秒后把手柄抢回来 —— 那正是最不该抢的时刻。
            yielding = watch is not None and watch.yielding(cfg.get('human_idle', HUMAN_IDLE))
            if yielding:
                exec_dir, bomb_now, prev = 'none', False, 'none'
                if not was_yielding:
                    log('检测到玩家操作：让位，松开按键且不发送任何按键。')
                was_yielding = True
            elif was_yielding:
                log(f'玩家已停手 {cfg.get("human_idle", HUMAN_IDLE):g}s，恢复自动操作。')
                was_yielding = False

            if not dry:
                if foreground() != hwnd:
                    log('前台已切走，松开按键并退出。')
                    reason = '前台切走'
                    break
                if yielding:
                    # 让位：松开脚本按的键（玩家自己按着的不动），连射也停
                    release_all(held, skip=watch.physical())
                    firing = apply_fire(firing, False)
                else:
                    # 过场/开场对话：场上没有威胁源时轻点 Z 把它推过去 —— 对话的 WAIT 指令
                    # 只认按下沿（原版 Gui.cpp:577 WAS_PRESSED），按住连射永远推不动，
                    # 脚本会一直卡在第一句上。有威胁源时绝不轻点：那会松开正在连射的 Z。
                    quiet = (n_enemy == 0 and len(bx) == 0 and n_laser == 0)
                    if cfg.get('advance', True) and flow.tap_due(t0, quiet):
                        firing = apply_fire(firing, False)
                        th06.tap(FIRE_KEY, ADVANCE_TAP_MS)
                    firing = apply_fire(firing, cfg.get('autofire', True))
                    keys = set(DIR_KEYS[exec_dir])
                    if focus_on:
                        keys.add(FOCUS_KEY)
                    if bomb_now:
                        keys.add(BOMB_KEY)
                    apply_keys(held, keys)

            # 暂停检测：按住方向但自机不动
            pos = (round(px, 3), round(py, 3))
            still = still + 1 if (pos == last_pos and exec_dir != 'none') else 0
            last_pos = pos
            if still == 90:
                log('按住方向但自机 1.5s 未移动，可能处于暂停状态（按 Z 可解除）。')
                still = 0

            frame += 1
            el = time.perf_counter() - t_start
            top = sorted(scores.items(), key=lambda kv: -kv[1])[:3]
            if on_frame is not None:
                state = {
                    'frame': frame, 'fps': (frame / el if el > 0 else 0.0),
                    'bullets': len(bx), 'enemies': n_enemy, 'lasers': n_laser,
                    'items': n_item,
                    'px': px, 'py': py, 'dir': exec_dir, 'plan': best, 'lives': lv,
                    'wait': gate.waited, 'wait_limit': gate.limit,
                    'screen': code, 'top': top, 'held': sorted(held),
                    'target': target, 'firing': firing, 'focus': focus_on,
                    'bombs': ps['bombs'] if ps else -1, 'bomb_use': bool(bomb_now),
                    'bombs_fired': guard.rescues + guard.preempts,
                    'warn': int(min(warn)) if warn is not None and len(warn) and min(warn) >= 0 else -1,
                    'poc': trip.state, 'poc_t': trip.t, 'poc_val': w.get('poc_val', 0.0),
                    'poc_trips': trip.trips, 'poc_gives': trip.gives,
                    'yield': yielding, 'switches': flow.switches,
                }
                if on_frame(state) is False:
                    reason = '界面停止'
                    break
            elif frame % 30 == 0:
                brief = '　'.join(f'{n}={s:5.1f}' for n, s in top)
                wait = f'（等 {gate.waited}/{gate.limit} 帧转 {best}）' if gate.waited else ''
                pc = '  冲线' if dashing else ''
                fc = '  低速' if focus_on else ''
                bn = f'  炸弹{ps["bombs"]}' if ps else ''
                log(f'[{frame:5d}] 弹{len(bx):3d} 敌{n_enemy:2d} 激光{n_laser:2d} '
                    f'道具{n_item:2d} 自机({px:6.1f},{py:6.1f}) 方向 {exec_dir:<5}'
                    f'{wait}{pc}{fc}{bn} | {brief}')
            if limit and frame >= limit:
                reason = '到达帧数上限'
                break

            dt = time.perf_counter() - t0
            if dt < period:
                time.sleep(period - dt)
    except KeyboardInterrupt:
        reason = '中断'
    finally:
        release_all(held)
        if firing:
            th06.key_up(FIRE_KEY)
        if watch is not None:
            watch.stop()
        if not dry and cfg.get('restore', True) and orig_fg:
            set_foreground(orig_fg)
    el = time.perf_counter() - t_start
    if guard.rescues or guard.preempts:
        log(f'  灵击合计：死亡炸弹 {guard.rescues} 次，必死预判 {guard.preempts} 次。')
    if trip.trips or trip.gives:
        log(f'  道具线合计：成功 {trip.trips} 次，放弃 {trip.gives} 次。')
    if flow.switches:
        log(f'  关卡推进合计：跨过 {flow.switches} 次关卡过渡，对话轻点 Z {flow.taps} 次。')
    return frame, el, reason


def main():
    # 默认值一律取自 default_params()（出厂默认的唯一真源）—— 控制台保存的值不作用于命令行，
    # 命令行的默认值必须始终可预期：`--help` 显示什么，不传参就跑什么。
    d = default_params()
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry', action='store_true', help='只决策不按键')
    ap.add_argument('--frames', type=int, default=0, help='运行帧数，0=无限')
    ap.add_argument('--horizon', type=int, default=int(d['horizon']), help='预测帧数')
    ap.add_argument('--speed', type=float, default=d['speed'],
                    help='自机速度 px/帧；先用 tools\\calib_speed.py 标定再改')
    ap.add_argument('--safe', type=float, default=d['safe'], help='额外安全裕度 px')
    ap.add_argument('--inertia', type=float, default=d['inertia'], help='同向奖励，抑制抖动')
    ap.add_argument('--edge', type=float, default=d['edge'],
                    help='贴边惩罚权重：离边界 60px 内才扣分，场地中部自由')
    ap.add_argument('--comfort', type=float, default=d['comfort'],
                    help='安全分数线(px)：有方向间隙达到它，才让贴边/惯性/进攻参与排序')
    ap.add_argument('--period', type=float, default=1.0 / 60.0, help='循环周期(秒)')
    ap.add_argument('--verbose', action='store_true')
    ap.add_argument('--no-unpause', action='store_true', default=not d['unpause'],
                    help='开始前不按 Z（默认按一次：暂停菜单里是解除暂停，游戏中只是射击，无害）')
    ap.add_argument('--no-restore', action='store_true', help='结束时不恢复原前台窗口')
    ap.add_argument('--no-enemy', action='store_true', default=not d['use_enemy'],
                    help='不纳入敌人本体（只躲子弹/激光）')
    ap.add_argument('--no-laser', action='store_true', default=not d['use_laser'],
                    help='不纳入激光')
    ap.add_argument('--no-autofire', action='store_true', default=not d['autofire'],
                    help='不自动射击（默认按住 Z 连射）')
    ap.add_argument('--no-item', action='store_true', default=not d['use_item'],
                    help='不捡掉落道具（默认会去捡 P 点/蓝点等）')
    ap.add_argument('--item', type=float, default=d['item'],
                    help='道具吸引权重，0 = 不捡；越大越主动朝掉落物靠')
    ap.add_argument('--item-wait', type=float, default=d['item_wait'],
                    help='愿意为道具等的帧数：道具还要更久才落到自机高度就不追（不干等）')
    ap.add_argument('--no-poc', action='store_true', default=not d['poc'],
                    help='不冲收集线（默认开：满火力且可转化掉落价值足够时冲上 y<128 全屏吸道具）')
    ap.add_argument('--poc-min', type=float, default=d['poc_min'],
                    help='冲线触发价值：场上普通掉落总价值 ≥ 它才值得冲（约 4 小P；'
                         '0 = 满火力且有普通掉落就冲）')
    ap.add_argument('--risk', type=float, default=d['risk'],
                    help='紧张档同等安全容差(px)：最优方向间隙 < 分数线时，只在与它相差 ≤ 此值'
                         '的方向间让软项决胜负（0 = 退回纯躲）')
    ap.add_argument('--warn', type=float, default=d['warn'],
                    help='弹幕预警窗口(帧)：敌人还有这么多帧就发弹时提前扩大其危险半径；0 = 关闭')
    ap.add_argument('--warn-dist', type=float, default=d['warn_dist'],
                    help='预警最大额外危险半径(px)：发弹瞬间要躲开多远')
    ap.add_argument('--attack', type=float, default=d['attack'],
                    help='进攻吸引权重，0 = 不追敌人；越大越主动往目标靠')
    ap.add_argument('--standoff', type=float, default=d['standoff'],
                    help='输出带下沿：停在目标下方 standoff..standoff+ATTACK_REACH px，0 = 贴近敌人')
    ap.add_argument('--margin', type=float, default=d['margin'],
                    help='安全余量权重：候选池内间隙越大越优先，0 = 关闭（治贴敌人）')
    ap.add_argument('--clear', type=float, default=d['clear'],
                    help='空旷区吸引权重：同等安全时优先退向弹少的一带，0 = 关闭（治逐帧钻缝）')
    ap.add_argument('--clear-r', type=float, default=d['clear_r'],
                    help='空旷度评价半径(px)：落点周围这么大范围里的弹密度')
    ap.add_argument('--center', type=float, default=d['center'],
                    help='自动回中权重：离场地中心超出自由半径就往回拉，0 = 关闭（治角落恋战）')
    ap.add_argument('--center-r', type=float, default=d['center_r'],
                    help='回中自由半径(px)：离中心这么近完全不干预，软项自由发挥')
    ap.add_argument('--switch', type=float, default=d['switch'],
                    help='方向切换门槛：新方向优势不足此值就维持原方向（治抖动）')
    ap.add_argument('--react', type=float, default=d['react'],
                    help='安全时的反应延迟(帧)：局面宽裕才慢半拍再动，危险时零延迟；0 = 关闭')
    ap.add_argument('--no-bomb', action='store_true', default=not d['bomb'],
                    help='不自动灵击（默认开：被击中时抢在掉命前按 X，九向必死时提前炸）')
    ap.add_argument('--bomb-pre', type=float, default=d['bomb_pre'],
                    help='必死预判前瞻(帧)：九向外推这么多帧全部重叠就提前炸；0 = 只做死亡炸弹抢救')
    ap.add_argument('--no-advance', action='store_true', default=not d['advance'],
                    help='不自动进下一关（默认开：关卡过渡不退出，开场对话自动轻点 Z 推进）')
    ap.add_argument('--no-yield', action='store_true', default=not d['human_yield'],
                    help='玩家按键时不让位（默认开：检测到真人按键就停手，人停手后再接管）')
    ap.add_argument('--human-idle', type=float, default=d['human_idle'],
                    help='玩家最后一次按键后，脚本再静默多少秒才接管回来')
    ap.add_argument('--no-focus', action='store_true', default=not d['focus'],
                    help='不用低速模式（开着时：慢着走也宽裕就按住 Shift 半速走，紧起来回高速）')
    ap.add_argument('--focus-slack', type=float, default=d['focus_slack'],
                    help='低速门槛余量(px)：最优间隙 ≥ 安全分数线 + 它才敢切低速；调大 = 更少低速')
    ap.add_argument('--blackbox', action='store_true', default=d['blackbox'],
                    help='死亡黑匣子：掉命时把前 4 秒完整现场落盘（复用主循环的读取，'
                         '不额外抢带宽），事后用 tools\\death_report.py 解剖')
    ap.add_argument('--stop-on-death', action='store_true',
                    default=not d['keep_going_on_death'],
                    help='掉命就松键退出（默认：掉命继续跑，含掉到残机 0 那次；'
                         '真进 Continue 画面无论如何都会停手）')
    ap.add_argument('--resume', action='store_true',
                    help='失败菜单（Continue / 符卡练习 Failed）里自动按 Z 继续：'
                         '符卡练习下等于「重试」，普通关卡下等于「续关」')
    args = ap.parse_args()

    p, pid = th06.get_proc()
    mb = module_base(pid, 'th06nc.exe')[0]
    hwnd = find_windows(pid=pid)[0][0]
    print(f'PID {pid}  基址 0x{mb:X}  游戏 hwnd 0x{hwnd:X}')

    cfg = dict(dry=args.dry, frames=args.frames, horizon=args.horizon, speed=args.speed,
               safe=args.safe, inertia=args.inertia, edge=args.edge,
               comfort=args.comfort, period=args.period,
               use_enemy=not args.no_enemy, use_laser=not args.no_laser,
               use_item=not args.no_item,
               unpause=not args.no_unpause, resume=args.resume,
               restore=not args.no_restore, keep_going_on_death=not args.stop_on_death,
               autofire=not args.no_autofire, attack=args.attack, standoff=args.standoff,
               margin=args.margin, switch=args.switch, item=args.item,
               clear=args.clear, clear_r=args.clear_r,
               center=args.center, center_r=args.center_r,
               item_wait=args.item_wait, poc=not args.no_poc, poc_min=args.poc_min,
               risk=args.risk,
               warn=args.warn, warn_dist=args.warn_dist, react=args.react,
               bomb=not args.no_bomb, bomb_pre=args.bomb_pre,
               advance=not args.no_advance, human_yield=not args.no_yield,
               human_idle=args.human_idle,
               focus=not args.no_focus, focus_slack=args.focus_slack, blackbox=args.blackbox)
    # 打印生效参数：CLI **不读**控制台保存值（`SAVED_PATH` 只被 GUI 读），
    # 不带参数跑时用的就是 `default_params()` —— 出问题时先看这一行，
    # 别拿命令行复现出来的现象去解释控制台里的表现（两套默认值曾长期不一致）。
    dp = default_params()
    print('生效参数（来自 default_params()，非控制台保存值）：')
    print('  ' + '　'.join(
        f'{k}={"开" if cfg[k] else "关"}' if isinstance(cfg[k], bool) else f'{k}={cfg[k]:g}'
        for k in sorted(dp) if k in cfg))
    bb = None
    if cfg.get('blackbox'):
        import death_recorder       # 延迟 import：death_recorder 反过来 import 本模块
        bb = death_recorder.BlackBox(p, mb, log=print, params=cfg)
        print(f'死亡黑匣子已启用：掉命时落盘至 {bb.out_dir}\\death_*.npz。')
    frame, el, reason = run_session(p, mb, hwnd, cfg,
                                    on_world=(bb.feed if bb else None), log=print)
    if bb is not None and bb.paths:
        print('黑匣子已保存现场（可用 death_report.py 解剖）：')
        for pth in bb.paths:
            print(f'  {pth}')
    if frame:
        print(f'结束（{reason}）：{frame} 帧，{el:.2f}s，{frame / el:.1f} fps 有效。')
    else:
        print(f'未运行（{reason}）。')
    p.close()


if __name__ == '__main__':
    main()
