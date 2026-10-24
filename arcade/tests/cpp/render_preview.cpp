// Desktop build of the MCU renderer: writes one frame as a 2x-scaled PPM.
//   render_preview out.ppm [seconds]                       demo orbit at `seconds`
//   render_preview out.ppm --scene scene.bin --frame f.bin  a Python scene upload plus one g3d_frame
// scene.bin: u16 header length, header, u8 chunk count, {u8 kind, u8 index, u16 length, data}..., u16 crc.
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include <vector>

#include "g3d_proto.h"
#include "render.h"
#include "scene.h"

static uint16_t framebuffer[render::W * render::H];

static void collect(int tile, const uint16_t* pixels) {
  memcpy(framebuffer + tile * render::W * render::TILE_H, pixels,
         sizeof(uint16_t) * render::W * render::TILE_H);
}

static std::vector<uint8_t> readFile(const char* path) {
  std::vector<uint8_t> data;
  FILE* f = fopen(path, "rb");
  if (!f) {
    fprintf(stderr, "cannot open %s\n", path);
    exit(1);
  }
  int c;
  while ((c = fgetc(f)) != EOF) data.push_back(uint8_t(c));
  fclose(f);
  return data;
}

static void loadScene(const char* path) {
  const std::vector<uint8_t> d = readFile(path);
  size_t at = 0;
  auto need = [&](size_t n) {
    if (at + n > d.size()) {
      fprintf(stderr, "%s: truncated\n", path);
      exit(1);
    }
  };
  need(2);
  const size_t hdr = g3d::rd16(&d[at]);
  at += 2;
  need(hdr + 1);
  if (!scene::uploadBegin(&d[at], hdr)) {
    fprintf(stderr, "scene header rejected\n");
    exit(1);
  }
  at += hdr;
  const int chunks = d[at++];
  for (int i = 0; i < chunks; ++i) {
    need(4);
    const uint8_t kind = d[at], index = d[at + 1];
    const size_t len = g3d::rd16(&d[at + 2]);
    at += 4;
    need(len);
    if (!scene::uploadChunk(kind, index, &d[at], len)) {
      fprintf(stderr, "chunk kind %d index %d rejected\n", kind, index);
      exit(1);
    }
    at += len;
  }
  need(2);
  if (!scene::uploadCommit(g3d::rd16(&d[at])) || !scene::applyUpload()) {
    fprintf(stderr, "scene commit rejected (CRC or missing chunks)\n");
    exit(1);
  }
}

int main(int argc, char** argv) {
  const char* out = argc > 1 ? argv[1] : "preview.ppm";
  const char* scenePath = nullptr;
  const char* framePath = nullptr;
  float seconds = 0;
  for (int i = 2; i < argc; ++i) {
    if (!strcmp(argv[i], "--scene") && i + 1 < argc) scenePath = argv[++i];
    else if (!strcmp(argv[i], "--frame") && i + 1 < argc) framePath = argv[++i];
    else seconds = strtof(argv[i], nullptr);
  }
  scene::buildDemo(1);
  if (scenePath) loadScene(scenePath);
  render::begin();
  g3d::Frame frame = render::demoFrame(seconds);
  if (framePath) {
    const std::vector<uint8_t> pkt = readFile(framePath);
    if (!g3d::parseFrame(pkt.data(), pkt.size(), frame)) {
      fprintf(stderr, "%s: frame rejected by parseFrame\n", framePath);
      return 1;
    }
  }
  render::frame(frame, collect);

  FILE* f = fopen(out, "wb");
  if (!f) return 1;
  fprintf(f, "P6\n%d %d\n255\n", render::W * 2, render::H * 2);
  for (int y = 0; y < render::H * 2; ++y) {
    for (int x = 0; x < render::W * 2; ++x) {
      const uint16_t c = framebuffer[(y / 2) * render::W + x / 2];
      const unsigned char rgb[3] = {(unsigned char)(((c >> 11) & 31) * 255 / 31),
                                    (unsigned char)(((c >> 5) & 63) * 255 / 63),
                                    (unsigned char)((c & 31) * 255 / 31)};
      fwrite(rgb, 1, 3, f);
    }
  }
  fclose(f);
  printf("%s: %d terrain quad draws, %d objects\n", out, render::lastQuadDraws(), frame.nObj);
  return 0;
}
