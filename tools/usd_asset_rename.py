"""Rename a character stage to a prefix-based asset naming convention.

The convention is `Prefix_BaseAssetName_Variant_Suffix`, the prefixes used here:

  S_     a mesh part            S_Elaina_Hat_Star_01
  SK_    the skinned character  SK_Elaina
  SKEL_  the rig and skeleton   SKEL_Elaina, SKEL_Elaina_Skeleton
  M_     a material             M_Elaina_Hat
  T_     an image               T_Elaina_Hat_D   (D = diffuse / base colour)
  CAM_   a camera               CAM_Elaina_Snap
  LGT_   a light                LGT_Elaina_Env

Base asset name is the character; the variant names the part; a two-digit variant
number starts at 01. The camera and the light are not asset classes in the usual
sense -- the prefixes keep the stage reading as one set, which is the point of a
convention.

It also collapses the one-mesh wrapper Xforms Blender leaves behind (baking any
transform onto the mesh prim, so a part is a single prim) and renames the image
files to match. Everything is checked afterwards: a path-independent geometry
digest, the world bounding box, material bindings and the skinning.

  usd_asset_rename.py --src IN.usda --dst OUT.usda --textures DIR [--prefix Elaina]
"""
from pxr import Usd, UsdGeom, UsdShade, Sdf
import argparse, os, re, hashlib
import numpy as np

MATERIAL_VARIANTS = {
    "Overcoat_F": "Overcoat_Front",
    "Overcoat_B": "Overcoat_Back",
    "WhiteDress_F": "WhiteDress_Front",
    "WhiteDress_B": "WhiteDress_Back",
    "Hair_OL": "Hair_Outline",
    "WhiteDress_OL": "WhiteDress_Outline",
    "Hat_Cover_001_OL": "HatCover_Outline",
    "Gold_OL": "Gold",
}
TEXTURE_PARTS = {          # fragment of the source file name -> material variant
    "Body_BaseCo": "Body",
    "Eye_BaseCol": "Eye",
    "Eyebrow_Bas": "Eyebrow",
    "Hair_BaseCo": "Hair",
    "Hat_BaseCol": "Hat",
    "Overcoat_B_": "Overcoat_Back",
    "Overcoat_F_": "Overcoat_Front",
    "WhiteDress_": "WhiteDress_Front",
}


def digest(stage):
    """Path-independent digest of everything a rename must not change."""
    h = hashlib.sha256()
    for p in sorted((p for p in stage.Traverse() if p.GetTypeName() == "Mesh"),
                    key=lambda p: str(p.GetPath())):
        for name in ("points", "faceVertexIndices", "faceVertexCounts"):
            v = p.GetAttribute(name).Get()
            h.update(np.asarray(v).tobytes() if v is not None else b"")
        for a in sorted(p.GetAttributes(), key=lambda a: a.GetName()):
            if a.GetName().startswith("primvars:") or a.GetName() in ("normals", "st"):
                v = a.Get()
                if v is not None:
                    h.update(a.GetName().encode())
                    h.update(np.asarray(v).tobytes())
    return h.hexdigest()[:16]


def world_bounds(stage):
    lo, hi = np.array([1e9] * 3), np.array([-1e9] * 3)
    for p in stage.Traverse():
        if p.GetTypeName() != "Mesh":
            continue
        pts = UsdGeom.Mesh(p).GetPointsAttr().Get()
        if pts is None:
            continue
        m = np.asarray(UsdGeom.Xformable(p).ComputeLocalToWorldTransform(Usd.TimeCode.Default()))
        arr = np.array([[float(q[0]), float(q[1]), float(q[2])] for q in pts])
        arr = arr @ m[:3, :3].T + m[:3, 3]
        lo, hi = np.minimum(lo, arr.min(axis=0)), np.maximum(hi, arr.max(axis=0))
    return lo, hi


