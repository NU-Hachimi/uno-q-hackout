#include "scene.h"

#include <math.h>

namespace scene {

Params params;
int8_t heights[MAX_N * MAX_N];

namespace {

constexpr uint16_t rgb565(int r, int g, int b) {
  return ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3);
}

// Smooth value noise on a coarse lattice; deterministic for a given seed.
float lattice(uint32_t seed, int x, int z) {
  uint32_t h = seed ^ (uint32_t)(x * 374761393) ^ (uint32_t)(z * 668265263);
  h = (h ^ (h >> 13)) * 1274126177u;
  return ((h ^ (h >> 16)) & 0xFFFF) / 32767.5f - 1.0f;
}

float valueNoise(uint32_t seed, float x, float z) {
  int x0 = (int)floorf(x), z0 = (int)floorf(z);
  float fx = x - x0, fz = z - z0;
  fx = fx * fx * (3 - 2 * fx);
  fz = fz * fz * (3 - 2 * fz);
  float a = lattice(seed, x0, z0), b = lattice(seed, x0 + 1, z0);
  float c = lattice(seed, x0, z0 + 1), d = lattice(seed, x0 + 1, z0 + 1);
  return (a + (b - a) * fx) + ((c + (d - c) * fx) - (a + (b - a) * fx)) * fz;
}

}  // namespace

void buildDemo(uint32_t seed) {
  params.skyTop = rgb565(92, 124, 168);
  params.skyHorizon = rgb565(186, 196, 202);
  params.fogColor = params.skyHorizon;
  params.fogNear = 12;
  params.fogFar = 64;
  params.terrainN = 17;
  params.cell = 8;
  params.originX = -(params.terrainN - 1) * params.cell / 2;
  params.originZ = params.originX;
  params.heightScale = 1.0f / 16;
  params.grassA = rgb565(58, 108, 42);
  params.grassB = rgb565(120, 158, 66);
  params.lightYaw = 0.7f;
  params.lightPitch = 0.9f;

  const int n = params.terrainN;
  for (int j = 0; j < n; ++j) {
    for (int i = 0; i < n; ++i) {
      float x = params.originX + i * params.cell, z = params.originZ + j * params.cell;
      float h = 4.0f * valueNoise(seed, x / 40, z / 40) + 1.5f * valueNoise(seed + 1, x / 16, z / 16);
      // Flatten the arena where the boss fight happens.
      float r = sqrtf(x * x + z * z);
      float t = r < 20 ? 0 : (r > 44 ? 1 : (r - 20) / 24);
      h *= 0.15f + 0.85f * t * t * (3 - 2 * t);
      int v = (int)lroundf(h / params.heightScale);
      heights[j * n + i] = (int8_t)(v < -127 ? -127 : (v > 127 ? 127 : v));
    }
  }
}

float terrainHeight(float x, float z) {
  const int n = params.terrainN;
  float gx = (x - params.originX) / params.cell, gz = (z - params.originZ) / params.cell;
  gx = gx < 0 ? 0 : (gx > n - 1 ? n - 1 : gx);
  gz = gz < 0 ? 0 : (gz > n - 1 ? n - 1 : gz);
  int i = (int)gx, j = (int)gz;
  if (i > n - 2) i = n - 2;
  if (j > n - 2) j = n - 2;
  float fx = gx - i, fz = gz - j;
  const int8_t* row = heights + j * n + i;
  float top = row[0] + (row[1] - row[0]) * fx;
  float bottom = row[n] + (row[n + 1] - row[n]) * fx;
  return (top + (bottom - top) * fz) * params.heightScale;
}

}  // namespace scene
