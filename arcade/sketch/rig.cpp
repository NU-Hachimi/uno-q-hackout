#include "rig.h"

#include <math.h>

#include "gen/rigs.h"

namespace rig {
namespace {

constexpr float DEG = 3.14159265358979f / 180.0f;

Xform rotation(const float r[9]) {
  Xform m;
  for (int i = 0; i < 9; ++i) m.r[i] = r[i];
  m.t[0] = m.t[1] = m.t[2] = 0;
  return m;
}

Xform translation(float x, float y, float z) {
  Xform m = {{1, 0, 0, 0, 1, 0, 0, 0, 1}, {x, y, z}};
  return m;
}

inline float lerp(float a, float b, float t) { return a + (b - a) * t; }

}  // namespace

const gen::Rig* find(uint8_t rigId) { return rigId < gen::RIG_COUNT ? gen::RIGS[rigId] : nullptr; }

Xform euler(float rx, float ry, float rz) {
  const float cx = cosf(rx * DEG), sx = sinf(rx * DEG);
  const float cy = cosf(ry * DEG), sy = sinf(ry * DEG);
  const float cz = cosf(rz * DEG), sz = sinf(rz * DEG);
  const float ryM[9] = {cy, 0, sy, 0, 1, 0, -sy, 0, cy};
  const float rxM[9] = {1, 0, 0, 0, cx, -sx, 0, sx, cx};
  const float rzM[9] = {cz, -sz, 0, sz, cz, 0, 0, 0, 1};
  return compose(compose(rotation(ryM), rotation(rxM)), rotation(rzM));
}

Xform compose(const Xform& a, const Xform& b) {
  Xform m;
  for (int i = 0; i < 3; ++i) {
    for (int j = 0; j < 3; ++j)
      m.r[i * 3 + j] = a.r[i * 3] * b.r[j] + a.r[i * 3 + 1] * b.r[3 + j] + a.r[i * 3 + 2] * b.r[6 + j];
    m.t[i] = a.r[i * 3] * b.t[0] + a.r[i * 3 + 1] * b.t[1] + a.r[i * 3 + 2] * b.t[2] + a.t[i];
  }
  return m;
}

void apply(const Xform& m, const float p[3], float out[3]) {
  for (int i = 0; i < 3; ++i) out[i] = m.r[i * 3] * p[0] + m.r[i * 3 + 1] * p[1] + m.r[i * 3 + 2] * p[2] + m.t[i];
}

Xform rigToWorld(float x, float y, float z, float yawRad) {
  Xform m = euler(0, yawRad / DEG, 0);
  m.t[0] = x;
  m.t[1] = y;
  m.t[2] = z;
  return m;
}

bool pose(const gen::Rig& rig, uint8_t animId, uint8_t phase, Xform out[MAX_BONES]) {
  if (animId >= rig.nAnims || rig.nBones > MAX_BONES) return false;
  const gen::RigAnim& anim = rig.anims[animId];
  // Key blend, as python/rig.py key_position(): loops wrap the last key back to the first.
  int i = 0, j = 0;
  float t = 0;
  if (anim.keys > 1) {
    if (anim.loop) {
      const float f = phase * anim.keys / 256.0f;
      i = int(f);
      j = (i + 1) % anim.keys;
      t = f - i;
    } else {
      const float f = phase * (anim.keys - 1) / 255.0f;
      i = int(f);
      if (i > anim.keys - 2) i = anim.keys - 2;
      j = i + 1;
      t = f - i;
    }
  }
  for (int b = 0; b < rig.nBones; ++b) {
    const gen::RigBone& bone = rig.bones[b];
    const float* track = anim.tracks[b];
    Xform local = track ? euler(lerp(track[i * 3], track[j * 3], t), lerp(track[i * 3 + 1], track[j * 3 + 1], t),
                                lerp(track[i * 3 + 2], track[j * 3 + 2], t))
                        : translation(0, 0, 0);
    local.t[0] = bone.offset[0];
    local.t[1] = bone.offset[1];
    local.t[2] = bone.offset[2];
    if (bone.parent < 0 && anim.rootY) local.t[1] += lerp(anim.rootY[i], anim.rootY[j], t);
    out[b] = bone.parent < 0 ? local : compose(out[bone.parent], local);
  }
  return true;
}

Xform slot(const gen::Rig& rig, const Xform* bones, int slotIndex) {
  const gen::RigSlot& s = rig.slots[slotIndex];
  return compose(bones[s.bone], compose(translation(s.offset[0], s.offset[1], s.offset[2]),
                                        euler(s.rot[0], s.rot[1], s.rot[2])));
}

}  // namespace rig
