// The core compiles sketches with -Os; TGX's rasterizer templates are instantiated here.
#pragma GCC optimize("O2")

#include "render.h"

#include <math.h>
#include "src/tgx/tgx.h"

#include "gen/meshes.h"
#include "gen/rigs.h"
#include "hud.h"
#include "hud_text.h"
#include "rig.h"
#include "scene.h"

#ifndef RENDER_NO_CULL
#define RENDER_NO_CULL 0
#endif
#ifndef RENDER_NO_FOG
#define RENDER_NO_FOG 0
#endif

namespace render {
namespace {

using namespace tgx;

constexpr Shader SHADERS = SHADER_PERSPECTIVE | SHADER_ZBUFFER | SHADER_GOURAUD | SHADER_FLAT | SHADER_NOTEXTURE;
constexpr float NEAR_PLANE = 0.5f;
constexpr float SKY_SPAN = 0.55f;  // rad above the horizon where the sky reaches skyTop
constexpr int FOG_STEPS = 16;
constexpr int MAX_VERTS = scene::MAX_N * scene::MAX_N;

struct Camera {
  float x, y, z;     // m
  float yaw, pitch;  // rad; yaw 0 faces +Z, pitch > 0 looks up
  float fovX;        // rad, horizontal
};

Renderer3D<RGB565, SHADERS, uint16_t> renderer;
alignas(4) RGB565 tileBuf[W * TILE_H];
uint16_t zbuf[W * TILE_H];
Image<RGB565> tileImage(tileBuf, W, TILE_H);

fVec3 verts[MAX_VERTS];
RGBf colors[MAX_VERTS];
float screenY[MAX_VERTS];  // viewport row of each vertex this frame; NAN when behind the eye
uint8_t fogAlpha[4096];    // zbuffer >> 4 -> blend weight 0..32 towards fogColor
uint16_t baseColors[MAX_VERTS];  // baked terrain colours (RGB565); `colors` gets them plus ground fog each frame
float meshCenter[gen::MESH_COUNT][3];  // vertex centroid of each mesh, where its ground fog is sampled
fVec3 eye;                             // camera position this frame

// Ground fog (Look byte 75): thick at y = 0, gone at GROUND_FOG_TOP; it builds up over GROUND_FOG_RAMP m of
// distance so the PC in the foreground stays clear while the boss's legs and the far ground sink into mist.
// Evaluated per terrain vertex and per mesh (not per pixel), so it costs almost nothing.
constexpr float GROUND_FOG_TOP = 9.0f, GROUND_FOG_RAMP = 30.0f;

float groundFog(const fVec3& p) {
  const float g = scene::params.groundFog;
  if (g <= 0) return 0;
  float low = 1 - p.y / GROUND_FOG_TOP;
  if (low <= 0) return 0;
  low = low > 1 ? 1 : low;
  const fVec3 d = p - eye;
  const float ramp = sqrtf(d.x * d.x + d.y * d.y + d.z * d.z) / GROUND_FOG_RAMP;
  return g * low * low * (ramp > 1 ? 1 : ramp);
}
uint32_t (*clockUs)() = nullptr;
Profile profile;
uint32_t skyPattern[H][2];  // per row: 4 dithered pixels packed as two words, repeated across
int quadDraws = 0;

static_assert(sizeof(fVec3) == 3 * sizeof(float), "gen/meshes.h stores packed xyz floats");

// Everything drawn on top of the terrain this frame: rig bones and slot parts, objects, then rocks.
// Transformed once, drawn in every tile its bounding sphere overlaps.
struct ObjectDraw {
  const gen::Mesh* mesh;
  fMat4 model;
  float rowLo, rowHi;  // viewport rows covered by the bounding sphere
  uint8_t tint;        // palette index; 0 keeps the mesh colours
  bool flash;          // hit_slot: draw in FLASH
  bool charLight;      // rflags bit0: camera-relative key light
  float fade;          // 0..1 towards the fog colour
};
constexpr int MAX_DRAWS = 128;  // 3 rigs * (16 bones + their slots) + 9 objects + rocks; rocks are dropped first
ObjectDraw objects[MAX_DRAWS];
int objectCount = 0;
fVec3 sunTravel, charTravel;  // light directions as TGX wants them (the way the light travels)

// Sun material strengths, and the character light's (art.md §4, api.md §3.3).
constexpr float SUN_AMBIENT = 0.5f, SUN_DIFFUSE = 0.65f, CHAR_AMBIENT = 0.55f, CHAR_DIFFUSE = 0.6f;

RGBf toRGBf(uint16_t c) {
  return RGBf(((c >> 11) & 31) / 31.0f, ((c >> 5) & 63) / 63.0f, (c & 31) / 31.0f);
}

// RGB565 blend with weight a in 0..32 using the spread-channel trick.
inline uint16_t blend565(uint16_t c, uint16_t towards, uint32_t a) {
  uint32_t x = (c | (uint32_t(c) << 16)) & 0x07E0F81F;
  uint32_t y = (towards | (uint32_t(towards) << 16)) & 0x07E0F81F;
  uint32_t r = ((x * (32 - a) + y * a) >> 5) & 0x07E0F81F;
  return uint16_t(r | (r >> 16));
}

void bakeTerrain() {
  const scene::Params& p = scene::params;
  const int n = p.terrainN;
  const fVec3 light(cosf(p.lightPitch) * sinf(p.lightYaw), sinf(p.lightPitch),
                    cosf(p.lightPitch) * cosf(p.lightYaw));
  const RGBf grassA = toRGBf(p.grassA), grassB = toRGBf(p.grassB);
  for (int j = 0; j < n; ++j) {
    for (int i = 0; i < n; ++i) {
      const int k = j * n + i;
      const float h = scene::heights[k] * p.heightScale;
      verts[k] = fVec3(p.originX + i * p.cell, h, p.originZ + j * p.cell);
      auto at = [&](int ii, int jj) {
        ii = ii < 0 ? 0 : (ii >= n ? n - 1 : ii);
        jj = jj < 0 ? 0 : (jj >= n ? n - 1 : jj);
        return scene::heights[jj * n + ii] * p.heightScale;
      };
      fVec3 normal(at(i - 1, j) - at(i + 1, j), 2 * p.cell, at(i, j - 1) - at(i, j + 1));
      normal.normalize();
      const float shade = 0.6f + 0.4f * fmaxf(0.0f, dotProduct(normal, light));
      // Two grass tones scattered per vertex; Gouraud interpolation blends them into patches.
      uint32_t hash = uint32_t(i * 73856093) ^ uint32_t(j * 19349663);
      hash = (hash ^ (hash >> 13)) * 1274126177u;
      const RGBf& grass = ((hash >> 16) & 1) ? grassA : grassB;
      baseColors[k] = uint16_t(RGB565(RGBf(grass.R * shade, grass.G * shade, grass.B * shade)).val);
    }
  }
}

void bakeFog() {
  const scene::Params& p = scene::params;
  const float f = p.fogFar, n = NEAR_PLANE;
  const float k = (f - n) / (65536.0f * n);
  const float full = p.fogNear + (f - p.fogNear) * 0.92f;  // fully fogged just before the far clip
  for (int i = 0; i < 4096; ++i) {
    // uint16 zbuffer stores wa / depth + wb (TGX _recompute_wa_wb), so depth = f / (1 + z * k).
    const float depth = f / (1.0f + (i * 16 + 8) * k);
    float t = (depth - p.fogNear) / (full - p.fogNear);
    t = t < 0 ? 0 : (t > 1 ? 1 : t);
    fogAlpha[i] = uint8_t(lroundf(t * FOG_STEPS) * (32 / FOG_STEPS));
  }
}

// Sets the camera; returns the vertical focal length in viewport pixels.
float prepareFrame(const Camera& cam, fMat4& projView) {
  const scene::Params& p = scene::params;
  const float aspect = float(W) / H;
  const float fovY = 2 * atanf(tanf(cam.fovX / 2) / aspect);
  const fVec3 eye(cam.x, cam.y, cam.z);
  const fVec3 dir(sinf(cam.yaw) * cosf(cam.pitch), sinf(cam.pitch), cosf(cam.yaw) * cosf(cam.pitch));
  renderer.setPerspective(fovY * 180 / float(M_PI), aspect, NEAR_PLANE, p.fogFar);
  renderer.setLookAt(eye, eye + dir, fVec3(0, 1, 0));

  fMat4 proj, view;
  proj.setPerspective(fovY * 180 / float(M_PI), aspect, NEAR_PLANE, p.fogFar);
  view.setLookAt(eye, eye + dir, fVec3(0, 1, 0));
  projView = proj * view;

  const float focal = (H / 2) / tanf(fovY / 2);
  for (int y = 0; y < H; ++y) {
    const float elevation = cam.pitch + atanf((H / 2 - (y + 0.5f)) / focal);
    float t = elevation / SKY_SPAN;
    t = t < 0 ? 0 : (t > 1 ? 1 : t);
    // Ordered dither between neighbouring blend steps hides RGB565 banding.
    static const uint8_t BAYER4[4][4] = {{0, 8, 2, 10}, {12, 4, 14, 6}, {3, 11, 1, 9}, {15, 7, 13, 5}};
    const float steps = t * 32;
    const uint32_t step = uint32_t(steps);
    const uint16_t c0 = blend565(p.skyHorizon, p.skyTop, step);
    const uint16_t c1 = blend565(p.skyHorizon, p.skyTop, step < 32 ? step + 1 : 32);
    const uint8_t level = uint8_t((steps - step) * 16);
    uint16_t px[4];
    for (int x = 0; x < 4; ++x) px[x] = BAYER4[y & 3][x] < level ? c1 : c0;
    skyPattern[y][0] = px[0] | (uint32_t(px[1]) << 16);  // little-endian: first pixel in the low half
    skyPattern[y][1] = px[2] | (uint32_t(px[3]) << 16);
  }
  return focal;
}

}  // namespace

void begin() {
  renderer.setViewportSize(W, H);
  renderer.setImage(&tileImage);
  renderer.setZbuffer(zbuf);
  renderer.setCulling(0);
  renderer.setShaders(SHADER_GOURAUD);
  // Light travels away from the sun; terrain zeroes the diffuse term so its baked colours pass through.
  const scene::Params& p = scene::params;
  const fVec3 sun(cosf(p.lightPitch) * sinf(p.lightYaw), sinf(p.lightPitch), cosf(p.lightPitch) * cosf(p.lightYaw));
  sunTravel = -sun;
  renderer.setLight(sunTravel, RGBf(1, 1, 1), RGBf(1, 1, 1), RGBf(0, 0, 0));
  bakeTerrain();
  bakeFog();
  static bool centred = false;
  if (!centred) {
    centred = true;
    for (int m = 0; m < gen::MESH_COUNT; ++m) {
      const gen::Mesh& mesh = gen::MESHES[m];
      int n = 0;
      float c[3] = {0, 0, 0};
      for (int t = 0; t < mesh.nTris * 3; ++t, ++n)
        for (int a = 0; a < 3; ++a) c[a] += mesh.verts[3 * mesh.tris[t] + a];
      for (int a = 0; a < 3; ++a) meshCenter[m][a] = n ? c[a] / n : 0;
    }
  }
}

inline uint32_t now() { return clockUs ? clockUs() : 0; }

namespace {

fMat4 toMat4(const rig::Xf& x) {
  fMat4 m;  // TGX is column-major: M[col * 4 + row]
  for (int c = 0; c < 3; ++c)
    for (int r = 0; r < 3; ++r) m.M[c * 4 + r] = x.r[r][c];
  m.M[3] = m.M[7] = m.M[11] = 0;
  m.M[12] = x.t[0];
  m.M[13] = x.t[1];
  m.M[14] = x.t[2];
  m.M[15] = 1;
  return m;
}

// Queues one mesh at `model` (origin at `center`, bounding radius `radius`) if it can be visible.
void addDraw(uint8_t meshId, const fMat4& model, const fVec3& center, float scale, const fMat4& projView, float focal,
             uint8_t tint, bool flash, bool charLight, float fade) {
  if (objectCount >= MAX_DRAWS || meshId >= gen::MESH_COUNT || !gen::MESHES[meshId].nTris) return;
  const gen::Mesh* mesh = &gen::MESHES[meshId];
  const float radius = mesh->radius * scale;
  const fVec4 clip = projView.mult1(center);
  if (clip.w < -radius || clip.w - radius > scene::params.fogFar) return;  // behind or beyond the far plane
  ObjectDraw& d = objects[objectCount];
  if (clip.w > radius) {
    const float row = (1 - clip.y / clip.w) * (H / 2), reach = radius * focal / clip.w + 2;
    d.rowLo = row - reach;
    d.rowHi = row + reach;
    if (d.rowHi < 0 || d.rowLo > H) return;
  } else {
    d.rowLo = -1e9f;  // straddles the eye plane: draw in every tile
    d.rowHi = 1e9f;
  }
  d.mesh = mesh;
  d.model = model;
  d.tint = tint < 32 ? tint : 0;
  d.flash = flash;
  d.charLight = charLight;
  const fVec4 c = model.mult1(fVec3(meshCenter[meshId][0], meshCenter[meshId][1], meshCenter[meshId][2]));
  const float g = flash ? 0 : groundFog(fVec3(c.x, c.y, c.z));
  d.fade = fade > g ? fade : g;  // ground fog reuses the fade path: blend towards the fog colour
  ++objectCount;
}

// T(pos) * Ry(yaw) * Rx(pitch) * S(scale); TGX mult* pre-multiplies.
fMat4 objectModel(float x, float y, float z, float yaw, float pitch, float scale) {
  fMat4 m;
  m.setScale(scale, scale, scale);
  m.multRotate(pitch * (180 / float(M_PI)), 1, 0, 0);
  m.multRotate(yaw * (180 / float(M_PI)), 0, 1, 0);
  m.multTranslate(x, y, z);
  return m;
}

void addRig(const g3d::RigState& s, bool boss, const fMat4& projView, float focal) {
  if (!s.rigId || s.rigId >= gen::RIG_COUNT || s.fade >= 1) return;
  const gen::Rig& r = gen::RIGS[s.rigId];
  static rig::Xf bones[rig::MAX_BONES], world[rig::MAX_BONES];  // static: keep 1.5 KB off the render stack
  if (!rig::pose(r, s.anim, s.phase, bones)) return;
  const rig::Xf place = rig::placement(s.x, s.y, s.z, s.yaw);
  for (int i = 0; i < r.nBones; ++i) {
    world[i] = rig::compose(place, bones[i]);
    const fVec3 c(world[i].t[0], world[i].t[1], world[i].t[2]);
    addDraw(r.bones[i].mesh, toMat4(world[i]), c, 1, projView, focal, 0, false, s.charLight, s.fade);
  }
  for (int i = 0; i < r.nSlots && i < 32; ++i) {
    if (!(s.partAlive >> i & 1)) continue;
    const gen::RigSlot& slot = r.slots[i];
    // Slot variants come from the scene header for the boss; other rigs show variant 1.
    const int v = boss && s.rigId == scene::bossRig ? (i < scene::nSlots ? scene::slotVariant[i] : 0) : 1;
    if (v <= 0 || v >= slot.nVariants) continue;
    rig::Xf local = rig::euler(slot.rot);
    for (int c = 0; c < 3; ++c) local.t[c] = slot.offset[c];
    const rig::Xf x = rig::compose(world[slot.bone], local);
    addDraw(slot.variants[v], toMat4(x), fVec3(x.t[0], x.t[1], x.t[2]), 1, projView, focal, 0, s.hitSlot == i,
            s.charLight, s.fade);
  }
}

void prepareObjects(const g3d::Frame& f, const fMat4& projView, float focal, float camX, float camZ) {
  objectCount = 0;
  for (int k = 0; k < g3d::FRAME_RIGS; ++k) addRig(f.rig[k], k == 0, projView, focal);
  for (int i = 0; i < f.nObj; ++i) {
    const g3d::Object& o = f.obj[i];
    addDraw(o.mesh, objectModel(o.x, o.y, o.z, o.yaw, o.pitch, o.scale), fVec3(o.x, o.y, o.z), o.scale, projView,
            focal, o.tint, false, false, 0);
  }
  const float reach = scene::params.fogFar;
  for (int i = 0; i < scene::nRocks; ++i) {
    const scene::Rock& k = scene::rocks[i];
    const float dx = k.x - camX, dz = k.z - camZ;
    if (dx * dx + dz * dz > (reach + 8) * (reach + 8)) continue;  // cheap reject before the projection
    addDraw(k.mesh, objectModel(k.x, k.y, k.z, k.yaw, 0, k.scale), fVec3(k.x, k.y, k.z), k.scale, projView, focal,
            k.tint, false, false, 0);
  }
}

void drawObjects(int top) {
  bool started = false, charLight = false;
  const RGBf fog = toRGBf(scene::params.fogColor), flash = toRGBf(scene::palette[gen::PAL_FLASH]);
  for (int i = 0; i < objectCount; ++i) {
    const ObjectDraw& d = objects[i];
    if (d.rowHi < top || d.rowLo > top + TILE_H) continue;
    if (!started) {
      renderer.setShaders(SHADER_FLAT);
      renderer.setCulling(1);  // OBJ front faces are counter-clockwise (art.md §8)
      started = true;
    }
    if (d.charLight != charLight) {
      renderer.setLightDirection(d.charLight ? charTravel : sunTravel);
      charLight = d.charLight;
    }
    // Fade blends towards the fog colour and flattens the lighting, so fade 1 is exactly the fog.
    const float k = d.fade, ambient = d.charLight ? CHAR_AMBIENT : SUN_AMBIENT;
    const float diffuse = d.charLight ? CHAR_DIFFUSE : SUN_DIFFUSE;
    renderer.setMaterial(RGBf(1, 1, 1), ambient * (1 - k) + k, diffuse * (1 - k), 0.0f, 1);
    renderer.setModelMatrix(d.model);
    const fVec3* verts = reinterpret_cast<const fVec3*>(d.mesh->verts);
    uint16_t first = 0;
    for (int g = 0; g < d.mesh->nGroups; ++g) {
      const uint16_t end = d.mesh->groupEnd[g];
      RGBf c = d.flash ? flash : toRGBf(scene::palette[d.tint ? d.tint : d.mesh->groupColor[g]]);
      if (k > 0) c = RGBf(c.R + (fog.R - c.R) * k, c.G + (fog.G - c.G) * k, c.B + (fog.B - c.B) * k);
      renderer.setMaterialColor(c);
      renderer.drawTriangles(end - first, d.mesh->tris + 3 * first, verts);
      first = end;
    }
  }
  if (started) {
    if (charLight) renderer.setLightDirection(sunTravel);
    fMat4 identity;
    identity.setIdentity();
    renderer.setModelMatrix(identity);
    renderer.setShaders(SHADER_GOURAUD);
    renderer.setCulling(0);
  }
}

}  // namespace

void frame(const g3d::Frame& f, PushTile push) {
  const scene::Params& p = scene::params;
  const int n = p.terrainN;
  profile = Profile{};
  uint32_t t0 = now();
  const Camera cam{f.camX, f.camY, f.camZ, f.camYaw, f.camPitch, f.fovX};
  fMat4 projView;
  const float focal = prepareFrame(cam, projView);
  // Character light: from just above and right of the camera (api.md §3.3); TGX wants the travel direction.
  const fVec3 forward(sinf(cam.yaw) * cosf(cam.pitch), sinf(cam.pitch), cosf(cam.yaw) * cosf(cam.pitch));
  const fVec3 right(-cosf(cam.yaw), 0, sinf(cam.yaw));
  fVec3 key = -forward + fVec3(0, 0.7f, 0) + right * 0.45f;
  key.normalize();
  charTravel = -key;
  eye = fVec3(cam.x, cam.y, cam.z);  // groundFog() measures from here
  prepareObjects(f, projView, focal, cam.x, cam.z);

  const RGBf fogRGB = toRGBf(p.fogColor);
  for (int k = 0; k < n * n; ++k) {
    const RGBf base = toRGBf(baseColors[k]);
    const float g = groundFog(verts[k]);
    colors[k] = RGBf(base.R + (fogRGB.R - base.R) * g, base.G + (fogRGB.G - base.G) * g, base.B + (fogRGB.B - base.B) * g);
    const fVec4 clip = projView.mult1(verts[k]);
    // Image rows grow downwards while NDC y grows upwards (checked against the desktop preview).
    screenY[k] = clip.w > NEAR_PLANE * 0.5f ? (1 - clip.y / clip.w) * (H / 2) : NAN;
  }

  quadDraws = 0;
  profile.setupUs = now() - t0;
  const bool fog = !RENDER_NO_FOG && !(f.flags & g3d::FLAG_NO_FOG);
  uint16_t* pixels = reinterpret_cast<uint16_t*>(tileBuf);
  for (int tile = 0; tile < TILES; ++tile) {
    const int top = tile * TILE_H;
    t0 = now();
    renderer.setOffset(0, top);
    uint32_t* words = reinterpret_cast<uint32_t*>(pixels);
    for (int y = 0; y < TILE_H; ++y) {
      const uint32_t w0 = skyPattern[top + y][0], w1 = skyPattern[top + y][1];
      for (int x = 0; x < W / 2; x += 2) {
        words[x] = w0;
        words[x + 1] = w1;
      }
      words += W / 2;
    }
    renderer.clearZbuffer();
    uint32_t t1 = now();
    profile.skyUs += t1 - t0;

    renderer.setMaterial(RGBf(1, 1, 1), 1.0f, 0.0f, 0.0f, 1);
    for (int j = 0; j + 1 < n; ++j) {
      for (int i = 0; i + 1 < n; ++i) {
        const int a = j * n + i, b = a + 1, c = a + n, d = c + 1;
        const float ya = screenY[a], yb = screenY[b], yc = screenY[c], yd = screenY[d];
        if (!RENDER_NO_CULL && !isnan(ya) && !isnan(yb) && !isnan(yc) && !isnan(yd)) {
          const float lo = fminf(fminf(ya, yb), fminf(yc, yd));
          const float hi = fmaxf(fmaxf(ya, yb), fmaxf(yc, yd));
          if (hi < top - 1 || lo > top + TILE_H + 1) continue;
        }
        renderer.drawTriangleWithVertexColor(verts[a], verts[c], verts[b], colors[a], colors[c], colors[b]);
        renderer.drawTriangleWithVertexColor(verts[b], verts[c], verts[d], colors[b], colors[c], colors[d]);
        ++quadDraws;
      }
    }
    uint32_t t2 = now();
    profile.rasterUs += t2 - t1;
    drawObjects(top);
    uint32_t t3 = now();
    profile.objectUs += t3 - t2;

    if (fog) {
      for (int i = 0; i < W * TILE_H; ++i) {
        const uint16_t z = zbuf[i];
        if (!z) continue;  // sky
        const uint32_t a = fogAlpha[z >> 4];
        if (a) pixels[i] = blend565(pixels[i], p.fogColor, a);
      }
    }
    if (f.flags & g3d::FLAG_HURT) {
      const uint16_t hurt = gen::PALETTE[gen::PAL_HURT];
      for (int i = 0; i < W * TILE_H; ++i) pixels[i] = blend565(pixels[i], hurt, 8);
    }
    hud::drawTile(pixels, W, TILE_H, top, f);
    profile.fogUs += now() - t3;
    push(tile, pixels);
  }
}

int lastQuadDraws() { return quadDraws; }
void setClock(uint32_t (*micros)()) { clockUs = micros; }
const Profile& lastProfile() { return profile; }

g3d::Frame demoFrame(float seconds) {
  // Orbit the boss while it cycles through its animations and the PC gallops around it.
  g3d::Frame f = {};
  const float angle = seconds * 2 * float(M_PI) / 40;
  const float radius = 30;
  const float ground = scene::terrainHeight(0, 0);
  f.camX = radius * sinf(angle);
  f.camZ = radius * cosf(angle);
  f.camY = scene::terrainHeight(f.camX, f.camZ) + 4.0f;
  f.camYaw = angle + float(M_PI);  // face the arena centre
  f.camPitch = atan2f(ground + 6.5f - f.camY, radius);
  f.fovX = 75 * float(M_PI) / 180;
  f.state = g3d::READY;
  f.msg = hud::MSG_WAITING;

  static const uint8_t SHOW[] = {gen::ANIM_MOOSE_IDLE,       gen::ANIM_MOOSE_WALK,  gen::ANIM_MOOSE_PUNCH_R,
                                 gen::ANIM_MOOSE_SWEEP,      gen::ANIM_MOOSE_REAR_STOMP, gen::ANIM_MOOSE_SHAKE,
                                 gen::ANIM_MOOSE_KNEEL,      gen::ANIM_MOOSE_RISE};
  constexpr float SHOW_SECONDS = 3.0f;
  const int step = int(seconds / SHOW_SECONDS) % int(sizeof(SHOW));
  const float t = fmodf(seconds, SHOW_SECONDS) / SHOW_SECONDS;
  const gen::RigAnim& a = gen::RIGS[gen::RIG_MOOSE].anims[SHOW[step]];
  g3d::RigState& boss = f.rig[0];
  boss = g3d::RigState{gen::RIG_MOOSE, SHOW[step], uint8_t(a.loop ? int(t * 512) & 255 : int(t * 255)), 0xFF,
                       0, ground, 0, float(M_PI), 0xFFFFFFFFu, false, 0};

  // Horse + rider on a 14 m circle; the rider sits on the saddle attach (api.md §3.3).
  const float lap = seconds * 9.0f / 14.0f;
  const float hx = 14 * sinf(lap), hz = 14 * cosf(lap), hyaw = lap + float(M_PI) / 2;
  const uint8_t gait = uint8_t(int(seconds * 560) & 255);
  const float hy = scene::terrainHeight(hx, hz);
  f.rig[1] = g3d::RigState{gen::RIG_HORSE, gen::ANIM_HORSE_GALLOP, gait, 0xFF, hx, hy, hz, hyaw, 0, true, 0};
  static rig::Xf bones[rig::MAX_BONES];
  const gen::Rig& horse = gen::RIGS[gen::RIG_HORSE];
  rig::pose(horse, gen::ANIM_HORSE_GALLOP, gait, bones);
  const gen::RigAttach& sad = horse.attach[gen::ATTACH_HORSE_SADDLE];
  float saddle[3];
  rig::apply(rig::compose(rig::placement(hx, hy, hz, hyaw), bones[sad.bone]), sad.offset, saddle);
  const float riderRootY = gen::RIGS[gen::RIG_PC].bones[0].offset[1];
  f.rig[2] = g3d::RigState{gen::RIG_PC, gen::ANIM_PC_RIDE, gait, 0xFF, saddle[0], saddle[1] - riderRootY, saddle[2],
                           hyaw, 0, true, 0};
  return f;
}

}  // namespace render
