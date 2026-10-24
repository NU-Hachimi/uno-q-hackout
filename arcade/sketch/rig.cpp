#include "rig.h"

#include <math.h>

namespace rig {
namespace {

constexpr float DEG = 3.14159265358979f / 180;

// Linear interpolation of `keys` items of `width` floats each (python/rig.py sample()).
void sample(const float* keys, int n, int width, uint8_t phase, bool loop, float* out) {
  if (n == 1) {
    for (int c = 0; c < width; ++c) out[c] = keys[c];
    return;
  }
  const float f = loop ? phase * n / 256.0f : phase * (n - 1) / 255.0f;
  const int i = int(f);
  const float t = f - i;
  const int a = i % n, b = loop ? (i + 1) % n : (i + 1 < n ? i + 1 : n - 1);
  for (int c = 0; c < width; ++c) out[c] = keys[a * width + c] + (keys[b * width + c] - keys[a * width + c]) * t;
}

}  // namespace

Xf compose(const Xf& a, const Xf& b) {
  Xf o;
  for (int i = 0; i < 3; ++i) {
    for (int j = 0; j < 3; ++j) o.r[i][j] = a.r[i][0] * b.r[0][j] + a.r[i][1] * b.r[1][j] + a.r[i][2] * b.r[2][j];
    o.t[i] = a.r[i][0] * b.t[0] + a.r[i][1] * b.t[1] + a.r[i][2] * b.t[2] + a.t[i];
  }
  return o;
}

void apply(const Xf& x, const float p[3], float out[3]) {
  for (int i = 0; i < 3; ++i) out[i] = x.r[i][0] * p[0] + x.r[i][1] * p[1] + x.r[i][2] * p[2] + x.t[i];
}

Xf euler(const float deg[3]) {
  const float cx = cosf(deg[0] * DEG), sx = sinf(deg[0] * DEG);
  const float cy = cosf(deg[1] * DEG), sy = sinf(deg[1] * DEG);
  const float cz = cosf(deg[2] * DEG), sz = sinf(deg[2] * DEG);
  return Xf{{{cy * cz + sy * sx * sz, -cy * sz + sy * sx * cz, sy * cx},
             {cx * sz, cx * cz, -sx},
             {-sy * cz + cy * sx * sz, sy * sz + cy * sx * cz, cy * cx}},
            {0, 0, 0}};
}

Xf placement(float x, float y, float z, float yaw) {
  const float c = cosf(yaw), s = sinf(yaw);
  return Xf{{{c, 0, s}, {0, 1, 0}, {-s, 0, c}}, {x, y, z}};
}

int pose(const gen::Rig& rig, int anim, uint8_t phase, Xf out[MAX_BONES]) {
  if (!rig.nBones || rig.nBones > MAX_BONES || anim < 0 || anim >= rig.nAnims) return 0;
  const gen::RigAnim& a = rig.anims[anim];
  float angles[MAX_BONES][3] = {};
  for (int k = 0; k < a.nTracks; ++k) {
    const int bone = a.trackBone[k];
    if (bone < rig.nBones) sample(a.trackKeys + k * a.keys * 3, a.keys, 3, phase, a.loop, angles[bone]);
  }
  for (int i = 0; i < rig.nBones; ++i) {
    const gen::RigBone& b = rig.bones[i];
    Xf local = euler(angles[i]);
    for (int c = 0; c < 3; ++c) local.t[c] = b.offset[c];
    if (b.parent < 0) {
      if (a.rootY) {
        float dy;
        sample(a.rootY, a.keys, 1, phase, a.loop, &dy);
        local.t[1] += dy;
      }
      out[i] = local;
    } else {
      out[i] = compose(out[b.parent], local);
    }
  }
  return rig.nBones;
}

}  // namespace rig
