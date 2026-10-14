# 必读-总索引-INDEX.md —— th06nc 自动避弹辅助

> 【必读·P0】导航地图：是什么 / 结构 / 硬约束 / 任务→文档映射。
> 每份文档的路径与职责见 `README.md`（唯一详表），此处不重复。

## 1. 是什么

给《东方红魔乡：新典》(th06nc.exe, Steam AppID 4659620) 做**外部辅助程序**。
读进程内存拿自机与子弹位置 → 算安全方向 → `SendInput` 模拟方向键。
打完一关会自动接上下一关；玩家自己上手按键时它自动让位。
目标：LUNATIC 难度自动通关。**不注入、不改游戏文件。**

## 2. 结构与组成

```
th06nc-autododge/
├─ tools/       Python 工具集（内存读写 / 输入 / 反汇编 / 扫描）
├─ 项目文档/     本文档库
├─ _tmp/        截图、内存快照、中间产物，可整目录删
└─ AGENTS.md    T0 常驻指针
```

细则 → `01-规范/必读-结构与组成-STRUCTURE.md`。

## 3. 硬约束（不可违反，违反就坏）

1. **外部程序，不碰游戏文件**：不注入、不替换 DLL、不改 `data/*.dat`。
   违反后果：Steam 校验告警，且用户明确选择了外部方案。
2. **地址必须实测验证**：写进 MEMMAP 的地址都要在本机读过真实值。
   违反后果：文档变成误导源，接手者按错地址开发。
3. **先反汇编再扫描**：定位结构优先查参考项目 + capstone。
   违反后果：盲扫内存误报多、耗时长，本项目已因此浪费数轮。
4. **发字母键前校验前台窗口**：前台非游戏时只发方向键。
   违反后果：键盘输入打进 QQ / 浏览器输入框。

> 易错点 → `01-规范/必读-动手前的坑-PITFALLS.md`。

## 4. 任务 → 文档映射

> **先只读「首先读取」列**；遇依赖再沿「按需读取」取。

| 当前任务 | 首先读取 | 按需读取 |
|---|---|---|
| **接手项目（首次）** | **本文档 + `必读-项目现状-CONTEXT.md`** | `必读-结构与组成-STRUCTURE.md` |
| 写子弹读取 / 躲避算法 | `必读-项目现状-CONTEXT.md` §4 + `02-内存布局/相关-游戏内存映射-MEMMAP.md` | `01-规范/必读-动手前的坑-PITFALLS.md` |
| **改捡道具 / 道具读取** | `必读-项目现状-CONTEXT.md` §3.11 + `02-内存布局/相关-游戏内存映射-MEMMAP.md` §9 | `tools/read_items.py`、`tools/check_plan.py`（改完跑）|
| **改灵击 / 自动放技能** | `必读-项目现状-CONTEXT.md` §3.15 + `02-内存布局/相关-游戏内存映射-MEMMAP.md` §11 | `tools/check_autofire.py`（改完跑）、`tools/verify_bomb.py`（实机）|
| **改自动进关 / 玩家让位** | `必读-项目现状-CONTEXT.md` §3.17、§3.18 | `01-规范/必读-防回退清单-DO_NOT_REVERT.md`、`tools/check_autofire.py`（改完跑）|
| **改残机 0 / 掉命行为** | `必读-项目现状-CONTEXT.md` §3.19 | `01-规范/必读-防回退清单-DO_NOT_REVERT.md`、`tools/check_autofire.py`（改完跑）|
| **查掉命原因（脚本自己也不知道那种）** | `必读-项目现状-CONTEXT.md` §3.27 | `tools/death_recorder.py`（挂着收一例）、`tools/death_report.py`（解剖）|
| **改低速模式 / focus** | `必读-项目现状-CONTEXT.md` §3.20 + `02-内存布局/相关-游戏内存映射-MEMMAP.md` §12 | `01-规范/必读-防回退清单-DO_NOT_REVERT.md`、`tools/check_autofire.py`（改完跑）、`tools/verify_focus.py`（实机）|
| 查现成方案 / 找外部资料 | `09-依据/相关-现成方案调研-SURVEY.md` | — |
| 改输入模拟 | `01-规范/必读-动手前的坑-PITFALLS.md` | `01-规范/必读-防回退清单-DO_NOT_REVERT.md` |
| 改躲避 / 攻击 / 捡道具策略 | `00-入口/必读-项目现状-CONTEXT.md` §3.7、§3.9、§3.11 | `tools/check_plan.py`、`tools/check_autofire.py`（改完跑）|
| **调参 / 看不懂控制台滑条** | **`04-调参/相关-参数速查-TUNING.md`** | `tools/sweep_params.py`、`tools/explain_plan.py` |
| **换设备 / 自检报错** | `03-环境/相关-跨设备部署-DEPLOY.md` | `02-内存布局/相关-游戏内存映射-MEMMAP.md`（构建版本不一致时）|
| 新增内存地址 | `02-内存布局/相关-游戏内存映射-MEMMAP.md` | `01-规范/必读-文档编辑纪律-DOC_GUIDELINES.md` |
| 重构 / 简化代码 | `01-规范/必读-防回退清单-DO_NOT_REVERT.md` | `必读-结构与组成-STRUCTURE.md` |
