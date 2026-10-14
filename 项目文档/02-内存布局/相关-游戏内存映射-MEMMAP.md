# 相关-游戏内存映射-MEMMAP.md —— th06nc 地址与结构

> 【相关】写读取代码前看这份。所有地址均为**模块内 RVA**（相对 `th06nc.exe` 基址）。
> 访问方式：`绝对地址 = moduleBase + RVA`（每次启动都不同，一律用 `module_base()` 取）。
> 函数名来源：新典符号库 `09-依据/ref-th06nc-re-data/`。
> **全局变量的 RVA 随游戏更新变**：权威值是 `tools/addr_cache.json`（按 exe MD5 索引），
> 由 `tools/addr.py` 在 import `offsets.py` 时套用 —— 所以代码里别抄本表的数字。
> 本文记录的是**结构语义与考证依据**，那些（结构内偏移、stride、槽数）不随更新变。
> 表里的 RVA 对应当前构建；换构建先 `py tools\env.py` 看状态，失效就跑 `py tools\autofix.py`。
>
> **本文的 RVA 分两类，别混**：
> · **§1 表 = 当前构建的实际地址**（可直接用）；
> · **§2 起的考证叙述里的 RVA = 基线构建**（`b0cc28ec…`）当初逆向时的值，
>   用来说明「这个地址是怎么找出来的」。**它们不是当前值**，要对当前值一律查
>   `tools/addr_cache.json`（`py tools\addr.py` 可读）。

## 1. 全局变量

| 名称 | 当前 RVA | 宽度 | 实测值 / 依据 |
|---|---|---|---|
| **自机 x** | `0x551720` | float | 实读 `192.0`（场地水平正中）✓。⚠ 曾误取 `0x549D30` —— 那里是场地矩形常量 `{8,16,368,416}`，恒定不变且值同样落在场地内 |
| **自机 y** | `0x551724` | float | 实读 `384.0` ✓（= 自机 x + 4）|
| **自机判定半径** | `0x55173C` | float | 实读 `1.25`（= 自机 x + 28）—— **坐标基址最硬的判据**：基址错档时这里读 `0.00` |
| 残机 Lives | `0x549D40` | u8 | 关卡内实读 `2`、`Bombs` 读 `3` ✓ 判定见下方说明 |
| 炸弹 Bombs | `0x549D41` | u8 | 与 Lives 相邻 1 字节（旧构建同样相邻）✓ |
| 画面判据 Retry | `0x549D42` | u8 | `0xFF` = 停在 Continue 画面（有 `mov byte [X],0xff` 写入佐证）✓ |
| 火力 Power | `0x53CAD8` | u16 | 实读 `128` = 满火力 ✓ |
| 死亡次数 Deaths | `0x53CAB0` | i32 | 实读 `1`（跑过一局后）✓ |
| 死亡中 Dying | `0x53D401` | u8 | `1` = 自机死亡中 |
| 「时停」标志? | `0x53D409` | u8 | **恒为 0，不能当运行判据**（见 PITFALLS）|
| 输入 Input | `0xABAE80` | u16 | 按键位掩码 |
| Gui | `0xABAE28` | ptr | 未确认；与 Input 相距 `0x58`（旧构建距离相同）|
| 场景 Scene = `Supervisor.curState` | `0xC6DFBC` | i32 | **分不出画面**，判据见 §8；被赋 `1/7/8/0xc` 等场景号，47 处引用 |
| 想要的场景 wantedState | `0xC6DFB8` | i32 | = `curState − 4`；与 curState 同值 = 无场景切换进行中 |
| **帧计数** | `0xC6DE20` | u16 | 每帧 +1，**实测 60/秒**（`autofix.py` 按速率确认）。⚠ 别用 `0xC6DFD6` —— 那是相邻的一对动画计数器，形态像但根本不涨 |

**Player 结构基址 = `0x549FF0`**（= 自机 x − `0x7730`）；自机坐标 = `Player + 0x7730` / `+0x7734`，
判定半径 = `Player + 0x774C`。结构内固定关系：`LIVES = Player − 0x2B0`（不随构建变，可交叉验证基址）。

> **`0x549D40` = `Lives`（已定论）**
> 两条推导曾撞在同一地址上：① 位移档 `+0x4AC50` 推 `Lives`（旧 `0x4FF0F0`）；
> ② 结构偏移 `Player(0x542600) + 0x7740`（旧构建该处标为"自机副坐标"）。实测排除 ②：
> 该处原始字节是 `00 00 FF 00 | 43 4C 52 44` —— `0x549D42 = 0xFF`，紧跟着 ASCII `"CLRD…"`。
> **结构字段后面不会紧跟字符串常量**；而且若它是 4 字节 float，`0x549D42` 必须是 `0x00`。
> 加上它被 `inc/dec byte` 访问、`Retry` 有 `mov byte [X],0xff` 写入，三条独立证据一致。
> **"撞地址"是链接器把三个全局变量排到了那里，不是结构字段。**
> 运行佐证：`dodge.py --dry` 读到「残机 0」并在 Continue 画面正确松键退出。
>
> **⚠ `PLAYER_HITBOX`（`0x549D4C` = 自机 x + 28）实读 0，与旧的 1.25 不符**
> 该字段只被诊断脚本使用，避弹核心走 `offsets.PLAYER_R` 常量，所以不影响运行；
> 但**别拿它当判定半径的真源**，要确认得等自机在关卡内活动时再读一次。

**逻辑坐标系**：x ∈ [8, 376]，y ∈ [16, 432]；渲染到 1920×1080 全屏。
**帧率固定 60 Hz**（引擎是 DxLib；replay `T6RP` 每帧一条输入记录）→ 避弹循环按 16.7 ms 节拍。
**实测每帧开销**：读整帧 2.36 ms + 算方向 0.43 ms（59 弹，200 弹也只 0.48 ms）= 2.8 ms，占预算 17%。
跑不满 60 fps 时先查 GUI 的 GIL 竞争，别怀疑算法。
**自机移动速度 = `4.39` px/帧**（`tools/calib_speed.py` 实机标定，用户提供）。
唯一真源 = `tools/offsets.py` 的 `PLAYER_SPEED`，dodge / GUI / explain_plan / sweep_params / check_plan 一律 import。

