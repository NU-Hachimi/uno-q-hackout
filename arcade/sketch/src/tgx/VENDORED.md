# TGX 1.1.4 (vendored)

Source: https://github.com/vindar/tgx, release 1.1.4 from the Arduino Library Manager. License: LGPL-2.1 (see `LICENSE`).

Vendored because the registry library does not compile on the UNO Q Zephyr core: its `print(Stream&)` helpers call `Stream::printf`, which that core lacks, and the board's App CLI build cannot pass extra compiler flags.

Changes from upstream:

- `tgx_config.h`: `TGX_ON_ARDUINO` is not defined when `__ZEPHYR__` is set.
- The `font_tgx_*` files are omitted (about 4.3 MB). Copy back only the font the HUD uses.
- `*.inl` files are renamed to `*.inl.h` (and their `#include`s updated), because arduino-cli does not copy `.inl` files from a sketch into its build directory.
