# 必读-结构与组成-STRUCTURE.md —— 目录与模块

> 【必读】分层 + 模块清单 + 演化原则。

## 1. 分层

```
th06nc-autododge/
├─ AGENTS.md            T0 常驻指针（约定名，自动加载）
├─ README.md            给玩家与访客的门面（发布版随包分发）
├─ requirements.txt     依赖声明（numpy 必需，capstone 可选）
├─ dodge_params.json    控制台「保存为默认值」写的**覆盖值**（运行数据，不是代码；删掉 = 回出厂默认）
├─ tools/               全部 Python / Node 工具，一个职责一个文件（`assets/` 放运行资源，如游戏图标）
├─ 发布/                 发布物料（包内《使用说明.txt》）
├─ .github/workflows/   推 `v*` tag 自动构建并挂 Release
├─ dist/                构建产物；可整目录删，不进仓库
├─ 项目文档/             本文档库（T1 索引 + T2 主题）
├─ _tmp/                截图、内存快照、中间产物；可整目录删
└─ 项目文档/09-依据/     第三方参考，全部只读
   ├─ ref-th06nc-practice/   练习辅助器源码（本项目地址来源）
   ├─ ref-th06nc-re-data/    新典符号库（函数名 / 全局名 + 样本 MD5）
   ├─ ref-th06nc-re/         新典引擎笔记（DxLib / 时序 / 档案格式）
   └─ ref-th06-decomp/src/   原版 1.02h 反编译源码（CC0）
```

**脚本内一律用相对路径**：项目根由 `__file__` 推导，Steam 与游戏位置由 `tools/env.py` 探测 —— 换设备不需要改代码。

产物去向写死在 AGENTS.md 铁律 6：脚本 → `tools/`，文档 → `项目文档/`，其余 → `_tmp/`。

## 2. 工具清单

### 2.1 核心模块（读写游戏状态与输入）

| 文件 | 职责 |
|---|---|
| `tools/offsets.py` | **地址唯一真源**：结构偏移 / 场地常量 / 判定半径，以及**基线构建**的全局 RVA；其它模块只 import。文件末尾会调 `addr.apply_overrides()` 把全局 RVA 换成当前构建的值 |
| `tools/addr.py` | **地址解析层**：按 exe MD5 查 `addr_cache.json` 并覆盖 `offsets` 的全局 RVA —— 游戏更新后源码一行不用改 |
| `tools/addr_cache.json` | **当前构建的地址表**（按 MD5 索引，含置信度与依据）。不手改，由 `autofix.py` 生成 |
| `tools/autofix.py` | **游戏更新后一条命令恢复**：位移分档 + 反汇编指纹自动重定位全部全局地址，写缓存并做运行时验证；纯静态，不需要游戏在关卡内 |
| `tools/app_main.py` | **应用入口**：自动重定位地址 → 环境自检 → 按需拉起游戏 → 开控制台。打包（PyInstaller）也以它为入口，另收 `--run autofix` 内部子命令 |
| `tools/paths.py` | **路径唯一落点**：源码运行 vs 打包运行两套「可写根 / 只读资源根」。可写数据（保存的参数、地址缓存、日志）打包后落 exe 旁；其它模块不再各自推导 `__file__` |
| `tools/launcher.pyw` | **桌面壳**：双击无黑框，转调 `app_main.run()`。留 `.pyw` 是因为桌面快捷方式指向它，且 `.pyw` 不在 Python 源码后缀里、不能被 import —— 实现必须放 `.py` 才能被打包器静态分析 |
| `tools/env.py` | **环境唯一解析处**：Steam / 游戏目录 / **地址适配状态**自检（换设备只看它）|
| `tools/winmem.py` | Win32 内存读写：`Process` 类、区域枚举、`module_base`、窗口查找与置前 |
| `tools/th06.py` | SendInput 输入模拟（扫描码）+ IME 屏蔽 + 全内存浮点扫描 + 聚焦封装 |
| `tools/read_bullets.py` | 读子弹池：整块读 640 槽。**两个接口** —— `read_bullet_frame()` 给全部字段（几何 + **运动参数**：exFlags / 加速度 / 转向参数 / timer），`read_bullets()` 是只要几何的旧 6 元组；另读自机坐标 / 残机 / **灵击状态**（`read_player_state()`：playerState / 死亡窗口 / bombInUse）|
| `tools/read_enemies.py` | 读敌人本体池：整块读 256 槽 → 位置 / life / hitbox / 可碰撞标志 / **发弹倒计时**（`shoot_countdown()`）|
| `tools/read_lasers.py` | 读激光池：64 槽 → 位置 / angle（**逐帧会转**）/ width / 长度 |
| `tools/read_items.py` | 读道具池：整块读 1024 槽 → 位置 / 类型 / 下落速度；`read_power()` 读火力 |
| `tools/screen.py` | **画面判据**：`read_state()` / `screen_of()` / `is_running()` —— 发键前的安全闸（含 `STAGE_SWITCH` 过渡、`RELOAD` 重载过渡、`NO_LIVES` 残机 0 仍可发键、`CONTINUE` 失败菜单只松键不按方向键）|
| `tools/human_watch.py` | **玩家操作检测**：本进程低级键盘钩子（只读、放行）→「人刚按过键 / 人此刻按着键」，让位机制的唯一判据 |
| `tools/dodge.py` | 核心：`plan()` 9 向评分（子弹按 `bullet_paths()` 逐帧推进 —— 加速 / 转向弹）+ 进攻吸引 + 道具吸引、`LaserMotion`（轴平移 / **旋转** / 伸长三种速度逐帧差分）、`ReactionGate` 人类化反应延迟、`BombGuard` 自动灵击（死亡炸弹 + 必死预判）、`StageFlow` 关卡推进、`pick_target()` 选目标、`run_session()` 主循环 + 自动射击 + 玩家让位（CLI 与 GUI **共用同一套安全闸**）|
| `tools/dodge_gui.py` | **可视化控制台**：连接 / 启停躲避 / 状态显示（tkinter，复用 `run_session`）；参数在「高级设置」窗口、日志在「日志」窗口，窗口与任务栏图标 = 游戏图标 |
| `tools/make_icon.py` | 从 `th06nc.exe` 提取图标 → `tools/assets/th06nc.ico`（`ExtractIconExW` + `GetDIBits` 自封 ICO，不依赖 Pillow）；控制台缺图标时自动调用 |
| `tools/start_game.py` | 进入关卡：**只在判据明确时发键**（不再盲按菜单），否则报告当前画面 |
| `tools/unpack_assets.py` | 从 `data/*.dat` 按扩展名解包子集（复用第三方 `pkgl.py`；必须 `py -3` 调用）|

