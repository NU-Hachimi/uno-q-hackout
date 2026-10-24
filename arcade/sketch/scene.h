#pragma once

#include <stddef.h>
#include <stdint.h>

#include "gen/palette.h"

// Scene state decoded from the api.md §3.1 header; units converted to metres/radians.
namespace scene {

constexpr int MAX_N = 33;
constexpr int MAX_ROCKS = 64;

struct Params {
  uint16_t skyTop, skyHorizon, fogColor;  // RGB565, already graded by the Look
  float fogNear, fogFar;                  // m; fogFar is also the far clip plane
  int terrainN;                           // vertices per side
  float cell;                             // m
  float originX, originZ;                 // m, corner of vertex (0, 0)
  float heightScale;                      // m per height unit
  uint16_t grassA, grassB;                // RGB565, already graded
  float lightYaw, lightPitch;             // rad
  float groundFog;                        // 0..1, from the Look (height fog near the ground)
};

// Scattered scenery (api.md §3.2 kind 2); y is resolved from the terrain when the scene is applied.
struct Rock {
  float x, y, z, yaw, scale;  // m, rad, factor
  uint8_t mesh, tint;         // gen::MESHES id, palette index (0 keeps the mesh colours)
};

extern Params params;
extern Rock rocks[MAX_ROCKS];
extern int nRocks;
extern int8_t heights[MAX_N * MAX_N];  // row-major: heights[j * terrainN + i], i along X
extern uint16_t palette[32];          // object palette after the Look's grading

void buildDemo(uint32_t seed);          // used until Python commits a scene
float terrainHeight(float x, float z);  // bilinear, clamped to the edge (matches Python world.py)

// Scene upload (api.md §2): fills a staging copy, so the live scene stays usable while it arrives.
// Not thread-safe; the caller serialises these against applyUpload().
bool uploadBegin(const uint8_t* hdr, size_t n);
bool uploadChunk(uint8_t kind, uint8_t index, const uint8_t* data, size_t n);
bool uploadCommit(uint16_t crc);
// Sky update (api.md §3.6, g3d_scene_sky): sky/fog/grass colours, fog distances, sun and Look, without
// touching terrain or rocks. Python sends one every fraction of a second while the time of day changes.
bool uploadSky(const uint8_t* data, size_t n);
bool applyUpload();  // applies a committed upload, then a pending sky update; true means re-bake

uint8_t rigId();                  // boss rig of the live scene (header rig_id), 0 for none
uint8_t slotVariant(int slot);    // fitted part variant per rig slot, 0 = empty

}  // namespace scene
