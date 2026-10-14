"""th06nc 内存布局与场地常量 —— **全项目唯一写死地址的地方**

值全部来自 `项目文档/02-内存布局/相关-游戏内存映射-MEMMAP.md`（本机实测 + 反汇编确证），
分节与那份文档一一对应。改地址只改这里，其余模块 import 使用，别再写第二份。

地址是**模块内 RVA**，绝对地址 = moduleBase + RVA。
**只对 MEMMAP 记录的构建有效** —— 换构建先 `py tools\\env.py` 核对 exe MD5。
"""

# ---- 自机（MEMMAP §1）----
PLAYER_BASE = 0x4FF3A0           # Player 结构基址
PLAYER_OFF_X = 0x7730            # Player + 该偏移 = 自机 x
PLAYER_OFF_Y = 0x7734
PLAYER_OFF_X2 = 0x7740           # 副坐标，用途未确认（= 自机 x 全局 + 0x10）
PLAYER_OFF_Y2 = 0x7744
PLAYER_X = 0x506AD0              # float，独立全局（= PLAYER_BASE + PLAYER_OFF_X）
PLAYER_Y = 0x506AD4
PLAYER_HITBOX = 0x506AEC         # float，判定半径（实测 1.25）

# ---- 自机状态与灵击（MEMMAP §11）----
# 依据：反汇编 `Player__OnUpdate`（0x689A8..0x68B20）+ 实机读值。
# bomb 是**按下沿**触发（输入位图 bit1），且要求 respawnTimer != 0 —— 死亡后 respawnTimer
# 从 8 起逐帧递减，到 0 才结算掉命，这个窗口里按 X 仍能放技能（死亡炸弹）。
PLAYER_OFF_STATE = 0x7898        # u8，playerState：0=ALIVE 1=SPAWNING 2=DEAD 3=INVULNERABLE
PLAYER_OFF_RESPAWN = 0x773C      # i32，respawnTimer：存活恒 8；被击中后递减，到 0 才掉命
PLAYER_OFF_BOMB_INUSE = 0x9EC8   # u8，bombInfo.isInUse（符号库 g_BombInUse = 0x509268）
PLAYER_OFF_BOMB_DUR = 0x9F20     # i32，bombInfo.duration（灵击生效中 >= 0）
PLAYER_STATE_ALIVE = 0
PLAYER_STATE_SPAWNING = 1
PLAYER_STATE_DEAD = 2
PLAYER_STATE_INVULNERABLE = 3
RESPAWN_ALIVE = 8                # 存活时的 respawnTimer 值 = 死亡炸弹窗口的帧数
BOMB_INPUT_BIT = 0x0002          # 输入位图 bit1 = TH_BUTTON_BOMB（键位 X）

# ---- 低速模式 focus（反汇编 `Player__OnUpdate` 0x690A2 段 + 实机读值，MEMMAP §1）----
#   0x0690A2  mov edx, r11d              ; r11d = 输入位图 0xA6EC60
#   0x0690A5  and edx, 4                 ; bit2 = TH_BUTTON_SLOW（键位 Shift）
#   0x0690AD  mov byte [rdi+0x785c], al  ; focus 标志；其下 8 向跳表按 edx 选速度字段
#   0x069136  movss xmm6, [rdi+0x7864]   ; edx != 0（低速）
#   0x069143  movss xmm6, [rdi+0x7860]   ; edx == 0（高速）
FOCUS_INPUT_BIT = 0x0004         # 输入位图 bit2 = TH_BUTTON_SLOW（键位 Shift）
PLAYER_OFF_FOCUS = 0x785C        # u8，focus 标志（每帧由输入位图 bit2 刷新）
PLAYER_OFF_SPD_FAST = 0x7860     # float，直向速度（未 focus）；本机实测 4.0
PLAYER_OFF_SPD_SLOW = 0x7864     # float，直向速度（focus）；本机实测 2.0 = 精确半速
PLAYER_OFF_SPD_DIAG_FAST = 0x7868   # float，斜向每轴（未 focus）；实测 2.82843 = 4.0×0.70711
PLAYER_OFF_SPD_DIAG_SLOW = 0x786C   # float，斜向每轴（focus）；实测 1.41421 = 2.0×0.70711
# focus 还切换射击函数：`Player+0x7720`（非 focus）/ `+0x7728`（focus）每帧二选一 call。

