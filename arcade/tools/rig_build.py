#!/usr/bin/env python3
"""Turn assets/rigs/*.json into sketch/gen/rigs.h, python/gen/rigs.py and tests/golden/rig_<name>.json.

    python3 tools/rig_build.py          (run from arcade/; rewrites the generated files)
    python3 tools/rig_build.py --check  (exit 1 if the generated files are stale)

Mesh names resolve through assets/meshes.json, so run tools/mesh_build.py first when meshes change.
The golden file holds every bone's world origin at phases 0/64/128/192 of every animation, computed
by python/rig.py (the reference); sketch/rig.cpp must agree within 1 cm (api.md §5.1).
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"
sys.path.insert(0, str(ROOT / "python"))

import rig as rigmath  # noqa: E402

GOLDEN_PHASES = (0, 64, 128, 192)
EMPTY = 0xFF  # slot variant / mesh id meaning "nothing"


def fail(message):
    sys.exit(f"rig_build: {message}")


def f(v):
    return f"{v:.4f}f"


def vec(v):
    return "{" + ", ".join(f(c) for c in v) + "}"


def load():
    mesh_ids = {m["name"]: m["id"] for m in json.loads((ASSETS / "meshes.json").read_text())["meshes"]}
    rigs = []
    for path in sorted((ASSETS / "rigs").glob("*.json")):
        r = json.loads(path.read_text())
        names = [b["name"] for b in r["bones"]]
        if len(names) > 16 or len(r["slots"]) > 32 or len(r["anims"]) > 16:
            fail(f"{path.name}: over the bone/slot/anim limits (api.md §8)")
        for i, b in enumerate(r["bones"]):
            if b["parent"] is not None and (b["parent"] not in names or names.index(b["parent"]) >= i):
                fail(f"{path.name}: bone {b['name']} must come after its parent")
            if b["mesh"] and b["mesh"] not in mesh_ids:
                fail(f"{path.name}: bone {b['name']} uses unknown mesh {b['mesh']}")
        for s in r["slots"]:
            for v in s["variants"][1:]:
                if v not in mesh_ids:
                    fail(f"{path.name}: slot variant {v} is not in meshes.json")
        for i, a in enumerate(r["anims"]):
            if a["id"] != i:
                fail(f"{path.name}: anim ids must be 0..n-1 in order ({a['name']})")
            for bone, keys in a["tracks"].items():
                if bone not in names or len(keys) != a["keys"]:
                    fail(f"{path.name}: anim {a['name']} track {bone} is unknown or has the wrong key count")
            if len(a.get("root_y", [0] * a["keys"])) != a["keys"]:
                fail(f"{path.name}: anim {a['name']} root_y has the wrong key count")
        for point, a in r.get("attach", {}).items():
            if a["bone"] not in names:
                fail(f"{path.name}: attach {point} on unknown bone {a['bone']}")
        rigs.append(r)
    ids = [r["id"] for r in rigs]
    if len(set(ids)) != len(ids) or min(ids) < 1:
        fail("rig ids must be unique and >= 1")
    return rigs, mesh_ids


def header(rigs, mesh_ids, note):
    out = [f"// {note}", "#pragma once", "", "#include <stdint.h>", "", "namespace gen {", "",
           "struct RigBone {",
           "  int8_t parent;    // index, -1 for the root",
           "  uint8_t mesh;     // gen::MESHES index, 0xFF for none",
           "  float offset[3];  // m, in the parent's frame",
           "};",
           "struct RigSlot {",
           "  uint8_t bone, nVariants;",
           "  float offset[3], rot[3];  // m; degrees, same order as tracks",
           "  const uint8_t* variants;  // mesh id per variant; [0] is 0xFF (empty)",
           "};",
           "struct RigAttach {",
           "  uint8_t bone;",
           "  float offset[3];",
           "};",
           "struct RigAnim {",
           "  uint8_t keys, loop, nTracks;",
           "  const uint8_t* trackBone;  // bone index of each track",
           "  const float* trackKeys;    // nTracks * keys * [rx, ry, rz] degrees",
           "  const float* rootY;        // keys values (m) or nullptr",
           "};",
           "struct Rig {",
           "  uint8_t nBones, nSlots, nAnims;",
           "  int8_t hand;  // index into attach of `hand` (rope start), -1 if none",
           "  const RigBone* bones;",
           "  const RigSlot* slots;",
           "  const RigAnim* anims;",
           "  const RigAttach* attach;",
           "};", ""]
    count = max(r["id"] for r in rigs) + 1
    by_id = {r["id"]: r for r in rigs}
    for r in rigs:
        n = r["name"]
        names = [b["name"] for b in r["bones"]]
        out.append(f"// {n} (rig {r['id']}): {len(names)} bones, {len(r['slots'])} slots, {len(r['anims'])} anims")
        bones = [f"{{{names.index(b['parent']) if b['parent'] else -1}, "
                 f"{mesh_ids[b['mesh']] if b['mesh'] else EMPTY}, {vec(b['offset'])}}}" for b in r["bones"]]
        out.append(f"static const RigBone {n}_bones[] = {{{', '.join(bones)}}};")
        for i, s in enumerate(r["slots"]):
            ids = [EMPTY] + [mesh_ids[v] for v in s["variants"][1:]]
            out.append(f"static const uint8_t {n}_slot{i}_variants[] = {{{', '.join(map(str, ids))}}};")
        if r["slots"]:
            slots = [f"{{{names.index(s['bone'])}, {len(s['variants'])}, {vec(s['offset'])}, {vec(s['rot'])}, "
                     f"{n}_slot{i}_variants}}" for i, s in enumerate(r["slots"])]
            out.append(f"static const RigSlot {n}_slots[] = {{{', '.join(slots)}}};")
        attach = list(r.get("attach", {}).items())
        if attach:
            out.append(f"// attach: {', '.join(k for k, _ in attach)}")
            out.append(f"static const RigAttach {n}_attach[] = {{"
                       + ", ".join(f"{{{names.index(a['bone'])}, {vec(a['offset'])}}}" for _, a in attach) + "};")
        for a in r["anims"]:
            tracks = list(a["tracks"].items())
            tag = f"{n}_{a['name']}"
            out.append(f"static const uint8_t {tag}_bones[] = {{{', '.join(str(names.index(b)) for b, _ in tracks) or '0'}}};")
            keys = ", ".join(f(c) for _, ks in tracks for k in ks for c in k)
            out.append(f"static const float {tag}_keys[] = {{{keys or '0'}}};")
            if "root_y" in a:
                out.append(f"static const float {tag}_root_y[] = {{{', '.join(f(v) for v in a['root_y'])}}};")
        anims = [f"{{{a['keys']}, {1 if a['loop'] else 0}, {len(a['tracks'])}, {n}_{a['name']}_bones, "
                 f"{n}_{a['name']}_keys, {n + '_' + a['name'] + '_root_y' if 'root_y' in a else 'nullptr'}}}"
                 for a in r["anims"]]
        out.append(f"static const RigAnim {n}_anims[] = {{{', '.join(anims)}}};")
        out.append("")
    for r in rigs:
        up = r["name"].upper()
        out.append(f"constexpr uint8_t RIG_{up} = {r['id']};")
        out += [f"constexpr uint8_t ANIM_{up}_{a['name'].upper()} = {a['id']};" for a in r["anims"]]
        out += [f"constexpr uint8_t ATTACH_{up}_{k.upper()} = {i};" for i, k in enumerate(r.get("attach", {}))]
    out.append("")
    out.append(f"constexpr int RIG_COUNT = {count};  // index = rig_id; 0 and gaps are empty")
    out.append("static const Rig RIGS[RIG_COUNT] = {")
    for i in range(count):
        if i in by_id:
            r = by_id[i]
            n = r["name"]
            attach = list(r.get("attach", {}))
            out.append(f"    {{{len(r['bones'])}, {len(r['slots'])}, {len(r['anims'])}, "
                       f"{attach.index('hand') if 'hand' in attach else -1}, {n}_bones, "
                       f"{n + '_slots' if r['slots'] else 'nullptr'}, {n}_anims, "
                       f"{n + '_attach' if attach else 'nullptr'}}},  // {i} {n}")
        else:
            out.append(f"    {{0, 0, 0, -1, nullptr, nullptr, nullptr, nullptr}},  // {i} unused")
    out += ["};", "", "}  // namespace gen", ""]
    return "\n".join(out)


def python_module(rigs, note):
    out = [f'"""{note}"""', "", "# Rig ids (api.md §3.3) and animation ids by name."]
    for r in rigs:
        out.append(f"{r['name'].upper()} = {r['id']}")
    out += ["", "ANIM = {"]
    for r in rigs:
        anims = ", ".join(f"{a['name']!r}: {a['id']}" for a in r["anims"])
        out.append(f"    {r['name']!r}: {{{anims}}},")
    out += ["}", "", "# Full rig data (bones, colliders, slots, attach, anims with events), as in assets/rigs/.",
            "RIGS = {"]
    for r in rigs:
        out.append(f"    {r['id']}: {json.dumps(r, separators=(',', ':'))},".replace("null", "None")
                   .replace("true", "True").replace("false", "False"))
    out += ["}", ""]
    return "\n".join(out)


def golden(r):
    data = {"rig": r["name"], "phases": list(GOLDEN_PHASES), "bones": [b["name"] for b in r["bones"]], "anims": {}}
    for a in r["anims"]:
        data["anims"][a["name"]] = [[[round(c, 5) for c in rigmath.pose(r, a["id"], ph)[b["name"]][1]]
                                     for b in r["bones"]] for ph in GOLDEN_PHASES]
    return json.dumps(data, indent=1) + "\n"


def build():
    rigs, mesh_ids = load()
    note = "Generated by tools/rig_build.py from arcade/assets/rigs/. Do not edit."
    files = {ROOT / "sketch" / "gen" / "rigs.h": header(rigs, mesh_ids, note),
             ROOT / "python" / "gen" / "rigs.py": python_module(rigs, note)}
    for r in rigs:
        files[ROOT / "tests" / "golden" / f"rig_{r['name']}.json"] = golden(r)
    return files


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="only report whether the outputs are up to date")
    args = parser.parse_args()
    stale = []
    for path, text in build().items():
        if not path.exists() or path.read_text() != text:
            stale.append(path)
            if not args.check:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text)
    for path in stale:
        print(("stale: " if args.check else "wrote: ") + str(path.relative_to(ROOT)))
    if args.check and stale:
        sys.exit(1)


if __name__ == "__main__":
    main()
