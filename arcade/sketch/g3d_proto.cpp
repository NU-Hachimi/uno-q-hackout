#include "g3d_proto.h"

namespace g3d {
namespace {

constexpr float TAU = 6.28318530718f;

inline float pos(const uint8_t* p) { return rd16s(p) / 64.0f; }
inline float bam16(uint16_t v) { return v * (TAU / 65536.0f); }
inline float bam16s(int16_t v) { return v * (TAU / 65536.0f); }
inline float bam8s(int8_t v) { return v * (TAU / 256.0f); }

}  // namespace

bool parseFrame(const uint8_t* p, size_t n, Frame& f) {
  if (n < size_t(HEADER_SIZE) || p[0] != VERSION) return false;
  f.nObj = p[3];
  if (f.nObj > MAX_OBJ || n != size_t(HEADER_SIZE + OBJ_SIZE * f.nObj)) return false;
  f.seq = p[1];
  f.flags = p[2];
  f.camX = pos(p + 4);
  f.camY = pos(p + 6);
  f.camZ = pos(p + 8);
  f.camYaw = bam16(rd16(p + 10));
  f.camPitch = bam16s(rd16s(p + 12));
  if (p[14] < 10 || p[14] > 170) return false;
  f.fovX = p[14] * (TAU / 360.0f);
  f.state = p[15];
  f.hp = p[16];
  f.hpMax = p[17];
  if (f.state > PAUSED || f.hpMax > 10) return false;
  f.bossHp = p[18];
  f.msg = p[19];
  f.reticleX = int8_t(p[20]) * 2;
  f.reticleY = int8_t(p[21]) * 2;
  f.reticleFlags = p[22];
  f.timer = p[23];

  for (int k = 0; k < FRAME_RIGS; ++k) {
    const uint8_t* r = p + 24 + RIG_SIZE * k;
    RigState& s = f.rig[k];
    s.rigId = r[0];
    s.anim = r[1];
    s.phase = r[2];
    s.hitSlot = r[3];
    s.x = pos(r + 4);
    s.y = pos(r + 6);
    s.z = pos(r + 8);
    s.yaw = bam16(rd16(r + 10));
    s.partAlive = rd32(r + 12);
    s.charLight = r[16] & 1;
    s.fade = (r[16] >> 1) / 127.0f;
  }

  const uint8_t* hook = p + 24 + RIG_SIZE * FRAME_RIGS;
  f.hookFlags = hook[0];
  f.anchorX = pos(hook + 2);
  f.anchorY = pos(hook + 4);
  f.anchorZ = pos(hook + 6);

  for (int i = 0; i < f.nObj; ++i) {
    const uint8_t* o = p + HEADER_SIZE + OBJ_SIZE * i;
    Object& obj = f.obj[i];
    obj.mesh = o[0];
    obj.tint = o[1];
    obj.x = pos(o + 2);
    obj.y = pos(o + 4);
    obj.z = pos(o + 6);
    obj.yaw = bam16(rd16(o + 8));
    obj.pitch = bam8s(int8_t(o[10]));
    obj.scale = o[11] / 16.0f;
  }
  return true;
}

uint16_t crc16(const uint8_t* p, size_t n, uint16_t crc) {
  while (n--) {
    crc ^= uint16_t(*p++) << 8;
    for (int i = 0; i < 8; ++i) crc = (crc & 0x8000) ? uint16_t((crc << 1) ^ 0x1021) : uint16_t(crc << 1);
  }
  return crc;
}

}  // namespace g3d
