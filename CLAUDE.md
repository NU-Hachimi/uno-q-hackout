# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

Hackathon starter for the Arduino UNO Q, a dual-processor board:

- **MPU**: Qualcomm QRB2210, running Debian. Python runs here.
- **MCU**: STM32U585, running Zephyr. The Arduino sketch runs here.

There are two tracks, each a self-contained **Arduino App Lab app**: `robocar/` and `arcade/`. **This team works on `arcade/`**, a handheld with Modulino controls and a DIYables 3.5" parallel TFT. `robocar/` is upstream starter code that we don't touch.

The team's game is a low-poly 3D boss fight (巨构游戏), designed in `arcade/docs/`. The docs are in Chinese, and so is team discussion. Read them in this order:

1. `plan.md`: game design and P0/P1/P2 scope.
2. `research.md`: measured hardware limits.
3. `api.md`: **the MCU↔Python contract**.
4. `workflow.md`: the two-person split, file ownership, and phases.
5. `tasks.md`: the execution plan. Its task cards (A1–A11, B1–B11, P2-*) cover the full scope, with no cuts. Each card lists its files, a "Claude 自检" check, and a "人工确认" check.

When you're asked to do a card, follow its file list and run its "Claude 自检" yourself. You can't see the TFT, so for the "人工确认" part, stop and tell the human exactly what to look at. Stop and ask before editing `api.md`.

Two Claude sessions may run in parallel, each in its own worktree, and they share **one board**. Always flash with `flock /tmp/uno-q-board.lock make flash`. `make logs` and `make monitor` use `adb shell -t`. Without a TTY that prints nothing, so read logs non-interactively:

```sh
adb -d shell -T 'TMPDIR=/tmp arduino-app-cli app logs "$HOME/ArduinoApps/uno-q-arcade-cli" 2>&1 | tail -30'
```

Desktop Python is the repo-root `.venv`. It was created from miniforge's Python 3.14 because the system Python lacks `venv`. Use `.venv/bin/python -m pytest`. It has **pygame-ce** (imported as `pygame`), because stock pygame has no 3.14 wheel. For headless runs, set `SDL_VIDEODRIVER=dummy`.

`arduino-cli` is in `~/.local/bin`, so `make build` works locally. The first build downloads the core and libraries from the `sketch.yaml` profile.

Much of the layout described in `api.md` and `workflow.md` (`tools/`, `tests/`, `assets/`, `sketch/gen/`, `python/gen/`, `g3d.py`, etc.) is **planned and not built yet**. Check what actually exists before assuming it.

The root README holds the scoring rubrics; the arcade rubric is the target. The track READMEs and PREWORK.md are participant-facing docs. Keep them in sync when you change commands or defaults they quote.

## Commands

Run these from `arcade/`. Board commands go over `adb` to a USB-connected UNO Q.

```sh
make flash     # zip app.yaml+python/+sketch/, adb push, run scripts/flash.sh on board (arduino-app-cli compiles sketch + starts Python)
make logs      # follow Python stdout/errors on the board
make monitor   # MCU serial monitor
make stop      # stop the terminal-managed app
make build     # local MCU-only compile: arduino-cli compile --fqbn arduino:zephyr:unoq --profile default
make package   # build/uno-q-arcade.zip for App Lab import
make devices   # adb devices -l
```

Add `SERIAL=<adb serial>` when more than one device is connected. `make flash` deploys to `~/ArduinoApps/uno-q-arcade-cli` on the board:

- It replaces `python/` and `sketch/` wholesale and keeps `data/` and `.env`.
- It refuses to overwrite a directory that lacks the `.make-managed` marker.
- Only one App Lab app can run at a time.

Other tools:

- **Tests:** none exist yet. The plan is `pytest tests/` on the desktop, run against golden protocol and rig data.
- **Wi-Fi:** `tools/board-wifi.sh` joins the board to NUwave or eduroam over adb. `--forget` removes the saved login.

**Core version:** the boards run `arduino:zephyr 1.0.0`, but the starter README pins 0.55.2. `arcade/sketch/sketch.yaml` decides which version gets used. All library versions there are pinned.

## Current arcade starter (what exists)

### Bridge RPC is the contract

The sketch registers handlers with `Bridge.provide_safe("name", fn)` in `setup()`. Python calls them with `Bridge.call("name", *args)`. Names, argument order, and argument types must match on both sides, so change the provider and its callers together.

The link runs at **115200 baud**, roughly 11.5 KB/s, and the sketch accepts at most **256 B per request**. Never stream pixels from the MPU. All rendering happens on the MCU.

### Preview path

1. `python/main.py` calls `arcade_read_inputs` and gets a JSON snapshot: `connected` and `buttons` bitmasks, raw `x`/`y`, `ax`/`ay`/`az` in mg, and `video`.
2. `python/preview.py` `frame_values()` validates the snapshot and applies calibration.
3. Python calls `arcade_draw_frame(...)`, and `drawFrame()` in `sketch/sketch.ino` draws it.

If no frame arrives for 1.5 s, the sketch shows a waiting screen.

### Calibration

