#include <Arduino.h>
#include <Arduino_RouterBridge.h>
#include <Arduino_Modulino.h>
#include <DIYables_TFT_Touch_Shield.h>
#include <math.h>
#include "video_protocol.h"
#include "render.h"
#include "scene.h"
#include "tft8080.h"

#if !defined(ARDUINO_UNO_Q)
#error "Select Arduino UNO Q for this starter."
#endif

// Hosts select the controller fitted to their preassembled consoles.
#ifndef ARCADE_TFT_HX8357D
#define ARCADE_TFT_HX8357D 1
#endif
// G3D_DEMO renders the 3D meadow continuously on the MCU; Python is not needed.
#ifndef G3D_DEMO
#define G3D_DEMO 1
#endif

#if ARCADE_TFT_HX8357D
DIYables_TFT_HX8357D_Shield display;
#else
DIYables_TFT_RM68140_Shield display;
#endif

const uint8_t BUTTONS_ADDRESS = 0x3E;
const uint8_t JOYSTICK_ADDRESS = 0x2C;
ModulinoButtons buttons(BUTTONS_ADDRESS);
ModulinoMovement movement;
bool movementReady = false;

const uint16_t TFT_BLACK = 0x0000;
const uint16_t TFT_WHITE = 0xFFFF;
const uint16_t TFT_CYAN = 0x07FF;
unsigned long lastFrameAt = 0;
bool waiting = true;
int videoSession = 0;
int nextVideoSession = 0;
int lastX = -1;
int lastY = -1;

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

String readInputs() {
  uint8_t buttonData[3] = {};
  uint8_t stickData[3] = {};
  bool buttonsOk = readPacket(BUTTONS_ADDRESS, buttonData);
  bool joystickOk = readPacket(JOYSTICK_ADDRESS, stickData);
  bool movementOk = movementReady && movement.update();
  float ax = movementOk ? movement.getX() : 0;
  float ay = movementOk ? movement.getY() : 0;
  float az = movementOk ? movement.getZ() : 0;
  movementOk = movementOk && isfinite(ax) && isfinite(ay) && isfinite(az);
  int connected = (buttonsOk ? 1 : 0) | (joystickOk ? 2 : 0) | (movementOk ? 4 : 0);
  int pressed = 0;
  if (buttonsOk) {
    for (int i = 0; i < 3; ++i) if (buttonData[i]) pressed |= 1 << i;
    buttons.setLeds(buttonData[0], buttonData[1], buttonData[2]);
  }
  if (joystickOk && stickData[2]) pressed |= 8;
  char json[180];
  snprintf(json, sizeof(json),
           "{\"video\":%d,\"connected\":%d,\"buttons\":%d,\"x\":%d,\"y\":%d,"
           "\"ax\":%d,\"ay\":%d,\"az\":%d}",
           videoSession, connected, pressed,
           joystickOk ? 128 - (int)stickData[0] : 0,
           joystickOk ? 128 - (int)stickData[1] : 0,
           movementOk ? (int)(constrain(ax, -16.0f, 16.0f) * 1000) : 0,
           movementOk ? (int)(constrain(ay, -16.0f, 16.0f) * 1000) : 0,
           movementOk ? (int)(constrain(az, -16.0f, 16.0f) * 1000) : 0);
  return String(json);
}

void textLine(int y, const char* text) {
  display.setCursor(12, y);
  display.setTextColor(TFT_WHITE, TFT_BLACK);
  display.print(text);
}

void showWaiting() {
  if (videoSession) {
    videoSession = 0;
    display.fillScreen(TFT_BLACK);
    textLine(10, "UNO Q arcade starter");
    display.drawRect(12, 160, 456, 148, TFT_WHITE);
  }
  display.fillRect(12, 36, 456, 112, TFT_BLACK);
  textLine(36, "Waiting for App Lab...");
  if (lastX >= 0) display.fillCircle(lastX, lastY, 6, TFT_BLACK);
  lastX = -1;
  waiting = true;
}