# ---- 游戏状态与画面判据（MEMMAP §1 §8）----
LIVES = 0x4FF0F0                 # u8
BOMBS = 0x4FF0F1                 # u8
RETRY = 0x4FF0F2                 # u8；0xFF = 停在 Continue 画面
POWER = 0x4F1E88                 # u16
DEATHS = 0x4F1E60                # i32，每次死亡 +1
DYING = 0x4F27B1                 # u8，1 = 自机死亡中
INPUT = 0xA6EC60                 # u16，按键位掩码
GUI = 0xA6EC08                   # ptr，未确认用途
CUR_STATE = 0xC21D9C             # i32，Supervisor.curState（旧称 Scene）
WANT_STATE = 0xC21D98            # i32，Supervisor.wantedState
CALC_COUNT = 0xC21C00            # u8，帧计数每帧 +1；不走 = 暂停
NATIVE_TIME = 0x4F27B9           # u8，**恒为 0，不是运行判据**（见 PITFALLS）

# ---- 子弹池（MEMMAP §2）----
BM_RVA = 0x3EC2A0                # g_BulletManager（全局对象，不是指针）
BULLETS_OFF = 0x8                # bullets[0]
BULLET_STRIDE = 0x620
BULLET_COUNT = 640
BULLET_BLOCK = BULLET_STRIDE * BULLET_COUNT      # 0xF5000，整块读的长度
B_OFF_VX, B_OFF_VY = 0x08, 0x0C
B_OFF_X, B_OFF_Y = 0x30, 0x34
B_OFF_GRAZE = 0x5F4               # float×2，grazeSize（宽/高）—— 碰撞判定尺寸，见 MEMMAP §3
B_OFF_GRAZED = 0x618              # u8，isGrazed：1 = 已擦到，此后每帧判死（判定的前置门）
NEXT_IDX_OFF = 0xFF618           # i32，nextBulletIndex

# ---- 子弹槽内**运动**字段（反汇编 BulletManager__OnUpdate 确证，见 MEMMAP §2.1）----
# 为什么要读它们：`vx/vy` 只是**当前**速度。加速弹每帧还在加速、转向弹会在定时器
# 触发时把速度矢量整体改向 —— 只按当前速度做匀速外推，窗口内的位置就是错的。
B_OFF_DCSPEED = 0x000             # f32，dirChangeSpeed：转向事件发生时成为当前速度
B_OFF_DC_INT = 0x004              # i32，dirChangeInterval：两次转向相隔帧数
B_OFF_EXFLAGS = 0x014             # u16，扩展位（语义见 EXF_*）
B_OFF_EX5F1 = 0x018               # f32，EXF_TURN_CONT 的每帧角度增量
B_OFF_DC_NUM = 0x01C              # i32，已转向次数（事件时 +1）
B_OFF_DC_MAX = 0x020              # i32，转向次数上限，到顶清位
B_OFF_SPEED = 0x024               # f32，当前标量速度 |velocity|（事件时 = dirChangeSpeed）
B_OFF_PREVTIMER = 0x028           # i32，上一帧的 timer（引擎自己存，本项目不用）
B_OFF_TIMER = 0x02C               # i32，子弹计时器：每帧 +1，转向判据就是它
B_OFF_ANGLE = 0x040               # f32，方向角（转向弹每帧可能被改写）
B_OFF_STATE = 0x044               # u16，BulletState（BULLET_STATE_*）
B_OFF_HOLD = 0x048                # i32，加速 / EXF_TURN_CONT 的持续帧数上限（原版 ex5Int0）
B_OFF_EX5F0 = 0x600               # f32，EXF_TURN_CONT 的每帧速度增量
B_OFF_ACCEL = 0x608               # f32×2，加速度矢量（EXF_ACCEL 时每帧累加到 velocity）
B_OFF_DC_ROT = 0x614              # f32，转向角增量（EXF_TURN_ABS 时是绝对角）

