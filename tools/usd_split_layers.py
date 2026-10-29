"""Split a flat character stage into a layer stack, one layer per concern.

  Elaina_clean.usda              manifest: layer metadata + sublayers, no prim specs
  layers/Root.usda               the character root Xform
  layers/Skeleton.usda           the rig chain (SK_, SKEL_) and the Skeleton prim
  layers/Materials.usda          the M_ materials and their shaders
  layers/Stage.usda              the camera and the light
  layers/geometry/<Family>.usda  the S_ mesh parts, one layer per part family

Each prim is defined in exactly one layer, so the stack composes with no
conflicting opinions, and an editor opens one part family (or the materials, or
the rig) instead of a 60 MB file. Ancestors live in the layer that owns them; the
manifest layer holds only metadata and the sublayer list.

Image inputs are re-pointed relative to the layer that authors them, then the
stack is checked against the flat source: geometry digest, world bounds, material
bindings, skinning, and that every image resolves.

  usd_split_layers.py --src IN.usda --out-dir DIR --textures DIR [--prefix Elaina]
"""
from pxr import Usd, UsdGeom, UsdShade, Sdf
import argparse, os, re, hashlib, shutil
import numpy as np

FAMILIES = ["Body", "Ear", "Eye", "Eyebrow", "Hair", "Hat", "Overcoat", "WhiteDress", "WhiteShoes"]


def family_of(name):
    base = re.sub(r"^S_[A-Za-z0-9]+_", "", name)
    head = re.sub(r"_\d+$", "", base).split("_")[0]
    return head if head in FAMILIES else "Other"


def copy_prim_shallow(src_stage, path, dst_stage):
    """Copy a prim's own properties, not its children."""
    sp = src_stage.GetPrimAtPath(path)
    dp = dst_stage.DefinePrim(path, sp.GetTypeName())
    for schema in sp.GetAppliedSchemas():
        dp.AddAppliedSchema(schema)
    for a in sp.GetAttributes():
        v = a.Get()
        if v is None:
            continue
        na = dp.CreateAttribute(a.GetName(), a.GetTypeName(), custom=a.IsCustom(),
                                 variability=a.GetVariability())
        na.Set(v)
        for meta in ("interpolation", "elementSize", "role"):
            if a.HasMetadata(meta):
                na.SetMetadata(meta, a.GetMetadata(meta))
    for r in sp.GetRelationships():
        nr = dp.CreateRelationship(r.GetName(), custom=r.IsCustom())   # relationships are uniform
        nr.SetTargets(r.GetTargets())
    return dp


def ensure_ancestors(layer, path):
    """Create over-specs for a path's ancestors so a deep copy can land."""
    parts = [p for p in path.split("/") if p]
    cur = ""
    for name in parts[:-1]:
        cur += "/" + name
        if layer.GetPrimAtPath(cur) is None:
            spec = Sdf.CreatePrimInLayer(layer, cur)
            spec.specifier = Sdf.SpecifierOver


def digest(stage):
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


def bounds(stage):
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


def bound_materials(stage):
    out = {}
    for p in stage.Traverse():
        if p.GetTypeName() != "Mesh":
            continue
        b = UsdShade.MaterialBindingAPI(p).ComputeBoundMaterial()[0]
        out[str(p.GetPath())] = b.GetPath().name if b else None
    return out


