# 相关-现成方案调研-SURVEY.md —— 网络可用方案盘点

> 【相关】开工前判断"是否已有现成方案"时读。
> **结论：无成品可直接用于新典；但两套符号资产已当场解除子弹池阻塞点。**

## 1. 结论一览

| 需求 | 网络现成方案 | 可用性 |
|---|---|---|
| 新典自动避弹成品 | **不存在** | ✗ 无任何仓库/工具实现 |
| 新典内存符号 | `Renko6626/th06nc-re-data` | **★★★ 直接可用**，MD5 与本机一致 |
| 子弹/玩家结构定义 | `GensokyoClub/th06` 反编译 | **★★★ 结构对照源**，CC0 |
| 现成避弹算法 | `Netdex/twinject` | ✗ 不支持 th06；思路可借鉴 |
| 内存修改器 | CE 表 / 一修大师 / 七项修改器 | ✗ 只有残机炸弹火力，无子弹指针 |
| **游戏资源解包** | 本机第三方 `ref-th06nc-re/tools/pkgl.py` + 本项目 `tools/unpack_assets.py` | **★★★ 已跑通**，1783 个成员可解 |
| ECL 弹幕脚本反编译 | `thpatch/thtk`（`thecl`） | ★★ 格式与原版同源，本项目尚未引入 |

## 2. 决定性资产

### 2.1 `Renko6626/th06nc-re-data` —— 新典专属符号库

- 内容：36 函数 + 18 全局 + 142 代码标签 + 183 条注释（JSON）。
- 样本 MD5 `b0cc28ec904e9efce2439ad857c938b5` **与本机 exe 完全一致** → 地址直接有效。
- 本地副本：`ref-th06nc-re-data/`（56 KB）。
- **作者自述由 AI 逆向 agent 自动生成，可能有误导** → 关键地址须自行复核。
  本项目已用 capstone 反汇编 + 运行时读值复核 `g_BulletManager` 与子弹布局，结论一致。

### 2.2 `GensokyoClub/th06` —— 原版 1.02h 反编译

- 590★，CC0-1.0，仍在更新；含 `BulletManager.hpp/cpp`、`Player.hpp` 等完整 C++ 源码。
- 本地副本：`ref-th06-decomp/src/`（1.07 MB）。
- **已验证新典与原版源码级同构**，可直接拿原版结构推断新典：
  - ECL opcode 1..135 实现集完全一致；ANM opcode 0..31 一致（新典扩到 35）。
  - `Player` 数值一致：判定半径 `1.25`、生成点 `(192, 384, 0.49)`、抓取范围 `(12,12,5)`。
- 用法：新典未知字段先查原版同名结构，再按 x64 尺寸变化核对。

### 2.3 资源解包（本机已跑通）

- 工具：第三方只读 `ref-th06nc-re/tools/pkgl.py`（格式与解密）+ 本项目 `tools/unpack_assets.py`（筛子集落盘）。
- 格式：`PKGL` = 成员表 `XOR(SplitMix64(CRC32(档案名)))` + 成员 `XOR(keystream(xkey))` + 可选 zstd → `ref-th06nc-re/docs/archive-format.md`。
- 实测：7 个 `data/th06*.dat` 共 **1783 个成员**；关键子集（ECL/ANM/文本，不含 DDS）= **530 个 / 7.68 MB / 1.1 秒** → `_tmp/unpacked/`。
- 校验：`th06MD/ver0102.dat` 解出 ASCII 原文；`ecldata1.ecl` = 26,936 B，与格式文档记录一致。
- 依赖：`py -3 -m pip install zstandard`（`flag=1` 成员是 zstd 帧）。
- 命令：`py -3 tools\unpack_assets.py --out _tmp\unpacked`（`--list` 只列名，`--all` 含 4K 纹理）。
- **ECL 反编译**：`ecldata1-7.ecl` 与原版同源，可用 [thpatch/thtk](https://github.com/thpatch/thtk) 的 `thecl`；本项目尚未引入。
- 网上**没有**已解包好的成品资源。搜到的 xmodhub「Scarlet Engine」一文是 SEO 推广页且事实错误（称无解包工具、音频为 `.fsb/.pck`），**不要引用**。

## 3. 不可用方案与原因

| 方案 | 为什么不能用 |
|---|---|
| `Netdex/twinject` | `th06_player::getPlayerEntity()` 是 `// TODO no implementation` 空壳；且为 x86 注入式（DLL + trampoline），本项目不注入。**算法可借鉴**：`twinhook/algo/th_vo_algo.cpp`（速度障碍法）、`th_vector_algo.cpp`、`model/`（AABB/圆/OBB 碰撞模型）|
| `Netdex/TouhouCV` | 图像识别取坐标，精度不足以判定 1.25 半径的判定点 |
| CE 表（Korados）/ fearlessrevolution | 只有"玩家编辑器"（残机/炸弹/火力），无子弹数组指针；站点有 Cloudflare，web_fetch 返回 403 |
| 一修大师 / 七项修改器 / `thprac` | 常规修改与练习工具，均无自动避弹 |
| `creeperkafasi/th06nc-re` | 代码是代理 DLL 注入路线，本项目不采用；但**引擎/文件格式笔记有价值**（DxLib 引擎、60 Hz tick、`T6RP` replay 结构、PKGL 档案格式），本地副本 `ref-th06nc-re/` |

## 4. 网络获取方式（本机实测）

- `github.com` 与 `raw.githubusercontent.com` **直连超时**，勿用浏览器式抓取。
- 可用：`api.github.com`、`codeload.github.com`。

```powershell
# 下载整仓（最快，推荐）
Invoke-WebRequest 'https://codeload.github.com/<owner>/<repo>/zip/refs/heads/<branch>' -OutFile repo.zip
# 取单文件
$h = @{'User-Agent'='dsh'; 'Accept'='application/vnd.github.raw'}
Invoke-WebRequest 'https://api.github.com/repos/<owner>/<repo>/contents/<path>' -Headers $h -OutFile file
# 仓库搜索
Invoke-RestMethod 'https://api.github.com/search/repositories?q=<kw>&sort=stars'
```

## 5. 相关文档

- 权威地址表 → `02-内存布局/相关-游戏内存映射-MEMMAP.md`
- 参考项目来源 → `09-依据/选读-参考项目-th06nc-practice.md`
