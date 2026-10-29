"""Point each material's UV reader at the UV primvar the meshes actually carry.

The Blender USD export writes `UsdPrimvarReader_float2.varname = "_"` -- a
placeholder for an unnamed UV map -- while the meshes carry `primvars:st`. A
renderer that honours the reader therefore samples a primvar that does not
exist, and every textured material comes out black (Quick Look / RealityKit,
and usdrecord too). The Sketchfab preview renders the artist's own shader graph,
so it shows colour and the USD export does not.

  usd_fix_uv_reader.py --src IN.usdc --dst OUT.usdc [--varname st]

Reports every reader whose name is not a primvar present on the meshes, so the
fix is visible rather than silent.
"""
from pxr import Usd, UsdGeom, UsdShade
import argparse, sys
from collections import Counter


def uv_primvars(stage):
    """primvar names the meshes actually carry, e.g. {'st': 124}."""
    found = Counter()
    for p in stage.Traverse():
        if p.GetTypeName() != "Mesh":
            continue
        for a in p.GetAttributes():
            n = a.GetName()
            if n.startswith("primvars:") and a.Get() is not None and not n.endswith(":indices"):
                found[n.split(":", 1)[1]] += 1
    return found


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True)
    ap.add_argument("--dst", required=True)
    ap.add_argument("--varname", default=None, help="default: the UV primvar the meshes carry")
    args = ap.parse_args()

    stage = Usd.Stage.Open(args.src)
    carried = uv_primvars(stage)
    print("mesh primvars:", dict(sorted(carried.items())))
    want = args.varname or ("st" if "st" in carried else max(carried, key=carried.get))

    fixed, already, missing = 0, 0, []
    for p in stage.Traverse():
        if not p.IsA(UsdShade.Shader):
            continue
        sh = UsdShade.Shader(p)
        if sh.GetIdAttr().Get() != "UsdPrimvarReader_float2":
            continue
        inp = sh.GetInput("varname")
        cur = inp.Get()
        if cur == want:
            already += 1
            continue
        if cur not in carried:
            missing.append((str(p.GetPath()), cur))
        inp.Set(want)
        fixed += 1

    print(f"UV readers: {already} already '{want}', {fixed} repointed to '{want}'")
    for path, cur in missing:
        print(f"   was '{cur}' -> '{want}': {path}")

    left = [str(p.GetPath()) for p in stage.Traverse()
            if p.IsA(UsdShade.Shader)
            and UsdShade.Shader(p).GetIdAttr().Get() == "UsdPrimvarReader_float2"
            and UsdShade.Shader(p).GetInput("varname").Get() not in carried]
    if left:
        print("readers still pointing at a missing primvar:", left)
        sys.exit(1)

    stage.GetRootLayer().Export(args.dst)
    print("exported", args.dst)


if __name__ == "__main__":
    main()
