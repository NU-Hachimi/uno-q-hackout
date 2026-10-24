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
uint16_t baseColors[MAX_VERTS];  // baked terrain colours; `colors` gets them plus ground fog each frame
RGBf colors[MAX_VERTS];
float screenY[MAX_VERTS];  // viewport row of each vertex this frame; NAN when behind the eye
uint8_t fogAlpha[4096];    // zbuffer >> 4 -> blend weight 0..32 towards fogColor
uint32_t (*clockUs)() = nullptr;
Profile profile;
uint32_t skyPattern[H][2];  // per row: 4 dithered pixels packed as two words, repeated across
int quadDraws = 0;

static_assert(sizeof(fVec3) == 3 * sizeof(float), "gen/meshes.h stores packed xyz floats");

// Meshes of the current frame (rig bones, boss parts, objects, then rocks), transformed once and drawn
// in every tile their bounding sphere overlaps.
struct ObjectDraw {
  const gen::Mesh* mesh;
  fMat4 model;
  float rowLo, rowHi;  // viewport rows covered by the bounding sphere
  uint8_t tint;
  bool charLight;      // rig rflags bit0: the camera-relative key light instead of the sun
  float fade;          // 0..1 towards the fog colour: rig rflags fade, or ground fog
};
// 3 rigs * 16 bones + 32 parts + 9 objects = 89, leaving 23 for the rocks within the fog; rocks are queued
// last, so they are what gets dropped if the list is ever full.
constexpr int MAX_DRAWS = 112;
ObjectDraw objects[MAX_DRAWS];
int objectCount = 0;

// Sun and character light (api.md §3.3), as the direction the light travels; material strengths.
fVec3 sunTravel, charTravel;
constexpr float SUN_AMBIENT = 0.5f, SUN_DIFFUSE = 0.65f, CHAR_AMBIENT = 0.55f, CHAR_DIFFUSE = 0.6f;

// Ground fog (Look byte 75): thick at y = 0, gone at GROUND_FOG_TOP; it builds up over GROUND_FOG_RAMP m
// from the eye, so the PC stays clear while the boss's legs and the far ground sink into mist. Evaluated
// per terrain vertex and per mesh, not per pixel, so it costs almost nothing.
constexpr float GROUND_FOG_TOP = 9.0f, GROUND_FOG_RAMP = 30.0f;
float meshCenter[gen::MESH_COUNT][3];  // vertex centroid of each mesh, where its ground fog is sampled
fVec3 eye;

float groundFog(const fVec3& p) {
  const float g = scene::params.groundFog;
  float low = 1 - p.y / GROUND_FOG_TOP;
  if (g <= 0 || low <= 0) return 0;
  low = low > 1 ? 1 : low;
  const float ramp = (p - eye).norm() / GROUND_FOG_RAMP;
  return g * low * low * (ramp > 1 ? 1 : ramp);
}

// Hook rope (api.md §3.3 Hook block): a camera-facing strip from the PC's hand to the anchor.
constexpr float ROPE_HALF_WIDTH = 0.06f;  // m
bool ropeVisible = false;
fVec3 rope[4];

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
      baseColors[k] = RGB565(RGBf(grass.R * shade, grass.G * shade, grass.B * shade)).val;
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
  for (int m = 0; m < gen::MESH_COUNT && !centred; ++m) {
    const gen::Mesh& mesh = gen::MESHES[m];
    float c[3] = {0, 0, 0};
    for (int t = 0; t < mesh.nTris * 3; ++t)
      for (int a = 0; a < 3; ++a) c[a] += mesh.verts[3 * mesh.tris[t] + a];
    for (int a = 0; a < 3; ++a) meshCenter[m][a] = mesh.nTris ? c[a] / (mesh.nTris * 3) : 0;
  }
  centred = true;
}

inline uint32_t now() { return clockUs ? clockUs() : 0; }

