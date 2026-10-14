# 选读-参考项目-th06nc-practice.md —— 地址来源与可复用内容

> 【选读】追溯本项目内存地址的出处时读。**只读，不要改。**

## 1. 来源

- 仓库：`https://github.com/sky1641/th06nc-practice`
- 发现路径：B 站视频「新典多功能辅助器效果演示」(BV1oDYo6gEsq) 简介中的下载地址
- 性质：第三方开源 Windows x64 练习辅助，C# / .NET 9，作者自述由 AI 协助开发
- 本地位置：`项目文档/09-依据/ref-th06nc-practice/`（`git clone --depth 1`）

## 2. 它做什么

残机 / 炸弹 / 火力自定义、游戏内变速、弹幕透明度、无敌、敌方时停、和平模式（无弹幕）。
**它不提供自动躲避** —— 躲避算法仍需本项目自己实现。

## 3. 从它提取到的信息（本项目已实测复核）

### 3.1 全局 RVA（源：`src/MemorySession.cs`）

```
LivesRva  = 0x4FF0F0    BombsRva = 0x4FF0F1    PowerRva = 0x4F1E88
CollisionRva = 0x6A980  PatchRva = 0x6AA9D     SignatureRva = 0x6AA97
LaserCollisionRva = 0x6ABA0  LaserPatchRva = 0x6ACF2
支持的游戏 SHA256 = 07850C8C6E469C0E82C13423E6D0D096A88D693455BDACACBB44C0AA3BCCE473
```

### 3.2 内部常量（源：`src/ModeCode.cs`）

```
Player = 0x4FF3A0     Scene = 0xC21D9C     Input = 0xA6EC60
Gui = 0xA6EC08        NativeTime = 0x4F27B9
```

由此推出并**本机实测确认**：自机 `x = 0x506AD0`、`y = 0x506AD4`（即 `Player + 0x7730/0x7734`）。

### 3.3 子弹池结构（源：ModeCode 的"和平模式"清空循环）

```asm
LEA RDX,[RCX+0x4C] ; MOV EAX,0x280 ; loop { MOV WORD[RDX],0 ; ADD RDX,0x620 ; DEC EAX }
LEA RDX,[RCX+0xF528C] ; MOV EAX,0x40 ; loop { MOV BYTE[RDX],0 ; ADD RDX,0x298 ; DEC EAX }
```

推出：子弹 640 槽 × stride `0x620`；激光 64 槽 × stride `0x298`。
**本项目的槽内字段偏移（x@+0x30、y@+0x34 等）是自己反汇编 `0x10F00` / `0x1140D` 得到的。**

### 3.4 挂钩点清单（源：`ModeCode.Sites`）

`0x6882D` player、`0x1087F` bullets、`0x373B0` enemy、`0xF870` spawn、
`0x10850` laser、`0x6A980` contact、`0x6ABA0` contact、`0x689DE` bomb、
`0x69774` shots、`0x69B98` fire、`0x3CC56` guiTime、`0x77BC7`/`0x76310` time 等。

本项目**不使用 hook**，仅将其作为反汇编的入口线索。

## 4. 注意

- 它是**注入式**方案（`VirtualAllocEx` + 代码洞穴 + 远程线程冻结），本项目不采用。
- 它校验游戏文件 SHA256，版本不匹配即拒绝运行；本项目无此限制但要自行验证地址。
- 上表地址只对该版本游戏有效；Steam 更新后需重新核对。