bool drawFrame(int x, int y, int pressed, int ax, int ay, int az, int connected) {
  if (videoSession || G3D_DEMO) return false;  // RetroArch owns the display until release/timeout.
  // Bound every RPC input before using it for drawing or bit masks.
  x = constrain(x, 20, 460);
  y = constrain(y, 168, 300);
  pressed &= 15;
  connected &= 7;
  if (!(connected & 1)) pressed &= 8;
  if (!(connected & 2)) { pressed &= 7; x = 240; y = 234; }
  if (!(connected & 4)) { ax = 0; ay = 0; az = 0; }
  ax = constrain(ax, -16000, 16000);
  ay = constrain(ay, -16000, 16000);
  az = constrain(az, -16000, 16000);
  if (waiting) display.fillRect(12, 36, 456, 112, TFT_BLACK);
  char line[40];
  snprintf(line, sizeof(line), "Buttons:%s Stick:%s IMU:%s  ",
           connected & 1 ? "OK" : "--", connected & 2 ? "OK" : "--",
           connected & 4 ? "OK" : "--");
  textLine(36, line);
  snprintf(line, sizeof(line), "A:%d  B:%d  C:%d  Stick press:%d ",
           !!(pressed & 1), !!(pressed & 2), !!(pressed & 4), !!(pressed & 8));
  textLine(64, line);
  textLine(92, "Motion from neutral (mg)");
  snprintf(line, sizeof(line), "%6d / %6d / %6d   ", ax, ay, az);
  textLine(120, line);
  if (lastX >= 0) display.fillCircle(lastX, lastY, 6, TFT_BLACK);
  display.fillCircle(x, y, 6, pressed ? TFT_WHITE : TFT_CYAN);
  lastX = x;
  lastY = y;
  lastFrameAt = millis();
  waiting = false;
  return true;
}

int beginVideo() {
  if (videoSession || G3D_DEMO) return 0;  // Only one stream may own the display.
  nextVideoSession = nextVideoSession == 2147483647 ? 1 : nextVideoSession + 1;
  videoSession = nextVideoSession;
  display.fillScreen(TFT_BLACK);
  textLine(10, "RetroArch / TFT bridge");
  textLine(294, "C + stick press: menu");
  lastX = -1;
  lastFrameAt = millis();
  waiting = false;
  return videoSession;
}

String pollVideo(int session) {
  if (!videoSession || session != videoSession) return String("");
  String inputs = readInputs();
  lastFrameAt = millis();
  return inputs;
}

String videoTile(int session, int tile, MsgPack::bin_t<uint8_t> data) {
  static uint16_t pixels[ArcadeVideo::TILE_PIXELS * 4];
  if (!videoSession || session != videoSession ||
      !ArcadeVideo::decode(tile, data.data(), data.size(), pixels)) return String("");
  display.drawRGBBitmap(80 + (tile % 10) * 32, 40 + (tile / 10) * 16, pixels, 32, 16);
  return pollVideo(session);  // Return fresh controls after each acknowledged tile.
}

bool endVideo(int session) {
  if (!videoSession || session != videoSession) return false;
  showWaiting();
  return true;
}

uint32_t statFrames = 0, statRenderUs = 0, statPushUs = 0, statStartMs = 0;
uint32_t statSkyUs = 0, statRasterUs = 0, statFogUs = 0, statSetupUs = 0;
volatile int initStage = 0;  // last setup() step reached; reported by g3d_debug_stats
String lastStats = "{}";

// Each 240xTILE_H tile is pushed at 2x (480x2*TILE_H) on the panel.
void pushTile(int tile, const uint16_t* pixels) {
  uint32_t start = micros();
  tft::window(0, tile * render::TILE_H * 2, render::W * 2 - 1, (tile + 1) * render::TILE_H * 2 - 1);
  for (int y = 0; y < render::TILE_H; ++y) {
    tft::pushRow2x(pixels + y * render::W, render::W);
    tft::pushRow2x(pixels + y * render::W, render::W);
  }
  statPushUs += micros() - start;
  // Serve Bridge once mid-frame; each idle safeUpdate() sleeps 1 ms, so not after every tile.
  if (tile == render::TILES / 2) safeUpdate();
}

