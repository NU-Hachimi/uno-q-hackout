"""Megalith's HUD on alia-engine's HUD layer: hearts, the boss bar, the reticle, the messages and the pause menu.
Laid out like the hackathon console's 240x160 HUD (its sketch/hud.cpp), at twice the pixel size."""

import screen
from gen import palette as pal
from look import rgba

# The console's HUD was laid out at 240x160; at 640x360 everything is twice the pixel size.
MCU_W = 240
PX = 2

MESSAGES = (
    "",                                          # 0
    "PRESS START",                               # 1
    "BREAK THE ARMOR",                           # 2
    "HOOK ON! (X)",                              # 3
    "STRIKE THE HEAD",                           # 4
    "HOLD ON!",                                  # 5
    "VICTORY - A TO RESTART",                    # 6 (superseded by 13)
    "DEFEATED - A TO RESTART",                   # 7 (superseded by 14)
    "CONTROLLER MISSING",                        # 8
    "CONTINUE",                                  # 9  pause menu, item selected
    "RESTART",                                   # 10
    "RECALIBRATE",                               # 11 (unused: no tilt on Alia Pad)
    "PRESS START",                               # 12 (was the tilt calibration prompt)
    "VICTORY - A TO RESTART",                    # 13
    "DEFEATED - A TO RESTART",                   # 14
    "L MOVE  R LOOK  B SHOOT  X HOOK  START MENU",  # 15
    "WAITING FOR PYTHON",                        # 16
    "BREAK THE CRYSTALS",                        # 17
    "JUMP OFF! (X)",                             # 18
    "FINISH HIM (B)",                            # 19
)
MENU_ITEMS = (9, 10)


def draw(e, hud):
    """One HUD: drawn every displayed frame (the engine clears it)."""
    w, h = e.scene_size
    text, shadow = rgba(pal.PALETTE_565[pal.HUD_TEXT]), rgba(pal.PALETTE_565[pal.HUD_SHADOW])

    def shade(x, y, bw, bh, alpha32):
        e.hud_rect(x, y, bw, bh, rgba(pal.PALETTE_565[pal.HUD_SHADOW], alpha32 * 8))

    def say(x, y, s, color=text):
        e.hud_text(x, y, s, color, PX, shadow)

    def centred(y, s, color=text):
        say((w - (len(s) * 6 - 1) * PX) // 2, y, s, color)

    message = MESSAGES[hud.msg] if hud.msg < len(MESSAGES) else ""
    if hud.state == screen.STATE_FIGHT:
        for i in range(hud.hp_max):
            x, y = 8 + i * 16, 8
            if i < hud.hp:
                e.hud_rect(x + PX, y + PX, 12, 12, shadow)
                e.hud_rect(x, y, 12, 12, text)
            else:
                e.hud_rect(x, y, 12, 12, rgba(pal.PALETTE_565[pal.HURT]))
                e.hud_rect(x + PX, y + PX, 8, 8, shadow)
        if hud.boss_hp:
            bar = 260
            e.hud_rect((w - bar) // 2, 10, bar, 5, shadow)
            e.hud_rect((w - bar) // 2, 10, (bar * hud.boss_hp + 254) // 255, 5,
                            rgba(pal.PALETTE_565[pal.HUD_BAR]))
        _reticle(e, hud, w // 2 + hud.reticle_dx * w / MCU_W, h // 2 + hud.reticle_dy * w / MCU_W)
        if message:
            centred(h - 45, message)
    elif hud.state == screen.STATE_PAUSED:
        if hud.msg in MENU_ITEMS:
            bw, bh = 268, 110
            x0, y0 = (w - bw) // 2, (h - bh) // 2
            shade(x0, y0, bw, bh, 20)
            centred(y0 + 14, "PAUSED")
            for k, item in enumerate(MENU_ITEMS):
                y = y0 + 46 + k * 26
                color = rgba(pal.PALETTE_565[pal.HOOK_OK]) if item == hud.msg else text
                if item == hud.msg:
                    say(x0 + 28, y, ">", color)
                say(x0 + 54, y, MESSAGES[item], color)
        elif message:
            shade(0, h // 2 - 22, w, 44, 16)
            centred(h // 2 - 7, message)
    elif message:  # READY, WIN, LOSE
        shade(0, h - 144, w, 44, 12)
        centred(h - 129, message)



def _reticle(e, hud, x, y):
    """Cross; corners on a part; diamond when a hook point is in range; both when both (art.md §5)."""
    x, y, p = round(x), round(y), PX
    rect = e.hud_rect
    if hud.reticle_flags & 2:
        col = rgba(pal.PALETTE_565[pal.HOOK_OK])
        for i in range(-4, 5):
            d = 4 - abs(i)
            rect(x + i * p, y - d * p, p, p, col)
            rect(x + i * p, y + d * p, p, p, col)
    if hud.reticle_flags & 1:
        col = rgba(pal.PALETTE_565[pal.SIGIL])
        for sx in (-1, 1):
            for sy in (-1, 1):
                rect(x + (sx * 5 - (0 if sx < 0 else 2)) * p, y + sy * 5 * p, 3 * p, p, col)
                rect(x + sx * 5 * p, y + (sy * 5 - (0 if sy < 0 else 2)) * p, p, 3 * p, col)
    if not hud.reticle_flags & 3:
        for o, col in ((p, rgba(pal.PALETTE_565[pal.HUD_SHADOW])), (0, rgba(pal.PALETTE_565[pal.HUD_TEXT]))):
            rect(x - 5 * p + o, y + o, 3 * p, p, col)
            rect(x + 3 * p + o, y + o, 3 * p, p, col)
            rect(x + o, y - 5 * p + o, p, 3 * p, col)
            rect(x + o, y + 3 * p + o, p, 3 * p, col)