> **⚠ 未解释的 10% 差额**：代码侧的基准常量是 **`4.0`**（`Player + 0x7860` 实读；
> 原版 `Player.cpp:113` 的 `orthogonalMovementSpeed`，斜向 = 它 / √2。
> 同一结构里还有低速档 `+0x7864 = 2.0` → 见 **§12**）。
> `4.39 / 4.0 = 1.0975`，来源未定位（帧率补偿倍率 `effectiveFramerateMultiplier`
> 未在新典找到；`0x4FF0E0..EC` 的 `8/16/368/416` 是场地矩形，不是倍率）。
> 标定工具本身有 ±1 帧时序错位（`measure()` 读坐标与读帧计数不同步），40 帧下约 ±2.5%，
> **不足以解释 9.75%**。数字对不上时先复核标定，再怀疑地址。

**斜向 = 直向 / √2（归一化）** —— 原版 `Player.cpp:113`
（`diagonalMovementSpeed = orthogonalMovementSpeed / sqrtf(2.0)`），DIRS 的 `0.70711` 正确。
> 新典侧未独立复现该公式；`calib_speed.report()` 会打印「归一化 / 分轴独立」判定，
> 与本节不符时以**实机报告**为准并回来改这里（分轴独立则 DIRS 斜向分量要改成 ±1）。

旧记录「按 0.5s：右 +92 / 上 −88 / 左 −36」不可用 —— sleep 估帧数不准，左移 36px 是撞到边界，不是速度。

## 2. 子弹池（已实测验证）

**BulletManager 基址 `0x3EC2A0`** —— 全局对象，不是指针。

三重确证：① 全 `.text` 扫描有 13 处 `lea rcx, [rip+…]` 指向它；② `0x10870` 内以 `[mgr+0xFF618] × 0x620 + 8` 取槽；③ 解除暂停后实测 5 发子弹，x/y 全在场地内。

| 项 | 偏移 | 说明 |
|---|---|---|
| （对象头） | `+0x0000` | 8 字节，值 `0x324` / `0x325`，含义未确认 |
| **bullets[640]** | **`+0x0008`** | stride **`0x620`** = 1568 |
| **lasers[64]** | **`+0xF5018`** | stride `0x298`；反汇编三处确证（§7）。旧表 `+0xF5008` 系误算，已废弃 |
| nextBulletIndex | `+0xFF618` | i32，实测随生成 `7 → 14` |
| bulletCount? | `+0xFF61C` | 实测 `0` 与活跃弹数不符，**语义未确认** |

槽内偏移（几何已实测；**运动字段**由反汇编 `BulletManager__OnUpdate` 逐条确证）：

| 槽内偏移 | 类型 | 含义 |
|---|---|---|
| `+0x000` | f32 | dirChangeSpeed —— 转向事件发生时它成为当前速度 |
| `+0x004` | i32 | dirChangeInterval —— 两次转向相隔帧数 |
| `+0x008` / `+0x00C` | f32 | vx / vy —— **就是每帧位移**（`pos += velocity`，系数 1.0） |
| **`+0x014`** | u16 | **exFlags**：`0x10` 加速 / `0x20` 连续转向 / `0x1c0` 定时转向 / `0xc00` 边界反弹 |
| `+0x018` | f32 | `0x20` 弹的每帧角度增量 |
| `+0x01C` | i32 | 已转向次数（转向事件 +1） |
| `+0x020` | i32 | 转向次数上限，到顶清位 |
| `+0x024` | f32 | 当前标量速度（间隔内插值的起点） |
| **`+0x02C`** | i32 | **timer，每帧 +1**；转向判据就是 `timer >= interval × (num+1)` |
| **`+0x030` / `+0x034`** | f32 | **x / y** |
| `+0x040` | f32 | 方向角 —— **会被改写**（转向弹每帧重算，见 §2.1） |
| `+0x044` | u16 | state：`1` = FIRED 才判死，`5` = 消散（无判定）|
| `+0x048` | i32 | 加速 / 连续转向的持续帧数上限 |
| `+0x150` | ptr | ANM 精灵指针 |
| **`+0x5F4` / `+0x5F8`** | f32 | **grazeSize（宽 / 高）** —— 碰撞判定尺寸，见 §3 |
| `+0x600` | f32 | `0x20` 弹的每帧速度增量 |
| `+0x608` / `+0x60C` | f32 | 加速度矢量（`0x10` 时每帧累加到 velocity） |
| `+0x614` | f32 | 转向角增量（`0x100` 时是绝对角） |
| **`+0x618`** | u8 | **isGrazed**（1 = 已擦到；判死的前置门，见 §3）|

**推荐读法**：一次 `ReadProcessMemory` 读 `0x620 × 640` 整块，按 x/y 非零筛活跃弹。
参考项目"和平模式"是逐槽把 `+0x44` 的 WORD 写 0 —— 本项目不采用。

> `+0x14` 实测恒为 `0x200`（普通弹的基础位，语义未确认）。转向 / 加速位与它**按位并存**，
> 判断时只需 `& 0x10` / `& 0x1c0` / `& 0xc00`。

### 2.1 子弹的三种「不匀速」（`read_bullets.py` 读到，`dodge.bullet_paths()` 建模）

每颗弹每帧的次序（反汇编 0x1400113xx~0x14001175C）：先按 exFlags 更新 velocity → 再
`pos += velocity` → 最后 `timer++`。只按当前 vx/vy 匀速外推，窗口内的落点就是错的。

