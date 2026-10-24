#include "inputs.h"

#include <Arduino.h>
#include <Arduino_Modulino.h>
#include <math.h>
#include <zephyr/kernel.h>

namespace inputs {
namespace {

const uint8_t BUTTONS_ADDRESS = 0x3E;
const uint8_t JOYSTICK_ADDRESS = 0x2C;
ModulinoButtons buttons(BUTTONS_ADDRESS);
ModulinoMovement movement;
bool movementReady = false;

struct k_mutex lock;
uint8_t lastHeld = 0, pressedLatch = 0, ledState = 0xFF;

bool readPacket(uint8_t address, uint8_t payload[3]) {
  // update() means "changed", not "read succeeded"; reject incomplete wire packets.
  int count = Wire1.requestFrom(address, (uint8_t)4);
  if (count != 4) {
    while (Wire1.available()) Wire1.read();
    return false;
  }
  Wire1.read();  // Modulino pinstrap address precedes the three input bytes.
  for (int i = 0; i < 3; ++i) payload[i] = Wire1.read();
  return true;
}

// Reads the buttons and stick press; updates the latch. Caller holds `lock`.
void sampleButtons(uint8_t& connected, uint8_t& held, uint8_t stick[3]) {
  uint8_t buttonData[3] = {};
  const bool buttonsOk = readPacket(BUTTONS_ADDRESS, buttonData);
  const bool joystickOk = readPacket(JOYSTICK_ADDRESS, stick);
  connected = (buttonsOk ? 1 : 0) | (joystickOk ? 2 : 0);
  held = 0;
  if (buttonsOk) {
    for (int i = 0; i < 3; ++i)
      if (buttonData[i]) held |= 1 << i;
    const uint8_t leds = held & 7;
    if (leds != ledState) {  // an I2C write; only when it changes
      buttons.setLeds(leds & 1, leds & 2, leds & 4);
      ledState = leds;
    }
  }
  if (joystickOk && stick[2]) held |= 8;
  // Keep the previous state of a module that failed this read, so a glitch is not a new press.
  const uint8_t valid = (buttonsOk ? 7 : 0) | (joystickOk ? 8 : 0);
  held = (held & valid) | (lastHeld & ~valid);
  pressedLatch |= held & ~lastHeld;
  lastHeld = held;
}

}  // namespace

void begin() {
  k_mutex_init(&lock);
  Modulino.begin(Wire1);
  buttons.begin();
  movementReady = movement.begin();
}

Snapshot read() {
  Snapshot s = {};
  uint8_t stick[3] = {};
  k_mutex_lock(&lock, K_FOREVER);
  sampleButtons(s.connected, s.held, stick);
  if (s.connected & 2) {
    s.x = 128 - int16_t(stick[0]);
    s.y = 128 - int16_t(stick[1]);
  }
  bool movementOk = movementReady && movement.update();
  const float ax = movementOk ? movement.getX() : 0;
  const float ay = movementOk ? movement.getY() : 0;
  const float az = movementOk ? movement.getZ() : 0;
  movementOk = movementOk && isfinite(ax) && isfinite(ay) && isfinite(az);
  k_mutex_unlock(&lock);
  if (movementOk) {
    s.connected |= 4;
    s.ax = int16_t(constrain(ax, -16.0f, 16.0f) * 1000);
    s.ay = int16_t(constrain(ay, -16.0f, 16.0f) * 1000);
    s.az = int16_t(constrain(az, -16.0f, 16.0f) * 1000);
  }
  return s;
}

void pollButtons() {
  uint8_t connected, held, stick[3];
  k_mutex_lock(&lock, K_FOREVER);
  sampleButtons(connected, held, stick);
  k_mutex_unlock(&lock);
}

uint8_t takePressed() {
  k_mutex_lock(&lock, K_FOREVER);
  const uint8_t pressed = pressedLatch;
  pressedLatch = 0;
  k_mutex_unlock(&lock);
  return pressed;
}

}  // namespace inputs
