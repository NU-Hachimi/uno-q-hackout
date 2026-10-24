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
};

extern Params params;
extern int8_t heights[MAX_N * MAX_N];  // row-major: heights[j * terrainN + i], i along X
extern uint16_t palette[32];          // object palette after the Look's grading

void buildDemo(uint32_t seed);          // used until Python commits a scene
float terrainHeight(float x, float z);  // bilinear, clamped to the edge (matches Python world.py)

// Scene upload (api.md §2): fills a staging copy, so the live scene stays usable while it arrives.
// Not thread-safe; the caller serialises these against applyUpload().
bool uploadBegin(const uint8_t* hdr, size_t n);
bool uploadChunk(uint8_t kind, uint8_t index, const uint8_t* data, size_t n);
bool uploadCommit(uint16_t crc);
bool applyUpload();  // copies a committed upload into the live scene; true means re-bake

uint8_t rigId();                  // boss rig of the live scene (header rig_id), 0 for none
uint8_t slotVariant(int slot);    // fitted part variant per rig slot, 0 = empty

}  // namespace scene
