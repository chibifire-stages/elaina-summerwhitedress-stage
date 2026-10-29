"""Sweep the Elaina USD: outline copies, controller gizmos, junk empties.

The asset ships each toon outline as a duplicated shell inside the same mesh,
split by Blender's exporter into `<name>` (fill) and `<name>_OL` (outline)
GeomSubsets with their own point ranges and skin weights. This removes every
`_OL` subset's faces and the points only they reference, remaps the vertex- and
faceVarying-interpolated primvars, repairs a mesh-level material binding left
pointing at a removed outline material, then removes the `cs_*` controller
gizmo group and the childless leftover Xforms at the scene root.

It writes a manifest of the surgery (old point and old face index per surviving
element) so a checker can prove the kept geometry is the source's own data,
element for element, rather than merely similar.
"""
from pxr import Usd, UsdGeom, UsdShade, Sdf, Vt
import argparse, json


def face_offsets(counts):
    offs, o = [], 0
    for c in counts:
        offs.append(o)
        o += c
    return offs


def strip_mesh(prim, suffix):
    mesh = UsdGeom.Mesh(prim)
    counts = list(mesh.GetFaceVertexCountsAttr().Get())
    fvi = list(mesh.GetFaceVertexIndicesAttr().Get())
    offs = face_offsets(counts)
    subsets = [c for c in prim.GetChildren() if c.GetTypeName() == "GeomSubset"]

    removed, surviving = set(), []
    for s in subsets:
        idx = list(UsdGeom.Subset(s).GetIndicesAttr().Get())
        if s.GetName().endswith(suffix):
            removed.update(idx)
        else:
            surviving.append((s, idx))
    if not removed:
        return None

    kept_faces = [f for f in range(len(counts)) if f not in removed]
    kept_positions = [offs[f] + k for f in kept_faces for k in range(counts[f])]
    new_fvi_old = [fvi[p] for p in kept_positions]
    old_points = sorted(set(new_fvi_old))
    point_map = {old: new for new, old in enumerate(old_points)}

    old_pts = list(mesh.GetPointsAttr().Get())
    mesh.GetPointsAttr().Set(Vt.Vec3fArray([old_pts[i] for i in old_points]))
    mesh.GetFaceVertexCountsAttr().Set(Vt.IntArray([counts[f] for f in kept_faces]))
    mesh.GetFaceVertexIndicesAttr().Set(Vt.IntArray([point_map[i] for i in new_fvi_old]))

    for a in prim.GetAttributes():
        name = a.GetName()
        if name == "points" or a.Get() is None or name.endswith(":indices"):
            continue
        interp = a.GetMetadata("interpolation")
        if interp not in ("vertex", "faceVarying"):
            continue
        pv = UsdGeom.PrimvarsAPI(prim).GetPrimvar(name)
        if pv and pv.IsIndexed():
            continue  # an indexed primvar's values are addressed by its indices
        v = a.Get()
        if interp == "vertex":
            a.Set(type(v)([v[i] for i in old_points]))
        elif interp == "faceVarying":
            a.Set(type(v)([v[i] for i in kept_positions]))
    for a in prim.GetAttributes():
        if a.GetName().endswith(":indices") and a.Get() is not None and len(a.Get()) == len(fvi):
            v = a.Get()
            a.Set(type(v)([v[i] for i in kept_positions]))

    mesh.GetExtentAttr().Set(UsdGeom.PointBased(prim).ComputeExtent(mesh.GetPointsAttr().Get()))

    # A surviving subset whose material the mesh already binds and which covers
    # every kept face is the mesh binding restated, so it goes. A mesh binding
    # left pointing at a removed outline material is re-pointed at the fill.
    remap = {f: i for i, f in enumerate(kept_faces)}
    surviving_mats = {str(UsdShade.MaterialBindingAPI(s).GetDirectBinding().GetMaterialPath()) for s, _ in surviving}
    mesh_mat = UsdShade.MaterialBindingAPI(prim).GetDirectBinding().GetMaterialPath()
    if str(mesh_mat) not in surviving_mats and len(surviving_mats) == 1 and mesh_mat:
        UsdShade.MaterialBindingAPI(prim).Bind(UsdShade.Material(prim.GetStage().GetPrimAtPath(surviving_mats.pop())))
        mesh_mat = UsdShade.MaterialBindingAPI(prim).GetDirectBinding().GetMaterialPath()

    drop_paths = []
    for s, idx in surviving:
        new_idx = [remap[f] for f in idx if f in remap]
        same_mat = str(UsdShade.MaterialBindingAPI(s).GetDirectBinding().GetMaterialPath()) == str(mesh_mat)
        if len(new_idx) == len(kept_faces) and same_mat:
            drop_paths.append(s.GetPath())
        else:
            UsdGeom.Subset(s).GetIndicesAttr().Set(Vt.IntArray(new_idx))
    for s in subsets:
        if s.GetName().endswith(suffix):
            drop_paths.append(s.GetPath())
    for path in drop_paths:
        prim.GetStage().RemovePrim(path)

    return {"old_points": old_points, "old_faces": kept_faces,
            "faces_removed": len(removed), "faces_kept": len(kept_faces),
            "points_kept": len(old_points)}