### 2.2 诊断与验证

| 文件 | 一条命令的用途 |
|---|---|
| `check.py` | 打印 Scene / 残机 / 自机坐标，判断游戏当前状态 |
| `check_threadsafe.py` | 多线程同读一个 Process 的回归检查（不加锁时 33% 长度错位）|
| `check_plan.py` | `plan()` 决策回归：软项不得覆盖安全（纯计算，不需游戏）|
| `humanize_sweep.py` | 反应延迟仿真扫描：更像人 vs 更迟钝，安全 / 切换次数 / 对齐与拾取三判据同时看 |
| `check_autofire.py` | `run_session()` 回归：Z 按住/松开、朝目标走、**灵击该不该按 X**、**关卡过渡与让位时序**（桩化，不需游戏）|
| `human_watch.py --seconds N` | 键盘钩子自测：注入键不得被算成真人按键，且必须收到注入事件（证明钩子真在工作）|
| `verify_bomb.py` | **实机**验证死亡炸弹：切前台、自机挨打，进死亡窗口就按 X，看能否取消死亡（会掉命风险）|
| `verify_focus.py` | **实机**验证低速模式按键链路：只按 Shift、自机不动，读输入位图 bit2（附近 60px 内有子弹就拒绝执行）|
| `check_offsets.py` | 地址集中护栏：活跃代码里不该有裸游戏地址 |
| `calib_speed.py` | **唯一标定处**：帧计数计时 + 8 向，自动剔除撞墙；`--focus` 标低速档 |
| `sample_lasers.py` | 只读等一次真实激光并落盘，核对 MEMMAP §7 槽内偏移 |
| `disasm.py` | capstone 反汇编指定 RVA（含 `caller`、`collision` 等预设）|
| `find_callers.py` | 在 `.text` 段搜索 `CALL rel32` 指向某 RVA 的位置 |
| `scan_xrefs.py` | 扫描 `.text` 段全部 RIP 相对引用，查"谁引用了某全局地址" |
| `scan_globals.py` | 反汇编一段代码，列出**它引用了哪些全局地址** |
| `scan_struct.py` | 列出函数访问的 `[reg+disp]` **结构偏移**；`--src` 追指针来源、`--call` 追调用参数（`scan_globals` 只管全局，结构字段靠它）|
| `watch_globals.py` | **只读**监控所有全局变量的变化，用来发现画面判据 |
| `watch_live.py` | **只读实机观测器**（不按键、不切前台）：被打中 / 死亡 / 画面切换时打现场 —— 谁碰上的（弹的完整字段 / 激光的 pos·angle·宽·轴移·转角）、前 N 帧间隙曲线；`--csv` 逐帧落盘、`--log` 后台挂着看 |
| `death_recorder.py` | **死亡黑匣子**：按游戏帧逐帧录完整世界（自机 + 全弹 + 全激光 + 全敌人）进环形缓冲，掉命瞬间把前 N 帧落盘成 npz（含当时的 `params`，复算要用同一套）。**两种用法**：控制台勾选 / `dodge.py --blackbox` 挂在主循环上（`BlackBox.feed` 复用已读到的世界）；或单独跑（自己读帧） |
| `death_report.py` | **死因解剖**：读 npz，用**游戏碰撞几何**定位真凶 → 脚本视角（`live_params()` 取实机参数离线复算九向）→ 反事实（当时还有没有活路）；`replan(px=, py=, prev=)` 供闭环回放复用；`--self-test` 合成场景自测，不需游戏 |
| `verify_blackbox.py` | **实机**验证黑匣子链路（只读、不按键）：真读帧喂 `feed()` → 人为触发落盘 → 用解剖器验回来。钩子只在「关卡进行中」才被调到，用它可以随时验链路 |
| `find_stride.py` | 搜索 `ADD reg, 0x620` 等 stride 递增指令，定位遍历循环 |
| `dumpmem.py` | dump 指定地址的 float / int 双视图 |
| `from_ref.py` | 用参考项目的 RVA 直接读值，校验地址是否正确 |
| `memprofile.py` | 内存区域统计，判断扫描策略 |
| `verify.py` | 对候选地址做按键响应验证 |
| `test_input.py` | 校验前台窗口 + 输入是否生效（只发方向键）|
| `window_game.py` | 游戏窗口移动 / 聚焦 / 查前台 |