# exFlags 位（对应原版 BulletManager.cpp 709-882；新典同一套，OnUpdate 里 test 的立即数
# 就是 0x10 / 0x1c0 / 0xc00，见反汇编 0x140010AB8、0x1400119B8）
EXF_ACCEL_FAST = 0x001            # 前 16 帧速度 5.0 → 0（本项目未建模，按直线）
EXF_ACCEL = 0x010                 # 每帧 velocity += accel，直到 timer >= hold
EXF_TURN_CONT = 0x020             # 每帧 angle += ex5F1、speed += ex5F0，直到 timer >= hold
EXF_TURN_REL = 0x040              # 定时：angle += dcRot
EXF_TURN_AIM = 0x080              # 定时：angle = 朝自机角 + dcRot（最致命）
EXF_TURN_ABS = 0x100              # 定时：angle = dcRot（绝对角）
EXF_TURN_ANY = 0x1C0             # 上面三个定时转向位
EXF_BOUNCE_X = 0x400              # 出界反弹（本项目未建模，按直线）
EXF_BOUNCE_Y = 0x800

BULLET_STATE_UNUSED = 0
BULLET_STATE_FIRED = 1            # 只有它做碰撞判定
BULLET_STATE_SPAWN_FAST = 2
BULLET_STATE_SPAWN_NORMAL = 3
BULLET_STATE_SPAWN_SLOW = 4
BULLET_STATE_DESPAWNING = 5       # 消散：无判定，躲它是纯浪费移动

# ---- 激光池（MEMMAP §7）----
LASERS_OFF = 0xF5018             # lasers[0] = g_BulletManager + 该偏移
LASER_STRIDE = 0x298
LASER_COUNT = 64
L_OFF_WIDTH = 0x004              # f32，激光宽度（判定半宽 = width/2）
L_OFF_TIMER = 0x00C              # i32，当前阶段已过帧数（切阶段时归零）
L_OFF_STARTOFF = 0x010           # f32，线段起点在激光轴上的偏移
L_OFF_ENDOFF = 0x014             # f32，线段终点偏移；**每帧 += speed**
L_OFF_FADE_FRAMES = 0x018        # i32，消散阶段总帧数
L_OFF_ANGLE = 0x260              # f32，方向角（引擎只读；实测会逐帧转 —— 旋转激光）
L_OFF_FIRE_FRAMES = 0x268        # i32，发射阶段总帧数
L_OFF_SPEED = 0x26C              # f32，偏移前进速度(px/帧)；≠0 → 激光整体横扫
L_OFF_WARN_FRAMES = 0x270        # i32，预警阶段总帧数
L_OFF_STATE = 0x274              # u8，0 = 空闲
L_OFF_X, L_OFF_Y, L_OFF_Z = 0x278, 0x27C, 0x280   # f32，激光轴原点（**不是线段起点**）
L_OFF_STARTLEN = 0x288           # f32，线段长度上限（startOffset 被它推着走）
L_OFF_FLAGS = 0x290              # u8 = 阶段，取值见 L_PHASE_*
# 判定几何（`Player__CalcLaserHitbox` 入参，反汇编 0x1161D..0x11883 确证）：
#   线段 = pos + 方向(angle) × [startOffset, endOffset]，半宽 = width/2
#   **起点要加 startOffset** —— 把 pos 当起点会让整条激光错位（离屏时尤其离谱）。
#   每帧 `endOffset += speed`，startOffset 被 startLength 推着跟走 → 激光会整体平移。
#   横扫过来的激光必须带时间维躲避（见 dodge.laser_gap 的 ts 参数）。
# 激光阶段（`BulletManager__OnUpdate` 的激光循环按它四路分派；生成时 = (预警时长 == 0)）
L_PHASE_WARN = 0                 # 预警：只算透明度放大，**没有伤害判定**
L_PHASE_FIRE = 1                 # 发射：唯一会调 `Player__CalcLaserHitbox` 的阶段
L_PHASE_FADE = 2                 # 消散：无判定，淡出完 state 归 0
L_PHASE_TAIL = 3                 # 收尾：startOffset ≥ 640 即销毁

