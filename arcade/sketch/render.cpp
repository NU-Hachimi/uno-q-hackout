// The core compiles sketches with -Os; TGX's rasterizer templates are instantiated here.
#pragma GCC optimize("O2")

#include "render.h"

#include <math.h>
#include "src/tgx/tgx.h"

#include "gen/meshes.h"
#include "hud.h"
#include "hud_text.h"
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
uint32_t (*clockUs)() = nullptr;
Profile profile;
uint32_t skyPattern[H][2];  // per row: 4 dithered pixels packed as two words, repeated across
int quadDraws = 0;

static_assert(sizeof(fVec3) == 3 * sizeof(float), "gen/meshes.h stores packed xyz floats");

// Objects of the current frame, transformed once and drawn in every tile they overlap.
struct ObjectDraw {
  const gen::Mesh* mesh;
  fMat4 model;
  float rowLo, rowHi;  // viewport rows covered by the bounding sphere
  uint8_t tint;
};
ObjectDraw objects[g3d::MAX_OBJ];
int objectCount = 0;

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
      colors[k] = RGBf(grass.R * shade, grass.G * shade, grass.B * shade);
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
  renderer.setLight(-sun, RGBf(1, 1, 1), RGBf(1, 1, 1), RGBf(0, 0, 0));
  bakeTerrain();
  bakeFog();
}

inline uint32_t now() { return clockUs ? clockUs() : 0; }

namespace {

void prepareObjects(const g3d::Frame& f, const fMat4& projView, float focal) {
  objectCount = 0;
  for (int i = 0; i < f.nObj; ++i) {
    const g3d::Object& o = f.obj[i];
    if (o.mesh >= gen::MESH_COUNT || !gen::MESHES[o.mesh].nTris) continue;  // 0xFF and unknown ids
    ObjectDraw& d = objects[objectCount];
    d.mesh = &gen::MESHES[o.mesh];
    d.tint = o.tint < 32 ? o.tint : 0;
    const float radius = d.mesh->radius * o.scale;
    const fVec4 clip = projView.mult1(fVec3(o.x, o.y, o.z));
    if (clip.w < -radius || clip.w - radius > scene::params.fogFar) continue;  // behind or beyond the far plane
    if (clip.w > radius) {
      const float row = (1 - clip.y / clip.w) * (H / 2), reach = radius * focal / clip.w + 2;
      d.rowLo = row - reach;
      d.rowHi = row + reach;
    } else {
      d.rowLo = -1e9f;  // straddles the eye plane: draw in every tile
      d.rowHi = 1e9f;
    }
    // T(pos) * Ry(yaw) * Rx(pitch) * S(scale); TGX mult* pre-multiplies.
    d.model.setScale(o.scale, o.scale, o.scale);
    d.model.multRotate(o.pitch * (180 / float(M_PI)), 1, 0, 0);
    d.model.multRotate(o.yaw * (180 / float(M_PI)), 0, 1, 0);
    d.model.multTranslate(o.x, o.y, o.z);
    ++objectCount;
  }
}

void drawObjects(int top) {
  bool started = false;
  for (int i = 0; i < objectCount; ++i) {
    const ObjectDraw& d = objects[i];
    if (d.rowHi < top || d.rowLo > top + TILE_H) continue;
    if (!started) {
      renderer.setShaders(SHADER_FLAT);
      renderer.setCulling(1);  // OBJ front faces are counter-clockwise (art.md §8)
      renderer.setMaterial(RGBf(1, 1, 1), 0.5f, 0.65f, 0.0f, 1);
      started = true;
    }
    renderer.setModelMatrix(d.model);
    const fVec3* verts = reinterpret_cast<const fVec3*>(d.mesh->verts);
    uint16_t first = 0;
    for (int g = 0; g < d.mesh->nGroups; ++g) {
      const uint16_t end = d.mesh->groupEnd[g];
      renderer.setMaterialColor(toRGBf(scene::palette[d.tint ? d.tint : d.mesh->groupColor[g]]));
      renderer.drawTriangles(end - first, d.mesh->tris + 3 * first, verts);
      first = end;
    }
  }
  if (started) {
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
  prepareObjects(f, projView, focal);

  for (int k = 0; k < n * n; ++k) {
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
  g3d::Frame f = {};
  const float angle = seconds * 2 * float(M_PI) / 40;
  const float radius = 7;
  const float ground = scene::terrainHeight(0, 0);
  f.camX = radius * sinf(angle);
  f.camZ = radius * cosf(angle);
  f.camY = scene::terrainHeight(f.camX, f.camZ) + 2.2f;
  f.camYaw = angle + float(M_PI);  // face the arena centre
  f.camPitch = atan2f(ground + 1.2f - f.camY, radius);
  f.fovX = 75 * float(M_PI) / 180;
  f.state = g3d::READY;
  f.msg = hud::MSG_WAITING;
  f.nObj = 1;
  f.obj[0] = g3d::Object{0, 0, 0, ground, 0, angle * 0.5f, 0, 1};  // the PC turning slowly
  return f;
}

}  // namespace render
