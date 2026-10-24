#include "render.h"

#include <math.h>
#include "src/tgx/tgx.h"

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

constexpr Shader SHADERS = SHADER_PERSPECTIVE | SHADER_ZBUFFER | SHADER_GOURAUD | SHADER_NOTEXTURE;
constexpr float NEAR_PLANE = 0.5f;
constexpr float SKY_SPAN = 0.55f;  // rad above the horizon where the sky reaches skyTop
constexpr int FOG_STEPS = 16;
constexpr int MAX_VERTS = scene::MAX_N * scene::MAX_N;

Renderer3D<RGB565, SHADERS, uint16_t> renderer;
RGB565 tileBuf[W * TILE_H];
uint16_t zbuf[W * TILE_H];
Image<RGB565> tileImage(tileBuf, W, TILE_H);

fVec3 verts[MAX_VERTS];
RGBf colors[MAX_VERTS];
float screenY[MAX_VERTS];  // viewport row of each vertex this frame; NAN when behind the eye
uint8_t fogAlpha[4096];    // zbuffer >> 4 -> blend weight 0..32 towards fogColor
uint16_t skyRows[H][2];  // each row dithers between two neighbouring blend steps
uint8_t skyLevel[H];     // share of the second colour, 0..16
int quadDraws = 0;

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

void prepareFrame(const Camera& cam, fMat4& projView) {
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
    const float steps = t * 32;
    const uint32_t step = uint32_t(steps);
    skyRows[y][0] = blend565(p.skyHorizon, p.skyTop, step);
    skyRows[y][1] = blend565(p.skyHorizon, p.skyTop, step < 32 ? step + 1 : 32);
    skyLevel[y] = uint8_t((steps - step) * 16);
  }
}

}  // namespace

void begin() {
  renderer.setViewportSize(W, H);
  renderer.setImage(&tileImage);
  renderer.setZbuffer(zbuf);
  renderer.setCulling(0);
  renderer.setShaders(SHADER_GOURAUD);
  // Ambient-only white light so baked vertex colours pass through unchanged.
  renderer.setLight(fVec3(0, -1, 0), RGBf(1, 1, 1), RGBf(0, 0, 0), RGBf(0, 0, 0));
  renderer.setMaterial(RGBf(1, 1, 1), 1.0f, 0.0f, 0.0f, 1);
  fMat4 identity;
  identity.setIdentity();
  renderer.setModelMatrix(identity);
  bakeTerrain();
  bakeFog();
}

void frame(const Camera& cam, PushTile push) {
  const scene::Params& p = scene::params;
  const int n = p.terrainN;
  fMat4 projView;
  prepareFrame(cam, projView);

  for (int k = 0; k < n * n; ++k) {
    const fVec4 clip = projView.mult1(verts[k]);
    // Image rows grow downwards while NDC y grows upwards (checked against the desktop preview).
    screenY[k] = clip.w > NEAR_PLANE * 0.5f ? (1 - clip.y / clip.w) * (H / 2) : NAN;
  }

  quadDraws = 0;
  uint16_t* pixels = reinterpret_cast<uint16_t*>(tileBuf);
  for (int tile = 0; tile < TILES; ++tile) {
    const int top = tile * TILE_H;
    renderer.setOffset(0, top);
    for (int y = 0; y < TILE_H; ++y) {
      static const uint8_t BAYER4[4][4] = {{0, 8, 2, 10}, {12, 4, 14, 6}, {3, 11, 1, 9}, {15, 7, 13, 5}};
      const int row = top + y;
      for (int x = 0; x < W; ++x)
        pixels[y * W + x] = skyRows[row][BAYER4[row & 3][x & 3] < skyLevel[row]];
    }
    renderer.clearZbuffer();

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

    for (int i = 0; i < W * TILE_H; ++i) {
      const uint16_t z = zbuf[i];
      if (z && !RENDER_NO_FOG) pixels[i] = blend565(pixels[i], p.fogColor, fogAlpha[z >> 4]);
    }
    push(tile, pixels);
  }
}

int lastQuadDraws() { return quadDraws; }

Camera demoCamera(float seconds) {
  const float angle = seconds * 2 * float(M_PI) / 40;
  const float radius = 22;
  Camera cam;
  cam.x = radius * sinf(angle);
  cam.z = radius * cosf(angle);
  cam.y = scene::terrainHeight(cam.x, cam.z) + 3.5f;
  cam.yaw = angle + float(M_PI);  // face the arena centre
  cam.pitch = -0.12f;
  cam.fovX = 75 * float(M_PI) / 180;
  return cam;
}

}  // namespace render
