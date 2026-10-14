# Engine / binary analysis

Target: `th06nc.exe` (Windows x64 build of 東方紅魔郷: New Classic, v1.03).

## Binary facts

| property | value |
|---|---|
| format | PE32+ (`pei-x86-64`), 6 sections, subsystem 2 (GUI) |
| image base | `0x140000000` |
| `.text` | 2,878,097 bytes (~725k instructions) |
| functions | ~4,367 (`.pdata` unwind entries) |
| entry point | RVA `0x2bd700` |
| PE timestamp | `0x6a9e3a91` → 2026-09-07 04:16 UTC |
| linker | 14.44 (Visual Studio 2022 toolset) |
| runtime | `/MD` — imports `VCRUNTIME140`, `VCRUNTIME140_1`, `MSVCP140`, `api-ms-win-crt-*` |

Static imports (whole list): `steam_api64.dll`, `KERNEL32.dll`, `USER32.dll`,
`ole32.dll`, `MSVCP140.dll`, `VCRUNTIME140_1.dll`, `VCRUNTIME140.dll`, and the
UCRT API-set DLLs. Everything else — D3D11, DXGI, DirectSound, XAudio2, WASAPI,
winmm, dinput8/xinput, Opus — is loaded at runtime via `LoadLibrary` +
`GetProcAddress`, which is also why a `GetProcAddress` hook is the key to
intercepting DxLib's dynamic resolution (see `modding.md`).

## What's inside the binary

The game is a **DxLib** title (the Japanese DX Library, ZUN's engine of
choice). Evidence: thousands of DxLib internal debug strings
(`Graphics_D3D11_Shader_Normal3DDraw_Setup`,
`IDXGIFactory2->CreateSwapChainForHwnd`, `CreateFontToHandle`, TLSF heap dumps,
`DX_FONTTYPE_*`, `MEMIMG`, `Multi Media Timer`, …), plus DxLib's own
Japanese error strings stored as UTF-16.

Statically linked libraries identified by fingerprints:

| library | evidence |
|---|---|
| DxLib (3.2x era) | internal debug strings, D3D9 + D3D11 backends, TLSF allocator |
| libopus / CELT | full source assertion strings (`opus_custom_decoder_ctl(...)`, `st->mode == opus_custom_mode_create(48000, 960, NULL)`) |
| Zstandard | frame magics `0xFD2FB528` and skippable-frame mask `0x184D2A50` |
| MSVC CRT | `/MD` imports, `__CxxFrameHandler4`, standard prologues |

Graphics path: D3D11 via dynamically loaded `d3d11.dll`/`dxgi.dll`
(`D3D11CreateDevice`, `CreateDXGIFactory2`, BC7-sRGB formats, 4K-capable).
Audio: DxLib's WASAPI / XAudio2 / DirectSound / MME stack, with Opus decoding
for the shipped `data/bgm*/*.opus`.
Input: DirectInput (COM, hence the `ole32` imports) + XInput, with WMI
(`\\.\root\cimv2`, `Win32_PNPEntity`, `VID_%4X`/`PID_%4X`) used to identify pads.

Steam: `steam_api64.dll` is imported at load time. The game calls
`SteamAPI_RestartAppIfNecessary(4763590)`; Steam itself tags the window class
`steam_app_4659620`.

## Startup chain

```
0x1402bd700  entry point            (CRT; calls __security_init_cookie, jmps to mainCRTStartup)
0x1402bdd4c  __security_init_cookie
0x1402bd58c  mainCRTStartup
0x1400454f0  wWinMain               (rcx = image base)
```

`wWinMain` initialises the game (config, archives, DxLib), then enters the main
loop at `0x140045c64`. Structure recovered from the disassembly:

```
loop 0x140045c64:
  0x14003c750          window/exit check
  0x1400c98e0(1)       frame bookkeeping
  0x1400b9ba0          input
  0x14007ad30 / 0x1400bcb90
  *0x1402c05f0         SteamAPI_RunCallbacks (IAT)
  <steam overlay vtable call>
  0x14007b120          game logic update (float args)
  0x14003be80          message pump (up to 7 iterations)
  0x14003bf70          draw
  0x14003c330          present + frame limiter   <-- see frame-timing.md
  0x1400c16d0          exit check -> loop
```

## Data files

| file | notes |
|---|---|
| `data/th06{CM,ED,FN,IN,MD,ST,TL}.dat` | custom `PKGL` archives, see `archive-format.md` |
| `data/bgm/`, `data/bgm2/` | Opus BGM, two sets (the `*.pos` loop-point files pair with them) |
| `th06.cfg` | 44-byte binary config (key bindings, flags, player name; default name `DEniZ`) |
| `th06.env` | 12-byte environment/state blob |
| `score.dat` | score database |
| `replay/th6_NN.rpy` | replays, magic `T6RP` + obfuscated one-record-per-frame input stream |

The `T6RP` per-frame input records are the strongest evidence that the game
logic is a fixed 60 Hz tick, which is why frame-rate mods change game speed
(see `frame-timing.md`).
