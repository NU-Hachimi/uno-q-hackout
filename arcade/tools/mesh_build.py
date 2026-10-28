#!/usr/bin/env python3
"""Turn assets/ (meshes, palette, Looks) into sketch/gen/ and python/gen/.

python/gen/meshes.bin is the mesh pack alia-engine loads (python/alia_view.py); the same
triangles as sketch/gen/meshes.h:
    "AMP1", u16 count, then per mesh: u8 id, u16 n_verts, u16 n_tris,
    f32 xyz[n_verts], u16 tri[n_tris][3], u8 palette_index[n_tris]   (little-endian)

    python3 tools/mesh_build.py          (run from arcade/; rewrites the generated files)
    python3 tools/mesh_build.py --check  (exit 1 if the generated files are stale)

OBJ faces are fan-triangulated and grouped by material. Material names must be palette
names and their Kd must match the palette colour (api.md §5.2, art.md §8).
"""

import argparse
import json
import math
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"
DEFAULT_LOOK = "forbidden_plain"
KD_TOLERANCE = 1.5 / 255
FIXED_IDS = {"pc": 0, "bullet": 1, "boss_shot": 2, "hook_head": 3, "spark": 4, "shockwave_ring": 5}


def fail(message):
    sys.exit(f"mesh_build: {message}")


def hex_rgb(value):
    value = value.lstrip("#")
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))


def rgb565(rgb):
    r, g, b = rgb
    return ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)


def load_palette():
    data = json.loads((ASSETS / "palette.json").read_text())
    colors = sorted(data["colors"], key=lambda c: c["index"])
    if [c["index"] for c in colors] != list(range(1, 32)):
        fail("palette.json must define indices 1..31")
    for c in colors:
        if rgb565(hex_rgb(c["rgb"])) != int(c["rgb565"], 16):
            fail(f"palette {c['name']}: rgb565 {c['rgb565']} does not match {c['rgb']}")
    return colors, data["scene_defaults"]


def load_materials(colors):
    by_name = {c["name"]: c for c in colors}
    materials, name = {}, None
    for line in (ASSETS / "meshes" / "palette.mtl").read_text().splitlines():
        parts = line.split()
        if not parts:
            continue
        if parts[0] == "newmtl":
            name = parts[1]
        elif parts[0] == "Kd" and name:
            if name not in by_name:
                fail(f"palette.mtl material {name} is not a palette name")
            kd = [float(v) for v in parts[1:4]]
            want = [v / 255 for v in hex_rgb(by_name[name]["rgb"])]
            if any(abs(a - b) > KD_TOLERANCE for a, b in zip(kd, want)):
                fail(f"palette.mtl {name}: Kd {kd} is not the palette colour {by_name[name]['rgb']}")
            materials[name] = by_name[name]["index"]
    return materials


def load_obj(path, materials):
    verts, tris, material = [], [], None
    for number, line in enumerate(path.read_text().splitlines(), 1):
        parts = line.split()
        if not parts:
            continue
        if parts[0] == "v":
            verts.append(tuple(float(v) for v in parts[1:4]))
        elif parts[0] == "usemtl":
            if parts[1] not in materials:
                fail(f"{path.name}:{number}: material {parts[1]} is not in the palette")
            material = materials[parts[1]]
        elif parts[0] == "f":
            if material is None:
                fail(f"{path.name}:{number}: face before usemtl")
            index = [int(p.split("/")[0]) for p in parts[1:]]
            index = [i - 1 if i > 0 else len(verts) + i for i in index]
            for k in range(1, len(index) - 1):  # fan triangulation keeps the winding
                tris.append((material, index[0], index[k], index[k + 1]))
    if not tris:
        fail(f"{path.name}: no faces")
    # Merge identical positions; flat shading takes normals from the triangle itself.
    remap, unique, lookup = {}, [], {}
    for old, v in enumerate(verts):
        key = tuple(round(c, 5) for c in v)
        if key not in lookup:
            lookup[key] = len(unique)
            unique.append(key)
        remap[old] = lookup[key]
    tris.sort(key=lambda t: t[0])  # stable: groups by palette index, keeps face order within
    groups = []
    for t in tris:
        if not groups or groups[-1][0] != t[0]:
            groups.append([t[0], 0])
        groups[-1][1] += 1
    radius = max(math.sqrt(sum(c * c for c in v)) for v in unique)
    return {
        "verts": unique,
        "tris": [(remap[a], remap[b], remap[c]) for _, a, b, c in tris],
        "groups": groups,
        "radius": radius,
    }


