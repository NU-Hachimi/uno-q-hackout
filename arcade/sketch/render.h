#pragma once

#include <stdint.h>

// Platform-independent renderer: also compiled on the desktop by tests/cpp/render_preview.sh.
namespace render {

constexpr int W = 240, H = 160, TILE_H = 16, TILES = H / TILE_H;

struct Camera {
  float x, y, z;     // m
  float yaw, pitch;  // rad; yaw 0 faces +Z, pitch > 0 looks up
  float fovX;        // rad, horizontal
};

// Receives each finished tile top to bottom: W * TILE_H RGB565 pixels, row-major.
using PushTile = void (*)(int tile, const uint16_t* pixels);

void begin();  // after the scene is built: bake terrain colours, lighting and the fog table
void frame(const Camera& cam, PushTile push);
int lastQuadDraws();  // terrain quads rasterized in the last frame, summed over tiles

Camera demoCamera(float seconds);  // slow orbit around the arena

}  // namespace render