# ---- 敌人池（MEMMAP §6）----
EM_RVA = 0xAA1E90                # g_EnemyManager（全局对象）
ENEMIES_OFF = 0x8                # enemies[0]
ENEMY_STRIDE = 0x10B0
ENEMY_COUNT = 256
ENEMY_BLOCK = ENEMY_STRIDE * ENEMY_COUNT         # 0x10B000
E_OFF_X, E_OFF_Y, E_OFF_Z = 0xB0, 0xB4, 0xB8
E_OFF_LIFE = 0x234               # i32
E_OFF_HBW, E_OFF_HBH = 0x2C0, 0x2C4
E_OFF_FLAGS1, E_OFF_FLAGS2, E_OFF_FLAGS3 = 0xBC, 0xBD, 0xBE

E_OCCUPIED = 0x80                # flags1 bit7：槽被占用
E_COLLIDABLE = 0x02              # flags2 bit1：可碰撞
E_BOSS = 0x08                    # flags2 bit3：BOSS
E_INVISIBLE = 0x08               # flags3 bit3：隐形

# ---- 敌人射击节奏（弹幕预警；反汇编 0x28A8A 段确证，MEMMAP §10）----
#   0x028A8A  cmp dword ptr [rdi+0xf68], 0    ; 0 < shootInterval 才射击
#   0x028AA3  inc dword ptr [rdi+0x10a4]      ; shootIntervalTimer++
#   0x028AAF  cmp eax, dword ptr [rdi+0xf68]  ; timer >= interval → 发射
#   0x028B09  mov dword ptr [rdi+0x10a4], 0   ; 清零
E_OFF_SHOOT_INTERVAL = 0xF68     # i32，射击间隔（帧）；<=0 = 不射击
E_OFF_SHOOT_TIMER = 0x10A4       # i32，每帧 +1，到 interval 即发射并清零
E_OFF_SHOOT_OFF = 0xC5C          # float×3，发射点相对敌人的偏移（实测 y=8）

# ---- 道具池（MEMMAP §9）----
IM_RVA = 0xBAF0D8                # g_ItemManager.items[0]（全局对象，不是指针）
ITEM_STRIDE = 0x160
ITEM_COUNT = 1024                # 代码按 0x400 循环；数组 1025 槽，末槽当哨兵不读
ITEM_BLOCK = ITEM_STRIDE * ITEM_COUNT            # 0x58000，整块读的长度
I_OFF_INUSE = 0x00               # i8，非 0 = 在用
I_OFF_STATE = 0x0C               # i8，0=普通掉落 1=已被吸引(8px/帧追自机) 2=散射抛物线
I_OFF_X, I_OFF_Y = 0x10, 0x14    # float，currentPosition.x / y
I_OFF_VY = 0x20                  # float，startPosition.y = 下落速度，范围 [-2.2, 3.0]
                                 # ⚠ 仅 state≠2 或散射结束后有效；散射途中该字段是出生点 y（垃圾）
I_OFF_TX, I_OFF_TY = 0x28, 0x2C  # float，targetPosition.x / y（仅 state=2 用，散射终点）
I_OFF_TYPE = 0x34                # i8，ItemType
ITEM_NEXT_IDX = 0xC07238         # i32，nextIndex（实测：最后槽 312 → 值 313 ✓）

# ItemType（ref-th06-decomp ItemManager.hpp 枚举，新典编号一致）
I_POWER_SMALL = 0
I_POINT = 1
I_POWER_BIG = 2
I_BOMB = 3
I_FULL_POWER = 4
I_LIFE = 5
I_POINT_BULLET = 6               # 清弹转化，SpawnItem 直接丢弃（不到 +0x34 写入路径）

ITEM_PICK_R = 8.0                # 道具半边长（itemSize 16）
PLAYER_GRAB_R = 6.0              # 自机拾取半边长（grabItemSize 12）
ITEM_GRAB_DIST = ITEM_PICK_R + PLAYER_GRAB_R     # 14px：x/y 各在此距离内即拾取

# ---- 道具收集线（PoC；MEMMAP §9，新典反汇编确证）----
# ItemManager::OnUpdate（RVA 0x42980）：火力 ≥ 128（满）且自机 y < 128 时，
# 全屏 state-0 道具被强制转为追踪（state→1，8px/帧 飞向自机，不可能再漏捡）。
# 原版同构：state=2（散射）的道具不参与转化 —— 那些只能身体接。
POC_LINE_Y = 128.0               # 收集线：自机 y 严格小于它才触发
POC_TARGET_Y = 120.0             # 冲线目标：线低 8px，留出抖动余量，且在贴边惩罚区(60px)外

