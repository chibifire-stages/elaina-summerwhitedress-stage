"""Rebuild a layer so its bytes carry no stale paths, and its textures are relative.

Setting a field does not remove the old value from a `.usdc` string table:
`Sdf.Layer.Save()` rewrites the layer but keeps unused strings,
`Usd.Stage.Export()` copies that table, and `Usd.Stage.Flatten()` appends
"Generated from Composed Stage of root layer <path>" to the documentation. So a
layer whose asset paths were once absolute keeps those bytes
even after the paths are fixed -- and publishing content must not carry them.

This fixes the asset inputs in a scratch copy, then builds the output layer from
the *values* with `Sdf.CopySpec`, so the output's string table holds only what its
content references. Stage metadata goes through the stage API (`UsdGeom`), which
this build's `Sdf.Layer` exposes no generic field access for, and the
documentation is set explicitly, last.

  usd_layer_clean.py --src IN.usdc --dst OUT.usdc [--documentation TEXT]
"""
from pxr import Usd, UsdGeom, UsdShade, Sdf
import argparse, os

DEFAULT_DOC = ("Elaina - The Witch's Journey (Summer White Dress), fan art by "
               "ScarletJadeDream (Sketchfab, CC-BY-4.0), exported from Blender and "
               "cleaned with OpenUSD: duplicate outline shells, controller gizmos and "
               "empty Xforms removed, prim names in English, material UV readers "
               "repointed at primvars:st.")


def place(layer_dir, path):
    base = os.path.basename(path)
    if os.path.exists(os.path.join(layer_dir, base)):
        return base
    for sub in sorted(os.listdir(layer_dir)):
        cand = os.path.join(layer_dir, sub)
        if os.path.isdir(cand) and os.path.exists(os.path.join(cand, base)):
            return os.path.join(sub, base)
    return None


def copy_specs(src_layer, dst_layer):
    for name in src_layer.rootPrims:
        Sdf.CopySpec(src_layer, f"/{name.name}", dst_layer, f"/{name.name}")


def copy_stage_metadata(src_stage, dst_stage):
    UsdGeom.SetStageMetersPerUnit(dst_stage, UsdGeom.GetStageMetersPerUnit(src_stage))
    UsdGeom.SetStageUpAxis(dst_stage, UsdGeom.GetStageUpAxis(src_stage))
    if src_stage.GetDefaultPrim():
        dst_stage.SetDefaultPrim(dst_stage.GetPrimAtPath(src_stage.GetDefaultPrim().GetPath()))
    for getter, setter in ((Usd.Stage.GetTimeCodesPerSecond, Usd.Stage.SetTimeCodesPerSecond),
                           (Usd.Stage.GetFramesPerSecond, Usd.Stage.SetFramesPerSecond)):
        try:
            v = getter(src_stage)
            if v:
                setter(dst_stage, v)
        except Exception:
            pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True)
    ap.add_argument("--dst", required=True)
    ap.add_argument("--documentation", default=DEFAULT_DOC)
    ap.add_argument("--needle", action="append",
                    default=["/Users/", "/home/", "/tmp/"],
                    help="a string the rebuilt layer must not contain")
    args = ap.parse_args()

    dst_dir = os.path.dirname(os.path.realpath(args.dst))
    src = Sdf.Layer.FindOrOpen(args.src)
    src_stage = Usd.Stage.Open(args.src)

    work_path = os.path.join(dst_dir, ".work.usdc")
    work = Sdf.Layer.CreateNew(work_path)
    copy_specs(src, work)
    work.Save()
    work_stage = Usd.Stage.Open(work_path)
    copy_stage_metadata(src_stage, work_stage)

    # every asset-valued attribute, not just shader inputs: a dome light's
    # inputs:texture:file is an attribute and is just as likely to be absolute
    fixed = unplaced = 0
    for p in work_stage.Traverse():
        for attr in p.GetAttributes():
            if attr.GetTypeName() != Sdf.ValueTypeNames.Asset:
                continue
            a = attr.Get()
            if not a or not a.path:
                continue
            rel = place(dst_dir, a.path)
            if rel is None:
                unplaced += 1
                continue
            if rel != a.path:
                attr.Set(Sdf.AssetPath(rel))
                fixed += 1
    work.Save()
    if unplaced:
        raise SystemExit(f"{unplaced} asset inputs have no copy under {dst_dir}")

    dst = Sdf.Layer.CreateNew(os.path.realpath(args.dst))
    copy_specs(work, dst)
    dst.Save()
    dst_stage = Usd.Stage.Open(args.dst)
    copy_stage_metadata(work_stage, dst_stage)
    dst.documentation = args.documentation
    dst.Save()
    os.remove(work_path)
    print(f"inputs repointed {fixed} | wrote {args.dst} ({os.path.getsize(args.dst)} bytes)")

    raw = open(args.dst, "rb").read()
    hits = {n: raw.count(n.encode()) for n in args.needle
            if raw.count(n.encode())}
    print("stale-path scan:", hits if hits else "clean")

    check = Usd.Stage.Open(args.dst)
    authored, unresolved = set(), set()
    for p in check.Traverse():
        if p.IsA(UsdShade.Shader):
            for inp in UsdShade.Shader(p).GetInputs():
                if inp.GetTypeName() == Sdf.ValueTypeNames.Asset and inp.Get() and inp.Get().path:
                    a = inp.Get()
                    authored.add(a.path)
                    if not a.resolvedPath:
                        unresolved.add(a.path)
    print(f"texture inputs {len(authored)} | sample {sorted(authored)[:2]} | unresolved {sorted(unresolved)}")
    print(f"defaultPrim {check.GetDefaultPrim().GetName() if check.GetDefaultPrim() else None} "
          f"| upAxis {UsdGeom.GetStageUpAxis(check)} | metersPerUnit {UsdGeom.GetStageMetersPerUnit(check)}")
    if hits or unresolved:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