def load_look(name, colors):
    look = json.loads((ASSETS / "looks" / f"{name}.json").read_text())
    by_name = {c["name"]: c["index"] for c in colors}
    palette = [0] + [int(c["rgb565"], 16) for c in colors]
    for key, value in look.get("palette", {}).items():
        if key not in by_name:
            fail(f"look {name}: unknown palette name {key}")
        palette[by_name[key]] = rgb565(hex_rgb(value))
    return look, palette


def fmt_float(v):
    return f"{v:.4f}f"


def build():
    colors, scene_defaults = load_palette()
    materials = load_materials(colors)
    table = json.loads((ASSETS / "meshes.json").read_text())["meshes"]
    for name, fixed in FIXED_IDS.items():
        if not any(m["id"] == fixed and m["name"] == name for m in table):
            fail(f"meshes.json: {name} must have id {fixed} (api.md §5.3)")
    if len({m["id"] for m in table}) != len(table):
        fail("meshes.json: duplicate ids")
    meshes = {m["id"]: (m, load_obj(ASSETS / "meshes" / f"{m['name']}.obj", materials)) for m in table}
    look, look_palette = load_look(DEFAULT_LOOK, colors)
    by_name = {c["name"]: c for c in colors}

    def scene_color(value):
        return int(by_name[value]["rgb565"], 16) if value in by_name else rgb565(hex_rgb(value))

    scene = {
        "sky_top": scene_color(scene_defaults["sky_top"]),
        "sky_horizon": scene_color(scene_defaults["sky_horizon"]),
        "fog_color": scene_color(scene_defaults["fog_color"]),
        "grass_a": scene_color(scene_defaults["grass_a"]),
        "grass_b": scene_color(scene_defaults["grass_b"]),
        "fog_near": scene_defaults["fog_near"],
        "fog_far": scene_defaults["fog_far"],
        "light_yaw": scene_defaults["light_yaw"],
        "light_pitch": scene_defaults["light_pitch"],
    }
    header = "Generated by tools/mesh_build.py from arcade/assets/. Do not edit."
    count = max(meshes) + 1

    out = [f"// {header}", "#pragma once", "", "#include <stdint.h>", "", "namespace gen {", "",
           "struct Mesh {",
           "  const float* verts;      // xyz triples, metres; origin at the joint",
           "  const uint16_t* tris;    // vertex index triples, counter-clockwise front faces",
           "  const uint16_t* groupEnd;  // exclusive triangle end of each colour group",
           "  const uint8_t* groupColor; // palette index of each group",
           "  uint16_t nTris;",
           "  uint8_t nGroups;",
           "  float radius;            // bounding sphere around the origin",
           "};", ""]
    for mid in sorted(meshes):
        name, mesh = meshes[mid][0]["name"], meshes[mid][1]
        flat = ", ".join(fmt_float(c) for v in mesh["verts"] for c in v)
        tris = ", ".join(str(i) for t in mesh["tris"] for i in t)
        ends, total = [], 0
        for _, n in mesh["groups"]:
            total += n
            ends.append(str(total))
        out += [f"// {name}: {len(mesh['tris'])} tris, {len(mesh['verts'])} verts",
                f"static const float {name}_verts[] = {{{flat}}};",
                f"static const uint16_t {name}_tris[] = {{{tris}}};",
                f"static const uint16_t {name}_group_end[] = {{{', '.join(ends)}}};",
                f"static const uint8_t {name}_group_color[] = {{{', '.join(str(g[0]) for g in mesh['groups'])}}};", ""]
    out += [f"constexpr uint8_t MESH_{meshes[mid][0]['name'].upper()} = {mid};" for mid in sorted(meshes)]
    out.append("")
    out.append(f"constexpr int MESH_COUNT = {count};")
    out.append("static const Mesh MESHES[MESH_COUNT] = {")
    for mid in range(count):
        if mid in meshes:
            name, mesh = meshes[mid][0]["name"], meshes[mid][1]
            out.append(f"    {{{name}_verts, {name}_tris, {name}_group_end, {name}_group_color, "
                       f"{len(mesh['tris'])}, {len(mesh['groups'])}, {fmt_float(mesh['radius'])}}},  // {mid}")
        else:
            out.append(f"    {{nullptr, nullptr, nullptr, nullptr, 0, 0, 0.0f}},  // {mid} unused")
    out += ["};", "", "// Attachment points in mesh space, metres (meshes.json attach)."]
    for mid in sorted(meshes):
        for point, xyz in meshes[mid][0].get("attach", {}).items():
            out.append(f"constexpr float ATTACH_{meshes[mid][0]['name'].upper()}_{point.upper()}[3] = "
                       f"{{{', '.join(fmt_float(c) for c in xyz)}}};")
    out += ["", "}  // namespace gen", ""]
    meshes_h = "\n".join(out)

    def u16(value):
        return f"0x{value:04X}"

    out = [f"// {header}", "#pragma once", "", "#include <stdint.h>", "", "namespace gen {", "",
           "// Default palette (art.md §3); index 0 is unused.",
           f"constexpr uint16_t PALETTE[32] = {{{', '.join(u16(v) for v in [0] + [int(c['rgb565'], 16) for c in colors])}}};",
           ""]
    out += [f"constexpr uint8_t PAL_{c['name']} = {c['index']};" for c in colors]
    out += ["", f"// Built-in Look '{DEFAULT_LOOK}' (api.md §3.2 kind 3), used until Python uploads one.",
            "struct Look {",
            "  uint16_t palette[32];",
            "  uint8_t gradeMode, saturation, contrast;",
            "  int8_t brightness;",
            "  uint8_t gamma;",
            "  uint16_t lift, gain;",
            "  uint8_t posterize, dither;",
            "  uint8_t groundFog;  // 0..255: height fog strength near the ground (api.md §3.2 byte 75)",
            "};",
            f"constexpr Look DEFAULT_LOOK = {{{{{', '.join(u16(v) for v in look_palette)}}}, "
            f"{look['grade_mode']}, {look['saturation']}, {look['contrast']}, {look['brightness']}, {look['gamma']}, "
            f"{u16(rgb565(hex_rgb(look['lift'])))}, {u16(rgb565(hex_rgb(look['gain'])))}, "
            f"{look['posterize']}, {look['dither']}, {look.get('ground_fog', 0)}}};",
            "",
            "// palette.json scene_defaults; the demo scene uses them until Python commits a scene.",
            f"constexpr uint16_t SCENE_SKY_TOP = {u16(scene['sky_top'])}, SCENE_SKY_HORIZON = {u16(scene['sky_horizon'])},",
            f"                   SCENE_FOG_COLOR = {u16(scene['fog_color'])}, SCENE_GRASS_A = {u16(scene['grass_a'])},",
            f"                   SCENE_GRASS_B = {u16(scene['grass_b'])};",
            f"constexpr uint8_t SCENE_FOG_NEAR = {scene['fog_near']}, SCENE_FOG_FAR = {scene['fog_far']};  // 2 m units",
            f"constexpr uint8_t SCENE_LIGHT_YAW = {scene['light_yaw']}, SCENE_LIGHT_PITCH = {scene['light_pitch']};  // BAM8",
            "", "}  // namespace gen", ""]
    palette_h = "\n".join(out)

    out = [f'"""{header}"""', "", "# Palette indices for object tints (api.md §5.4)."]
    out += [f"{c['name']} = {c['index']}" for c in colors]
    out += ["", "PALETTE_565 = (" + ", ".join(u16(v) for v in [0] + [int(c['rgb565'], 16) for c in colors]) + ")",
            "", "# palette.json scene_defaults with colours resolved to RGB565.",
            "SCENE_DEFAULTS = {"]
    out += [f"    {k!r}: {u16(v) if k in ('sky_top', 'sky_horizon', 'fog_color', 'grass_a', 'grass_b') else v}," for k, v in scene.items()]
    out += ["}", ""]
    palette_py = "\n".join(out)

    out = [f'"""{header}"""', "", "# Mesh ids (api.md §5.3)."]
    out += [f"{meshes[mid][0]['name'].upper()} = {mid}" for mid in sorted(meshes)]
    out += ["", "# Bounding radius around each mesh origin, metres.", "RADIUS = {"]
    out += [f"    {mid}: {meshes[mid][1]['radius']:.4f}," for mid in sorted(meshes)]
    out += ["}", "", "# Attachment points in mesh space, metres."]
    for mid in sorted(meshes):
        for point, xyz in meshes[mid][0].get("attach", {}).items():
            out.append(f"{meshes[mid][0]['name'].upper()}_{point.upper()} = ({', '.join(f'{c:.4f}' for c in xyz)})")
    out.append("")
    mesh_ids_py = "\n".join(out)

    # Every Look as its 76 B kind 3 block (api.md §3.2) plus the scene header overrides (api.md §5.4).
    out = [f'"""{header}"""', "", "# Look name -> {'block': kind 3 chunk bytes, 'scene': scene_defaults overrides}.",
           "LOOKS = {"]
    for path in sorted((ASSETS / "looks").glob("*.json")):
        lk, pal = load_look(path.stem, colors)
        block = b"".join(v.to_bytes(2, "little") for v in pal)
        block += bytes([lk["grade_mode"], lk["saturation"], lk["contrast"], lk["brightness"] & 0xFF, lk["gamma"]])
        block += rgb565(hex_rgb(lk["lift"])).to_bytes(2, "little") + rgb565(hex_rgb(lk["gain"])).to_bytes(2, "little")
        block += bytes([lk["posterize"], lk["dither"], lk.get("ground_fog", 0)])
        assert len(block) == 76
        over = {k: scene_color(v) if k in ("sky_top", "sky_horizon", "fog_color", "grass_a", "grass_b") else v
                for k, v in lk.get("scene", {}).items()}
        out.append(f"    {path.stem!r}: {{'block': bytes.fromhex({block.hex()!r}), 'scene': {over!r}}},")
    out += ["}", ""]
    looks_py = "\n".join(out)

    pack = bytearray(b"AMP1" + struct.pack("<H", len(meshes)))
    for mid in sorted(meshes):
        mesh = meshes[mid][1]
        colors = [g[0] for g in mesh["groups"] for _ in range(g[1])]
        pack += struct.pack("<BHH", mid, len(mesh["verts"]), len(mesh["tris"]))
        pack += struct.pack(f"<{3 * len(mesh['verts'])}f", *(c for v in mesh["verts"] for c in v))
        pack += struct.pack(f"<{3 * len(mesh['tris'])}H", *(i for t in mesh["tris"] for i in t))
        pack += bytes(colors)

    return {
        ROOT / "python" / "gen" / "meshes.bin": bytes(pack),
        ROOT / "python" / "gen" / "looks.py": looks_py,
        ROOT / "sketch" / "gen" / "meshes.h": meshes_h,
        ROOT / "sketch" / "gen" / "palette.h": palette_h,
        ROOT / "python" / "gen" / "__init__.py": f'"""{header}"""\n',
        ROOT / "python" / "gen" / "palette.py": palette_py,
        ROOT / "python" / "gen" / "mesh_ids.py": mesh_ids_py,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="only report whether the outputs are up to date")
    args = parser.parse_args()
    stale = []
    for path, data in build().items():
        binary = isinstance(data, bytes)
        if not path.exists() or (path.read_bytes() if binary else path.read_text()) != data:
            stale.append(path)
            if not args.check:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data) if binary else path.write_text(data)
    for path in stale:
        print(("stale: " if args.check else "wrote: ") + str(path.relative_to(ROOT)))
    if args.check and stale:
        sys.exit(1)


if __name__ == "__main__":
    main()
