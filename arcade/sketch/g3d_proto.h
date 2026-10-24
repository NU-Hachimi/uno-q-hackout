#pragma once

#include <stddef.h>
#include <stdint.h>

// g3d wire format (docs/api.md §3). Platform-independent: the desktop preview parses with it too.
namespace g3d {

constexpr uint8_t VERSION = 2;
constexpr int MAX_OBJ = 9, MAX_PAYLOAD = 192, INPUT_SIZE = 16, CAPS_SIZE = 11;
constexpr int FRAME_RIGS = 3, RIG_SIZE = 17;  // blocks: 0 boss, 1 horse, 2 rider
constexpr int HEADER_SIZE = 24 + FRAME_RIGS * RIG_SIZE + 8, OBJ_SIZE = 12;  // 83

enum State : uint8_t { READY = 0, FIGHT = 1, WIN = 2, LOSE = 3, PAUSED = 4 };

enum Flag : uint8_t {
  FLAG_WIREFRAME = 1,
  FLAG_NO_FOG = 2,
  FLAG_NO_HUD = 4,
  FLAG_HURT = 8,
  FLAG_FREEZE = 16,
  FLAG_NO_GRADE = 32,
};

struct Object {
  uint8_t mesh, tint;       // tint: palette index, 0 keeps the mesh colours
  float x, y, z;            // m
  float yaw, pitch, scale;  // rad, rad, factor
};

struct RigState {
  uint8_t rigId, anim, phase, hitSlot;  // rigId 0: not drawn; hitSlot 0xFF: none
  float x, y, z, yaw;                   // m, rad
  uint32_t partAlive;
  bool charLight;                       // rflags bit0
  float fade;                           // rflags bits1-7 as 0..1 (1 = not drawn)
};

struct Frame {
  uint8_t seq, flags, nObj;
  float camX, camY, camZ, camYaw, camPitch, fovX;  // m and rad
  uint8_t state, hp, hpMax, bossHp, msg;
  int16_t reticleX, reticleY;  // px offset from the 240x160 centre
  uint8_t reticleFlags, timer;
  RigState rig[FRAME_RIGS];
  uint8_t hookFlags;
  float anchorX, anchorY, anchorZ;
  Object obj[MAX_OBJ];
};

// Validates and decodes one g3d_frame packet; false leaves `out` unspecified.
bool parseFrame(const uint8_t* p, size_t n, Frame& out);

// CRC-16/CCITT-FALSE, chainable through `crc`.
uint16_t crc16(const uint8_t* p, size_t n, uint16_t crc = 0xFFFF);

inline uint16_t rd16(const uint8_t* p) { return uint16_t(p[0] | (p[1] << 8)); }
inline int16_t rd16s(const uint8_t* p) { return int16_t(rd16(p)); }
inline uint32_t rd32(const uint8_t* p) { return rd16(p) | (uint32_t(rd16(p + 2)) << 16); }
inline void wr16(uint8_t* p, uint16_t v) {
  p[0] = uint8_t(v);
  p[1] = uint8_t(v >> 8);
}

}  // namespace g3d
