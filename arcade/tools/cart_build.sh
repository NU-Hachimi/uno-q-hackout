#!/bin/sh
# Assemble the cart directory (alia-pad docs/cart.md §1):
#   tools/cart_build.sh ENGINE_BUILD ART_ENGINE_BUILD OUT
# ENGINE_BUILD: the alia-engine build the cart ships (board or PC); ART_ENGINE_BUILD: a PC build
# to render the art with (tools/cart_art.py, headless). Run from arcade/ (make cart does).
set -eu
engine=$1 art_engine=$2 out=$3
PYTHON=${PYTHON:-python3}

rm -rf "$out"
mkdir -p "$out/content"
cp cart/cart.toml "$out/"
# The game: every module, the generated tables and mesh pack, the music.
cp python/*.py "$out/content/"
cp -r python/gen python/music python/sfx "$out/content/"
find "$out/content" -name __pycache__ -prune -exec rm -rf {} +
# alia-engine ships inside the cart: content/python/alia_engine.abi3.so (main.py puts it on sys.path).
cmake --install "$engine" --prefix "$out/content" >/dev/null
PYTHONPATH="$art_engine" "$PYTHON" tools/cart_art.py "$out" >/dev/null
echo "cart: $out ($(du -sh "$out" | cut -f1))"
