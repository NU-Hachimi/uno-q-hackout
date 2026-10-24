# UNO Q 硬件调研：3D 方向

[文档索引](README.md) · [API](api.md)

> 标 *实测* 的数据是 2026-10-24 在 `SCL-Arqade11` 上测得；标 *估算* 的数据要在 [workflow.md](workflow.md) 的 M0 基准测试中验证。

## 结论

1. **只能在 MCU 上渲染。** TFT 接在 STM32U585 的 8080 并口上。MPU 到 MCU 的 Bridge 只有 **115200 baud（约 11.5 KB/s）**，sketch 单次接收上限 **256 B**，在 MPU 或 GPU 上渲染的画面无法实时传到屏幕。
2. **主流框架（raylib、Godot 等）不能直接用**，除非能打通 MPU → MCU 的 SPI 链路（实验性，见 §3）。
3. **MCU 端用 TGX 1.1.4**（`vindar/tgx`，Arduino 库管理器可装）。它支持透视投影、`uint16_t` z-buffer、平面和 Gouraud 着色、分块渲染（`setOffset`），并自带 `tools/tgx_mesh.py` 把 OBJ 转成头文件。**TGX 没有雾**，需要我们自己做后处理。
4. **TFT 驱动必须重写写像素路径。** DIYables 2.2.1 在 UNO Q 上退回到 `digitalWrite`，每个像素约 20 次 GPIO 调用，刷满一屏要秒级时间。

## 1. MPU：Qualcomm QRB2210

| 项目 | 值 | 来源 |
| --- | --- | --- |
| CPU | 4 × Cortex-A53，2.016 GHz，NEON | 实测 |
| 内存 | 3.6 GiB + 1.8 GiB swap | 实测 |
| 存储 | eMMC 根分区剩余 1.9 G | 实测 |
| GPU | Adreno 702，355–845 MHz；Mesa 26.1.6（Turnip Vulkan 1.0、freedreno GL） | 实测 |
| 系统 | Debian 13，内核 7.0，Xorg `:0` | 实测 |
| 外接显示 | DRM `DP-1`（USB-C DP Alt），可用于调试 | 实测 |
| 音频 | ALSA `Arduino-Imola-HPH-LOUT`，带耳机口 | 实测 |
| 纯 Python 顶点变换 | 约 157k 顶点/秒（单核） | 实测 |

## 2. MCU：STM32U585

| 项目 | 值 | 来源 |
| --- | --- | --- |
| CPU | Cortex-M33 @ 160 MHz，FPU，DSP | 规格 |
| 内存 | 786 KB SRAM / 2 MB Flash | 规格 |
| Sketch 运行方式 | Zephyr LLEXT，`CONFIG_LLEXT_HEAP_SIZE=256`（KB）；可选 static link | 实测 |
| 缓存 | I/D cache 开启 | 实测 |
| 核心版本 | 板载 `arduino:zephyr 1.0.0`，starter 锁定 0.55.2 | 实测 |

## 3. 互连

| 链路 | 带宽 / 限制 | 用途 |
| --- | --- | --- |
| Bridge（`arduino-router`，`/dev/ttyHS1`） | 115200 baud，单次请求 ≤256 B | 主通道 |
| SPI（`/dev/spidev0.0` → MCU `spi3` 从机：MOSI PB5、MISO PG10、NSS PG12） | 估算 ≥1 MB/s；`spidev` 需要 root；Arduino SPI 库只提供主机 API | 实验性。引脚与 TFT 不冲突 |
| Qwiic `Wire1` | 400 kHz | Buttons `0x3E`、Joystick `0x2C`、Movement `0x6A` |
| 8080 并口 | 取决于驱动写法 | TFT |

## 4. TFT 引脚映射

| 总线位 | 引脚 | GPIO | | 控制 | 引脚 | GPIO |
| --- | --- | --- | --- | --- | --- | --- |
| D0 | D8 | PB4 | | RD | A0 | PA4 |
| D1 | D9 | PB8 | | WR | A1 | PA5 |
| D2 | D2 | PB3 | | CD | A2 | PA6 |
| D3 | D3 | PB0 | | CS | A3 | PA7 |
| D4 | D4 | PA12 | | RST | A4 | PC1 |
| D5 | D5 | PA11 | | | | |
| D6 | D6 | PB1 | | | | |
| D7 | D7 | PB2 | | | | |

每写一个字节需要 3 次寄存器写：GPIOB BSRR（查表）、GPIOA BSRR（D4/D5 + WR 拉低合并）、WR 拉高。触摸与显示共用引脚，本项目不使用触摸。

## 5. 性能预算（估算）

| 环节 | 估算 |
| --- | --- |
| 全屏推屏，DIYables 原路径 | 2–5 s |
| 全屏推屏，BSRR 快速路径 | 20–40 ms |
| Bridge 每帧可用流量（30 fps） | 约 380 B（上下行合计） |
| 单次 RPC 往返（约 220 B） | 约 20 ms |
| 240×160 渲染（≤1500 三角面） | 10–20 ms（TGX，未测） |
| 目标帧率 | 15–20 fps，渲染 240×160，2× 放大到全屏 |
