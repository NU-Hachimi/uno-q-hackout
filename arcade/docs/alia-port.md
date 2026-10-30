# Megalith 移植到 Alia Pad：现状和路线图

> 2026-10-30。`alia-pad` 分支。引擎是 [alia-engine](https://github.com/SaltyfishAlpha/alia-engine)，接口见它的 `docs/api.md`，阶段见它的 `docs/architecture.md` §6.1（E4 的 8 步）。

## 1. 为什么现在看起来乱

比赛时的架构是 **Python 写逻辑、MCU 负责画**，中间隔着每次 192 字节的 Bridge 通道。所以 `game.py` 每一步要把"这一帧画什么"压成一个数据包（`g3d.Frame`），`g3d.py` 就是那份协议。

移植时为了让玩法代码不改就能跑起来、并且能和原来的 MCU 渲染器逐像素对比，保留了这份契约，把 MCU 换成一层翻译：

```
玩法（game.py 及以下） → g3d.Frame → alia_view.py 翻译 → alia-engine
```

这层翻译是临时的。引擎每做完一步（材质、世界、动画、碰撞、粒子、系统），就把一部分搬进引擎；到第 8 步，玩法直接驱动引擎里的物体，翻译层消失。

## 2. 现在每个文件是什么

| 文件 | 是什么 | 去向 |
|---|---|---|
| `main.py` | 入口：一个 `Game` 类交给 `alia_engine.run`；`fixed_update` 里跑 `game.step`，`render` 里画 | 保留，更薄 |
| `game.py` | 一局的状态机（Ready → Intro → Fight ⇄ Menu → Execute → Win/Lose），每步调度玩家、BOSS、相机、瞄准，最后拼出 `Frame` | 保留；"拼 Frame"那部分去掉 |
| `player.py`、`boss.py`、`finisher.py` | 玩法实体：骑行、射击、钩锁；BOSS 的 AI 和部件；处决演出。BOSS、马和骑手都是它们自己持有的引擎 rig（第 5、5b 步） | 保留，直接持有引擎里的物体 |
| `camera.py`、`aim.py`、`controls.py` | 相机怎么跟、瞄准吸附、输入映射 | 保留（玩法逻辑）；相机结果直接写引擎的 `world.camera`，输入直接读引擎 |
| `world.py` | **Megalith 自己的世界**：地形高度、竞技场、石头散布、昼夜循环。和引擎的 `engine.world` 无关，名字撞了 | 改名 `terrain.py` |
| `rig.py` | rig 姿态（Python 参考实现） | 只剩测试和 `rig_build.py` 的黄金数据在用；玩法不再用（第 5b 步） |
| `collide.py` | 碰撞的**分类**：BODY / PART / HOOK 层、`Collider`（骨骼号、槽号）、`push_out`。形状和射线在引擎里 | 保留（玩法逻辑） |
| `assets.py` | 把 `gen/rigs.apak` 加载进引擎一次 | 保留 |
| `g3d.py` | 原来的通信协议：数据结构 + 打包函数（打包函数现在只有测试在用） | 第 8 步删掉 |
| `alia_view.py` | 翻译层：Frame → 引擎；Look 调色、地形烘焙、绳子、HUD 排版 | 拆成 `look.py`（调色、天色）和 `hud.py`（HUD），其余删掉 |
| `tilt_config.py`、`preview.py` | 手感参数（名字还是"倾斜"）、摇杆死区 | 合并成 `tuning.py` |
| `audio.py` | 用 `aplay` 放音乐 | 第 7 步换成引擎的混音器 |
| `tools/mesh_build.py`、`rig_build.py`、`audio_build.py` | PC 上把 `assets/` 烘焙成 `python/gen/` | 保留；输出改成引擎的资源包（`meshes.apak` 已经是） |
| `tools/snapshot.py`（`--alia`）、`cart_art.py`、`cart_build.sh` | 44 张关键帧快照（回归）、卡带美术、卡带打包 | 保留 |
| `sketch/` | 原来的 MCU 渲染器 | 保留作画面参照（`tests/cpp/render_preview.sh`） |

## 3. 目标结构（E4 第 8 步）

引擎只给积木（世界里的物体、Animator、碰撞体、粒子发射器），游戏用自己的类组织逻辑（alia-engine `docs/api.md` §8 第 5 条）：

```
main.py       alia_engine.run(Megalith())
game.py       状态机；持有 Player、Boss、Camera，直接驱动它们
player.py     持有马和骑手的 rig、碰撞体、绳子
boss.py       持有 BOSS 的 rig、部件、碰撞体；尘环和碎片交给粒子发射器
camera.py     跟随逻辑不变，结果写 world.camera
terrain.py    地形、竞技场、石头、昼夜（原 world.py）
look.py       Look 调色、调色板、天色（从 alia_view.py 拆出）
hud.py        HUD 排版（唯一还每帧画的东西）
controls.py   直接读 alia_engine 的输入
tuning.py     手感参数（原 tilt_config.py + preview.py）
```

数据流：玩法直接改世界里的物体 → 引擎画。

## 4. 每一步搬走什么

| 引擎步骤 | Megalith 里的变化 | 状态 |
|---|---|---|
| E3a 运行时 | `main.py` 变成 `Game` 类，主循环和显示交给引擎 | ✅ |
| 1 资源 | 网格从自定义格式换成 `meshes.apak` | ✅ |
| 2 材质 | 地形、绳子用材质，不再每次 `draw()` 传参数 | ✅ |
| 3 世界 | 地形、石头变成常驻物体 | ✅ |
| 4 动画 | 三个 rig 变成引擎的 rig 物体（C++ 求姿态，和 `rig.py` 对照差在 10⁻⁶ 以内，`tests/test_alia.py`）；子弹、火花、尘环、钩头是世界里的物体（`alia_view.py` 里按网格分的对象池；它们在两帧之间没有身份，所以不插值）；相机写 `world.camera`；绳子是世界里的物体。`alia_view.py` 分成 `update`（逻辑步里同步世界，引擎插值）和 `draw`（只画 HUD）。玩法里的碰撞体、手和马鞍的位置仍然用 `rig.py`（碰撞体第 5 步换掉了，手和马鞍见第 8 步） | ✅ |
| 5 碰撞 | BOSS 持有自己的引擎 rig（`boss.node`），每步摆好位置和姿态；碰撞体在资源包里（`rig_build.py` 把 JSON 的碰撞体标成层：骨骼 BODY、部件 PART 且平局优先、user 是骨骼号或槽号；马和骑手的碰撞体不在任何层上），两个钩点是骨骼上的 HOOK 球。射击、瞄准吸附、钩点遮挡、BOSS 的脚、动画事件、钩锁的锚点、处决的弱点全部问引擎；子弹打地面用引擎的高度图（`world.set_ground`，和 `terrain_height` 同一个面，`tests/test_alia.py` 对照）。部件打碎时关掉它的碰撞体。`alia_view.py` 不再管 BOSS（`boss.present()` 自己隐藏、淡出、闪烁）。`collide.py` 只剩分类；测试在一个无头引擎里跑（`tests/arena.py`）。玩法里的高度查询（骑行、相机）还是 Python 的 `terrain_height`，第 8 步和 `terrain.py` 一起定 | ✅ |
| 5b 激活、挂载 | 引擎有了 `active`（Unity 语义）、`set_parent(keep_world=True)`、`Rig.attach_position()`。打碎的部件 `slot.active = False`（不画、碰撞体也关）；Ready 时 BOSS 用 `fade = 1`（不画，但还能被打到）；`boss.present()` 只剩淡出和闪烁。Player 持有马和骑手两个 rig：马按原来的规则摆（跟着 PC、跑走淡出、落地前淡入；不在时 `active = False`），骑着的时候骑手挂在马鞍上（`SADDLE_TILT`：跟着马背前后晃，飞奔 4°、受击 14°；`False` 是原来的"直立在马鞍上方"），离开、落回都用 `keep_world`，插值不断。手是骑手的 `hand` 挂点；处决里"打中那一刻手在哪"用 `Rig.attach_position()`。`alia_view.py` 不再管任何 rig，只剩 Frame 里的物体、绳子和 HUD。关掉 `SADDLE_TILT` 时 44 个帧包全部一致；打开时 5 个骑行的帧变了（骑手跟着马背倾斜） | ✅ |
| 6 粒子 | 火花、碎片换成粒子发射器（去掉 MCU 时代的 `MAX_SPARKS = 4`） | |
| 7 系统 | `audio.py` 换成引擎的混音器；按键映射用引擎的动作映射 | |
| 6b 清理 | `rig.py` 回到简单好读的参考实现（去掉姿态缓存和手工展开）；引擎的黄金姿态存成固定文件 | |
| 8 收尾 | **MCU 那条路整个去掉**（原版留在 `main` 分支）：`sketch/`、`tests/cpp/`、`scripts/flash.sh`、`mesh_build.py` / `rig_build.py` 生成的 C 头文件、`g3d.py`（不只是协议：`RawInput`、`Camera`、`Obj`、`Hud`、按键常量是玩法和画面之间传的数据类型，要换成游戏自己的类型或者直接读引擎的输入）、`Frame`、快照里的 `.frame` 包。**先换回归手段**：`.frame` 包逐字节一致是现在最严的检查，删掉之前 `snapshot.py` 改成每个关键帧转储一份游戏状态（PC、BOSS、相机、物体，JSON），比对它和截图。然后拆分 `alia_view.py`，改名（`world.py` → `terrain.py` 等）。`retroarch/` 和 Megalith 无关（比赛的另一个演示），留着 | |

## 5. 怎么验收

- `make test`：82 个玩法测试，在无头的 alia-engine 里跑（先编译 `build/engine-pc`；BOSS 的 rig 和碰撞体在引擎的世界里）。
- `tools/snapshot.py OUT --alia`：44 张关键帧，和上一版逐像素比对。画面确实会变的步骤（插值让运动更平滑、C++ 和 Python 的浮点差异）改成"关掉插值时一致，或者只差在边缘像素"，并在提交说明里写明差了多少。
- 板上：`make cart install launch`，`--stats` 看 `update_ms`、`render_ms`。
