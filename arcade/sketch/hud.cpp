#include "hud.h"

#include <string.h>

#include "gen/palette.h"
#include "hud_font.h"
#include "hud_text.h"

namespace hud {
namespace {

constexpr int FRAME_W = 240, FRAME_H = 160;
constexpr int ADVANCE = FONT_W + 1;

// HUD colours use the ungraded palette: the Look must not tint the UI (art.md §4).
inline uint16_t pal(uint8_t index) { return gen::PALETTE[index]; }

struct Canvas {
  uint16_t* px;
  int w, rows, top;

  void fill(int x, int y, int fw, int fh, uint16_t c) const {
    int x0 = x < 0 ? 0 : x, x1 = x + fw > w ? w : x + fw;
    int y0 = y < top ? top : y, y1 = y + fh > top + rows ? top + rows : y + fh;
    for (int yy = y0; yy < y1; ++yy)
      for (int xx = x0; xx < x1; ++xx) px[(yy - top) * w + xx] = c;
  }

  // Darken towards `c` with weight a in 0..32 (same spread-channel trick as the fog).
  void shade(int x, int y, int fw, int fh, uint16_t c, uint32_t a) const {
    const uint32_t t = (c | (uint32_t(c) << 16)) & 0x07E0F81F;
    int x0 = x < 0 ? 0 : x, x1 = x + fw > w ? w : x + fw;
    int y0 = y < top ? top : y, y1 = y + fh > top + rows ? top + rows : y + fh;
    for (int yy = y0; yy < y1; ++yy) {
      for (int xx = x0; xx < x1; ++xx) {
        uint16_t& p = px[(yy - top) * w + xx];
        uint32_t s = (p | (uint32_t(p) << 16)) & 0x07E0F81F;
        uint32_t r = ((s * (32 - a) + t * a) >> 5) & 0x07E0F81F;
        p = uint16_t(r | (r >> 16));
      }
    }
  }

  void glyph(int x, int y, char ch, uint16_t c) const {
    if (ch < FONT_FIRST || ch > FONT_LAST || y + FONT_H <= top || y >= top + rows) return;
    const uint8_t* g = FONT5X7 + (ch - FONT_FIRST) * FONT_W;
    for (int col = 0; col < FONT_W; ++col)
      for (int row = 0; row < FONT_H; ++row)
        if (g[col] & (1 << row)) fill(x + col, y + row, 1, 1, c);
  }

  // Text with a 1 px HUD_SHADOW drop shadow, because the sky and fog are bright.
  void text(int x, int y, const char* s, uint16_t c) const {
    for (; *s; ++s, x += ADVANCE) {
      glyph(x + 1, y + 1, *s, pal(gen::PAL_HUD_SHADOW));
      glyph(x, y, *s, c);
    }
  }

  void centred(int y, const char* s, uint16_t c) const {
    text((w - (int(strlen(s)) * ADVANCE - 1)) / 2, y, s, c);
  }
};

const char* message(uint8_t id) { return id < MESSAGE_COUNT ? MESSAGES[id] : ""; }

void healthPips(const Canvas& c, const g3d::Frame& f) {
  for (int i = 0; i < f.hpMax; ++i) {
    const int x = 4 + i * 8, y = 4;
    if (i < f.hp) {
      c.fill(x + 1, y + 1, 6, 6, pal(gen::PAL_HUD_SHADOW));
      c.fill(x, y, 6, 6, pal(gen::PAL_HUD_TEXT));
    } else {
      c.fill(x, y, 6, 6, pal(gen::PAL_HURT));
      c.fill(x + 1, y + 1, 4, 4, pal(gen::PAL_HUD_SHADOW));
    }
  }
}

void bossBar(const Canvas& c, uint8_t hp) {
  if (!hp) return;
  const int x = 70, w = 100;
  c.fill(x, 4, w, 2, pal(gen::PAL_HUD_SHADOW));
  c.fill(x, 4, (w * hp + 254) / 255, 2, pal(gen::PAL_HUD_BAR));
}

// Cross, corners on a part, diamond when hookable (art.md §5).
void reticle(const Canvas& c, const g3d::Frame& f) {
  const int x = FRAME_W / 2 + f.reticleX, y = FRAME_H / 2 + f.reticleY;
  if (f.reticleFlags & 2) {
    const uint16_t col = pal(gen::PAL_HOOK_OK);
    for (int i = -4; i <= 4; ++i) {
      const int d = 4 - (i < 0 ? -i : i);
      c.fill(x + i, y - d, 1, 1, col);
      c.fill(x + i, y + d, 1, 1, col);
    }
  } else if (f.reticleFlags & 1) {
    const uint16_t col = pal(gen::PAL_SIGIL);
    for (int sx = -1; sx <= 1; sx += 2) {
      for (int sy = -1; sy <= 1; sy += 2) {
        c.fill(x + sx * 5 - (sx < 0 ? 0 : 2), y + sy * 5, 3, 1, col);
        c.fill(x + sx * 5, y + sy * 5 - (sy < 0 ? 0 : 2), 1, 3, col);
      }
    }
  } else {
    for (int pass = 0; pass < 2; ++pass) {
      const int o = pass ? 0 : 1;
      const uint16_t col = pass ? pal(gen::PAL_HUD_TEXT) : pal(gen::PAL_HUD_SHADOW);
      c.fill(x - 5 + o, y + o, 3, 1, col);
      c.fill(x + 3 + o, y + o, 3, 1, col);
      c.fill(x + o, y - 5 + o, 1, 3, col);
      c.fill(x + o, y + 3 + o, 1, 3, col);
    }
  }
}

void pauseMenu(const Canvas& c, uint8_t selected) {
  c.shade(70, 44, 100, 64, pal(gen::PAL_HUD_SHADOW), 20);
  c.centred(50, "PAUSED", pal(gen::PAL_HUD_TEXT));
  for (int item = MSG_MENU_CONTINUE; item <= MSG_MENU_RECALIBRATE; ++item) {
    const int y = 66 + (item - MSG_MENU_CONTINUE) * 12;
    const bool on = item == selected;
    const uint16_t col = on ? pal(gen::PAL_HOOK_OK) : pal(gen::PAL_HUD_TEXT);
    if (on) c.text(80, y, ">", col);
    c.text(90, y, MESSAGES[item], col);
  }
}

}  // namespace

void drawTile(uint16_t* pixels, int width, int rows, int top, const g3d::Frame& f) {
  if (f.flags & g3d::FLAG_NO_HUD) return;
  const Canvas c{pixels, width, rows, top};
  switch (f.state) {
    case g3d::FIGHT:
      healthPips(c, f);
      bossBar(c, f.bossHp);
      reticle(c, f);
      if (f.msg) c.centred(140, message(f.msg), pal(gen::PAL_HUD_TEXT));
      break;
    case g3d::PAUSED:
      if (f.msg >= MSG_MENU_CONTINUE && f.msg <= MSG_MENU_RECALIBRATE) {
        pauseMenu(c, f.msg);
      } else if (f.msg) {
        c.shade(0, 70, FRAME_W, 20, pal(gen::PAL_HUD_SHADOW), 16);
        c.centred(76, message(f.msg), pal(gen::PAL_HUD_TEXT));
      }
      break;
    default:  // READY, WIN, LOSE
      if (f.msg) {
        c.shade(0, 96, FRAME_W, 20, pal(gen::PAL_HUD_SHADOW), 12);
        c.centred(102, message(f.msg), pal(gen::PAL_HUD_TEXT));
      }
      break;
  }
}

}  // namespace hud
