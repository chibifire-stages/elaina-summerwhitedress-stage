"""Strip the outline (_OL) face copies from an Elaina USD mesh.

The asset carries a toon outline as a duplicated shell: the Body mesh is 20332
quads in two equal halves, subset `Body` (fill) and subset `Body_OL` (outline),
each with its own point range and skin weights. `--only-mesh` restricts the
strip to one mesh, so the body's outline copy goes and the garments' outlines
stay.

  faces        -> kept faces only, faceVertexIndices/faceVertexCounts rebuilt
  points       -> kept points only (those no kept face references are dropped)
  vertex       -> primvars:skel:jointIndices/jointWeights and any other
                  vertex-interpolated primvar sliced by the point remap
  faceVarying  -> sliced by the kept face-vertex list; an indexed primvar's
                  own indices array is sliced the same way
  GeomSubsets  -> surviving subsets remapped; a subset that still covers every
                  face and matches the mesh-level binding is dropped
  materials    -> an _OL material no prim references is removed with its shader
"""
from pxr import Usd, UsdGeom, UsdShade, Sdf, Vt
import argparse


def kept_face_lists(mesh, removed_faces):
    counts = list(mesh.GetFaceVertexCountsAttr().Get())
    fvi = list(mesh.GetFaceVertexIndicesAttr().Get())
    offsets, o = [], 0
    for c in counts:
        offsets.append(o)
        o += c
    kept = [f for f in range(len(counts)) if f not in removed_faces]
    new_counts, new_fvi = [], []
    for f in kept:
        new_counts.append(counts[f])
        new_fvi.extend(fvi[offsets[f]:offsets[f] + counts[f]])
    return counts, fvi, offsets, kept, new_counts, new_fvi


def slice_primvar(prim, name, point_map, kept_fv):
    a = prim.GetAttribute(name)
    if not a or a.Get() is None:
        return None
    interp = a.GetMetadata("interpolation")
    v = a.Get()
    if interp == "vertex":
        return Vt.IntArray([point_map[i] for i in v]) if isinstance(v[0], int) else \
            type(v)([v[i] for i in sorted(point_map, key=lambda k: point_map[k])])
    if interp == "faceVarying":
        return type(v)([v[i] for i in kept_fv])
    return None


def strip_mesh(stage, prim, suffix):
    mesh = UsdGeom.Mesh(prim)
    subsets = [c for c in prim.GetChildren() if c.GetTypeName() == "GeomSubset"]
    removed_faces, keep_subsets = set(), []
    for s in subsets:
        idx = list(UsdGeom.Subset(s).GetIndicesAttr().Get())
        if s.GetName().endswith(suffix):
            removed_faces.update(idx)
        else:
            keep_subsets.append((s, idx))

    counts, fvi, offsets, kept, new_counts, new_fvi = kept_face_lists(mesh, removed_faces)
    if not removed_faces:
        return None

    used_points = sorted(set(new_fvi))
    point_map = {old: new for new, old in enumerate(used_points)}
    # faceVarying arrays are addressed by the face-vertex *position*, not by the
    # point index the face-vertex list holds
    kept_fv = [offsets[f] + k for f in kept for k in range(counts[f])]

    old_points = list(mesh.GetPointsAttr().Get())
    mesh.GetPointsAttr().Set(Vt.Vec3fArray([old_points[i] for i in used_points]))
    mesh.GetFaceVertexCountsAttr().Set(Vt.IntArray(new_counts))
    mesh.GetFaceVertexIndicesAttr().Set(Vt.IntArray(new_fvi))

    for name in [a.GetName() for a in prim.GetAttributes()]:
        if name == "points":
            continue
        interp = prim.GetAttribute(name).GetMetadata("interpolation")
        if interp not in ("vertex", "faceVarying"):
            continue
        pv = UsdGeom.PrimvarsAPI(prim).GetPrimvar(name)
        if pv and pv.IsIndexed():
            continue  # an indexed primvar's values are addressed by its indices
        v = prim.GetAttribute(name).Get()
        if interp == "vertex":
            prim.GetAttribute(name).Set(type(v)([v[i] for i in used_points]))
        else:
            prim.GetAttribute(name).Set(type(v)([v[i] for i in kept_fv]))
    # an indexed primvar keeps its value array; only the index array is sliced
    for a in prim.GetAttributes():
        if a.GetName().endswith(":indices") and a.Get() is not None and len(a.Get()) == len(fvi):
            v = a.Get()
            a.Set(type(v)([v[i] for i in kept_fv]))

    pts = mesh.GetPointsAttr().Get()
    mesh.GetExtentAttr().Set(UsdGeom.PointBased(mesh.GetPrim()).ComputeExtent(pts))

    for s, idx in keep_subsets:
        new_idx = [f for f in idx if f in set(kept)]
        remap = {f: i for i, f in enumerate(kept)}
        if len(new_idx) == len(kept):
            s.GetPrim().SetActive(False)
        else:
            UsdGeom.Subset(s).GetIndicesAttr().Set(Vt.IntArray([remap[f] for f in new_idx]))
    for s in subsets:
        if s.GetName().endswith(suffix):
            s.SetActive(False)
    for s in subsets:
        if not s.IsActive():
            stage.RemovePrim(s.GetPath())

    return {"mesh": str(prim.GetPath()), "faces_removed": len(removed_faces),
            "faces_kept": len(kept), "points_before": len(old_points),
            "points_kept": len(used_points)}


def prune_unused_materials(stage, suffix):
    used = set()
    for p in stage.Traverse():
        for r in p.GetRelationships():
            if "material:binding" in r.GetName():
                used.update(str(t) for t in r.GetTargets())
    removed = []
    for p in list(stage.Traverse()):
        if p.GetTypeName() == "Material" and p.GetPath().name.endswith(suffix) \
                and str(p.GetPath()) not in used:
            for child in p.GetChildren():
                if child.GetTypeName() == "Shader":
                    stage.RemovePrim(child.GetPath())
            stage.RemovePrim(p.GetPath())
            removed.append(str(p.GetPath()))
    return removed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True)
    ap.add_argument("--dst", required=True)
    ap.add_argument("--suffix", default="_OL")
    ap.add_argument("--only-mesh", default=None)
    args = ap.parse_args()

    stage = Usd.Stage.Open(args.src)
    targets = [p for p in stage.Traverse()
               if p.GetTypeName() == "Mesh" and (args.only_mesh is None or str(p.GetPath()) == args.only_mesh)]
    report = []
    for p in targets:
        r = strip_mesh(stage, p, args.suffix)
        if r:
            report.append(r)
    mats = prune_unused_materials(stage, args.suffix)
    stage.Export(args.dst)
    print("meshes stripped:", len(report))
    for r in report:
        print("  ", r)
    print("materials removed:", mats)
    print("exported:", args.dst)


if __name__ == "__main__":
    main()
