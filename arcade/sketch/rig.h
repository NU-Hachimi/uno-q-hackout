#pragma once

#include <stdint.h>

#include "gen/rig_types.h"

// Rig pose evaluation (api.md §5.1); must match python/rig.py, checked by tests/cpp/rig_golden.sh.
// Platform-independent and TGX-free so the golden test can build it alone.
namespace rig {

constexpr int MAX_BONES = 16;

struct Xform {
  float r[9];  // row-major rotation
  float t[3];  // translation; maps p to r * p + t
};

const gen::Rig* find(uint8_t rigId);  // nullptr for 0 or an unknown id

// Rig-space transform of every bone; false (and nothing written) for a bad rig or animation.
bool pose(const gen::Rig& rig, uint8_t anim, uint8_t phase, Xform out[MAX_BONES]);

Xform slot(const gen::Rig& rig, const Xform* bones, int slotIndex);
Xform euler(float rxDeg, float ryDeg, float rzDeg);  // Ry * Rx * Rz
Xform compose(const Xform& a, const Xform& b);       // a * b: b first
Xform rigToWorld(float x, float y, float z, float yawRad);  // T(pos) * Ry(yaw)
void apply(const Xform& m, const float p[3], float out[3]);

}  // namespace rig
