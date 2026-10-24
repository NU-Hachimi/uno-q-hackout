#!/bin/sh
# Render frames on the desktop with the MCU renderer and save PNGs to build/preview/ (run from arcade/).
#   sh tests/cpp/render_preview.sh [seconds ...]   demo orbit frames -> build/preview/t<seconds>.png
#   sh tests/cpp/render_preview.sh --snapshots     scene + frames from tools/snapshot.py (the real
#                                                  Python game code) -> build/preview/<name>.png
set -eu
cd "$(dirname "$0")/../.."
mkdir -p build/preview
g++ -std=gnu++17 -O2 -w ${CXXFLAGS:-} -I sketch \
    tests/cpp/render_preview.cpp sketch/g3d_proto.cpp sketch/scene.cpp sketch/render.cpp sketch/rig.cpp sketch/hud.cpp \
    sketch/src/tgx/*.cpp -o build/preview/render_preview

to_png() {
    python3 - "$1" "$2" <<'EOF'
import struct, sys, zlib
data = open(sys.argv[1], "rb").read()
header, _, rest = data.partition(b"\n255\n")
w, h = map(int, header.split()[1:3])
rows = b"".join(b"\0" + rest[y * w * 3:(y + 1) * w * 3] for y in range(h))
chunk = lambda t, d: struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d))
png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
open(sys.argv[2], "wb").write(png + chunk(b"IDAT", zlib.compress(rows, 6)) + chunk(b"IEND", b""))
EOF
    rm "$1"
}

if [ "${1:-}" = "--snapshots" ]; then
    snap=build/preview/snap
    rm -rf "$snap"
    python3 tools/snapshot.py "$snap"
    for frame in "$snap"/*.frame; do
        name=$(basename "$frame" .frame)
        scene="$snap/scene.bin"
        [ -f "$snap/$name.scene" ] && scene="$snap/$name.scene"
        sky=""
        [ -f "$snap/$name.sky" ] && sky="--sky $snap/$name.sky"
        build/preview/render_preview "build/preview/$name.ppm" --scene "$scene" --frame "$frame" $sky
        to_png "build/preview/$name.ppm" "build/preview/$name.png"
    done
    exit 0
fi

[ $# -gt 0 ] || set -- 0
for t in "$@"; do
    build/preview/render_preview "build/preview/t$t.ppm" "$t"
    to_png "build/preview/t$t.ppm" "build/preview/t$t.png"
done
