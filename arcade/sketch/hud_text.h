#pragma once

// msg_id texts (api.md §3.5). Append only; never renumber. ASCII 0x20-0x7E, upper case (art.md §5).
namespace hud {

constexpr int MSG_MENU_CONTINUE = 9, MSG_MENU_RESTART = 10, MSG_MENU_RECALIBRATE = 11;
constexpr int MSG_WAITING = 16;  // MCU only: shown by the demo while no g3d_frame arrives

static const char* const MESSAGES[] = {
    "",                                     // 0
    "PRESS A TO START",                     // 1
    "BREAK THE ARMOR",                      // 2
    "HOOK ON! (C)",                         // 3
    "STRIKE THE HEAD",                      // 4
    "HOLD ON!",                             // 5
    "VICTORY - C TO RESTART",               // 6 (superseded by 13)
    "DEFEATED - C TO RESTART",              // 7 (superseded by 14)
    "CONTROLLER MISSING",                   // 8
    "CONTINUE",                             // 9  pause menu, item selected
    "RESTART",                              // 10
    "RECALIBRATE",                          // 11
    "HOLD THE CONSOLE NATURALLY, PRESS A",  // 12
    "VICTORY - A TO RESTART",               // 13
    "DEFEATED - A TO RESTART",              // 14
    "STICK MOVE  TILT LOOK  B SHOOT  A MENU",  // 15
    "WAITING FOR PYTHON",                   // 16
    "BREAK THE CRYSTALS",                   // 17
};
constexpr int MESSAGE_COUNT = sizeof(MESSAGES) / sizeof(MESSAGES[0]);

}  // namespace hud