// Debug only (not part of the api.md contract): init stage and frame timing for desktop checks.
// Registered with provide() so it answers from the Bridge thread even if setup() stalls.
String debugStats() { return String("{\"stage\":") + initStage + ",\"frame\":" + lastStats + "}"; }

void renderDemoFrame() {
  if (initStage < 8) initStage = 8;
  uint32_t start = micros();
  uint32_t pushBefore = statPushUs;
  render::frame(render::demoCamera(millis() / 1000.0f), pushTile);
  statRenderUs += (micros() - start) - (statPushUs - pushBefore);
  const render::Profile& prof = render::lastProfile();
  statSetupUs += prof.setupUs;
  statSkyUs += prof.skyUs;
  statRasterUs += prof.rasterUs;
  statFogUs += prof.fogUs;
  ++statFrames;
  uint32_t now = millis();
  if (now - statStartMs >= 2000) {
    char json[240];
    const float perFrame = 1000.0f * statFrames;
    snprintf(json, sizeof(json),
             "{\"fps\":%.1f,\"render_ms\":%.1f,\"push_ms\":%.1f,\"setup_ms\":%.1f,\"sky_ms\":%.1f,"
             "\"raster_ms\":%.1f,\"fog_ms\":%.1f,\"quads\":%d,\"frames\":%lu}",
             statFrames * 1000.0f / (now - statStartMs), statRenderUs / perFrame, statPushUs / perFrame,
             statSetupUs / perFrame, statSkyUs / perFrame, statRasterUs / perFrame, statFogUs / perFrame,
             render::lastQuadDraws(), (unsigned long)statFrames);
    lastStats = json;
    statFrames = statRenderUs = statPushUs = 0;
    statSetupUs = statSkyUs = statRasterUs = statFogUs = 0;
    statStartMs = now;
  }
}

void setup() {
  bool bridgeOk = Bridge.begin();
  if (bridgeOk) Bridge.provide("g3d_debug_stats", debugStats);
  initStage = 1;
  Modulino.begin(Wire1);
  buttons.begin();
  movementReady = movement.begin();
  display.begin();
  display.setRotation(1);  // Landscape: 480 x 320.
  initStage = 2;
#if G3D_DEMO
  tft::begin(&display);
  initStage = 3;
  tft::window(0, 0, 479, 319);
  tft::fill(TFT_BLACK, 480 * 320);
  initStage = 4;
  scene::buildDemo(1);
  initStage = 5;
  render::begin();
  render::setClock([]() -> uint32_t { return micros(); });
  initStage = 6;
#else
  display.fillScreen(TFT_BLACK);
  display.setTextSize(2);
  display.setTextWrap(false);
  textLine(10, "UNO Q arcade starter");
  display.drawRect(12, 160, 456, 148, TFT_WHITE);
  showWaiting();
#endif
  if (bridgeOk) {
    Bridge.provide_safe("arcade_read_inputs", readInputs);
    Bridge.provide_safe("arcade_draw_frame", drawFrame);
    Bridge.provide_safe("arcade_video_begin", beginVideo);
    Bridge.provide_safe("arcade_video_tile", videoTile);
    Bridge.provide_safe("arcade_video_poll", pollVideo);
    Bridge.provide_safe("arcade_video_end", endVideo);
  } else {
    textLine(36, "Bridge failed: restart app");
  }
  initStage = 7;
}

void loop() {
#if G3D_DEMO
  renderDemoFrame();
#else
  if (!waiting && millis() - lastFrameAt > 1500) showWaiting();
  delay(5);
#endif
}
