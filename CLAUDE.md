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

Parts of the layout in `api.md` and `workflow.md` are still planned: `tools/rig_build.py`, `tools/sim.py`, `rig.*`, `collide.py`, `boss.py` and the golden rig data don't exist yet. Check what actually exists before assuming it.

**Controls follow the 操作表 in `docs/plan.md`** (settled 2026-10-24): stick moves, tilt turns the view (rate control), A opens the menu (Continue / Restart / Recalibrate) and confirms, B shoots, C is the hook. There is no dodge or jump. Don't bring back stick-press dodge, hold-C lock-on or tilt-only aiming.

The root README holds the scoring rubrics; the arcade rubric is the target. The track READMEs and PREWORK.md are participant-facing docs. Keep them in sync when you change commands or defaults they quote.

## Commands

Run these from `arcade/`. Board commands go over `adb` to a USB-connected UNO Q.

```sh
make flash     # zip app.yaml+python/+sketch/, adb push, run scripts/flash.sh on board (arduino-app-cli compiles sketch + starts Python)
make logs      # follow Python stdout/errors on the board
make monitor   # MCU serial monitor
make stop      # stop the terminal-managed app
make build     # local MCU-only compile: arduino-cli compile --fqbn arduino:zephyr:unoq --profile default
make package   # zip/uno-q-arcade.zip for App Lab import (a tracked file: `git restore` it after `make flash`)
make devices   # adb devices -l
```

Add `SERIAL=<adb serial>` when more than one device is connected. `make flash` deploys to `~/ArduinoApps/uno-q-arcade-cli` on the board:

- It replaces `python/` and `sketch/` wholesale and keeps `data/` and `.env`.
- It refuses to overwrite a directory that lacks the `.make-managed` marker.
- Only one App Lab app can run at a time.

Other tools:

- **Tests:** `.venv/bin/python -m pytest arcade/tests` (protocol, terrain, game state machine). `tests/conftest.py` puts `python/` on `sys.path`, as on the board.
- **Generated code:** `python3 tools/mesh_build.py` turns `assets/` into `sketch/gen/{meshes,palette}.h` and `python/gen/{mesh_ids,palette}.py`; `--check` exits 1 if they are stale. Rerun it after any asset change.
- **Wi-Fi:** `tools/board-wifi.sh` joins the board to NUwave or eduroam over adb. `--forget` removes the saved login.

**Core version:** the boards run `arduino:zephyr 1.0.0`, but the starter README pins 0.55.2. `arcade/sketch/sketch.yaml` decides which version gets used. All library versions there are pinned.

## How the arcade app works now

### Bridge RPC is the contract

The sketch registers handlers in `setup()`; Python calls them with `Bridge.call("name", *args, timeout=s)`. Names, argument order and types must match on both sides, so change the provider and its callers together.

- `g3d_*` methods (`sketch/rpc.cpp`) use `Bridge.provide`: they run on the Bridge thread, validate, and copy into a buffer under a `k_mutex`. The render loop takes the newest frame.
- `arcade_read_inputs` / `arcade_video_*` (RetroArch) still use `provide_safe`, which only runs between `loop()` iterations and at the mid-frame `safeUpdate()`.
- `MsgPack::bin_t<uint8_t>` works both as an argument and as a return value.

The link runs at **115200 baud**, roughly 11.5 KB/s, and the sketch accepts at most **256 B per request**. Never stream pixels from the MPU. All rendering happens on the MCU.

### Game path

1. `python/main.py` connects (`g3d_hello`, scene upload), then loops at ~20 Hz: `game.step(raw_input, dt)` → `g3d.pack_frame` → `g3d_frame`, whose reply is the next 16 B Input.
2. Python modules: `g3d.py` (wire format, client), `world.py` (scene, `terrain_height`), `controls.py` (stick, button edges, tilt rates), `camera.py`, `player.py`, `game.py` (Ready → Fight ⇄ Menu).
3. The MCU latches button presses between frames (Input `buttons` bit4–7), so short taps are not lost.
4. If no frame arrives for 1.5 s, the sketch renders its own demo orbit with "WAITING FOR PYTHON".

**Coordinates:** yaw 0 faces +Z and +Y is up, so with the view along +Z, +X is on screen **left**. Turning right lowers yaw; `camera.right(yaw) = (-cos yaw, 0, sin yaw)`. Objects are drawn as `T·Ry(yaw)·Rx(pitch)·S`, so positive object pitch tips the +Z nose down.

### Calibration

`python/preview.py` keeps `DEAD_ZONE` and `INVERT_X/Y`, used by `controls.py` and `retroarch/controls.py`. Tilt uses the gravity direction relative to a neutral pose sampled on the Ready-screen A press. **Every tilt parameter lives in `python/tilt_config.py`**: axes and inversion, dead zone, full-speed angle, max rates, curve, smoothing, pitch limits, and `DEBUG_LOG`, which prints per-axis degrees to the app log. The user tunes that file by hand, so don't move these values elsewhere or override them in code.

### RetroArch path (`retroarch/`)

- It runs on board Linux outside App Lab. `run.sh` starts `run.py` under a 160×120 Xvfb display.
- `run.py` sends changed RGB332 tiles through `arcade_video_*`. The tile format lives in `sketch/video_protocol.h` and is mirrored in `retroarch/video.py`.
- `api.md` requires keeping these RPCs alongside the new `g3d_*` ones.

