#!/bin/sh
# Check sketch/rig.cpp against tests/golden/rig_*.json (python/rig.py is the reference; api.md §5.1).
# Run from anywhere; exits 1 if any bone is off by more than 1 cm.
set -eu
cd "$(dirname "$0")/../.."
mkdir -p build/preview
g++ -std=gnu++17 -O2 -Wall -I sketch tests/cpp/rig_golden.cpp sketch/rig.cpp -o build/preview/rig_golden
build/preview/rig_golden | python3 tests/cpp/rig_golden_check.py
