#include "tft8080.h"

#include <DIYables_TFT_Touch_Shield.h>

// Raise if the panel shows shifted or speckled pixels; each NOP lengthens WR low.
#ifndef TFT_WR_NOPS
#define TFT_WR_NOPS 2
#endif

namespace {
// STM32U585 non-secure GPIO aliases (TrustZone is disabled on UNO Q); BSRR at +0x18.
// Macros rather than pointer constants: reinterpret_cast is not constant-initialised and
// would need a static constructor in the LLEXT image.
#define GPIOA_BSRR ((volatile uint32_t*)(0x42020000 + 0x18))
#define GPIOB_BSRR ((volatile uint32_t*)(0x42020400 + 0x18))
constexpr uint32_t WR = 1u << 5;  // A1 = PA5
constexpr uint32_t CD = 1u << 6;  // A2 = PA6

// Bus bit -> GPIO pin, from the UNO Q overlay: D8 D9 D2 D3 D4 D5 D6 D7.
constexpr int8_t BUS_PB[8] = {4, 8, 3, 0, -1, -1, 1, 2};
constexpr int8_t BUS_PA[8] = {-1, -1, -1, -1, 12, 11, -1, -1};

uint32_t lutA[256];
uint32_t lutB[256];
DIYables_TFT_Touch_Shield_Base* panel = nullptr;

inline void writeByte(uint8_t v) {
  *GPIOB_BSRR = lutB[v];
  *GPIOA_BSRR = lutA[v] | (WR << 16);  // D4/D5 and WR low share one write
  for (int i = 0; i < TFT_WR_NOPS; ++i) __asm__ volatile("nop");
  *GPIOA_BSRR = WR;
}
}  // namespace

namespace tft {

void begin(DIYables_TFT_Touch_Shield_Base* display) {
  panel = display;
  uint32_t maskA = 0, maskB = 0;
  for (int bit = 0; bit < 8; ++bit) {
    if (BUS_PA[bit] >= 0) maskA |= 1u << BUS_PA[bit];
    if (BUS_PB[bit] >= 0) maskB |= 1u << BUS_PB[bit];
  }
  for (int v = 0; v < 256; ++v) {
    uint32_t setA = 0, setB = 0;
    for (int bit = 0; bit < 8; ++bit) {
      if (!(v & (1 << bit))) continue;
      if (BUS_PA[bit] >= 0) setA |= 1u << BUS_PA[bit];
      if (BUS_PB[bit] >= 0) setB |= 1u << BUS_PB[bit];
    }
    lutA[v] = setA | ((maskA & ~setA) << 16);
    lutB[v] = setB | ((maskB & ~setB) << 16);
  }
}

void window(int x0, int y0, int x1, int y1) {
  panel->setAddrWindow(x0, y0, x1, y1);  // ends with RAMWR (0x2C), CD low
  *GPIOA_BSRR = CD;
}

void pushPixels(const uint16_t* px, size_t n) {
  while (n--) {
    uint16_t c = *px++;
    writeByte(c >> 8);
    writeByte(c & 0xFF);
  }
}

void pushRow2x(const uint16_t* row, int w) {
  for (int i = 0; i < w; ++i) {
    uint8_t hi = row[i] >> 8, lo = row[i] & 0xFF;
    writeByte(hi);
    writeByte(lo);
    writeByte(hi);
    writeByte(lo);
  }
}

void fill(uint16_t color, size_t n) {
  uint8_t hi = color >> 8, lo = color & 0xFF;
  while (n--) {
    writeByte(hi);
    writeByte(lo);
  }
}

}  // namespace tft
