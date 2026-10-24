#pragma once

#include <stdint.h>

// Scene state decoded from the api.md §3.1 header; units converted to metres/radians.
namespace scene {

constexpr int MAX_N = 33;

struct Params {
  uint16_t skyTop, skyHorizon, fogColor;  // RGB565
  float fogNear, fogFar;                  // m; fogFar is also the far clip plane
  int terrainN;                           // vertices per side
  float cell;                             // m
  float originX, originZ;                 // m, corner of vertex (0, 0)
  float heightScale;                      // m per height unit
  uint16_t grassA, grassB;                // RGB565
  float lightYaw, lightPitch;             // rad
};

extern Params params;
extern int8_t heights[MAX_N * MAX_N];  // row-major: heights[j * terrainN + i], i along X

void buildDemo(uint32_t seed);   // misty meadow with gentle hills and a flat central arena
float terrainHeight(float x, float z);  // bilinear, clamped to the edge (matches Python world.py)

}  // namespace scene
