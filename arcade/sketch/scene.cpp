#include "scene.h"

#include <math.h>
#include <string.h>

#include "g3d_proto.h"

namespace scene {

Params params;
int8_t heights[MAX_N * MAX_N];
uint16_t palette[32];

namespace {
uint8_t liveRig = 0;
uint8_t liveVariants[32];
}  // namespace

namespace {

constexpr float TAU = 6.28318530718f;
constexpr int CHUNK = 192;
constexpr int LOOK_SIZE = 76;

// Header colours before grading, so a new Look can be applied to them.
struct RawColors {
  uint16_t skyTop, skyHorizon, fogColor, grassA, grassB;
};

struct Staging {
  Params params;
  RawColors colors;
  int8_t heights[MAX_N * MAX_N];
  uint8_t rocks[MAX_ROCKS * 8];
  int nRocks;
  uint32_t terrainChunks, rockChunks;  // bit per received chunk index
  uint8_t lookRaw[LOOK_SIZE];  // kept as sent, for the CRC
  uint8_t rig, nSlots, variants[32];
  gen::Look look;
  bool hasLook, begun, committed;
};
Staging staging;

// Smooth value noise on a coarse lattice; deterministic for a given seed (same as world.py).
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

inline float clamp01(float v) { return v < 0 ? 0 : (v > 1 ? 1 : v); }

// Mode 1 grading (art.md §4): saturation, contrast/brightness, gamma, then lift/gain.
uint16_t grade(uint16_t c, const gen::Look& look) {
  if (look.gradeMode == 0) return c;
  float rgb[3] = {((c >> 11) & 31) / 31.0f, ((c >> 5) & 63) / 63.0f, (c & 31) / 31.0f};
  const float lift[3] = {((look.lift >> 11) & 31) / 31.0f, ((look.lift >> 5) & 63) / 63.0f, (look.lift & 31) / 31.0f};
  const float gain[3] = {((look.gain >> 11) & 31) / 31.0f, ((look.gain >> 5) & 63) / 63.0f, (look.gain & 31) / 31.0f};
  const float y = 0.299f * rgb[0] + 0.587f * rgb[1] + 0.114f * rgb[2];
  const float exponent = 64.0f / (look.gamma ? look.gamma : 64);
  for (int i = 0; i < 3; ++i) {
    float v = y + (rgb[i] - y) * look.saturation / 128.0f;
    v = clamp01((v - 0.5f) * look.contrast / 128.0f + 0.5f + look.brightness / 128.0f);
    v = powf(v, exponent);
    rgb[i] = clamp01(lift[i] + v * (gain[i] - lift[i]));
  }
  return uint16_t((lroundf(rgb[0] * 31) << 11) | (lroundf(rgb[1] * 63) << 5) | lroundf(rgb[2] * 31));
}

void applyLook(const gen::Look& look, const RawColors& raw, Params& p) {
  for (int i = 0; i < 32; ++i) palette[i] = grade(look.palette[i], look);
  p.skyTop = grade(raw.skyTop, look);
  p.skyHorizon = grade(raw.skyHorizon, look);
  p.fogColor = grade(raw.fogColor, look);
  p.grassA = grade(raw.grassA, look);
  p.grassB = grade(raw.grassB, look);
}

}  // namespace

void buildDemo(uint32_t seed) {
  params.fogNear = gen::SCENE_FOG_NEAR * 2;
  params.fogFar = gen::SCENE_FOG_FAR * 2;
  params.terrainN = 17;
  params.cell = 16;
  params.originX = -(params.terrainN - 1) * params.cell / 2;
  params.originZ = params.originX;
  params.heightScale = 1.0f / 16;
  params.lightYaw = gen::SCENE_LIGHT_YAW * (TAU / 256);
  params.lightPitch = gen::SCENE_LIGHT_PITCH * (TAU / 256);
  const RawColors raw = {gen::SCENE_SKY_TOP, gen::SCENE_SKY_HORIZON, gen::SCENE_FOG_COLOR, gen::SCENE_GRASS_A,
                         gen::SCENE_GRASS_B};
  applyLook(gen::DEFAULT_LOOK, raw, params);
  liveRig = 1;  // the moose with the first variant of every part, for the demo
  memset(liveVariants, 1, sizeof(liveVariants));

  const int n = params.terrainN;
  for (int j = 0; j < n; ++j) {
    for (int i = 0; i < n; ++i) {
      float x = params.originX + i * params.cell, z = params.originZ + j * params.cell;
      float h = 5.0f * valueNoise(seed, x / 70, z / 70) + 2.0f * valueNoise(seed + 1, x / 28, z / 28);
      // Flatten the arena where the boss fight happens.
      float t = (sqrtf(x * x + z * z) - 30) / 40;
      t = clamp01(t);
      h *= 0.1f + 0.9f * t * t * (3 - 2 * t);
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

bool uploadBegin(const uint8_t* h, size_t n) {
  staging.begun = staging.committed = false;
  if (n < 25 || h[0] != g3d::VERSION || n != size_t(25 + h[24])) return false;
  Params& p = staging.params;
  RawColors& raw = staging.colors;
  raw.skyTop = g3d::rd16(h + 2);
  raw.skyHorizon = g3d::rd16(h + 4);
  raw.fogColor = g3d::rd16(h + 6);
  p.fogNear = h[8] * 2.0f;
  p.fogFar = h[9] * 2.0f;
  p.terrainN = h[10];
  p.cell = h[11];
  p.originX = g3d::rd16s(h + 12) / 64.0f;
  p.originZ = g3d::rd16s(h + 14) / 64.0f;
  p.heightScale = h[16] / 16.0f;
  staging.nRocks = h[17];
  raw.grassA = g3d::rd16(h + 18);
  raw.grassB = g3d::rd16(h + 20);
  p.lightYaw = h[22] * (TAU / 256);
  p.lightPitch = h[23] * (TAU / 256);
  if (p.terrainN < 2 || p.terrainN > MAX_N || p.cell <= 0 || p.fogFar <= p.fogNear || p.fogFar < 4 ||
      staging.nRocks > MAX_ROCKS)
    return false;
  staging.rig = h[1];
  staging.nSlots = h[24] > 32 ? 32 : h[24];
  memset(staging.variants, 0, sizeof(staging.variants));
  memcpy(staging.variants, h + 25, staging.nSlots);
  staging.terrainChunks = staging.rockChunks = 0;
  staging.hasLook = false;
  staging.begun = true;
  return true;
}

bool uploadChunk(uint8_t kind, uint8_t index, const uint8_t* data, size_t n) {
  if (!staging.begun || staging.committed || n == 0 || n > size_t(CHUNK)) return false;
  if (kind == 1) {
    const size_t total = size_t(staging.params.terrainN) * staging.params.terrainN;
    const size_t offset = size_t(index) * CHUNK;
    if (index >= 32 || offset + n > total || (offset + n < total && n != size_t(CHUNK))) return false;
    memcpy(staging.heights + offset, data, n);
    staging.terrainChunks |= 1u << index;
    return true;
  }
  if (kind == 2) {
    const size_t offset = size_t(index) * 24 * 8;
    if (index >= 3 || n % 8 || offset + n > size_t(staging.nRocks) * 8) return false;
    memcpy(staging.rocks + offset, data, n);
    staging.rockChunks |= 1u << index;
    return true;
  }
  if (kind == 3) {
    if (index != 0 || n != size_t(LOOK_SIZE)) return false;
    memcpy(staging.lookRaw, data, LOOK_SIZE);
    gen::Look& look = staging.look;
    for (int i = 0; i < 32; ++i) look.palette[i] = g3d::rd16(data + 2 * i);
    look.gradeMode = data[64] > 2 ? 0 : (data[64] == 2 ? 1 : data[64]);  // no per-pixel grading yet
    look.saturation = data[65];
    look.contrast = data[66];
    look.brightness = int8_t(data[67]);
    look.gamma = data[68];
    look.lift = g3d::rd16(data + 69);
    look.gain = g3d::rd16(data + 71);
    look.posterize = data[73];
    look.dither = data[74];
    staging.hasLook = true;
    return true;
  }
  return false;
}

bool uploadCommit(uint16_t crc) {
  if (!staging.begun || staging.committed) return false;
  const int n = staging.params.terrainN;
  const uint32_t terrainNeeded = (1u << ((n * n + CHUNK - 1) / CHUNK)) - 1;
  const uint32_t rocksNeeded = staging.nRocks ? (1u << ((staging.nRocks + 23) / 24)) - 1 : 0;
  if (staging.terrainChunks != terrainNeeded || staging.rockChunks != rocksNeeded) return false;
  // CRC over all chunk data in kind, then index order (api.md §3.2).
  uint16_t check = g3d::crc16(reinterpret_cast<const uint8_t*>(staging.heights), size_t(n) * n);
  check = g3d::crc16(staging.rocks, size_t(staging.nRocks) * 8, check);
  if (staging.hasLook) check = g3d::crc16(staging.lookRaw, LOOK_SIZE, check);
  if (check != crc) return false;
  staging.committed = true;
  return true;
}

bool applyUpload() {
  if (!staging.committed) return false;
  staging.committed = staging.begun = false;
  params = staging.params;
  memcpy(heights, staging.heights, sizeof(int8_t) * params.terrainN * params.terrainN);
  applyLook(staging.hasLook ? staging.look : gen::DEFAULT_LOOK, staging.colors, params);
  liveRig = staging.rig;
  memcpy(liveVariants, staging.variants, sizeof(liveVariants));
  return true;
}

uint8_t rigId() { return liveRig; }
uint8_t slotVariant(int slot) { return slot >= 0 && slot < 32 ? liveVariants[slot] : 0; }

}  // namespace scene
