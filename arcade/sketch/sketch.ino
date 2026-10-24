#include <Arduino.h>
#include <Arduino_RouterBridge.h>
#include <DIYables_TFT_Touch_Shield.h>
#include <math.h>
#include "video_protocol.h"
#include "inputs.h"
#include "render.h"
#include "rpc.h"
#include "scene.h"
#include "tft8080.h"

#if !defined(ARDUINO_UNO_Q)
#error "Select Arduino UNO Q for this starter."
#endif

// Hosts select the controller fitted to their preassembled consoles.
#ifndef ARCADE_TFT_HX8357D
#define ARCADE_TFT_HX8357D 1
#endif

#if ARCADE_TFT_HX8357D
DIYables_TFT_HX8357D_Shield display;
#else
DIYables_TFT_RM68140_Shield display;
#endif

// Python frames older than this fall back to the built-in demo orbit (api.md §4).
const uint32_t FRAME_TIMEOUT_MS = 1500;

const uint16_t TFT_BLACK = 0x0000;
const uint16_t TFT_WHITE = 0xFFFF;
unsigned long lastVideoAt = 0;
int videoSession = 0;
int nextVideoSession = 0;

String readInputs() {
  const inputs::Snapshot s = inputs::read();
  char json[180];
  snprintf(json, sizeof(json),
           "{\"video\":%d,\"connected\":%d,\"buttons\":%d,\"x\":%d,\"y\":%d,"
           "\"ax\":%d,\"ay\":%d,\"az\":%d}",
           videoSession, s.connected, s.held, s.x, s.y, s.ax, s.ay, s.az);
  return String(json);
}

void textLine(int y, const char* text) {
  display.setCursor(12, y);
  display.setTextColor(TFT_WHITE, TFT_BLACK);
  display.print(text);
}

// RetroArch (retroarch/run.py) borrows the display while the 3D game is not running.
int beginVideo() {
  g3d::Frame frame;
  uint32_t age;
  if (videoSession || (rpc::latestFrame(frame, age) && age < FRAME_TIMEOUT_MS)) return 0;
  nextVideoSession = nextVideoSession == 2147483647 ? 1 : nextVideoSession + 1;
  videoSession = nextVideoSession;
  rpc::setVideoActive(true);
  display.fillScreen(TFT_BLACK);
  display.setTextSize(2);
  textLine(10, "RetroArch / TFT bridge");
  textLine(294, "C + stick press: menu");
  lastVideoAt = millis();
  return videoSession;
}

String pollVideo(int session) {
  if (!videoSession || session != videoSession) return String("");
  String state = readInputs();
  lastVideoAt = millis();
  return state;
}

String videoTile(int session, int tile, MsgPack::bin_t<uint8_t> data) {
  static uint16_t pixels[ArcadeVideo::TILE_PIXELS * 4];
  if (!videoSession || session != videoSession ||
      !ArcadeVideo::decode(tile, data.data(), data.size(), pixels)) return String("");
  display.drawRGBBitmap(80 + (tile % 10) * 32, 40 + (tile / 10) * 16, pixels, 32, 16);
  return pollVideo(session);  // Return fresh controls after each acknowledged tile.
}

void stopVideo() {
  videoSession = 0;
  rpc::setVideoActive(false);
}

bool endVideo(int session) {
  if (!videoSession || session != videoSession) return false;
  stopVideo();
  return true;
}

uint32_t statFrames = 0, statRenderUs = 0, statPushUs = 0, statStartMs = 0, statRxStart = 0;
uint32_t statSkyUs = 0, statRasterUs = 0, statObjectUs = 0, statFogUs = 0, statSetupUs = 0;
bool statLive = false;
uint8_t statSeq = 0;
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
  inputs::pollButtons();  // latch taps shorter than a frame
  // Serve Bridge once mid-frame; each idle safeUpdate() sleeps 1 ms, so not after every tile.
  if (tile == render::TILES / 2) safeUpdate();
}

// Debug only (not part of the api.md contract): init stage and frame timing for desktop checks.
// Registered with provide() so it answers from the Bridge thread even if setup() stalls.
String debugStats() { return String("{\"stage\":") + initStage + ",\"frame\":" + lastStats + "}"; }

void renderFrame() {
  if (initStage < 8) initStage = 8;
  if (rpc::applyScene()) render::begin();
  g3d::Frame frame;
  uint32_t age = 0;
  const bool live = rpc::latestFrame(frame, age) && age < FRAME_TIMEOUT_MS;
  if (live) rpc::markRendered(frame.seq);
  else frame = render::demoFrame(millis() / 1000.0f);

  uint32_t start = micros();
  uint32_t pushBefore = statPushUs;
  render::frame(frame, pushTile);
  const uint32_t pushUs = statPushUs - pushBefore, renderUs = (micros() - start) - pushUs;
  rpc::setTimings(renderUs, pushUs);
  statRenderUs += renderUs;
  const render::Profile& prof = render::lastProfile();
  statSetupUs += prof.setupUs;
  statSkyUs += prof.skyUs;
  statRasterUs += prof.rasterUs;
  statObjectUs += prof.objectUs;
  statFogUs += prof.fogUs;
  statLive = live;
  statSeq = frame.seq;
  ++statFrames;
  uint32_t now = millis();
  if (now - statStartMs >= 2000) {
    const uint32_t rx = rpc::framesReceived();
    char json[320];
    const float perFrame = 1000.0f * statFrames, seconds = (now - statStartMs) / 1000.0f;
    snprintf(json, sizeof(json),
             "{\"fps\":%.1f,\"live\":%d,\"seq\":%u,\"rx_fps\":%.1f,\"render_ms\":%.1f,\"push_ms\":%.1f,"
             "\"setup_ms\":%.1f,\"sky_ms\":%.1f,\"raster_ms\":%.1f,\"object_ms\":%.1f,\"fog_hud_ms\":%.1f,"
             "\"quads\":%d,\"frames\":%lu}",
             statFrames / seconds, statLive ? 1 : 0, statSeq, (rx - statRxStart) / seconds,
             statRenderUs / perFrame, statPushUs / perFrame, statSetupUs / perFrame, statSkyUs / perFrame,
             statRasterUs / perFrame, statObjectUs / perFrame, statFogUs / perFrame, render::lastQuadDraws(),
             (unsigned long)statFrames);
    lastStats = json;
    statFrames = statRenderUs = statPushUs = 0;
    statSetupUs = statSkyUs = statRasterUs = statObjectUs = statFogUs = 0;
    statStartMs = now;
    statRxStart = rx;
  }
}

void setup() {
  bool bridgeOk = Bridge.begin();
  if (bridgeOk) Bridge.provide("g3d_debug_stats", debugStats);
  initStage = 1;
  inputs::begin();
  display.begin();
  display.setRotation(1);  // Landscape: 480 x 320.
  initStage = 2;
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
  if (bridgeOk) {
    rpc::begin();
    Bridge.provide_safe("arcade_read_inputs", readInputs);
    Bridge.provide_safe("arcade_video_begin", beginVideo);
    Bridge.provide_safe("arcade_video_tile", videoTile);
    Bridge.provide_safe("arcade_video_poll", pollVideo);
    Bridge.provide_safe("arcade_video_end", endVideo);
  }
  initStage = 7;
}

void loop() {
  if (videoSession) {
    if (millis() - lastVideoAt > FRAME_TIMEOUT_MS) stopVideo();
    delay(5);
    return;
  }
  renderFrame();
}
