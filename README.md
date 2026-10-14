# th06nc-autododge

《东方红魔乡：新典》（`th06nc.exe`）的外部自动避弹辅助程序。

程序读取游戏进程内存中的自机、子弹、敌人与掉落道具位置，逐帧计算安全方向，
并通过模拟键盘输入执行避让、射击与道具拾取。

程序不注入进程、不替换动态链接库、不修改游戏文件，也不进行网络通信。

[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/platform-Windows%2010%20%7C%2011%20x64-lightgrey.svg)](#系统要求)
[![Python](https://img.shields.io/badge/python-3.8%2B-blue.svg)](requirements.txt)
[![Release](https://img.shields.io/github/v/release/FanerJian/th06nc-autododge?label=release)](../../releases/latest)

## 功能

| 能力 | 说明 |
|---|---|
| 自动避弹 | 对九个候选方向各外推若干帧弹道，选取整个时间窗内最小间隙最大的方向。 |
| 自动射击 | 进入关卡后持续按住 `Z` 连射。 |
| 自动拾取道具 | 带时间模型：仅在道具接近自机高度时做水平对齐，不为拾取牺牲输出。 |
| 智能道具线 | 满火力且掉落足量时冲上收集线，全屏普通掉落转为追踪。 |
| 自动灵击 | 被击中后 8 帧死亡窗口内按 `X` 取消死亡；九向必死时提前触发。 |
| 自动进入下一关 | 关卡过渡不退出；开场对话按节奏轻点 `Z` 推进。 |
| 玩家接管 | 检测到真人按键即停止发送按键，停手数秒后恢复接管。 |

## 系统要求

| 项 | 要求 |
|---|---|
| 操作系统 | Windows 10 / 11（64 位） |
| 运行环境 | 发布包免安装 Python；源码运行需 Python 3.8 或更高版本 |
| 游戏 | 《东方红魔乡：新典》，Steam AppID `4659620` |
| 权限 | 与游戏相同（游戏以管理员身份运行时，本程序亦须以管理员身份运行） |
| 目录 | 程序目录须可写（参数与地址缓存写入程序目录） |

## 下载与安装

1. 在 [Releases](../../releases/latest) 页面下载最新版 `th06nc-autododge-v<版本>-win64.zip`。
2. 解压到可写目录，例如 `D:\th06nc-autododge`。
   程序将参数与地址缓存写入自身目录，因此不要解压到 `C:\Program Files` 等受限目录。

发布包内含分步说明 [`使用说明.txt`](发布/使用说明.txt)。

## 使用步骤

1. 启动游戏（可由 Steam 启动，也可在控制台点击「启动游戏」）。
2. 双击 `th06nc-autododge.exe`。
3. 在控制台点击「连接游戏」。
4. 手动进入关卡。
5. 点击「开始避弹」。

## 参数配置

全部参数位于「高级设置」窗口。滑条悬停 0.4 秒显示该项说明，运行中改动即时生效。

逐项含义与调参后果见[参数速查](项目文档/04-调参/相关-参数速查-TUNING.md)。

## 安全边界与免责声明

- 只读游戏内存并模拟按键：不注入、不替换 DLL、不修改游戏文件、不联网。
- 本程序仅供个人学习与练习使用，使用风险自负，请遵守游戏与平台的服务条款。
- 本仓库不包含任何游戏本体文件、资源档案或存档。

## 开发与构建

- 环境：Python ≥ 3.8，然后执行 `pip install -r requirements.txt`；地址自动适配另需 `capstone`。
- 环境自检：`py tools\launcher.pyw --check`
- 源码运行：双击 `tools\launcher.pyw`，或执行 `py tools\app_main.py --auto`
- 打包发布包：`powershell -File tools\build_release.ps1 -Version 0.1.0`
- 持续集成：推送 `v*` 标签触发构建验证（产物为 Actions artifact，不作为发布件）
- 文档入口：[项目文档/README.md](项目文档/README.md)

目录约定：

```
tools/         全部源码与诊断脚本（含自检与打包脚本）
发布/          随发布包分发的中文使用说明
项目文档/      设计、内存布局、调参与部署文档
```

## 许可证

本项目以 **MIT** 许可证发布，见 [`LICENSE`](LICENSE)。

`tools/assets/th06nc.ico` 由控制台首次运行时从本机游戏 exe 提取，不进入仓库；
游戏图标版权归原作者所有。

`项目文档/09-依据/` 下的参考材料各自保留上游授权：

| 目录 | 内容 | 授权 |
|---|---|---|
| `ref-th06-decomp/` | 原版 1.02h 反编译源码 | CC0 |
| `ref-th06nc-re/` | 新典逆向笔记与 modkit | MIT |
| `ref-th06nc-re-data/` | 新典符号库 | CC0 1.0 |

上游练习辅助器无 LICENSE，未随本仓库分发；说明见
[选读-参考项目-th06nc-practice.md](项目文档/09-依据/选读-参考项目-th06nc-practice.md)。
