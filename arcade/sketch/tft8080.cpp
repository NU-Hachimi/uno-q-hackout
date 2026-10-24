// The pixel loops are the hottest code on the MCU; the core builds sketches with -Os,
// which leaves writeByte() as an out-of-line call per byte.
#pragma GCC optimize("O3")

#include "tft8080.h"

#include <DIYables_TFT_Touch_Shield.h>

// Bus timing in CPU cycles (160 MHz). Inlined at -O3 the stores come back to back, which is
// faster than the panel latches: raise these if the screen shows shifted or speckled pixels.
#ifndef TFT_WR_NOPS
#define TFT_WR_NOPS 3  // WR low pulse
#endif
#ifndef TFT_WR_HOLD_NOPS
#define TFT_WR_HOLD_NOPS 3  // WR high and data hold before the next byte changes the bus
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

// BSRR words for one bus byte; `a` also drives WR low so D4/D5 and the strobe share a write.
struct BusWords {
  uint32_t b, a;
};
BusWords lut[256];
DIYables_TFT_Touch_Shield_Base* panel = nullptr;

__attribute__((always_inline)) inline void writeWords(uint32_t b, uint32_t a) {
  *GPIOB_BSRR = b;
  *GPIOA_BSRR = a;
  for (int i = 0; i < TFT_WR_NOPS; ++i) __asm__ volatile("nop");
  *GPIOA_BSRR = WR;  // the panel latches the byte on this rising edge
  for (int i = 0; i < TFT_WR_HOLD_NOPS; ++i) __asm__ volatile("nop");
}

__attribute__((always_inline)) inline void writeByte(uint8_t v) { writeWords(lut[v].b, lut[v].a); }
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
    lut[v].a = setA | ((maskA & ~setA) << 16) | (WR << 16);
    lut[v].b = setB | ((maskB & ~setB) << 16);
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
    const BusWords hi = lut[row[i] >> 8], lo = lut[row[i] & 0xFF];
    writeWords(hi.b, hi.a);
    writeWords(lo.b, lo.a);
    writeWords(hi.b, hi.a);
    writeWords(lo.b, lo.a);
  }
}

void fill(uint16_t color, size_t n) {
  const BusWords hi = lut[color >> 8], lo = lut[color & 0xFF];
  while (n--) {
    writeWords(hi.b, hi.a);
    writeWords(lo.b, lo.a);
  }
}

}  // namespace tft
