#include "rpc.h"

#include <Arduino.h>
#include <Arduino_RouterBridge.h>
#include <zephyr/kernel.h>

#include "gen/meshes.h"
#include "gen/rigs.h"
#include "inputs.h"
#include "render.h"
#include "scene.h"

// Return Input and Caps as msgpack bin; set to 0 to fall back to hex strings (api.md §2).
#ifndef G3D_BIN_RETURN
#define G3D_BIN_RETURN 1
#endif

namespace rpc {
namespace {

struct k_mutex lock;
g3d::Frame pending;
bool havePending = false;
uint32_t pendingAtMs = 0, received = 0;
volatile uint8_t seqAck = 0, renderMs = 0, pushMs = 0;
volatile bool videoActive = false;

#if G3D_BIN_RETURN
using Reply = MsgPack::bin_t<uint8_t>;
Reply reply(const uint8_t* p, size_t n) { return Reply(p, p + n); }
#else
using Reply = String;
Reply reply(const uint8_t* p, size_t n) {
  static const char HEX_DIGITS[] = "0123456789abcdef";
  String s;
  for (size_t i = 0; i < n; ++i) {
    s += HEX_DIGITS[p[i] >> 4];
    s += HEX_DIGITS[p[i] & 15];
  }
  return s;
}
#endif

Reply hello(int version) {
  if (version != g3d::VERSION) return reply(nullptr, 0);
  uint8_t caps[g3d::CAPS_SIZE] = {g3d::VERSION};
  g3d::wr16(caps + 1, render::W);
  g3d::wr16(caps + 3, render::H);
  caps[5] = render::TILE_H;
  caps[6] = g3d::MAX_OBJ;
  caps[7] = 32;                // max slots
  caps[8] = gen::MESH_COUNT;
  caps[9] = gen::RIG_COUNT - 1;  // rig ids 1..n
  caps[10] = G3D_BIN_RETURN;   // bit0 bin return; bit1 per-pixel grading (not yet)
  return reply(caps, sizeof(caps));
}

bool sceneBegin(MsgPack::bin_t<uint8_t> header) {
  k_mutex_lock(&lock, K_FOREVER);
  const bool ok = scene::uploadBegin(header.data(), header.size());
  k_mutex_unlock(&lock);
  return ok;
}

bool sceneChunk(int kind, int index, MsgPack::bin_t<uint8_t> data) {
  if (kind < 0 || kind > 255 || index < 0 || index > 255) return false;
  k_mutex_lock(&lock, K_FOREVER);
  const bool ok = scene::uploadChunk(uint8_t(kind), uint8_t(index), data.data(), data.size());
  k_mutex_unlock(&lock);
  return ok;
}

bool sceneSky(MsgPack::bin_t<uint8_t> data) {
  k_mutex_lock(&lock, K_FOREVER);
  const bool ok = scene::uploadSky(data.data(), data.size());
  k_mutex_unlock(&lock);
  return ok;
}

bool sceneCommit(int crc) {
  if (crc < 0 || crc > 0xFFFF) return false;
  k_mutex_lock(&lock, K_FOREVER);
  const bool ok = scene::uploadCommit(uint16_t(crc));
  k_mutex_unlock(&lock);
  return ok;
}

Reply frame(MsgPack::bin_t<uint8_t> packet) {
  static g3d::Frame parsed;  // Bridge handlers run one at a time on the Bridge thread
  if (videoActive || !g3d::parseFrame(packet.data(), packet.size(), parsed)) return reply(nullptr, 0);
  k_mutex_lock(&lock, K_FOREVER);
  pending = parsed;
  havePending = true;
  pendingAtMs = millis();
  ++received;
  k_mutex_unlock(&lock);

  const inputs::Snapshot s = inputs::read();
  const uint8_t pressed = inputs::takePressed();
  uint8_t out[g3d::INPUT_SIZE] = {g3d::VERSION, seqAck, s.connected, uint8_t(s.held | (pressed << 4))};
  out[4] = uint8_t(int8_t(constrain(s.x, -128, 127)));
  out[5] = uint8_t(int8_t(constrain(s.y, -128, 127)));
  g3d::wr16(out + 6, uint16_t(s.ax));
  g3d::wr16(out + 8, uint16_t(s.ay));
  g3d::wr16(out + 10, uint16_t(s.az));
  out[12] = out[13] = 0;  // gyro is optional and not read yet
  out[14] = renderMs;
  out[15] = pushMs;
  return reply(out, sizeof(out));
}

bool release() {
  k_mutex_lock(&lock, K_FOREVER);
  havePending = false;
  k_mutex_unlock(&lock);
  return true;
}

}  // namespace

void begin() {
  k_mutex_init(&lock);
  // provide(), not provide_safe(): handlers answer from the Bridge thread without waiting for
  // the render loop. They only validate and copy, under `lock`.
  Bridge.provide("g3d_hello", hello);
  Bridge.provide("g3d_scene_begin", sceneBegin);
  Bridge.provide("g3d_scene_chunk", sceneChunk);
  Bridge.provide("g3d_scene_commit", sceneCommit);
  Bridge.provide("g3d_scene_sky", sceneSky);
  Bridge.provide("g3d_frame", frame);
  Bridge.provide("g3d_release", release);
}

bool latestFrame(g3d::Frame& out, uint32_t& ageMs) {
  k_mutex_lock(&lock, K_FOREVER);
  const bool ok = havePending;
  if (ok) {
    out = pending;
    ageMs = millis() - pendingAtMs;
  }
  k_mutex_unlock(&lock);
  return ok;
}

void markRendered(uint8_t seq) { seqAck = seq; }

bool applyScene() {
  k_mutex_lock(&lock, K_FOREVER);
  const bool changed = scene::applyUpload();
  k_mutex_unlock(&lock);
  return changed;
}

void setTimings(uint32_t renderUs, uint32_t pushUs) {
  renderMs = uint8_t(renderUs / 1000 > 255 ? 255 : renderUs / 1000);
  pushMs = uint8_t(pushUs / 1000 > 255 ? 255 : pushUs / 1000);
}

void setVideoActive(bool active) { videoActive = active; }

uint32_t framesReceived() {
  k_mutex_lock(&lock, K_FOREVER);
  const uint32_t n = received;
  k_mutex_unlock(&lock);
  return n;
}

}  // namespace rpc
