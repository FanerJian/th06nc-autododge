# `PKGL` archive format

The seven `data/th06*.dat` files are custom archives. Format recovered from
`th06nc.exe` (loader at RVA `0x59fb0`, member reader at `0x5a470`, keystream
generator at `0x59cb0`, basename CRC at `0x59e20`) and verified against the
shipped files.

## File layout

```
offset 0   'PKGL'                       4 bytes, plaintext
offset 4   u32 LE  table_size           size of the entry table in bytes
offset 8   entry table                  XOR-encrypted (see below)
offset 8+table_size                      payload area (member data, encrypted/zstd)
```

## Entry table decryption

The table is XORed with a 16-byte repeating keystream derived from

```
seed32 = CRC32(basename_stem)           # e.g. "th06CM" for data/th06CM.dat
```

with a SplitMix64-style generator (constants taken straight from the binary):

```
st = ((seed32 * 0x9E3779B1 + 1) ^ (seed32 << 32)) + 0x9E3779B97F4A7C15
ks = avalanche(st) || avalanche(st + 0x9E3779B97F4A7C15)      # 16 bytes

avalanche(x):
    x ^= x >> 30
    x *= 0xBF58476D1CE4E5B9
    x ^= x >> 27
    x *= 0x94D049BB133111EB
    return x ^ (x >> 31)

table[i] ^= ks[i & 15]
```

## Entry records

Parsed from the decrypted table, all little-endian:

```
u16 flag         0 = payload stored raw after XOR
                 1 = payload is a zstd frame after XOR
u32 xkey         per-member XOR seed
u64 real_size    size after decompression
u64 stored_size  bytes on disk
u64 offset       absolute file offset of the payload
u16 name_len     < 256
u8  name[name_len]  ASCII, no directory prefix (e.g. "eff00.dds")
```

Records are contiguous; parsing ends exactly at `table_size`.

## Payload decryption

```
ks = SplitMix64 keystream(xkey)          # same generator, seed = xkey
payload[i] ^= ks[i & 15]

if flag == 1:
    data = zstd_decompress(payload, real_size)
```

`flag == 0` payloads are the final file bytes; `flag == 1` are standard
Zstandard frames (`28 b5 2f fd` magic) that inflate to `real_size`.

## Verified examples

| archive / member | result |
|---|---|
| `th06MD/ver0102.dat` | `This Game is Curtain Fire Shooting Game by Shrine Maiden.\nZUN` (raw) |
| `th06MD/musiccmt.txt` | Shift-JIS text (raw) |
| `th06MD/th06_01.pos` | 8 bytes: two u32 loop points (raw) |
| `th06IN/ascii.dds` | zstd → 262,292 bytes, magic `DDS ` |
| `th06CM/eff00.dds` | zstd → 1,048,704 bytes, magic `DDS ` |
| `th06ST/ecldata1.ecl` | zstd → 26,936 bytes (ECL script) |

Every table in every archive parses to exactly `table_size`, which is the
strongest correctness check available.

## Contents overview (1,783 members)

| archive | count | contents |
|---|---|---|
| `th06CM` | 311 | player sprites, bullets (`etama*`), effects, HUD frames, shared faces |
| `th06ED` | 93 | ending/staff scripts (`*.end`) + CG |
| `th06FN` | 476 | font glyph atlases + JSON metrics, one set per locale |
| `th06IN` | 96 | sound effects, UI fonts (`ascii.anm`), `localization.msgpack`, `spellpractice.msgpack` |
| `th06MD` | 38 | `musiccmt.txt`, 36 `*.pos` BGM loop-point files |
| `th06ST` | 169 | `stage*.std`, `ecldata*.ecl`, `msg1..7.dat`, enemy sprites, portraits |
| `th06TL` | 600 | title/menu art incl. 4K variants and 12 localised sets |

Every archive also contains a `ver0102.dat` member — a fossil of the 2002
layout.

## Tools

```bash
python3 tools/pkgl.py list          # print every member + metadata
python3 tools/pkgl.py dump out/     # decrypt + decompress everything
python3 tools/dds2png.py out/ png/  # batch convert textures
```

`pkgl.py` needs `zstandard` (`pip install zstandard`) for `flag == 1`
members; `dds2png.py` needs Pillow.

## Repacking

The format is symmetric and fully documented above, so a packer is
straightforward: rebuild the table (any `xkey` works), encrypt it with the
CRC32-of-stem keystream, encrypt payloads with their own keystream, and
zstd-compress members that should carry `flag = 1`. This is left as an
exercise — it is the natural next step for asset mods.