# ---- 段边界与关键函数（静态分析工具用；MEMMAP §4）----
TEXT_LO, TEXT_HI = 0x1000, 0x2BEA91
DATA_LO, DATA_HI = 0x323000, 0xC29660
FN_COLLISION = 0x6A980           # Player::CalcKillBoxCollision
FN_LASER_COLLISION = 0x6ABA0     # Player::CalcLaserHitbox
FN_BULLET_UPDATE = 0x10870       # BulletManager::OnUpdate
FN_SPAWN_BULLET = 0xF870         # BulletManager::SpawnBulletPattern
FN_SPAWN_LASER = 0x105E0         # BulletManager::SpawnLaserPattern
FN_PLAYER_UPDATE = 0x68820       # Player::OnUpdate
FN_ENEMY_SPAWN = 0x360D0         # EnemyManager::SpawnEnemy
FN_ITEM_SPAWN = 0x426E0          # ItemManager::SpawnItem（道具池地址即由此函数反汇编得出）

# ---- 场地几何（MEMMAP §1）----
FIELD_X0, FIELD_X1 = 8.0, 376.0
FIELD_Y0, FIELD_Y1 = 16.0, 432.0
FIELD_CX, FIELD_CY = 192.0, 224.0                # 场地中心（也是归一化分母）

# 自机速度 px/帧 —— 实机标定值（`py tools\calib_speed.py`，8 向 × 40 帧）。
# **唯一真源**：dodge / GUI / explain_plan / sweep_params / check_plan 一律 import，别各写一份。
# 这是唯一「必须先实测、填错全盘失真」的参数：所有方向评分都建立在它上面。
PLAYER_SPEED = 4.39

# ---- 判定半径（碰撞判定常量；自机值取自 PLAYER_HITBOX 处的实测）----
# 子弹侧真实几何（MEMMAP §3，反汇编 0x6A980 + 调用点 0x11418 确证）：
#   r弹 = min(grazeSize.x, grazeSize.y) × 0.5，grazeSize 在 Bullet + 0x5F4，**逐弹不同**。
#   本机实测到两档：4×4 → 2.0（小玉，占多数）、6×6 → 3.0。
#   grazeSize 由精灵高度分档（原版 BulletManager.cpp:1379-1427）：4 / 5 / 6 / 9 / 11 / 16 / 32。
# BULLET_R 只在读不到 grazeSize 时兜底（槽未初始化等）；它等于 6×6 档，偏保守。
PLAYER_R = 1.25
BULLET_R = 3.0
GRAZE_R_MAX = 32.0       # 逐弹半径的合理上限：超过即视为读值异常，回落 BULLET_R

# ---- 构建适配（改地址请改 addr_cache.json，别改上面的字面量）----
# 上面这些全局地址只对 `addr.BASE_MD5` 那个构建成立。游戏更新后全部失效
# ——2026-09-24 那次 Steam 更新就让整套避弹报废（读错内存 → 判成不在关卡 → 拒发按键）。
# 但**结构内偏移 / 池 stride / 槽数从来不随更新变**，变的只是全局变量位置，
# 所以地址外置到 `addr_cache.json`，按 exe MD5 索引，由这里在 import 时套用：
#   · 缓存命中 → 换成当前构建的地址
#   · 没缓存 / 找不到游戏 → 保持上面的基线值，且不抛异常（诊断脚本仍要能跑）
# 状态见 `py tools\addr.py`；重新定位见 `py tools\autofix.py`。
import os as _os
import sys as _sys
if _os.path.dirname(_os.path.abspath(__file__)) not in _sys.path:
    _sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
try:
    import addr as _addr
    APPLIED_ADDRS = _addr.apply_overrides(globals())   # {名字: (旧值, 新值)}
except Exception as _e:                                # noqa: BLE001
    APPLIED_ADDRS = {}
    ADDR_ERROR = f'{type(_e).__name__}: {_e}'
