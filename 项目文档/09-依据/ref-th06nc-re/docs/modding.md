# Modding: the DLL proxy harness

`th06nc.exe` imports `VCRUNTIME140.dll` statically, so a proxy DLL with that
name is mapped **before any game code runs** — no injector, no Steam DRM
involvement, and (unlike `steam_api64.dll`) Steam does not manage the file.

## Why not proxy `steam_api64.dll`

It works, and the variant is kept in `mod/proxy.c` (it also lets the game start
outside Steam by forcing `SteamAPI_RestartAppIfNecessary` to false). But Steam
can restore or replace that DLL on verify/update, which silently disables the
mod. `vcruntime140.dll` has neither problem.

## The complete-export requirement

`msvcp140.dll` (and other modules in the process) also import from
`vcruntime140`, so a short export table can break process startup with
`c0000005`. The proxy therefore exports **all 74** vcruntime140 functions, each
as a one-instruction thunk in `.text`:

```asm
    .text
    .globl t_memcpy
t_memcpy:
    jmp *rp_memcpy(%rip)
    .data
    .globl rp_memcpy
rp_memcpy:
    .quad 0
```

At load time `DllMain` resolves every pointer from
`C:\Windows\System32\vcruntime140.dll` and verifies each target is executable.

> **Gotcha that cost an hour:** the generator must emit `.text` before *every*
> thunk. Emitting it once put 73 of 74 thunks in `.data`; calling them was a
> DEP fault, which Wine reported as `MSVCP140.dll failed to initialize`.
> `gen_vcruntime.py` now does it correctly, and the proxy checks protections at
> runtime.

## Hooks installed

| hook | purpose |
|---|---|
| `kernel32!GetProcAddress` | catches DxLib's *dynamic* user32/winmm resolution |
| `user32!MessageBoxA` | logs dialogs |
| `SetWindowTextW` (via the GPA hook) | forces a custom window title |
| `kernel32!SetWaitableTimerEx` | frame-wait instrumentation + `frame_scale` |
| `kernel32!CreateWaitableTimerExW` | logs timer flags (high-res = 0x2) |
| `kernel32!WaitForSingleObject` | wait-rate instrumentation |
| `kernel32!SleepConditionVariableSRW` | wait-rate instrumentation |
| `kernel32!QueryPerformanceCounter` | call-rate instrumentation |
| `timeSetEvent` (via the GPA hook) | MME-timer path instrumentation |

Plus a **polling renamer** thread: every 250 ms it finds the first visible
top-level window owned by the game process and sets the title directly. This
does not depend on hook timing, which is what made the title mod work reliably
in the end.

## Configuration

`th06nc_mod.ini` next to the exe:

```ini
title=東方紅魔郷: New Classic  [MODDED]
frame_scale=1.0
target_fps=60
```

- `title` — UTF-8 window title.
- `frame_scale` — multiplies every `SetWaitableTimerEx` due time/period
  (diagnostic; see `frame-timing.md`).
- `target_fps` — rewrites the hardcoded `60.0` frame-rate constant at RVA
  `0x30ce38` before DxLib initialises. Raises the frame rate **and game
  speed**; see `frame-timing.md`.

## Recovered RVAs useful for further work

| RVA | what |
|---|---|
| `0x2bd700` | entry point |
| `0x454f0` | `wWinMain` |
| `0x45c64` | main loop |
| `0x7b120` | game logic update (called once per frame) |
| `0x3bf70` | draw |
| `0x3c330` | present + frame limiter |
| `0x3be80` | message pump |
| `0x3c290` | DxLib high-resolution sleep (waitable timer) |
| `0x3c750` | window/exit check |
| `0xb04b0` | `GetNowCount` (ms clock) |
| `0xb04f0` | timer frequency getter (1000) |
| `0x59fb0` | `OpenPkglArchive` |
| `0x5a470` | `LoadPkglMember` |
| `0x59cb0` | keystream generator (SplitMix64 XOR) |
| `0x59e20` | basename → CRC32 (archive seed) |
| `0x61c80` / `0x62700` | zstd decompressor context / driver |
| `0x7b360` | archive registry / open by path |
| `0x30ce38` | `60.0` frame-rate constant (one reference: `0x3cb85`) |

## Extending the mod

Add code to `ensure`-style startup in `mod_core.h` (`mod_start`) — it runs once,
inside the game process, before `wWinMain`. Typical additions:

- signature scans + `VirtualProtect` patches (the code-write path is already
  proven by the self-check at RVA `0x5a470`),
- more IAT hooks (all imports are in the game's import directory; helper
  `find_iat_slot` is provided),
- inline hooks for functions reached through function-pointer tables (e.g. the
  DxLib timer table at `0x140c220e0/e8/f0`).

## Build

```bash
./build.sh          # mingw-w64; produces vcruntime140.dll
python3 gen_vcruntime.py   # regenerate thunks/def/syms from exports.txt
```

## Verified runs

Wine (this project): proxy loads, forwards 71–74/74 symbols, self-check
matches, hooks install, polling renamer applies the title.
Real Steam/Proton run: window `steam_app_4659620` came up with the original
title and ended up as `東方紅魔郷: New Classic  [MODDED]`.
