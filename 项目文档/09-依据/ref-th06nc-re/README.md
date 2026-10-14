# th06nc reverse-engineering notes & modkit

Static-analysis notes, format documentation and a working DLL mod harness for
the Windows build of **東方紅魔郷: New Classic ～ the Embodiment of Scarlet Devil.**
(*Touhou Koumakyou: New Classic*, `th06nc.exe`) — the 2026 remaster of Touhou 6.

Everything here was derived from the binary and the shipped data files only.
No game assets are included in this repository.

---

## TL;DR findings

**It is not Unity.** The Windows build is a native x86-64 MSVC C++ program
(linker 14.44, PE timestamp 2026-09-07) that statically links **DxLib**
(Direct3D 11 backend) and **libopus**, and imports only `steam_api64.dll`,
`KERNEL32`, `USER32`, `ole32` and the MSVC/UCRT runtimes. No `UnityPlayer.dll`,
no `*_Data` folder, no Mono/il2cpp, no CLR.

**Assets live in custom `PKGL` archives** (one per classic data group:
`th06CM/ED/FN/IN/MD/ST/TL.dat`, 1783 members total):

| layer | scheme |
|---|---|
| entry table | XOR with a 16-byte repeating keystream = SplitMix64(seed), seed = `CRC32(dat filename stem)` |
| per-member payload | XOR with SplitMix64 keystream from a per-member 32-bit seed |
| compression | standard **Zstandard** frames (`flag == 1` members) |

All of it is reversible, and `tools/pkgl.py` does it (table listing, full
extraction). The archive layout is the 2002 one, but the media is new:
DDS textures (incl. `_4k`), ANM animations, Opus BGM, JSON/msgpack data and
12 officially localised font sets.

**A working DLL mod harness** is in `mod/`: a `vcruntime140.dll` proxy that
loads before any game code, forwards all 74 vcruntime140 exports to the real
system DLL, and installs hooks + a config file. It was verified on a real
Steam/Proton run (window title mod applied live).

**Frame timing:** the game is a fixed-60-tick engine. The limiter derives its
frame interval from a hardcoded `60.0` double (`interval = freq/60 + 0.5` ms)
and then sleeps in ≤0.95 ms slices until the deadline. Patching that constant
to 144 makes the loop run at ~143 fps — and the **game runs 2.4× fast**,
confirming physics is coupled to the frame counter. Details and the map of the
main loop are in `docs/frame-timing.md`.

---

## Repository layout

```
docs/
  engine.md          binary/engine analysis, entry chain, main loop map
  archive-format.md  PKGL spec (header, table, crypto, zstd), verified examples
  modding.md         DLL proxy harness: design, hooks, RVAs, how to extend
  frame-timing.md    the 60 fps limiter, the 144 fps experiment, why it speeds up
mod/
  mod_core.h                shared hook/patch/renamer machinery
  vcruntime_proxy_full.c    recommended proxy (74 exports, thunks)
  vcruntime_thunks.S        generated thunks (one per export, in .text)
  vcruntime140_full.def     generated export list
  vcruntime_syms.h          generated symbol table
  exports.txt               vcruntime140 export names used by the generator
  gen_vcruntime.py          regenerates the three files above
  vcruntime_proxy.c         legacy 14-export variant (C wrappers)
  proxy.c                   legacy steam_api64.dll proxy variant
  build.sh                  builds everything with mingw-w64
  th06nc_mod.ini.example    config template
tools/
  pkgl.py            PKGL archive reader: list / dump (decrypt + zstd)
  dds2png.py         batch DDS -> PNG converter (Pillow)
```

## Quick start

### Read the game's assets

```bash
# works from the repo dir, the game dir, or with an explicit data path
python3 tools/pkgl.py list            # every archive member + metadata
python3 tools/pkgl.py dump out/       # decrypt + decompress everything (~7 GB)
python3 tools/pkgl.py list /path/to/th06nc/data   # explicit data dir
python3 tools/dds2png.py out/ out_png/ --workers 8
```

### Build and install the mod (Windows / Wine / Proton)

```bash
cd mod && ./build.sh              # needs x86_64-w64-mingw32-gcc
cp vcruntime140.dll "<game dir>/"
cp th06nc_mod.ini.example "<game dir>/th06nc_mod.ini"
```

- Windows: nothing else needed (app-directory DLL wins for non-KnownDLLs).
- Wine/Proton: add the launch option `WINEDLLOVERRIDES="vcruntime140=n,b" %command%`
- Log lands next to the exe as `th06nc_vcmod.log`.
- Uninstall: delete `vcruntime140.dll` (and the ini).

Config keys (`th06nc_mod.ini`):

```ini
title=東方紅魔郷: New Classic  [MODDED]   ; window title (UTF-8)
frame_scale=1.0                          ; multiplies every DxLib frame wait
target_fps=60                            ; rewrites the hardcoded 60.0 constant
```

`target_fps=144` demonstrably raises the frame rate to ~143 — but the game
logic runs 2.4× fast, because the engine advances one tick per frame. Read
`docs/frame-timing.md` before using it.

---

## Method notes (what worked)

- **String and constant sweeps beat reading code linearly.** Library
  fingerprints (DxLib debug strings, libopus CELT assertions, the zstd frame
  magics `0xFD2FB528` / `0x184D2A5x`) identified most of the 2.9 MB `.text`
  without disassembling it.
- **Crypto constants give away the scheme**: SplitMix64 avalanche constants
  (`0x9e3779b97f4a7c15`, `0xbf58476d1ce4e5b9`, `0x94d049bb133111eb`), the
  golden-ratio seed (`0x9e3779b1`), CRC32 table poly `0xEDB88320`, FNV-1a
  `0xcbf29ce484222325`.
- **Verify every claim against the data.** The archive format was accepted only
  after every table parsed cleanly and known members decrypted to known text
  (`ver0102.dat` → *"This Game is Curtain Fire Shooting Game by Shrine
  Maiden."*).
- **Instrument, don't guess.** The frame-rate conclusion came from the game's
  own log lines (`frame timer: N waits/sec, last wait X ms`), not from theory.

## Legal

Tooling and documentation only. The `.dat` archives, textures, music and all
other game content remain the property of their rights holders — extract and
modify only your own legally purchased copy, for personal use. No copyrighted
assets are committed here.