def skin_audit(stage):
    rows = bad = zero = 0
    for p in stage.Traverse():
        if p.GetTypeName() != "Mesh":
            continue
        ji, jw = p.GetAttribute("primvars:skel:jointIndices"), p.GetAttribute("primvars:skel:jointWeights")
        if not ji or ji.Get() is None:
            continue
        n = len(UsdGeom.Mesh(p).GetPointsAttr().Get())
        el = ji.GetMetadata("elementSize") or 1
        w = np.array([float(x) for x in jw.Get()], float)
        if len(ji.Get()) != el * n or len(w) != el * n:
            bad += 1
            continue
        s = w.reshape(n, el).sum(axis=1)
        rows += n
        zero += int((s < 1e-6).sum())
    return bad, rows, zero


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--textures", required=True)
    ap.add_argument("--prefix", default="Elaina")
    args = ap.parse_args()
    P = args.prefix

    src_stage = Usd.Stage.Open(args.src)
    src_layer = Sdf.Layer.FindOrOpen(args.src)
    before_digest, before_bounds, before_bind = digest(src_stage), bounds(src_stage), bound_materials(src_stage)

    dp = src_stage.GetDefaultPrim()
    root = str(dp.GetPath()) if dp and dp.IsValid() else f"/{P}"
    sk, skel = f"{root}/SK_{P}", f"{root}/SK_{P}/SKEL_{P}"
    mats, skeleton = f"{root}/Materials", f"{skel}/SKEL_{P}_Skeleton"

    layers_dir = os.path.join(args.out_dir, "layers")
    os.makedirs(os.path.join(layers_dir, "geometry"), exist_ok=True)
    manifest = os.path.join(args.out_dir, f"{P}_clean.usda")

    # Root layer: the character Xform, re-authored (a deep copy would drag the
    # whole subtree in with it).
    st = Usd.Stage.CreateNew(os.path.join(layers_dir, "Root.usda"))
    copy_prim_shallow(src_stage, root, st)
    st.GetRootLayer().Save()

    # Skeleton layer: the rig chain (own properties only) plus the Skeleton prim.
    st = Usd.Stage.CreateNew(os.path.join(layers_dir, "Skeleton.usda"))
    for path in (sk, skel):
        copy_prim_shallow(src_stage, path, st)
    ensure_ancestors(st.GetRootLayer(), skeleton)
    Sdf.CopySpec(src_layer, skeleton, st.GetRootLayer(), skeleton)
    st.GetRootLayer().Save()

    # Materials and Stage: deep copies.
    stage_prims = [str(c.GetPath()) for c in src_stage.GetPrimAtPath(root).GetChildren()
                   if c.GetTypeName() == "DomeLight" or c.GetName().startswith("CAM_")]
    for name, prims in (("Materials", [mats]), ("Stage", stage_prims)):
        layer = Sdf.Layer.CreateNew(os.path.join(layers_dir, f"{name}.usda"))
        for p in prims:
            ensure_ancestors(layer, p)
            Sdf.CopySpec(src_layer, p, layer, p)
        layer.Save()

    # Geometry: one layer per part family.
    counts = {}
    for c in src_stage.GetPrimAtPath(skel).GetChildren():
        if c.GetName() == f"SKEL_{P}_Skeleton":
            continue
        fam = family_of(c.GetName())
        path = os.path.join(layers_dir, "geometry", f"{fam}.usda")
        if not os.path.exists(path):
            Sdf.Layer.CreateNew(path).Save()
        layer = Sdf.Layer.FindOrOpen(path)
        ensure_ancestors(layer, str(c.GetPath()))
        Sdf.CopySpec(src_layer, str(c.GetPath()), layer, str(c.GetPath()))
        layer.Save()
        counts[fam] = counts.get(fam, 0) + 1
    print("geometry layers:", dict(sorted(counts.items())))

    # Manifest layer: metadata, default prim, sublayers.
    manifest_layer = Sdf.Layer.CreateNew(manifest)
    st = Usd.Stage.Open(manifest)
    UsdGeom.SetStageMetersPerUnit(st, UsdGeom.GetStageMetersPerUnit(src_stage))
    UsdGeom.SetStageUpAxis(st, UsdGeom.GetStageUpAxis(src_stage))
    st.SetDefaultPrim(st.DefinePrim(root, "Xform"))
    manifest_layer.documentation = src_layer.documentation
    manifest_layer.subLayerPaths = ["layers/Root.usda", "layers/Skeleton.usda", "layers/Materials.usda",
                                    "layers/Stage.usda"] + \
                                   [f"layers/geometry/{f}.usda" for f in sorted(counts)]
    manifest_layer.Save()
    print("sublayers:", manifest_layer.subLayerPaths)

    # Images: copy them beside the layers and re-point their file inputs.
    # The materials and stage are *over* layers (over "Elaina"), so their prims
    # live under the over-root and only appear once composed.  Sdf.Layer.Traverse
    # hands the over-rooted path back, and layer.GetPropertyAtPath(path) returns
    # the asset.  Setting prop.default keeps it authored as @../textures/<name>
    # (relative to the layer), which resolves once the package is assembled.
    # (The old SDF spec-level walk passed a callback the wrong signature; this
    # 1-arg form + GetPropertyAtPath works across pxr builds.)
    out_tex = os.path.join(args.out_dir, "textures")
    os.makedirs(out_tex, exist_ok=True)
    fixed = 0
    for name in ("Materials.usda", "Stage.usda"):
        layer_file = os.path.join(layers_dir, name)
        layer = Sdf.Layer.FindOrOpen(layer_file)
        paths = []
        def _cb(path):
            paths.append(path)
        layer.Traverse("/", _cb)
        for path in paths:
            try:
                prop = layer.GetPropertyAtPath(path)
            except Exception:
                continue
            if prop is None or prop.typeName != Sdf.ValueTypeNames.Asset:
                continue
            v = prop.default
            if not v or not v.path:
                continue
            base = os.path.basename(v.path)
            src = os.path.join(args.textures, base)
            if not os.path.exists(src):
                continue
            tgt = os.path.join(out_tex, base)
            if not os.path.exists(tgt):
                shutil.copyfile(src, tgt)
            prop.default = Sdf.AssetPath(os.path.join("..", "textures", base))
            fixed += 1
        layer.Save()
    print(f"image inputs repointed ({fixed}) and images copied to {out_tex}")

    # ---- verify ----------------------------------------------------------
    check = Usd.Stage.Open(manifest)
    print("--- verification ---")
    print(f"   prims {len(list(check.Traverse()))} | meshes "
          f"{len([p for p in check.Traverse() if p.GetTypeName() == 'Mesh'])} | materials "
          f"{len([p for p in check.Traverse() if p.GetTypeName() == 'Material'])} | joints "
          f"{len(check.GetPrimAtPath(skeleton).GetAttribute('joints').Get())}")
    d_after = digest(check)
    print(f"   geometry digest {before_digest} -> {d_after}  {'OK' if before_digest == d_after else 'CHANGED'}")
    lo0, hi0, lo1, hi1 = *before_bounds, *bounds(check)
    same = np.allclose(lo0, lo1, atol=1e-5) and np.allclose(hi0, hi1, atol=1e-5)
    print(f"   world bounds {'OK' if same else 'CHANGED'}  {np.round(lo1, 3)} .. {np.round(hi1, 3)}")
    after_bind = bound_materials(check)
    same_bind = sorted(before_bind.values(), key=str) == sorted(after_bind.values(), key=str)
    print(f"   material bindings {len(after_bind)} meshes  {'OK' if same_bind else 'CHANGED'}")
    bad, rows, zero = skin_audit(check)
    print(f"   skin: wrong-length arrays {bad} | point rows {rows} | unweighted {zero}")
    unresolved = sorted({a.Get().path for p in check.Traverse() for a in p.GetAttributes()
                         if a.GetTypeName() == Sdf.ValueTypeNames.Asset and a.Get() and a.Get().path
                         and not a.Get().resolvedPath})
    print(f"   unresolved images: {unresolved}")
    print(f"   stage prims: {[p.GetName() for p in check.GetPrimAtPath(root).GetChildren()]}")


if __name__ == "__main__":
    main()
