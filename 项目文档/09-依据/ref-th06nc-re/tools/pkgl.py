#!/usr/bin/env python3
"""
pkgl.py -- reader for the "PKGL" asset archives of
    Touhou Koumakyou (EoSD): New Classic / th06nc

Format facts recovered by static analysis of th06nc.exe
(see the session report for the full disassembly trail):

* File layout
    offset 0  : 'PKGL'                      (4 bytes, plaintext)
    offset 4  : u32 LE  = size of the entry table in bytes
    offset 8  : entry table, XOR-encrypted with a 16-byte repeating
                keystream derived from  seed = CRC32(basename-stem of
                the .dat file, e.g. "th06CM") as follows:

                splitmix64 seeding  (recovered at 0x140059cb0):
                  s   = seed & 0xFFFFFFFF
                  st  = ((s * 0x9E3779B1 + 1) ^ (s << 32))
                        + 0x9E3779B97F4A7C15
                  ks  = splitmix_avalanche(st)
                        || splitmix_avalanche(st + 0x9E3779B97F4A7C15)
                ciphertext[i] ^= ks[i % 16]

* Entry table (plaintext after the XOR):
    records of:  u16 flag        (0 = payload stored raw after XOR,
                                   1 = payload is a custom-compressed
                                       container after XOR)
                 u32 xkey        (per-member XOR seed)
                 u64 real_size   (size after decompression)
                 u64 stored_size (bytes on disk)
                 u64 file_offset (absolute offset in the .dat)
                 u16 name_len    (< 256)
                 name (name_len bytes, ASCII)

* Payload:  payload XOR keystream(seed = xkey)  -- same SplitMix64
    scheme.  For flag==0 that is the final file content.  For flag==1
    the payload is additionally compressed as a standard Zstandard
    (zstd) frame (magic 0xFD2FB528, or 0x184D2A5x skippable frames),
    decompressed to real_size bytes.

    Verified examples:  th06MD/ver0102.dat is raw plaintext after XOR
    ("This Game is Curtain Fire Shooting..."), musiccmt.txt decodes to
    Shift-JIS text; ascii.dds / eff00.dds decompress to genuine DDS
    textures ("DDS " magic) of the recorded real_size.

Usage:
    python3 pkgl.py list
    python3 pkgl.py dump OUTDIR      # full decrypt + zstd decompress
"""

import os
import struct
import sys
import zlib

DAT_STEMS = ["th06CM", "th06ED", "th06FN", "th06IN", "th06MD", "th06ST", "th06TL"]

# ---- SplitMix64 avalanche step (as recovered from the disassembly) ----
def _avalanche(x):
    x ^= x >> 30
    x = (x * 0xBF58476D1CE4E5B9) & 0xFFFFFFFFFFFFFFFF
    x ^= x >> 27
    x = (x * 0x94D049BB133111EB) & 0xFFFFFFFFFFFFFFFF
    return x ^ (x >> 31)


def keystream(seed32):
    """16-byte repeating-XOR keystream for a given 32-bit seed."""
    s = seed32 & 0xFFFFFFFF
    st = ((s * 0x9E3779B1 + 1) ^ (s << 32)) & 0xFFFFFFFFFFFFFFFF
    st = (st + 0x9E3779B97F4A7C15) & 0xFFFFFFFFFFFFFFFF
    return (
        _avalanche(st).to_bytes(8, "little")
        + _avalanche((st + 0x9E3779B97F4A7C15) & 0xFFFFFFFFFFFFFFFF).to_bytes(8, "little")
    )


def xor_bytes(buf, k16, start=0):
    return bytes(b ^ k16[(start + i) & 15] for i, b in enumerate(buf))


class PkglEntry:
    __slots__ = ("flag", "xkey", "real", "stored", "offset", "name")

    def __init__(self, flag, xkey, real, stored, offset, name):
        self.flag = flag
        self.xkey = xkey
        self.real = real
        self.stored = stored
        self.offset = offset
        self.name = name

    def __repr__(self):
        return (
            f"flag={self.flag} xkey=0x{self.xkey:08x} real={self.real} "
            f"stored={self.stored} off={self.offset} name={self.name!r}"
        )


