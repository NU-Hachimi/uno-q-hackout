// Desktop build of the MCU renderer: writes the demo frame as a 2x-scaled PPM.
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "render.h"
#include "scene.h"

static uint16_t framebuffer[render::W * render::H];

static void collect(int tile, const uint16_t* pixels) {
  memcpy(framebuffer + tile * render::W * render::TILE_H, pixels,
         sizeof(uint16_t) * render::W * render::TILE_H);
}

int main(int argc, char** argv) {
  const char* out = argc > 1 ? argv[1] : "preview.ppm";
  const float seconds = argc > 2 ? strtof(argv[2], nullptr) : 0;
  scene::buildDemo(1);
  render::begin();
  render::frame(render::demoCamera(seconds), collect);

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
  printf("%s: t=%.1fs, %d terrain quad draws\n", out, seconds, render::lastQuadDraws());
  return 0;
}