Calibration lives in `python/preview.py`: `DEAD_ZONE`, `INVERT_X/Y`, `MOVEMENT_ZERO_MG`, and `MOVEMENT_DEAD_ZONE_MG`. `retroarch/controls.py` imports it via `sys.path`, so changing it affects both paths.

### RetroArch path (`retroarch/`)

- It runs on board Linux outside App Lab. `run.sh` starts `run.py` under a 160×120 Xvfb display.
- `run.py` sends changed RGB332 tiles through `arcade_video_*`. The tile format lives in `sketch/video_protocol.h` and is mirrored in `retroarch/video.py`.
- `api.md` requires keeping these RPCs alongside the new `g3d_*` ones.

### Hardware

- **Display controller:** `ARCADE_TFT_HX8357D` selects it. `1` is HX8357D (the default) and `0` is RM68140.
- **Controls:** the Modulinos sit on Qwiic `Wire1`: Buttons `0x3E`, Joystick `0x2C`, Movement `0x6A`.

## Renderer built so far (branch `render/grass-demo`)

- **`G3D_DEMO` mode:** `sketch.ino` defaults to `G3D_DEMO 1`, which renders an orbiting misty meadow on the MCU. The starter's `drawFrame` and RetroArch paths are disabled while it is on.
- **Files:** `tft8080.*` does BSRR pixel writes, `scene.*` holds the terrain parameters and heights, and `render.*` is platform-independent TGX code (sky, grass, fog, 240×16 tiles).
- **TGX is vendored** in `sketch/src/tgx/`; see `VENDORED.md`. Don't switch back to the registry library, which fails to compile on the Zephyr core. `.inl` files are renamed to `.inl.h` because arduino-cli doesn't copy `.inl` files.
- **Desktop preview:** run `sh tests/cpp/render_preview.sh 0 10` from `arcade/`. It compiles `scene.cpp` and `render.cpp` with g++ and writes `build/preview/t*.png`; Read those PNGs to check the image before flashing. `-DRENDER_NO_CULL=1` and `-DRENDER_NO_FOG=1` (passed via `CXXFLAGS`) help isolate bugs.
- **Board-side check:** `g3d_debug_stats` is a debug-only RPC registered with `Bridge.provide`, not `provide_safe`, so it answers even if `setup()` stalls. It returns the init stage (8 = render loop running) plus fps, `render_ms` and `push_ms`. To read it, call it through `/var/run/arduino-router.sock` from board-side Python; the board has no msgpack module, so the client needs a minimal hand-written msgpack.
- **Stuck sketch:** if the sketch never starts, the CPU sits idle in the kernel. You can halt it over SWD without resetting by running `/opt/openocd/bin/openocd` with `openocd_gpiod.cfg` + `reset_config none` to read PC and the fault registers. Always `resume` afterwards.
- **Rendering conventions:**
  - Image rows grow downwards while NDC y grows upwards, so screen y = `(1 − ndc_y)·H/2`.
  - The uint16 zbuffer stores `wa/depth + wb`; 0 means empty (sky).
  - `provide_safe` handlers only run between `loop()` iterations (and where `safeUpdate()` is called), so the render loop calls `safeUpdate()` after each tile.

## Planned game architecture (`arcade/docs/api.md`)

### Who does what

- The **MCU renders.** It uses TGX (`vindar/tgx`), tiled 240×16 at 240×160 with 2× upscale. It does depth fog from the z-buffer, then draws the HUD, then pushes the frame through a custom BSRR 8080 driver.
- The stock DIYables write path uses `digitalWrite` and takes seconds per frame. The custom driver must replace it.

### Game loop

1. Python runs all game logic: state machine, player, boss AI, collision, and camera.
2. Each frame, Python sends one binary `g3d_frame` packet (≤192 B).
3. The sketch replies with a 16 B Input.
4. The scene (terrain, rocks, part variants) is uploaded once per round with `g3d_scene_begin/chunk/commit`, which is CRC-checked.

### Protocol rules

- Little-endian.
- Positions are `i16` in units of 1/64 m.
- Angles are BAM.
- `G3D_VERSION` must be bumped on any change to `api.md` §2–§5, and both people must agree to the change.

### Rigs

- A rig is ≤16 rigid bones with keyframed, linearly interpolated animation over phase 0–255.
- **Both sides evaluate poses independently.** `rig.cpp` draws them and `rig.py` uses them for collision.
- Golden data in `tests/golden/rig_<name>.json` must agree to within 1 cm. If the two sides disagree, Python is the reference.
- `terrain_height()` must use the same bilinear rule in both languages.

### Assets

- Sources live in `assets/rigs/*.json` and `assets/meshes/*.obj`.
- `tools/rig_build.py` and `tools/mesh_build.py` generate `sketch/gen/` and `python/gen/`. **Never hand-edit `gen/`.**

### Ownership

- **Renderer (A):** owns `sketch/**`. Branches are `render/<topic>`.
- **Gameplay (B):** owns `python/**`, `tools/**`, and `tests/**`. Branches are `game/<topic>`.
- Anything merged to `main` must `make flash` and boot.

### Working without the other side

- **Renderer:** `G3D_DEMO=1` builds a standalone renderer demo with no Python.
- **Gameplay:** `tools/sim.py` is a planned pygame wireframe simulator for desktop testing without a board.