class Pkgl:
    def __init__(self, path):
        with open(path, "rb") as f:
            self.blob = f.read()
        if self.blob[:4] != b"PKGL":
            raise ValueError(f"{path}: bad magic")
        self.path = path
        self.stem = os.path.splitext(os.path.basename(path))[0]
        self.table_size = struct.unpack_from("<I", self.blob, 4)[0]
        tkey = keystream(zlib.crc32(self.stem.encode("ascii")))
        table = xor_bytes(self.blob[8:8 + self.table_size], tkey)
        self.entries = []
        off = 0
        while off + 32 <= len(table):
            flag, xkey, real, stored, foff, nlen = struct.unpack_from(
                "<HIQQQH", table, off
            )
            name = table[off + 32:off + 32 + nlen].decode("ascii", "replace")
            self.entries.append(PkglEntry(flag, xkey, real, stored, foff, name))
            off += 32 + nlen
        if off != len(table):
            print(f"warning: {self.stem}: parsed {off} of {len(table)} table bytes")

    def raw_payload(self, e):
        return self.blob[e.offset:e.offset + e.stored]

    def decrypted_payload(self, e):
        """XOR layer removed; flag==1 payloads are still zstd frames."""
        return xor_bytes(self.raw_payload(e), keystream(e.xkey))

    def final_payload(self, e):
        """Fully decoded member content (zstd decompressed when needed)."""
        data = self.decrypted_payload(e)
        if e.flag == 1:
            try:
                import zstandard
            except ImportError:
                raise RuntimeError(
                    "flag==1 member is zstd-compressed; install python zstandard"
                )
            out = zstandard.ZstdDecompressor().decompress(
                data, max_output_size=max(e.real, 1)
            )
            if len(out) != e.real:
                raise ValueError(
                    f"{e.name}: decompressed {len(out)} bytes, expected {e.real}"
                )
            return out
        return data

    def __len__(self):
        return len(self.entries)

    def __getitem__(self, name):
        for e in self.entries:
            if e.name == name:
                return e
        raise KeyError(name)


def find_data_dir(explicit=None):
    """Locate the game's data/ directory: explicit arg, cwd, or ../data."""
    here = os.path.dirname(os.path.abspath(__file__))
    candidates = []
    if explicit:
        candidates.append(explicit)
    candidates += [
        os.path.join(os.getcwd(), "data"),
        os.path.join(here, "..", "data"),        # game dir/tools -> game dir/data
        os.path.join(here, "..", "..", "data"),  # repo/tools -> game dir/data
        os.path.join(here, "data"),
    ]
    for c in candidates:
        if os.path.isfile(os.path.join(c, "th06CM.dat")):
            return c
    raise SystemExit(
        "could not find data/ (expected th06CM.dat). Run from the game "
        "directory or pass the data dir as the last argument."
    )


def load_all(data_dir=None):
    d = find_data_dir(data_dir)
    out = {}
    for stem in DAT_STEMS:
        p = os.path.join(d, stem + ".dat")
        out[stem] = Pkgl(p)
    return out


def cmd_list(data_dir=None):
    for stem, arc in load_all(data_dir).items():
        print(f"== {stem}.dat  ({len(arc)} entries)")
        for e in arc.entries:
            print("   ", e)


def cmd_dump(outdir, data_dir=None):
    os.makedirs(outdir, exist_ok=True)
    total = 0
    for stem, arc in load_all(data_dir).items():
        sub = os.path.join(outdir, stem)
        os.makedirs(sub, exist_ok=True)
        for e in arc.entries:
            data = arc.final_payload(e)
            with open(os.path.join(sub, e.name), "wb") as f:
                f.write(data)
            total += 1
            print(f"{stem}/{e.name}  ({len(data)} bytes)")
    print(f"\nwrote {total} files under {outdir}")


if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in ("list", "dump"):
        print(__doc__)
        sys.exit(1)
    if sys.argv[1] == "list":
        cmd_list(sys.argv[2] if len(sys.argv) > 2 else None)
    else:
        cmd_dump(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None)
