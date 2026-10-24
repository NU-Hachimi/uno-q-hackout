#pragma once

#include <stdint.h>

#include "g3d_proto.h"

// HUD drawn into each finished tile (after fog), so it is pushed with the frame and never flickers.
namespace hud {

// pixels: the tile, `width` wide and `rows` tall, whose first row is frame row `top`.
void drawTile(uint16_t* pixels, int width, int rows, int top, const g3d::Frame& f);

}  // namespace hud
