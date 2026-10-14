# Mod build & install

See `../docs/modding.md` for the design and the full hook list, and
`../docs/frame-timing.md` for the frame-rate work.

## Build

```bash
./build.sh                 # needs x86_64-w64-mingw32-gcc
python3 gen_vcruntime.py   # optional: regenerate thunks/def/syms from exports.txt
```

Outputs:

| file | notes |
|---|---|
| `vcruntime140.dll` | **recommended** proxy: all 74 vcruntime140 exports as `.text` thunks |
| `vcruntime140_14.dll` | legacy 14-export C-wrapper variant (unsafe if a native msvcp140 is present) |
| `steam_api64.dll` | legacy Steam-DLL proxy (Steam may restore the original file) |

## Install

```bash
cp vcruntime140.dll        "<game dir>/"
cp th06nc_mod.ini.example  "<game dir>/th06nc_mod.ini"
```

- Windows: no DLL override needed (app-directory DLL wins for non-KnownDLLs).
- Wine/Proton launch option: `WINEDLLOVERRIDES="vcruntime140=n,b" %command%`
- Log: `th06nc_vcmod.log` next to the exe.
- Uninstall: delete `vcruntime140.dll` (and optionally the ini). The real
  `steam_api64.dll` is never touched by this variant.

## Config

```ini
title=東方紅魔郷: New Classic  [MODDED]   ; UTF-8 window title
frame_scale=1.0                          ; diagnostic: multiplies frame waits
target_fps=60                            ; rewrites the hardcoded 60.0 constant
```

`target_fps=144` makes the game run at ~143 fps **and 2.4x too fast** — the
engine is fixed-60-tick. See `../docs/frame-timing.md`.
