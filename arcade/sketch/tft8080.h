#pragma once

#include <stddef.h>
#include <stdint.h>

class DIYables_TFT_Touch_Shield_Base;

// Fast 8080 pixel writes through GPIO BSRR registers. DIYables still owns
// controller init and the address window; only pixel data bypasses digitalWrite.
namespace tft {
void begin(DIYables_TFT_Touch_Shield_Base* display);  // after display.begin() + setRotation()
void window(int x0, int y0, int x1, int y1);          // inclusive; leaves the bus in data mode
void pushPixels(const uint16_t* px, size_t n);
void pushRow2x(const uint16_t* row, int w);           // each pixel twice; caller writes the row twice
void fill(uint16_t color, size_t n);
}  // namespace tft