| 机制 | 触发 | 每帧做什么 | 后果（不外推时） |
|---|---|---|---|
| 加速 `0x10` | `timer < hold` | `velocity += accel` | 落点**偏近**（10 帧差 ½at²） |
| 连续转向 `0x20` | `timer < hold` | `angle += rate`、`speed += srate` | 轨迹是弧线，直线外推整段偏 |
| 定时转向 `0x40/0x80/0x100` | `timer >= interval×(num+1)` | 换 angle 与 speed，`velocity` **整体改向**；间隔内速度线性衰减到 0 | 转向帧之后**整段作废**；`0x80` 是朝自机转，最致命 |
| 反弹 `0x400/0x800` | 出界 | 反射角度 | 本项目未建模（窗口内少见） |

**依据**：原版 `ref-th06-decomp/src/BulletManager.cpp:709-882` + 本机反汇编同一套
（`test al,0x10` @ `0x140010AB8`、`test word [rbx+0x14],0x1c0` @ `0x140010B63`、
`addss xmm2,[rbx+8]` 的 `pos += velocity` @ `0x14001175C`）。

## 3. 碰撞判定

**函数 RVA `0x6A980`** = `Player::CalcKillBoxCollision`（死亡判定，非擦弹）。

```
f(RCX = Player, RDX = &bullet.x, R8 = &碰撞盒, R9b = 0 圆对 AABB / 1 圆对圆)
```

反汇编要点：

**判定半径 = min(碰撞盒宽, 碰撞盒高) × 0.5**，与自机半径相加成圆：

```asm
0x06A986  movss xmm3, [r8]            ; 碰撞盒宽（R8 = 子弹 + 0x5F4）
0x06A99B  movss xmm6, [r8 + 4]        ; 碰撞盒高
0x06AA12  minss xmm6, [r8]            ; min(高, 宽)
0x06AA29  mulss xmm6, [0x14030CD58]   ; × 0.5（本机实测 = 0.5）
0x06AA35  addss xmm6, [rbx + 0x774c]  ; + 自机判定半径 1.25
0x06AA49  comiss xmm6, xmm1           ; (r弹 + r自)² > dx² + dy²
```

**必须 `isGrazed == 1` 才判死**（逐字对应原版 `BulletManager.cpp:913-931`）：

```asm
0x010935  mov  r12d, 1                    ; 循环内恒为 1
0x011277  mov  byte [rbx + 0x618], r12b   ; isGrazed = 1
0x0113F5  cmp  byte [rbx + 0x618], r12b   ; ⇔ else if (isGrazed == 1)
0x011402  lea  r8,  [rbx + 0x5f4]         ; R8 = &grazeSize
0x01140D  lea  rdx, [rbx + 0x30]          ; &子弹.x
0x011409  movzx r9d, r12b                 ; r9d = 1 ⇒ 走圆对圆分支
0x011418  call 0x14006A980
```

| 项 | 位置 | 说明 |
|---|---|---|
| grazeSize | `Bullet + 0x5F4` / `+0x5F8` | float×2，生成时从弹型模板**逐弹拷贝** |
| isGrazed | `Bullet + 0x618` | u8，判死的前置门 |
| 半宽常量 | RVA `0x30CD58` | float = **0.5**（实测）|

**判定半径分档**（原版 `BulletManager.cpp:1379-1427` 按精灵图高度赋值；本机实测**新典沿用**）：

| 精灵高 | 弹型 | grazeSize | r弹 | r弹 + 1.25 |
|---|---|---|---|---|
| ≤ 8 | 小玉 | 4×4 | 2.0 | 3.25 |
| ≤ 16 | 米弹 / 鳞弹 | 4×4 | 2.0 | 3.25 |
| ≤ 16 | 苦无 | 5×5 | 2.5 | 3.75 |
| ≤ 16 | 其他 | 6×6 | 3.0 | 4.25 |
| ≤ 32 | 匕首 | 9×9 | 4.5 | 5.75 |
| ≤ 32 | 火球 | 11×11 | 5.5 | 6.75 |
| ≤ 32 | 其他 | 16×16 | 8.0 | 9.25 |
| > 32 | 大玉 | 32×32 | 16.0 | 17.25 |

> **代码已按逐弹半径判**（不再是统一常数）：`read_bullets()` 读 `+0x5F4`/`+0x5F8` 算出每颗弹的 r，
> `plan()` / `doomed_gap()` 先各减各的阈值再取 min。本机实测到两档：4×4 → 2.0（4349 颗）、
> 6×6 → 3.0（1747 颗）。`offsets.BULLET_R = 3.0` 只在读值异常时兜底。
> 擦弹环（`isGrazed` 的来源，原版 `Player.cpp:1199-1202`）：子弹矩形**外扩 20px** 后与自机判定盒求交。

**调用点**：`0x11418`（子弹侧）、`0x37A6C`（敌人接触侧）。

## 4. 关键函数 RVA

| RVA | 符号 | 作用 |
|---|---|---|
| `0x10870` | `BulletManager::OnUpdate` | 子弹每帧 tick，入口 RCX = BulletManager |
| `0xF870` | `BulletManager::SpawnBulletPattern` | 生成弹幕 |
| `0x105E0` | `BulletManager::SpawnLaserPattern` | 生成激光 |
| `0xEF00` | `BulletManager::TurnAllBulletsIntoPoints` | 清弹转道具 |
| `0x68160` | `Player::AddedCallback` | 自机初始化 |
| `0x68820` | `Player::OnUpdate` | 自机每帧 tick，读输入位图 `0xA6EC60` |
| `0x6ABA0` | `Player::CalcLaserHitbox` | 激光判定 |
| `0x25371` | ECL 67..75 共用处理器 | 子弹 pattern 入口 |

内部地址（仅反汇编所得，无符号）：`0x10970` 遍历循环、`0x10F00` 子弹积分、`0x11418` 对自机碰撞调用。
`0x11AA` 处有一处 `lea rcx, [g_BulletManager]`，疑似注册链回调，未细查。

## 5. 无敌补丁（参考项目做法，本项目未使用）

