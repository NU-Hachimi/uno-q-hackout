#pragma once

#include <stdint.h>

#include "g3d_proto.h"

// Platform-independent renderer: also compiled on the desktop by tests/cpp/render_preview.sh.
namespace render {

constexpr int W = 240, H = 160, TILE_H = 32, TILES = H / TILE_H;

// Receives each finished tile top to bottom: W * TILE_H RGB565 pixels, row-major.
using PushTile = void (*)(int tile, const uint16_t* pixels);

// Microseconds per phase in the last frame, summed over tiles (push time excluded).
struct Profile {
  uint32_t setupUs, skyUs, rasterUs, objectUs, fogUs;
};

void begin();  // after the scene changes: bake terrain colours, lighting and the fog table
void frame(const g3d::Frame& f, PushTile push);
int lastQuadDraws();  // terrain quads rasterized in the last frame, summed over tiles
void setClock(uint32_t (*micros)());  // optional; without it the profile stays zero
const Profile& lastProfile();

g3d::Frame demoFrame(float seconds);  // slow orbit around the arena, shown while Python is silent

}  // namespace render