namespace {

// Queues a mesh whose origin sits at (x, y, z); false when it is behind the eye or past the far plane.
bool addDraw(uint8_t meshId, const fMat4& model, float x, float y, float z, float scale, uint8_t tint,
             const fMat4& projView, float focal, bool charLight = false, float fade = 0) {
  if (meshId >= gen::MESH_COUNT || !gen::MESHES[meshId].nTris || objectCount >= MAX_DRAWS) return false;
  ObjectDraw& d = objects[objectCount];
  d.mesh = &gen::MESHES[meshId];
  d.tint = tint < 32 ? tint : 0;
  const float radius = d.mesh->radius * scale;
  const fVec4 clip = projView.mult1(fVec3(x, y, z));
  if (clip.w < -radius || clip.w - radius > scene::params.fogFar) return false;
  if (clip.w > radius) {
    const float row = (1 - clip.y / clip.w) * (H / 2), reach = radius * focal / clip.w + 2;
    d.rowLo = row - reach;
    d.rowHi = row + reach;
  } else {
    d.rowLo = -1e9f;  // straddles the eye plane: draw in every tile
    d.rowHi = 1e9f;
  }
  d.model = model;
  d.charLight = charLight;
  const float* c = meshCenter[meshId];
  const fVec4 centre = model.mult1(fVec3(c[0], c[1], c[2]));
  const float fog = tint == gen::PAL_FLASH ? 0 : groundFog(fVec3(centre.x, centre.y, centre.z));
  d.fade = fade > fog ? fade : fog;  // ground fog reuses the fade path
  ++objectCount;
  return true;
}

fMat4 toMat4(const rig::Xform& m) {
  return fMat4(m.r[0], m.r[1], m.r[2], m.t[0], m.r[3], m.r[4], m.r[5], m.t[1], m.r[6], m.r[7], m.r[8], m.t[2], 0, 0, 0,
               1);
}

// Boss bones and the parts that are fitted (scene slot variant) and still alive (frame part_alive).
// One rig block: its bones, and for the boss (block 0) the parts that are fitted (scene slot variant)
// and still alive (part_alive).
void prepareRig(const g3d::RigState& k, bool boss, const fMat4& projView, float focal) {
  const gen::Rig* r = rig::find(k.rigId);
  static rig::Xform bones[rig::MAX_BONES];  // static: keep 0.8 KB off the render stack
  if (!r || k.fade >= 1 || !rig::pose(*r, k.anim, k.phase, bones)) return;
  const rig::Xform base = rig::rigToWorld(k.x, k.y, k.z, k.yaw);
  for (int b = 0; b < r->nBones; ++b) {
    const rig::Xform w = rig::compose(base, bones[b]);
    addDraw(r->bones[b].mesh, toMat4(w), w.t[0], w.t[1], w.t[2], 1, 0, projView, focal, k.charLight, k.fade);
  }
  for (int s = 0; boss && s < r->nSlots && s < 32; ++s) {
    const uint8_t variant = scene::slotVariant(s);
    if (!variant || variant >= r->slots[s].nVariants || !(k.partAlive & (1u << s))) continue;
    const rig::Xform w = rig::compose(base, rig::slot(*r, bones, s));
    addDraw(r->slots[s].variantMesh[variant], toMat4(w), w.t[0], w.t[1], w.t[2], 1,
            k.hitSlot == s ? gen::PAL_FLASH : 0, projView, focal, k.charLight, k.fade);
  }
}

// World position of the rider's hand (rig block 2), the rope's start; false without a rider.
bool riderHand(const g3d::Frame& f, fVec3& out) {
  const g3d::RigState& k = f.rig[2];
  const gen::Rig* r = rig::find(k.rigId);
  static rig::Xform bones[rig::MAX_BONES];
  if (r != &gen::RIG_PC || !rig::pose(*r, k.anim, k.phase, bones)) return false;
  const gen::RigAttach& a = r->attach[gen::RIG_PC_HAND];
  float p[3];
  rig::apply(rig::compose(rig::rigToWorld(k.x, k.y, k.z, k.yaw), bones[a.bone]), a.offset, p);
  out = fVec3(p[0], p[1], p[2]);
  return true;
}

void prepareRocks(const fMat4& projView, float focal) {
  const float reach = scene::params.fogFar + 8;
  for (int i = 0; i < scene::nRocks; ++i) {
    const scene::Rock& k = scene::rocks[i];
    const float dx = k.x - eye.x, dz = k.z - eye.z;
    if (dx * dx + dz * dz > reach * reach) continue;  // cheap reject before the projection
    // Off to the side of the view (addDraw only culls by rows): |x| > w with a margin for the radius.
    const fVec4 clip = projView.mult1(fVec3(k.x, k.y, k.z));
    const float margin = gen::MESHES[k.mesh < gen::MESH_COUNT ? k.mesh : 0].radius * k.scale * 2;
    if (clip.x > clip.w + margin || clip.x < -clip.w - margin) continue;
    fMat4 model;
    model.setScale(k.scale, k.scale, k.scale);
    model.multRotate(k.yaw * (180 / float(M_PI)), 0, 1, 0);
    model.multTranslate(k.x, k.y, k.z);
    addDraw(k.mesh, model, k.x, k.y, k.z, k.scale, k.tint, projView, focal);
  }
}

// World position of the PC mesh's hand (single-mesh PC, without a rider rig); false if there is none.
bool meshHand(const g3d::Frame& f, fVec3& out) {
  for (int i = 0; i < f.nObj; ++i) {
    const g3d::Object& o = f.obj[i];
    if (o.mesh != 0) continue;
    fMat4 model;
    model.setScale(o.scale, o.scale, o.scale);
    model.multRotate(o.pitch * (180 / float(M_PI)), 1, 0, 0);
    model.multRotate(o.yaw * (180 / float(M_PI)), 0, 1, 0);
    model.multTranslate(o.x, o.y, o.z);
    const fVec4 h = model.mult1(fVec3(gen::ATTACH_PC_HAND[0], gen::ATTACH_PC_HAND[1], gen::ATTACH_PC_HAND[2]));
    out = fVec3(h.x, h.y, h.z);
    return true;
  }
  return false;
}

void prepareRope(const g3d::Frame& f) {
  ropeVisible = false;
  fVec3 hand;  // the rope starts at the rider's hand, or the PC mesh's
  if (!(f.hookFlags & 1) || !(riderHand(f, hand) || meshHand(f, hand))) return;
  const fVec3 anchor(f.anchorX, f.anchorY, f.anchorZ);
  fVec3 side = crossProduct(anchor - hand, (hand + anchor) * 0.5f - eye);
  const float len = side.norm();
  if (len < 1e-6f) return;
  side *= ROPE_HALF_WIDTH / len;
  rope[0] = hand + side;
  rope[1] = hand - side;
  rope[2] = anchor + side;
  rope[3] = anchor - side;
  ropeVisible = true;
}

void drawRope() {
  if (!ropeVisible) return;
  renderer.setShaders(SHADER_FLAT);
  renderer.setMaterial(toRGBf(scene::palette[gen::PAL_ROPE]), 1.0f, 0.0f, 0.0f, 1);  // unlit, constant colour
  renderer.drawTriangle(rope[0], rope[1], rope[2]);
  renderer.drawTriangle(rope[2], rope[1], rope[3]);
  renderer.setShaders(SHADER_GOURAUD);
}

void prepareObjects(const g3d::Frame& f, const fMat4& projView, float focal) {
  for (int i = 0; i < f.nObj; ++i) {
    const g3d::Object& o = f.obj[i];
    // T(pos) * Ry(yaw) * Rx(pitch) * S(scale); TGX mult* pre-multiplies.
    fMat4 model;
    model.setScale(o.scale, o.scale, o.scale);
    model.multRotate(o.pitch * (180 / float(M_PI)), 1, 0, 0);
    model.multRotate(o.yaw * (180 / float(M_PI)), 0, 1, 0);
    model.multTranslate(o.x, o.y, o.z);
    addDraw(o.mesh, model, o.x, o.y, o.z, o.scale, o.tint, projView, focal);  // 0xFF and unknown ids skip
  }
}

void drawObjects(int top) {
  bool started = false, charLight = false;
  const RGBf fog = toRGBf(scene::params.fogColor);
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
    const float k = d.fade;
    renderer.setMaterial(RGBf(1, 1, 1), (d.charLight ? CHAR_AMBIENT : SUN_AMBIENT) * (1 - k) + k,
                         (d.charLight ? CHAR_DIFFUSE : SUN_DIFFUSE) * (1 - k), 0.0f, 1);
    renderer.setModelMatrix(d.model);
    const fVec3* verts = reinterpret_cast<const fVec3*>(d.mesh->verts);
    uint16_t first = 0;
    for (int g = 0; g < d.mesh->nGroups; ++g) {
      const uint16_t end = d.mesh->groupEnd[g];
      RGBf c = toRGBf(scene::palette[d.tint ? d.tint : d.mesh->groupColor[g]]);
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
  eye = fVec3(cam.x, cam.y, cam.z);
  // Character light: from just above and right of the camera (api.md §3.3).
  const fVec3 forward(sinf(cam.yaw) * cosf(cam.pitch), sinf(cam.pitch), cosf(cam.yaw) * cosf(cam.pitch));
  fVec3 key = -forward + fVec3(0, 0.7f, 0) + fVec3(-cosf(cam.yaw), 0, sinf(cam.yaw)) * 0.45f;
  key.normalize();
  charTravel = -key;
  objectCount = 0;
  for (int k = 0; k < g3d::FRAME_RIGS; ++k) prepareRig(f.rig[k], k == 0, projView, focal);
  prepareObjects(f, projView, focal);
  prepareRocks(projView, focal);  // last: dropped first when the draw list is full
  prepareRope(f);

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
    drawRope();
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
  g3d::Frame f = {};
  const float angle = seconds * 2 * float(M_PI) / 60;
  const float radius = 26;
  const float ground = scene::terrainHeight(0, 0);
  f.camX = radius * sinf(angle);
  f.camZ = radius * cosf(angle);
  f.camY = scene::terrainHeight(f.camX, f.camZ) + 3.0f;
  f.camYaw = angle + float(M_PI);  // face the arena centre
  f.camPitch = atan2f(ground + 6.0f - f.camY, radius);
  f.fovX = 75 * float(M_PI) / 180;
  f.state = g3d::READY;
  f.msg = hud::MSG_WAITING;
  // The moose breathing in the arena (idle, 4 s per loop) with every fitted part alive.
  f.rig[0] = g3d::RigState{uint8_t(scene::rigId() ? scene::rigId() : 1), 0, uint8_t(int(seconds * 64) & 0xFF), 0xFF,
                           0, ground, 0, 0, 0xFFFFFFFFu, false, 0};
  // The PC galloping around it on a 14 m circle, the rider on the saddle (api.md §3.3), for scale.
  const float lap = seconds * 9.0f / 14.0f;
  const float hx = 14 * sinf(lap), hz = 14 * cosf(lap), hyaw = lap + float(M_PI) / 2;
  const float hy = scene::terrainHeight(hx, hz);
  const uint8_t gait = uint8_t(int(seconds * 560) & 0xFF);
  f.rig[1] = g3d::RigState{3, 0, gait, 0xFF, hx, hy, hz, hyaw, 0, true, 0};  // horse, gallop
  static rig::Xform bones[rig::MAX_BONES];
  if (rig::pose(gen::RIG_HORSE, 0, gait, bones)) {
    const gen::RigAttach& a = gen::RIG_HORSE.attach[gen::RIG_HORSE_SADDLE];
    float saddle[3];
    rig::apply(rig::compose(rig::rigToWorld(hx, hy, hz, hyaw), bones[a.bone]), a.offset, saddle);
    f.rig[2] = g3d::RigState{4, 0, gait, 0xFF, saddle[0], saddle[1] - gen::RIG_PC.bones[0].offset[1], saddle[2], hyaw,
                             0, true, 0};  // rider, ride
  }
  return f;
}

}  // namespace render