改 1 字节即可免疫普通弹：
- 碰撞判定 `RVA 0x6AA9D`：`JNE +7` → `JNE +0`
- 激光判定 `RVA 0x6ACF2`：`JNE` → `JAE`

原字节签名：`0F97C084C0750733C0E9CC00000080BB9878000000`。
**本项目目标是"躲避"而非"无敌"，仅作后备。**

## 6. 敌人本体池（已实测验证）

**`g_EnemyManager` RVA `0xAA1E90`**（全局对象）。反汇编 `EnemyManager__SpawnEnemy`（RVA `0x360D0`）得出，两处独立 `lea` 交叉验证一致。

| 项 | 偏移 | 说明 |
|---|---|---|
| **enemies[]** | **`+0x0008`** | **256 槽，stride `0x10B0`**（原版 `0xEC8`，x64 放大）|
| 槽占用标志 | `+0x00BC` | u8，bit7 = 占用（有符号判 `<0`）|
| flags 第二字节 | `+0x00BD` | bit1 = 可碰撞、bit3 = BOSS |
| flags 第三字节 | `+0x00BE` | bit3 = 隐形 |
| **position x / y / z** | **`+0x00B0` / `+0x00B4` / `+0x00B8`** | float |
| life | `+0x0234` | i32 |
| hitboxDimensions | `+0x02C0` / `+0x02C4` | float（宽 / 高）|

**池里没有速度字段**（表内无移动向量）：速度只能逐帧差分 → `dodge.EnemyMotion`
（判据同 `LaserMotion`：`life` 只减不增 + 位移 ≤ `MAX_STEP`，防槽复用伪造位移）。
**实测敌人会移动**：Laevatein 符卡里蕾米莉亚本体逐帧位移，hitbox 实测 **56×56**。
不外推的后果 = 前瞻窗口把「会动的敌人」当静止的 → 自机撞上去（护栏 `check_plan.py` 用例 42）。

读法：一次读 `mgr + 8` 起 `0x10B0 × 256` ≈ 1.07 MB，1.0 ms/帧。→ `tools/read_enemies.py`

## 7. 激光池（反汇编确证 + 阶段机）

**`lasers[0] = g_BulletManager + 0xF5018`**，**64 槽，stride `0x298`**。

依据（三处独立）：

1. `BulletManager__SpawnLaserPattern`（RVA `0x105E0`）：`lea rbx,[rip+…]` → 目标 RVA **`0x4E12B8`** = `0x3EC2A0 + 0xF5018`；接着 `cmp byte [rbx+0x274],0` → `add rbx,0x298` → `cmp eax,0x40`（找空槽循环）。
2. `0x3B1DC`：同一地址 `lea rcx,[rip+…]`，紧跟 `memset(…, 0x10108)` —— 初始化激光池。
3. 参考项目 `+0xF528C` = `lasers[0] + 0x274`（**不是 `+0x284`**）。旧表按 `+0x284` 反推，才得出错误的起点 `+0xF5008`。

### 7.1 槽内字段

`SpawnLaserPattern`（写）与 `BulletManager__OnUpdate` 的激光循环（读）两处互证 ——
OnUpdate 用 `lea rbx,[r15+0xF502C]`，即指针比槽基址高 `0x14`，下表已折算回槽内偏移。

| 槽内偏移 | 类型 | 含义 |
|---|---|---|
| `+0x0004` | f32 | width（判定半宽 = width/2）|
| `+0x000C` | i32 | **当前阶段已过帧数**（切阶段时归零，每帧 +1）|
| `+0x0010` | f32 | **startOffset** —— 线段起点在轴上的偏移 |
| `+0x0014` | f32 | **endOffset** —— 线段终点偏移，**每帧 += speed** |
| `+0x0018` | i32 | **消散阶段总帧数** |
| `+0x0260` | f32 | angle —— **会变**：引擎只读它，但实测同一槽逐帧 +2.25°（见 §7.3）|
| `+0x0264` | u16 | 位域，bit0 选透明度算法分支 |
| `+0x0268` | i32 | **发射阶段总帧数** |
| `+0x026C` | f32 | **speed** —— offset 前进速度(px/帧) |
| `+0x0270` | i32 | **预警阶段总帧数** |
| `+0x0274` | u8 | **state（0 = 空闲；生成时写 1）** |
| **`+0x0278` / `+0x027C` / `+0x0280`** | f32 | **pos x / y / z —— 轴的「原点」，不是线段起点** |
| `+0x0288` | f32 | startLength —— 线段长度上限（startOffset 被它推着走）|
| `+0x0290` | u8 | **阶段**（见 §7.2）|

> **旧表把 `+0x0010` / `+0x0014` / `+0x026C` 记成「上一帧的 timer / 纹理滚动偏移 / 纹理滚动速度」，
> 是错的**：OnUpdate 的激光循环里它们是浮点，做的是
> `endOffset += speed` → `startOffset = endOffset − startLength` → 起点 < 0 则归零，
> 也就是**线段沿自身方向平移**。实现曾按「静止线段」写 → 横扫的激光整条错位。
> 反汇编位置：RVA `0x1161D..0x11883`。

自洽校验：`0xF5018 + 64 × 0x298 = 0xFF618`，正好是 `nextBulletIndex`（§2）的位置。

### 7.2 阶段机（`+0x0290`）—— 唯一决定「打不打得到人」的东西

`BulletManager__OnUpdate`（RVA `0x10870`）的激光循环按它四路分派：`0` / `1` / `2` / `≥3`。
生成时初值 = **`(预警总帧数 == 0) ? 1 : 0`**（`SpawnLaserPattern` 结尾 `sete cl` → `mov [rbx+0x290], cl`）。
每次切阶段：计时器归零、该字节 +1。

