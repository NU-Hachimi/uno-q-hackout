# assets/

美术交付物，**提交进仓库**。由 `tools/`（B）生成 `sketch/gen/` 和 `python/gen/`。风格和规范见 [docs/art.md](../docs/art.md)。

| 路径 | 内容 | 格式 |
| --- | --- | --- |
| `palette.json` | 32 色默认调色板和场景默认颜色 | [api.md §5.4](../docs/api.md) |
| `looks/<name>.json` | Look 预设：调色参数、调色板覆盖、场景颜色覆盖 | [art.md §4](../docs/art.md#4-调色与滤镜look) |
| `rigs/<name>.json` | 骨骼、碰撞体、槽位、动画 | [api.md §5.1](../docs/api.md#51-骨骼与动画assetsrigsnamejson) |
| `meshes/*.obj` + `palette.mtl` | 导出的网格，材质名即调色板名 | [api.md §5.2](../docs/api.md#52-网格assetsmeshesobj) |
| `meshes.json` | 网格 ID 表 | [api.md §5.3](../docs/api.md#53-网格-id-表assetsmeshesjson) |
| `audio/*.mid`、`audio/music.json` | 战斗 BGM 和胜负短曲的 MIDI；`music.json` 写明哪首循环、从哪里循环 | `tools/audio_build.py` 渲染成 `python/music/*.wav` |
| `fonts/` | 像素字体源文件（TTF / BDF） | [api.md §5.5](../docs/api.md#55-字体assetsfonts) |
| `src/` | 建模源文件（`.blend` 等），手工建模时使用 | — |
| `CREDITS.md` | 每个资产的作者、来源、许可证 | — |

程序化生成的资产先在本地的 `arcade/tool/`（不提交）里生成和预览，确认后用 `tool/promote.py` 复制到这里，见 [art.md §9](../docs/art.md#9-资产工作流)。