### Hardware

- **Display controller:** `ARCADE_TFT_HX8357D` selects it. `1` is HX8357D (the default) and `0` is RM68140.
- **Controls:** the Modulinos sit on Qwiic `Wire1`: Buttons `0x3E`, Joystick `0x2C`, Movement `0x6A`.

## Renderer (MCU)

- **Files:**
  - `tft8080.*` does BSRR pixel writes.
  - `g3d_proto.*` parses frames (platform-independent).
  - `scene.*` holds terrain, the upload staging copy and Look grading.
  - `render.*` is platform-independent TGX code: sky, grass, objects, fog, 240×32 tiles, built at `-O2` via a pragma; the core defaults to `-Os`.
  - `hud.*` draws text, reticle and menu into each tile.
  - `inputs.*` reads the Modulinos under a mutex.
  - `rpc.*` holds the Bridge handlers.
- **Meshes** come from `sketch/gen/meshes.h`. Each mesh is grouped by palette index; each group sets `setMaterialColor` and calls `drawTriangles`, with flat shading and culling on.
- **TGX is vendored** in `sketch/src/tgx/`; see `VENDORED.md` for the three patches. Don't switch back to the registry library, which fails to compile on the Zephyr core.
  - `.inl` files are renamed to `.inl.h`, because arduino-cli doesn't copy `.inl` files.
  - `_clip()` ignores x/y outcodes of vertices behind the eye; without this, big terrain triangles under the camera vanished.
- **Desktop preview** (run from `arcade/`); Read the PNGs it writes before flashing:
  - `sh tests/cpp/render_preview.sh 0 10` renders the demo orbit.
  - `sh tests/cpp/render_preview.sh --snapshots` runs `tools/snapshot.py`, which drives the real Python `Game` with scripted inputs, then renders its scene upload and frames with the MCU code into `build/preview/*.png`.
  - `-DRENDER_NO_CULL=1` and `-DRENDER_NO_FOG=1` (passed via `CXXFLAGS`) help isolate bugs.
- **Push timing:** `tft8080.cpp` is built at `-O3`, which makes GPIO stores back to back. `TFT_WR_NOPS=3` and `TFT_WR_HOLD_NOPS=3` are the verified-safe values (about 29.5 ms per full screen). Lower values garbled the panel. Any change to the push loop needs a human to look at the screen, because the desktop preview can't catch bus timing.
- **Board-side check:** `g3d_debug_stats` is a debug-only RPC registered with `Bridge.provide`, not `provide_safe`, so it answers even if `setup()` stalls. It returns the init stage (8 = render loop running), fps, `live` (Python frames being rendered), `seq`, `rx_fps` and per-phase timings. To read it, call it through `/var/run/arduino-router.sock` from board-side Python; the board has no msgpack module, so the client needs a minimal hand-written msgpack.
- **Stuck sketch:** if the sketch never starts, the CPU sits idle in the kernel. You can halt it over SWD without resetting by running `/opt/openocd/bin/openocd` with `openocd_gpiod.cfg` + `reset_config none` to read PC and the fault registers. Always `resume` afterwards.
- **Rendering conventions:**
  - Image rows grow downwards while NDC y grows upwards, so screen y = `(1 − ndc_y)·H/2`.
  - The uint16 zbuffer stores `wa/depth + wb`; 0 means empty (sky).
  - Idle `safeUpdate()` sleeps 1 ms, so the render loop calls it once mid-frame, not after every tile.

## Planned game architecture (`arcade/docs/api.md`)

### Who does what

- The **MCU renders.** It uses TGX (`vindar/tgx`), tiled 240×32 at 240×160 with 2× upscale. It does depth fog from the z-buffer, then draws the HUD, then pushes the frame through a custom BSRR 8080 driver.
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

- Sources live in `assets/rigs/*.json` and `assets/meshes/*.obj`. `assets/` exists and holds `palette.json`, `looks/`, `meshes/` (23 OBJ files plus `palette.mtl`), `meshes.json` and `rigs/moose.json`. These are the promoted output of `arcade/tool/`.
- `arcade/tool/` is **git-ignored and local**. It generates the moose and props procedurally (`gen_meshes.py`, `gen_rig.py`) and renders previews (`preview.py`, which writes PNGs and GIFs to `tool/out/preview/`). `promote.py --apply` copies approved output into `assets/`. It needs only numpy and Pillow, both in system `python3`. See `arcade/docs/art.md` §9.
- `tools/rig_build.py` and `tools/mesh_build.py` generate `sketch/gen/` and `python/gen/`. **Never hand-edit `gen/`.**

### Ownership

- **Renderer (A):** owns `sketch/**`. Branches are `render/<topic>`.
- **Gameplay (B):** owns `python/**`, `tools/**`, and `tests/**`. Branches are `game/<topic>`.
- Anything merged to `main` must `make flash` and boot.

### Working without the other side

- **Renderer:** with no Python frames the sketch renders its demo orbit, so it runs standalone.
- **Gameplay:** `tests/test_game.py` plus `render_preview.sh --snapshots` cover most changes on the desktop. `tools/sim.py` (interactive pygame simulator) is still planned.
