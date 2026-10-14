#!/usr/bin/env bash
# Build the th06nc mod proxies with mingw-w64.
#
#   ./build.sh              build vcruntime140.dll (recommended) + legacy variants
#   ./build.sh clean        remove build outputs
set -euo pipefail

CC=${CC:-x86_64-w64-mingw32-gcc}
CFLAGS="-O2 -shared -Wl,--exclude-all-symbols"

build() {
    local out=$1; shift
    echo "==> $out"
    "$CC" $CFLAGS -o "$out" "$@"
}

clean() {
    rm -f vcruntime140.dll vcruntime140_fake.dll steam_api64.dll
    rm -f vcruntime140_14.dll
    echo "cleaned"
}

case "${1:-build}" in
    clean) clean; exit 0 ;;
    build) ;;
    *) echo "usage: $0 [build|clean]"; exit 1 ;;
esac

# recommended: complete export table (74 thunks), no Steam dependency
build vcruntime140.dll vcruntime_proxy_full.c vcruntime_thunks.S vcruntime140_full.def

# legacy: 14 hand-written C wrappers (worked on Wine, unsafe if a native
# msvcp140 is present because the export table is short)
build vcruntime140_14.dll vcruntime_proxy.c vcruntime140.def

# legacy: steam_api64.dll proxy (can be restored by Steam verify/update)
build steam_api64.dll proxy.c steam_api64.def

echo
echo "done. install:"
echo "  cp vcruntime140.dll <game dir>/"
echo "  cp th06nc_mod.ini.example <game dir>/th06nc_mod.ini"
echo "  Wine/Proton launch option: WINEDLLOVERRIDES=\"vcruntime140=n,b\" %command%"
