#pragma once

#include <stdint.h>

#include "gen/rigs.h"

// Rig poses (api.md §5.1), a port of python/rig.py (the reference). Platform-independent:
// tests/cpp/rig_golden.sh compiles it on the desktop and checks it against tests/golden/.
namespace rig {

constexpr int MAX_BONES = 16;

struct Xf {
  float r[3][3];  // row-major rotation
  float t[3];     // translation, m
};

Xf compose(const Xf& a, const Xf& b);                    // a · b
void apply(const Xf& x, const float p[3], float out[3]);  // x · p
Xf euler(const float deg[3]);                            // [rx, ry, rz] degrees: Ry · Rx · Rz
Xf placement(float x, float y, float z, float yaw);      // T(x, y, z) · Ry(yaw), yaw in rad

// Bone transforms in rig space (origin at 0, yaw 0). Returns the bone count, or 0 for a bad rig/anim.
int pose(const gen::Rig& rig, int anim, uint8_t phase, Xf out[MAX_BONES]);

}  // namespace rig