def bindings(stage):
    out = {}
    for p in stage.Traverse():
        if p.GetTypeName() != "Mesh":
            continue
        b = UsdShade.MaterialBindingAPI(p).ComputeBoundMaterial()[0]
        subs = sorted((c.GetName(),
                       str(UsdShade.MaterialBindingAPI(c).ComputeBoundMaterial()[0].GetPath().name))
                      for c in p.GetChildren())
        out[str(p.GetPath())] = (b.GetPath().name if b else None, subs)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True)
    ap.add_argument("--dst", required=True)
    ap.add_argument("--textures", required=True)
    ap.add_argument("--prefix", default="Elaina")
    args = ap.parse_args()
    P = args.prefix

    src_stage = Usd.Stage.Open(args.src)
    before_digest = digest(src_stage)
    before_bounds = world_bounds(src_stage)
    before_bind = bindings(src_stage)

    layer = Sdf.Layer.FindOrOpen(args.src)

    # ---- 1. ancestors ----------------------------------------------------
    edits = [Sdf.NamespaceEdit(old, new, False) for old, new in
             (("/root", f"/{P}"),
              (f"/{P}/char_grp", f"/{P}/SK_{P}"),
              (f"/{P}/SK_{P}/rig", f"/{P}/SK_{P}/SKEL_{P}"),
              (f"/{P}/_materials", f"/{P}/Materials"))]
    print("ancestors renamed:", layer.Apply(Sdf.BatchNamespaceEdit(edits)))
    if layer.defaultPrim in ("", "root"):      # the old name no longer resolves
        layer.defaultPrim = P

    root, rig = f"/{P}", f"/{P}/SK_{P}/SKEL_{P}"

    # ---- 2. mesh parts: collapse the wrapper, rename ---------------------
    stage = Usd.Stage.Open(args.src)
    moves, wrappers, bake, counters = [], [], [], {}
    for wrap in sorted((c for c in stage.GetPrimAtPath(rig).GetChildren() if c.GetTypeName() == "Xform"),
                       key=lambda c: c.GetName()):
        meshes = [x for x in Usd.PrimRange(wrap) if x.GetTypeName() == "Mesh"]
        if len(meshes) != 1:
            raise SystemExit(f"wrapper {wrap.GetPath()} holds {len(meshes)} meshes")
        mesh = meshes[0]
        base = re.sub(r"_\d+$", "", wrap.GetName())
        counters[base] = counters.get(base, 0) + 1
        new_name = f"S_{P}_{base}_{counters[base]:02d}"
        moves.append(Sdf.NamespaceEdit(str(mesh.GetPath()), f"{rig}/{new_name}", False))
        wrappers.append(Sdf.NamespaceEdit(str(wrap.GetPath()), "", False))
        ops = UsdGeom.Xformable(wrap).GetOrderedXformOps()
        if ops:
            bake.append((new_name, [(o.GetOpName(), o.Get()) for o in ops]))
    print(f"mesh parts renamed {len(moves)}, wrappers collapsed {len(wrappers)}:",
          layer.Apply(Sdf.BatchNamespaceEdit(moves + wrappers)))

    # ---- 3. materials, skeleton, camera, light ---------------------------
    stage = Usd.Stage.Open(args.src)
    edits = []
    for m in stage.GetPrimAtPath(f"{root}/Materials").GetChildren():
        edits.append(Sdf.NamespaceEdit(str(m.GetPath()),
                                       f"{root}/Materials/M_{P}_{MATERIAL_VARIANTS.get(m.GetName(), m.GetName())}",
                                       False))
    edits.append(Sdf.NamespaceEdit(f"{rig}/rig", f"{rig}/SKEL_{P}_Skeleton", False))
    cam = stage.GetPrimAtPath(f"{root}/SnapCam_001")
    if cam and cam.IsValid():
        for c in cam.GetChildren():
            edits.append(Sdf.NamespaceEdit(str(c.GetPath()), f"{root}/CAM_{P}_Snap/CAM_{P}_Snap_Camera", False))
        edits.append(Sdf.NamespaceEdit(str(cam.GetPath()), f"{root}/CAM_{P}_Snap", False))
    if stage.GetPrimAtPath(f"{root}/env_light").IsValid():
        edits.append(Sdf.NamespaceEdit(f"{root}/env_light", f"{root}/LGT_{P}_Env", False))
    print("materials / skeleton / camera / light renamed:", layer.Apply(Sdf.BatchNamespaceEdit(edits)))

    # ---- 4. bake a wrapper's transform onto its mesh ---------------------
    if bake:
        stage = Usd.Stage.Open(args.src)
        for name, ops in bake:
            x = UsdGeom.Xformable(stage.GetPrimAtPath(f"{rig}/{name}"))
            x.ClearXformOpOrder()
            for op_name, val in ops:
                if op_name == "xformOp:transform":
                    x.AddTransformOp().Set(val)
                elif op_name == "xformOp:translate":
                    x.AddTranslateOp().Set(val)
                elif op_name == "xformOp:orient":
                    x.AddOrientOp().Set(val)
                elif op_name == "xformOp:scale":
                    x.AddScaleOp().Set(val)
                else:
                    raise SystemExit(f"unhandled xform op {op_name}")
        layer.Save()
        print(f"baked transforms onto {len(bake)} mesh parts")

    # ---- 5. images -------------------------------------------------------
    renames = {}
    for f in sorted(os.listdir(args.textures)):
        stem, ext = os.path.splitext(f)
        for frag, part in TEXTURE_PARTS.items():
            if frag in stem:
                renames[f] = f"T_{P}_{part}_D{ext}"
                break
        else:
            if ext == ".exr":
                renames[f] = f"T_{P}_Env_D{ext}"
    for old, new in renames.items():
        os.replace(os.path.join(args.textures, old), os.path.join(args.textures, new))
    print(f"images renamed: {len(renames)}")
    for old, new in renames.items():
        print(f"   {old} -> {new}")

    rel_dir = os.path.relpath(os.path.abspath(args.textures), os.path.dirname(os.path.abspath(args.src)))
    stage = Usd.Stage.Open(args.src)
    fixed = 0
    for p in stage.Traverse():
        for a in p.GetAttributes():
            if a.GetTypeName() != Sdf.ValueTypeNames.Asset:
                continue
            v = a.Get()
            if v and v.path and os.path.basename(v.path) in renames:
                a.Set(Sdf.AssetPath(os.path.join(rel_dir, renames[os.path.basename(v.path)])))
                fixed += 1
    layer.Save()
    print(f"image inputs repointed: {fixed}")

    # ---- 6. verify -------------------------------------------------------
    if args.dst != args.src:
        Usd.Stage.Open(args.src).GetRootLayer().Export(args.dst)
    check = Usd.Stage.Open(args.dst)
    print("--- verification ---")
    d_after = digest(check)
    print(f"   geometry digest {before_digest} -> {d_after}  {'OK' if before_digest == d_after else 'CHANGED'}")
    lo0, hi0, lo1, hi1 = *before_bounds, *world_bounds(check)
    same = np.allclose(lo0, lo1, atol=1e-5) and np.allclose(hi0, hi1, atol=1e-5)
    print(f"   world bounds {'OK' if same else 'CHANGED'}  {np.round(lo1, 3)} .. {np.round(hi1, 3)}")
    print(f"   meshes {len([p for p in check.Traverse() if p.GetTypeName() == 'Mesh'])}"
          f" | materials {len([p for p in check.Traverse() if p.GetTypeName() == 'Material'])}"
          f" | joints {len(check.GetPrimAtPath(f'{rig}/SKEL_{P}_Skeleton').GetAttribute('joints').Get())}")
    print(f"   bindings before {len(before_bind)} meshes, after "
          f"{len(bindings(check))} meshes: {'OK' if sorted(before_bind.values(), key=str) == sorted(bindings(check).values(), key=str) else 'CHANGED'}")
    unresolved = sorted({a.Get().path for p in check.Traverse() for a in p.GetAttributes()
                         if a.GetTypeName() == Sdf.ValueTypeNames.Asset and a.Get() and a.Get().path
                         and not a.Get().resolvedPath})
    print(f"   unresolved images: {unresolved}")
    print(f"   mesh parts: {[p.GetName() for p in check.GetPrimAtPath(rig).GetChildren()][:6]}")
    print(f"   materials: {[p.GetName() for p in check.GetPrimAtPath(f'{root}/Materials').GetChildren()][:5]}")
    print(f"   stage prims: {[p.GetName() for p in check.GetPrimAtPath(root).GetChildren()]}")


if __name__ == "__main__":
    main()