| 值 | 阶段 | 这一阶段做什么 | 有伤害判定？ |
|---|---|---|---|
| 0 | 预警 | 只算透明度（显形），计时到 `+0x270` 帧切下一段 | **没有** |
| 1 | 发射 | 调 `Player__CalcLaserHitbox`（RVA `0x6ABA0`），计时到 `+0x268` 帧切下一段 | **有** |
| 2 | 消散 | 透明度淡出，计时到 `+0x018` 帧后 `state = 0` | **没有** |
| ≥3 | 收尾 | 长度（`+0x0010`）≥ 640 即 `state = 0` | **没有** |

**判定几何**（OnUpdate 内联，作为 `Player__CalcLaserHitbox` 的入参，反汇编 RVA `0x1161D..0x11883`）：
`center = pos + 方向(angle) × (startOffset + 长度/2)`，`长度 = endOffset − startOffset`，
`size = (长度, width/2)`。**`pos` 是轴原点** —— 线段从 `pos + 方向×startOffset` 起、
到 `pos + 方向×endOffset` 止。旧实现按 `[pos, pos + startLength]` 算，= 少加了一个 `startOffset`。

**两种移动是两回事，别混**：

| 移动方式 | 来源 | Laevatein 实测 |
|---|---|---|
| 沿自身方向伸长 / 平移 | `endOffset += speed`（槽内字段，直接可读）| 竖直激光 `speed = 0`，不动 |
| **轴原点整体平移** | **槽里没有这个量**，只能逐帧差分 | 横扫激光 **+6px/帧**，比自机 4.39px/帧还快 |

实测（`_tmp/laser_trace` 落盘 42716 条样本）：自机连续静止 25 帧期间激光照样在动 →
那是符卡的固定图案、与自机走位无关；被击中那几帧自机一直贴着激光右边缘（余量 0~3px）被从后面追上。

**预警阶段是个陷阱**：实测预警期 `pos` 静止、`speed = 0`，**开火后才开始扫** ——
「它会不会扫、往哪扫」在预警期**读不到任何信号**。所以不能把预警线的横向余量当成安全
（它一开火就 +6px/帧追上来，横向跑不掉），实现上给预警激光做**矩形避让软项**
（`dodge.WARN_RECT_W`）→ CONTEXT §3.23。

**怎么读**：`tools/read_lasers.py` 给 `starts / ends / lens / speeds` 与 `phases / timers / totals`
（`totals - timers` = 还剩几帧切阶段）。
**怎么用**：躲避要把预警线一起算（那就是马上要开火的位置）；**必死预判只能看 `1`（发射）** ——
拿预警阶段的激光当「不炸必死」会白扔炸弹（`dodge.read_frame()` 的 `laser_armed` 就是为此分的）。

**已实机复核**：阶段按 预警 → 发射 → 消散 正常切换、`还剩 N 帧` 逐帧递减（→ CONTEXT §3.23）。

### 7.3 旋转激光（angle 逐帧变）

`_tmp/laser_trace_20260924-000008.csv` 的 slot 0：连续 19 帧 `pos` / `start` / `end` /
`length` / `width` / `speed` **全部不动**，只有 `angle` 每帧 +2.25°（偶有 +4.5°，采样隔帧）。
阶段与计时连续、几何全同 → 不是槽复用，是真在转。

- **谁改的没定位到**：激光循环里 angle 只被读（`0x140011DC7` 取它算 ANM 旋转与判定几何），
  写入方不在该函数内。**不影响躲避** —— 逐帧差分角速度即可。
- **实测值**：2.25°/帧 = 0.0393 rad/帧；40 帧前瞻可累积 90°，一条 388px 长的激光整片扫过去。
- **样本画面是 `NO_LIVES`**（死亡后残留；这批数据一直只在菜单 / Continue / 死亡画面）。
  「战斗中多常见」待实机复核，但**数组里能转已经实锤**：按"不旋转"算就是错的。

## 8. 画面判据（已实测验证）

`Scene` 远远不够 —— **`2` 同时覆盖"关卡中"和"Continue 画面"**，这正是自动化脚本出事的根源。可用的判据：

| 名称 | RVA | 类型 | 判据 |
|---|---|---|---|
| curState（旧称 Scene）| `0xC6DFBC` | i32 | 1 = 主菜单系、2 = 游戏场景、**3 = 关卡切换中**、**0 / 12 = 场景重载中**（重开符卡，各 1~2 帧）、6/7 = 结算、9 = 音乐室 |
| wantedState | `0xC6DFB8` | i32 | 与 curState 同值 = 无场景切换进行中 |
| **帧计数** | **`0xC6DE20`** | u8 | **每帧 +1**；不走 = 游戏已暂停 / 最小化 |
| **失败菜单标志** | **`0x549D42`** | u8 | **`0xFF` = 停在失败菜单**（`isInRetryMenu`，依据 `0x6A430` 的 `mov byte […],0xff` = 原版 `Player.cpp:247`）：**普通关卡的 Continue 与符卡练习失败后的 "Failed..."（返回符卡选择 / 保存Replay / 重试）共用这一位**；关卡中为 `0x04` |
| Lives | `0x549D40` | u8 | 残机（**0 = 没有后备命，关卡仍在进行** —— 别拿它当退出条件）|
| Bombs | `0x549D41` | u8 | 炸弹 |
| deaths | `0x53CAB0` | i32 | 每次死亡 +1 |
| 自机死亡中 | `0x53D401` | u8 | `1` = 死亡中（发键不安全；结算完 `respawn <= 0` 就松键退出）|
| Power | `0x53CAD8` | u16 | 火力（与 §1 一致）|

**读法 → `tools/screen.py`**：`read_state()` / `screen_of()` / `is_running()`。

> **curState = 3（GAMEMANAGER_REINIT）= 关卡之间的过渡态**：依据是原版 `Gui.cpp` 的
> `MSG_OPCODE_STAGEEND`（把 curState 置成 `SUPERVISOR_STATE_GAMEMANAGER_REINIT`）
> 与 `GameManager::AddedCallback`（`currentStage++` 后自动载入下一关）—— 这段**不需要按键**。
> 新典同构，但**本机尚未在真实关卡过渡中采样到**（待实机验证）。`screen_of()` 判为
> `STAGE_SWITCH`：自动进下一关就是「在这里不退出、不按键地等过去」。
>
> 未确认：ESC 暂停菜单没有找到独立标志（原版是靠替换 chain 实现），改用「帧计数停滞」间接判定。
> 主菜单内部分屏（标题 / 难度 / 角色 / 御札）尚未定位 —— `curState` 在它们之间恒为 1。

