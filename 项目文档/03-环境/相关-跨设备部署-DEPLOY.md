# 相关-跨设备部署-DEPLOY.md —— 换台电脑 / 游戏更新后怎么跑起来

> 【相关】在新设备上部署、或自检报错时读。**一句话职责**：拷什么、装什么、探测什么、坏了看哪里。

## 什么时候需要读取

- 在第二台电脑上部署
- `py tools\launcher.pyw --check` 报错或报警告
- 换了 Steam 库位置 / 游戏安装目录 / **游戏更新过**

## 部署三步

1. **拷仓库**：整目录拷过去即可；`项目文档/09-依据/` 可省（只有解包与地址查证要用）。
2. **装环境**：Python ≥ 3.8（安装时勾 tcl/tk）→ `py -3 -m pip install -r requirements.txt`。
   反汇编类诊断工具另需 `capstone`（见 `requirements.txt` 注释）。
3. **自检**：`py tools\launcher.pyw --check` 全 ✓ 后，双击 `tools\launcher.pyw` 或桌面快捷方式。

游戏本体需在新设备自行安装：Steam AppID **4659620**。

## 游戏更新后怎么办（一条命令）

```powershell
py tools\autofix.py          # 自动重定位全部全局地址 → 写 tools/addr_cache.json
```

- 纯静态（读 exe 里的特征），**不需要游戏在关卡内**，一次约一分钟。
- **源码一行不用改**：`tools/addr.py` 在 import `offsets.py` 时套用新地址。
- launcher 检测到构建变了会自己跑这一步，所以日常只需双击启动器。
- 原理：**结构内偏移 / 池 stride / 槽数从不随更新变**，只有全局变量位置会动；
  按位移分档（`+0x43260` / `+0x4AC50` / `+0x4C220`）+ 反汇编指纹
  （`inc byte [rip+X]` = 帧计数、switch 跳转表 = curState）重新定位。

## 打发布包（给别人用，不用装 Python）

```powershell
py -3 -m venv --system-site-packages _tmp\buildenv
_tmp\buildenv\Scripts\python.exe -m pip install pyinstaller
powershell -ExecutionPolicy Bypass -File tools\build_release.ps1 `
    -PythonExe _tmp\buildenv\Scripts\python.exe -Version 0.1.0
```

产物在 `dist\v0.1.0\`：文件夹版 zip（约 24 MB）+ `SHA256SUMS.txt`。
脚本自己会用 exe 跑一次 `--check` 冒烟，失败即中止（不产出 zip）。

打包版与源码版的差别（改代码时必须知道）：

| 项 | 源码版 | 打包版 |
|---|---|---|
| 可写数据 | 项目根 / `tools/` | **exe 旁**：`dodge_params.json`、`addr_cache.json`、`launcher.log`、`autofix.log` |
| 地址缓存读 | `tools/addr_cache.json` | exe 旁的副本优先，回退包内 `_internal/tools/addr_cache.json` |
| 地址缓存写 | `tools/addr_cache.json` | exe 旁的副本 |
| 自动重定位 | `py tools\autofix.py` | `exe --run autofix`（内部子命令） |
| 路径规则 | 全部由 `tools/paths.py` 决定 —— 别在别处写 `dirname(__file__)` | 同左 |

发布渠道（正式包在本机打，需装有游戏才能提取图标）：

```powershell
powershell -File tools\build_release.ps1 -Version 0.1.0
gh release create v0.1.0 dist\v0.1.0\*.zip dist\v0.1.0\SHA256SUMS.txt
```

`.github/workflows/release.yml` 在推 `v*` tag 或手动触发时只做构建验证（产物走
Actions artifact）：托管运行器没有游戏本体，打出来的包不带图标，不作为发布件。

## 自动探测规则（`tools/env.py` + `tools/addr.py` 实现）

| 目标 | 探测顺序 | 全失败时 |
|---|---|---|
| Steam | `TH06NC_STEAM` → 注册表 HKCU/HKLM → 常见安装路径 | 手动启动游戏；只要游戏在跑，读内存不需要 Steam |
| 游戏目录 | `TH06NC_DIR` → 运行中进程的 exe 路径 → Steam 库扫描（`libraryfolders.vdf`） | 设 `TH06NC_DIR` |
| 游戏构建 | exe MD5 → 查 `tools/addr_cache.json` 有无该构建的地址 | 没有 = 地址失效 → 跑 `py tools\autofix.py` |

覆盖方式：

```powershell
$env:TH06NC_STEAM='D:\steam\steam.exe'
$env:TH06NC_DIR='D:\steam\steamapps\common\th06nc'
```

## 不随设备变的东西（别去改）

- 逻辑坐标 `x∈[8,376]`、`y∈[16,432]`：与分辨率、窗口模式无关。
- 进程名 `th06nc.exe`、窗口标题含 `Embodiment`：由游戏本体决定。
- 结构内偏移 / 池 stride / 槽数：只跟**游戏构建**绑定，与设备无关。
  全局变量 RVA 虽随构建变，但已由 `addr_cache.json` 按构建自动套用，不用手改。

## 常见问题

- **换设备或更新后读不到内存**：先看自检的「地址适配状态」，报「未适配」就跑
  `py tools\autofix.py`。参考符号库 `ref-th06nc-re-data` 只对基线构建有效，但结构偏移不变，照旧能用。
- **自检说找不到游戏目录**：游戏没运行、且 Steam 库里没有 → 设 `TH06NC_DIR`。
- **`py` 跑第三方脚本无输出**：改用 `py -3`（见 `01-规范/必读-动手前的坑-PITFALLS.md`）。
- **权限**：脚本要与游戏同权限运行；游戏若以管理员启动，脚本也要。

## 相关文档

- 环境与入口 → `00-入口/必读-项目现状-CONTEXT.md` §2
- 工具清单 → `01-规范/必读-结构与组成-STRUCTURE.md` §2
- 坑 → `01-规范/必读-动手前的坑-PITFALLS.md`