def prune_unused_materials(stage):
    used = set()
    for p in stage.Traverse():
        for r in p.GetRelationships():
            if "material:binding" in r.GetName():
                used.update(str(t) for t in r.GetTargets())
    doomed = [str(p.GetPath()) for p in stage.Traverse()
              if p.GetTypeName() == "Material" and str(p.GetPath()) not in used]
    for path in doomed:
        prim = stage.GetPrimAtPath(path)
        if not prim or not prim.IsValid():
            continue
        for child in list(prim.GetChildren()):
            stage.RemovePrim(child.GetPath())
        stage.RemovePrim(path)
    return doomed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True)
    ap.add_argument("--dst", required=True)
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--suffix", default="_OL")
    ap.add_argument("--only-mesh", default=None)
    ap.add_argument("--remove-cs-gizmos", action="store_true")
    ap.add_argument("--remove-empty-xforms", action="store_true")
    args = ap.parse_args()

    stage = Usd.Stage.Open(args.src)
    manifest = {"meshes": {}, "removed_prims": []}

    targets = [p for p in stage.Traverse()
               if p.GetTypeName() == "Mesh" and (args.only_mesh is None or str(p.GetPath()) == args.only_mesh)]
    for p in targets:
        r = strip_mesh(p, args.suffix)
        if r:
            manifest["meshes"][str(p.GetPath())] = r

    if args.remove_cs_gizmos:
        for p in list(stage.Traverse()):
            if str(p.GetPath()).startswith("/root/char_grp/cs_grp"):
                manifest["removed_prims"].append(str(p.GetPath()))
        stage.RemovePrim("/root/char_grp/cs_grp")

    if args.remove_empty_xforms:
        for c in list(stage.GetPrimAtPath("/root").GetChildren()):
            if c.GetTypeName() == "Xform" and not list(c.GetChildren()):
                manifest["removed_prims"].append(str(c.GetPath()))
                stage.RemovePrim(c.GetPath())

    manifest["materials_removed"] = prune_unused_materials(stage)
    stage.Export(args.dst)
    with open(args.manifest, "w") as f:
        json.dump(manifest, f)

    print("meshes stripped:", len(manifest["meshes"]))
    print("faces removed:", sum(m["faces_removed"] for m in manifest["meshes"].values()))
    print("points removed:", sum(m["points_kept"] for m in manifest["meshes"].values()),
          "kept of", sum(m["points_kept"] + m["faces_removed"] * 2 for m in manifest["meshes"].values()))
    print("prims removed:", len(manifest["removed_prims"]))
    print("materials removed:", manifest["materials_removed"])
    print("exported:", args.dst)


if __name__ == "__main__":
    main()