## 9. 道具池（已实测验证）

**`g_ItemManager.items[0]` RVA `0xBAF0D8`**（全局对象，不是指针）。

依据：反汇编 `ItemManager__SpawnItem`（RVA `0x426E0`）—— `lea rax,[rip+…]` 与 `lea r10,[rip+…]` 两处独立指向同一地址；取槽是 `imul rbx, rcx, 0x160` + `add rbx, rax`（rcx 来自 nextIndex），`cmp ecx, 0x400` 是回绕判断。

| 项 | 偏移 | 说明 |
|---|---|---|
| **items[]** | **`+0x0000`** | stride **`0x160`**；代码按 `0x400` 循环（数组 1025 槽，末槽当哨兵，读 1024 即可）|
| itemCount | `-0x0008`（= `0xBAF0D0`）| i32，**实测 7 = 在用道具数 ✓**；每帧清零后累加 |
| nextIndex | `+0x58160`（= `0xC07238`）| i32，**实测末槽 312 → 值 313 ✓** |

槽内偏移（`+0x00` / `+0x10` / `+0x14` / `+0x20` / `+0x34` 已实测）：

| 槽内偏移 | 类型 | 含义 |
|---|---|---|
| **`+0x00`** | i8 | **isInUse（活跃判据）** |
| `+0x04` | i32 | 常量 `-999`（原版 `unk_4`）|
| `+0x0C` | i8 | state；`0` = 普通下落，`1` = 正在飞向自机，`2` = 清弹转化的抛物线 |
| **`+0x10` / `+0x14`** | f32 | **currentPosition x / y（已实测）** |
| `+0x1C` / `+0x20` / `+0x24` | f32 | startPosition x / y / z；**`+0x20` 是下落速度**，实测值域 `[-2.2, 3.0]` |
| `+0x28` / `+0x2C` | f32 | targetPosition x / y（仅 state=2 用）|
| **`+0x34`** | i8 | **itemType（下表）** |

**ItemType**（与原版枚举一致，新典 `SpawnItem` 对 `6` 直接返回、不上屏）：
`0` 小P / `1` 蓝点 / `2` 大P / `3` Bomb / `4` 满P / `5` 1UP / `6` 清弹点。

**读法**：一次读 `0x160 × 1024` = 352 KB，单次 `ReadProcessMemory`（约 0.3 ms）。→ `tools/read_items.py`

**运动**：无水平速度，`+0x20` 从 `-2.2` 每帧 `+0.03`、到 `3.0` 封顶 ——
道具**竖直下落**，所以捡道具主要是水平对齐、等它自己落下来。

**拾取判定**：AABB 重叠，`|dx| < 14 且 |dy| < 14`
（自机 `grabItemSize` 12 + 道具 size 16，各取一半 → `ITEM_GRAB_DIST`）。
依据：原版 `Player::CalcItemBoxCollision`（`ref-th06-decomp/src/Player.cpp:1346`）。

**满火力全收（新典同样保留，反汇编确证）**：`ItemManager::OnUpdate`（RVA `0x42980`）里
`comiss xmm11, [0x506AD4]` + `ja` —— `xmm11` = `128.0f`、`0x506AD4` = 自机 y：
**自机 y < 128（PoC 线以上）时，全屏道具被强制吸引飞向自机**。
满火力阈值 `128` 亦在同一函数确证（`mov edx, 0x80`；`cmp ax, dx` / `mov [power], dx` 钳制）。
> 智能冲线已落地（`dodge.ItemLineTrip` → CONTEXT §3.16）：满火力 + 可转化价值达标时
> 冲线一次全屏吸；冲线吸引走软项通道，安全分压过它（堵死冲不上、限时就放弃）。
> 同函数还确证了 `g_PowerUpThresholds` 阈值表 `0x308550` 与 `g_PowerItemScore` `0x308580`（暂未使用）。

**state = 2（散射）细节**（原版 `ref-th06-decomp/src/ItemManager.cpp` 确证）：
60 帧从出生点插值到 targetPosition，期间 `+0x20`（vy 字段）被 `SpawnItem` 用出生点覆写
—— **是垃圾值，不能当下落速度**；第 60 帧 vy 清零、之后从静止重新 `+0.03` 加速；
**state 永不转 0，且 PoC 转化判据在 `state != 2` 分支里 —— 散射物永不参与收集线转化**。
决策侧近似 → `dodge.read_frame()`：位置用 targetPosition、vy=0、加平均 30 帧延迟。

**未确认**：`0xC0723C`（nextIndex + 4）实测恒为 `0`，**不是** itemCount —— 别拿它当场上道具数。

## 10. 敌人射击节奏 → 弹幕预警（已落地）

**用途**：不预测弹幕形状，只预测「下一波还有几帧来」。躲避从纯反应式变成提前让开 ——
反应式缺的正是「跑出弹幕覆盖区」的那段时间。

| 项 | 值 / 依据 |
|---|---|
| `EclManager::RunEcl` | RVA **`0x22060`**；**成员函数** —— `rcx = this`、`rdx = Enemy*`（`0x022108 mov rdi, rdx`）|
| **`shootInterval`** | **`Enemy + 0xF68`**（i32）：`<= 0` = 当前不射击 |
| **`shootIntervalTimer`** | **`Enemy + 0x10A4`**（i32）：每帧 +1，到达 interval 即发射并清零 |
| `shootOffset` | `Enemy + 0xC5C`（float×3）：发射点相对敌人的偏移；实测 `(0, 8, 0)` |
| `bulletProps` | `Enemy + 0x26C` —— 三个独立调用点一致：`0x25D63`(经 r12)、`0x269A9`、`0x28ABF` |
| `BulletManager::SpawnBulletPattern` | RVA **`0xF870`**，签名 `(BulletManager*, EnemyBulletShooter*)`；入口 `0x00F881 mov rdi, rdx` |
| ECL 指令格式 | `i32 time@+0`、`i16 opCode@+4`、`i16 offsetToNext@+6`；执行后 `currentInstr += offsetToNext`（`0x025D7D` / `0x025DA0`）|