### 2.3 实验遗留（盲扫路线，已证明低效）

> 保留仅供"已知 stride 时做基址验证"。**不要用它们替代反汇编。**

`analyze.py`、`locate.py`、`locate2.py`、`locate3.py`、`find_bullets.py`、
`find_bullet2.py`、`scan_bullets.py`、`scan_state.py`、`find_pool.py`、`find_pool2.py`、
`find_moving.py`、`probe_bullets.py`（后两个含"制造弹幕再冻结"的前置流程）。

理由见 `必读-防回退清单-DO_NOT_REVERT.md`。

### 2.4 静态分析（Node）

| 文件 | 用途 |
|---|---|
| `tools/pe_info.js` | 解析 PE 头 / 导入表 / 导出表 / 延迟导入 |
| `tools/strings.js` | 提取 ASCII 与 UTF-16 字符串并正则过滤 |

### 2.5 发布（打免安装 Python 的 exe 包）

| 文件 | 用途 |
|---|---|
| `tools/build_release.ps1` | 一条命令出发布包：PyInstaller onedir → 跑 exe 冒烟自检 → 拷随包文档 → zip → `SHA256SUMS.txt` |
| `发布/使用说明.txt` | 包内玩家说明（构建时拷进包） |
| `.github/workflows/release.yml` | 推 `v*` tag 自动构建并挂 Release；手动触发只出 artifact |

产物：`dist\v<版本>\th06nc-autododge-v<版本>-win64.zip`（文件夹版，约 24 MB，含 numpy / capstone / tkinter）。
选文件夹版而不是单文件：启动不必解压到临时目录，杀软误报也少。
`app_main.py` 是唯一打包入口，依赖树由它的 import 关系决定 —— 诊断脚本与项目文档不进包。

## 3. 数据流

```
读: moduleBase + RVA  --ReadProcessMemory-->  float / u8 / ptr
判: screen.py 画面判据  --非「关卡进行中」-->  一个键都不发
算: 自机 + 子弹 640 + 敌人 256 + 激光 64  --势场评分-->  安全方向
预: 敌人射击计时器  --interval - timer-->  发弹倒计时  --按倒计时放大危险半径-->  提前让开
选: 敌人池  --BOSS 优先、只认自机上方-->  攻击目标  --进攻吸引-->  朝它靠
捡: 道具池 1024  --按类型价值加权、够安全才参与-->  道具吸引  --与进攻同层-->  朝掉落物靠
炸: 自机 playerState / respawnTimer  --被击中(8 帧窗口) 或 九向必死-->  按 X 保命
关: curState=3  --关卡过渡-->  不退出不按键地等下一关载入；无威胁源时轻点 Z 推过开场对话
让: 低级键盘钩子  --非注入按键-->  停手（松键、零发键），人停手若干秒后自动接管
写: SendInput(扫描码)  -->  游戏 GetAsyncKeyState 轮询取到（Z 按住 = 连射；X 认按下沿）
```

**无注入、无文件修改。** 唯一的 hook 是本进程的**只读**键盘监听（`WH_KEYBOARD_LL`，
回调照常 `CallNextHookEx` 放行），只用来判断「人有没有上手」—— 不拦截、不改写任何按键。

## 4. 演化原则

- 一个工具一个职责；同类排查做到第三次就固化成一条命令。
- **菜单导航不盲按**：能确定当前画面才发对应的键，否则停下报告（判据见 MEMMAP §8）。
- 新脚本先放 `tools/`，过时后移入 `_tmp/` 或删除，不留死代码。
- **地址分两层放，别写死在流程里**：结构偏移 / 场地常量进 `tools/offsets.py`，
  全局变量的 RVA 进 `tools/addr_cache.json`（按构建 MD5 索引），依据与考证进 `MEMMAP.md`
  —— 别在第四个地方再抄一份。
- **游戏更新后不要手工改地址**：跑 `py tools\autofix.py`（launcher 会自动跑）。
  手工改字面量等于把项目拉回「每更新一次重做一轮逆向」的老路。
- 确认能跑：`py tools\dodge.py --dry`（不发键）。
