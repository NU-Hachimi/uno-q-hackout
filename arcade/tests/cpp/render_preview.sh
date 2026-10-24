#!/bin/sh
# Render the G3D demo frame on the desktop and save PNGs to build/preview/.
#   sh tests/cpp/render_preview.sh [seconds ...]     (run from arcade/)
set -eu
cd "$(dirname "$0")/../.."
mkdir -p build/preview
g++ -std=gnu++17 -O2 -w ${CXXFLAGS:-} -I sketch \
    tests/cpp/render_preview.cpp sketch/scene.cpp sketch/render.cpp sketch/src/tgx/*.cpp \
    -o build/preview/render_preview
[ $# -gt 0 ] || set -- 0
for t in "$@"; do
    build/preview/render_preview "build/preview/t$t.ppm" "$t"
    python3 - "build/preview/t$t.ppm" "build/preview/t$t.png" <<'EOF'
import struct, sys, zlib
data = open(sys.argv[1], "rb").read()
header, _, rest = data.partition(b"\n255\n")
w, h = map(int, header.split()[1:3])
rows = b"".join(b"\0" + rest[y * w * 3:(y + 1) * w * 3] for y in range(h))
chunk = lambda t, d: struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d))
png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
open(sys.argv[2], "wb").write(png + chunk(b"IDAT", zlib.compress(rows, 6)) + chunk(b"IEND", b""))
EOF
    rm "build/preview/t$t.ppm"
done