**反汇编原文**（RVA `0x28A8A` 段 =「正式射击」路径，字段全部由此确证）：

```asm
cmp  dword ptr [rdi+0xf68], 0    ; 0 < shootInterval 才射击
jle  skip
mov  eax, [rdi+0x10a4]
inc  dword ptr [rdi+0x10a4]      ; shootIntervalTimer++
mov  eax, [rdi+0x10a4]
cmp  eax, dword ptr [rdi+0xf68]  ; timer >= interval ?
jl   skip
lea  rdx, [rdi+0x26c]            ; bulletProps
addss xmm0, dword ptr [rdi+0xb0] ; 发射点 = 敌人坐标 + shootOffset
call 0xF870                      ; SpawnBulletPattern
mov  dword ptr [rdi+0x10a4], 0   ; timer 清零
```

读法 → `tools/read_enemies.py` 的 `shoot_countdown()`（`-1` = 不射击）；
决策 → `dodge.warn_radius()`（倒计时线性放大敌人危险半径，`--warn` / `--warn-dist`）。

**⚠ 仍未解决 / 未实测**：

- **新典的 `EnemyBulletShooter` 内部布局 ≠ 原版**：起点 `0x26C` 已确证，但按原版读
  `+0x18/+0x1C`（speed1/speed2）得到 denormal 垃圾。**要预测弹幕形状必须先反推该结构**
  （`SpawnBulletPattern` 里 `[rdi+0x18]`/`[rdi+0x1C]` 各被访问 7/5 次，是热点）。当前只做时机预测。
- **倒计时的逐帧递减未实机验证**：采样时游戏停在 Continue / 暂停态，敌人 `interval = 0`
  （符合 `0 < interval` 判据）。字段地址由反汇编确证，但「timer 确实在走」需在正常关卡复核。
- ECL 有条件跳转 + 随机数指令（`SETINTRAND` / `SETFLOATRAND`）——**更远的预测不可靠**，别做。

**顺带确证**：`RunEcl` 里 `[rcx+0x274]`、`[rcx+0x278/0x27C/0x280]`、`[rcx+0x290]` 正是激光槽偏移，
与 §7 互相印证。

## 11. 自机状态与灵击 → 死亡炸弹（反汇编确证 + 实机读值）

**用途**：被打中的那一瞬间放技能保命。三处依据：反汇编 `Player__OnUpdate`、
运行时读到的 `bombInfo.calc` 指针、原版 `BombData.cpp`。

| 名称 | 位置 | 类型 | 实测值 |
|---|---|---|---|
| **playerState** | `Player + 0x7898` | u8 | 存活测得 `3`（无敌中）；`2` = DEAD —— 死亡状态机入口 `0x68AD2` 比的就是它 |
| **respawnTimer** | `Player + 0x773C` | i32 | **存活恒为 `8`**（连续数百帧采样不变）|
| **bombInfo.isInUse** | `Player + 0x9EC8` | u8 | `0`；= 符号库 `g_BombInUse`（RVA `0x509268`）|
| bombInfo.calc | `Player + 0x9ED0` | ptr | 运行时 = RVA **`0xD1A0`**（角色专属 bomb 函数）|
| bombInfo.duration | `Player + 0x9F20` | i32 | 未使用时 `0` |

**playerState 取值**（原版 `Player.hpp:54` 枚举顺序，与 `0x68AD2` 的 `cmp al, 2` 互证）：
`0` = ALIVE / `1` = SPAWNING / `2` = DEAD / `3` = INVULNERABLE。

**反汇编原文**（`Player__OnUpdate`，RVA `0x689A8`..`0x68B20`）：

```asm
0689A8  cmp   byte ptr [rcx+0x9ec8], sil   ; bombInfo.isInUse == 0 ?
0689AF  je    0x689BF
0689B1  mov   rax, [rcx+0x9ed0]            ; 正在灵击中 → 只调 calc(p)
0689BF  mov   rax, [rip+…]                 ; g_Gui
0689C6  cmp   dword ptr [rax+0x36b0], esi  ; HasCurrentMsgIdx()：屏幕有对话文字就不能炸
0689CC  jge   skip
0689D2  cmp   dword ptr [rcx+0x773c], esi  ; ★ respawnTimer != 0
0689D8  je    skip
0689DE  movzx ecx, byte ptr [rip+…]        ; g_BombsRemaining
0689E5  test  cl, cl
0689E7  jle   skip                         ; 没炸弹 → skip
0689ED  mov   r11d, dword ptr [rip+…]      ; g_Input
0689F7  and   edx, 2                       ; ★ bit1 = TH_BUTTON_BOMB
0689FA  je    skip
0689FD  mov   eax, dword ptr [rip+…]       ; 上一帧输入位图
068A06  and   eax, 2
068A09  cmp   edx, eax
068A0B  je    skip                         ; ★ 上帧也按着 → 不是按下沿 → skip
068A63  movzx ecx, byte ptr [rip+…]        ; g_BombsRemaining
068A70  dec   cl                           ; ★ bombs--
068A72  inc   dword ptr [rip+…]            ; bombsUsed++
068A7B  mov   byte ptr [rip+…], cl
068A8D  mov   rax, [rdi+0x9ed0]            ; bombInfo.calc
068A94  mov   byte ptr [rdi+0x9ec8], 1     ; ★ isInUse = 1
068AAB  mov   dword ptr [rdi+0x9f20], 0x3e7 ; duration = 999
068AB5  call  rax                          ; ★ calc(p) → 把 playerState 改成 INVULNERABLE

; —— 死亡状态机紧随其后 ——
068AD2  movzx eax, byte ptr [rdi+0x7898]   ; playerState
068AD9  mov   ebx, 2                       ; PLAYER_STATE_DEAD
068AF5  cmp   al, bl
068AF7  jne   …                            ; 不是 DEAD → 整段跳过
068AFD  mov   eax, dword ptr [rdi+0x773c]  ; respawnTimer
068B03  test  eax, eax
068B05  je    …                            ; == 0 → 走真死流程
068B0B  sub   eax, 1
068B0E  mov   dword ptr [rdi+0x773c], eax  ; ★ respawnTimer--
068B14  jne   …                            ; != 0 → 还在窗口内，什么都不做
068B1A  inc   dword ptr [rip+…]            ; ★ 到 0 才 deaths++（掉道具 / 扣 power 紧随其后）
```

