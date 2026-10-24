#pragma once

#include <stdint.h>

// Modulino controls on Wire1. Safe to call from the loop and from Bridge handler threads.
namespace inputs {

struct Snapshot {
  uint8_t connected;  // bit0 Buttons, bit1 Joystick, bit2 Movement
  uint8_t held;       // bit0 A, bit1 B, bit2 C, bit3 stick press
  int16_t x, y;       // raw joystick, -127..128 (0 when disconnected)
  int16_t ax, ay, az; // mg, including gravity (0 when disconnected)
};

void begin();
Snapshot read();         // full read: buttons, joystick and Movement
void pollButtons();      // buttons and stick press only; call often so short taps are latched
uint8_t takePressed();   // buttons newly pressed since the previous call (rising edges)

}  // namespace inputs