**死亡炸弹为什么成立**：被击中 → `playerState = DEAD`，而 `respawnTimer` 从上次留下的 **8**
开始倒数，`0x68B14` 的 `jne` 让它**到 0 才结算掉命**。这 8 帧（≈133 ms）里按 X 就走
`0x68A8D` 那一段：角色 bomb 的 calc 把 `playerState` 改成 `PLAYER_STATE_INVULNERABLE`
（原版 `BombData.cpp` 四处一致，四个角色/类型都这样）→ 下一帧 `0x68AF5` 已不是 DEAD，
整段死亡逻辑被跳过，**死亡取消**。

**三个容易踩空的地方**：

- **按下沿**：一直按着 X 只有第一帧算（`0x68A09`）。所以按住几帧再松开；
  同帧 down+up 会被游戏轮询漏掉，等于没按。
- **`HasCurrentMsgIdx()`**（`0x689C6`）：屏幕上有对话文字时不能炸 —— 外部程序不用模拟，
  但要知道那一刻按 X 无效。
- **窗口只有 8 帧**：外部每帧读一次，通常能读到 `respawn` 7~6，够发一次键；读到 0 就晚了。

**判据别写成 `respawn < 8`**：`respawnTimer` 的值域不止 8 —— 原版复活后会被赋成 6
（`Player.cpp:287`），新典存活态实测为 8。**「是否在死亡窗口」要用 `state == DEAD 且 respawn > 0`**，
`respawn` 只当「还剩几帧」的参考读数（`get` 不到就当 0）。护栏见 `check_autofire.py` 的灵击用例。

读法 → `tools/read_bullets.read_player_state()`；决策 → `dodge.BombGuard`；
实机验证 → `tools/verify_bomb.py`。

## 12. 低速模式 focus（反汇编确证 + 实机读值）

**用途**：局面宽裕时按住 Shift 走半速。依据 = 反汇编 `Player__OnUpdate` 的方向选择段
+ 运行时读自机结构常量。

| 名称 | 位置 | 类型 | 实测值 |
|---|---|---|---|
| **focus 标志** | `Player + 0x785C` | u8 | 未按时 `0`；值 = 输入位图 bit2 |
| **直向速度（高速）** | `Player + 0x7860` | float | `4.0` |
| **直向速度（低速）** | `Player + 0x7864` | float | `2.0` |
| **斜向每轴（高速）** | `Player + 0x7868` | float | `2.82843` = 4.0 × 0.70711 |
| **斜向每轴（低速）** | `Player + 0x786C` | float | `1.41421` = 2.0 × 0.70711 |
| 射击函数（未 focus） | `Player + 0x7720` | ptr | 每帧与下一个二选一 `call` |
| 射击函数（focus） | `Player + 0x7728` | ptr | 同上 |

**输入位**（`0xA6EC60`，代码按 **dword** 读，§1 表里的 u16 够用）：
bit2 = `TH_BUTTON_SLOW`（键位 Shift）；bit1 = BOMB（§11 已证）。
`test r11b, 0x10 / 0x20 / 0x40` 与 `jns`（判 bit7）复现了原版枚举的上/下/左/右。

```asm
0690A2  mov   edx, r11d                     ; r11d = g_Input
0690A5  and   edx, 4                        ; ★ bit2 = TH_BUTTON_SLOW
0690AD  mov   byte ptr [rdi+0x785c], al     ; ★ focus 标志（setne 的结果）
0690B6  ja    …                             ; 8 个方向各一路，每路都 test edx, edx 二选一
069136  movss xmm6, dword ptr [rdi+0x7864]  ; ★ edx != 0 → 低速档
069143  movss xmm6, dword ptr [rdi+0x7860]  ; ★ edx == 0 → 高速档

069BF0  cmp   byte ptr [rdi+0x785c], 0      ; ★ focus 还会换射击函数
069C05  mov   rax, [rdi+0x7720]             ;   未 focus
069C0E  mov   rax, [rdi+0x7728]             ;   focus
069C15  call  rax
```

**结论**：

- 低速 = **精确半速**（4.0 → 2.0），斜向同样归一化（每轴 × 0.70711）
  → `plan(speed = PLAYER_SPEED × 0.5)` 是对的，不用另标一套 DIRS。
- 速度取自**结构字段**，不是代码里的立即数 —— 标定工具 `--focus` 量的是同一份值。
- focus 不只是慢：**射击函数整个换一套**（`0x7720` / `0x7728`），火力形态跟着变。

> §1 那条「代码侧基准常量 4.0 / 标定值 4.39 的 10% 差额」说的就是 `+0x7860` 这一格。

决策（什么时候按）→ `dodge.py` 的 `FOCUS_*` 常量与「双速规划」：判据是**原地不动的间隙**
≥ 安全分数线 + `FOCUS_SLACK`（说明这一步只是微调），护栏 → `check_autofire.py` 的低速用例；
实机验证 → `tools/verify_focus.py`；低速实测速度 → `py tools\calib_speed.py --focus`。
