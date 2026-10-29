"""Remove the inverted duplicate shells from a skinned USD, by the explode rule.

The criterion is orientation, not a name: the model-explorer exploder's shells
(weld by world position at 1e-5 of the model size, union-find over triangle
corners) are classified by signed volume, and an inverted shell that pairs with
an outward shell of the same face count and nearly the same centroid is a
duplicate of real surface -- the toon outline hull. An inverted shell with no
such twin is left alone and reported, because nothing proves it is a copy.

The surgery is the mesh surgery: the duplicate shells' faces go, the points only
they reference go, every vertex- and faceVarying-interpolated primvar is
remapped, and a manifest records the old point and old face index of each
surviving element so a checker can prove the kept geometry is the source's own
data element for element.
"""
from pxr import Usd, UsdGeom, UsdShade, Sdf, Vt
import argparse, json
import numpy as np
import usd_shell_pairs as pairing


def world_points(prim, mesh):
    pts = np.array([[p[0], p[1], p[2]] for p in mesh.GetPointsAttr().Get()], dtype=np.float64)
    xf = UsdGeom.Xformable(prim).ComputeLocalToWorldTransform(Usd.TimeCode.Default())
    m = np.array([[xf[i][j] for j in range(4)] for i in range(4)], dtype=np.float64)
    return pts @ m[:3, :3].T + m[:3, 3]


def triangulate(counts, fvi):
    tris, face_of_tri, off = [], [], 0
    for f, c in enumerate(counts):
        for k in range(1, c - 1):
            tris.append((fvi[off], fvi[off + k], fvi[off + k + 1]))
            face_of_tri.append(f)
        off += c
    return np.array(tris, np.int64).reshape(-1, 3), np.array(face_of_tri, np.int64)


def shells_of(pts, tris, q):
    keys = np.round(pts / q).astype(np.int64)
    _, w = np.unique(keys, axis=0, return_inverse=True)
    parent = np.arange(int(w.max()) + 1)

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    for t in tris:
        for u, v in ((t[0], t[1]), (t[1], t[2])):
            ra, rb = find(int(w[u])), find(int(w[v]))
            if ra != rb:
                parent[max(ra, rb)] = min(ra, rb)
    root = np.array([find(int(i)) for i in range(len(parent))])
    return root[w[tris[:, 0]]]


def classify(pts, tris, tri_root, face_of_tri, centroid_tol=0.05):
    entries = []
    for r in np.unique(tri_root):
        tmask = tri_root == r
        t = tris[tmask]
        a, b, c = pts[t[:, 0]], pts[t[:, 1]], pts[t[:, 2]]
        cent = (a + b + c).mean(axis=0) / 3.0
        entries.append({"tris": t, "faces": np.unique(face_of_tri[tmask]),
                        "volume": float(np.sum(np.einsum("ij,ij->i", a, np.cross(b, c))) / 6.0),
                        "centroid": cent,
                        "radius": float(np.linalg.norm(a - cent, axis=1).mean())})
    outward = [e for e in entries if e["volume"] > 0]
    for e in entries:
        if e["volume"] > 0:
            e["kind"] = "outward"
            continue
        cands = [o for o in outward if len(o["faces"]) == len(e["faces"])]
        best, best_d = None, np.inf
        for o in cands:
            d = float(np.linalg.norm(o["centroid"] - e["centroid"])) / max(e["radius"], 1e-12)
            if d < best_d:
                best, best_d = o, d
        if best is None or best_d > centroid_tol:
            e["kind"] = "inverted-unpaired"
            continue
        e["kind"] = "hull" if e["radius"] / best["radius"] > 1.001 else "twin"
        e["twin_offset"] = best_d
    return entries


def surgery(prim, mesh, drop_faces):
    counts = list(mesh.GetFaceVertexCountsAttr().Get())
    fvi = list(mesh.GetFaceVertexIndicesAttr().Get())
    offs, o = [], 0
    for c in counts:
        offs.append(o)
        o += c
    kept = [f for f in range(len(counts)) if f not in drop_faces]
    kept_pos = [offs[f] + k for f in kept for k in range(counts[f])]
    old_fvi_kept = [fvi[p] for p in kept_pos]
    old_points = sorted(set(old_fvi_kept))
    pmap = {old: new for new, old in enumerate(old_points)}

    old_pts = list(mesh.GetPointsAttr().Get())
    mesh.GetPointsAttr().Set(Vt.Vec3fArray([old_pts[i] for i in old_points]))
    mesh.GetFaceVertexCountsAttr().Set(Vt.IntArray([counts[f] for f in kept]))
    mesh.GetFaceVertexIndicesAttr().Set(Vt.IntArray([pmap[i] for i in old_fvi_kept]))
    for a in prim.GetAttributes():
        name = a.GetName()
        if name == "points" or a.Get() is None or name.endswith(":indices"):
            continue
        interp = a.GetMetadata("interpolation")
        if interp not in ("vertex", "faceVarying"):
            continue
        pv = UsdGeom.PrimvarsAPI(prim).GetPrimvar(name)
        if pv and pv.IsIndexed():
            continue
        # A vertex-interpolated primvar carries elementSize entries PER POINT, so a
        # kept point keeps a run of elementSize values. Indexing it like a
        # one-per-point array truncates the skin arrays and silently unweights the
        # mesh -- it renders in a bind pose in pxr and stretches in a skinned
        # viewer such as Quick Look.
        el = a.GetMetadata("elementSize") or 1
        idx = ([i * el + t for i in old_points for t in range(el)] if interp == "vertex"
               else kept_pos)
        v = a.Get()
        a.Set(type(v)([v[i] for i in idx]))
    for a in prim.GetAttributes():
        if a.GetName().endswith(":indices") and a.Get() is not None and len(a.Get()) == len(fvi):
            v = a.Get()
            a.Set(type(v)([v[i] for i in kept_pos]))
    mesh.GetExtentAttr().Set(UsdGeom.PointBased(prim).ComputeExtent(mesh.GetPointsAttr().Get()))

    remap = {f: i for i, f in enumerate(kept)}
    for s in [c for c in prim.GetChildren() if c.GetTypeName() == "GeomSubset"]:
        idx = [remap[f] for f in UsdGeom.Subset(s).GetIndicesAttr().Get() if f in remap]
        if not idx:
            prim.GetStage().RemovePrim(s.GetPath())
        else:
            UsdGeom.Subset(s).GetIndicesAttr().Set(Vt.IntArray(idx))
    return {"old_points": old_points, "old_faces": kept,
            "faces_removed": len(drop_faces), "points_kept": len(old_points)}


def prune_unused_materials(stage):
    used = set()
    for p in stage.Traverse():
        for r in p.GetRelationships():
            if "material:binding" in r.GetName():
                used.update(str(t) for t in r.GetTargets())
    doomed = [str(p.GetPath()) for p in stage.Traverse()
              if p.GetTypeName() == "Material" and str(p.GetPath()) not in used]
    for path in doomed:
        p = stage.GetPrimAtPath(path)
        if not p or not p.IsValid():
            continue
        for c in list(p.GetChildren()):
            stage.RemovePrim(c.GetPath())
        stage.RemovePrim(path)
    return doomed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True)
    ap.add_argument("--dst", required=True)
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--under", default=None)
    ap.add_argument("--remove-cs-gizmos", action="store_true")
    ap.add_argument("--remove-empty-xforms", action="store_true")
    ap.add_argument("--report", default=None)
    ap.add_argument("--quantum", type=float, default=None)
    ap.add_argument("--paired-only", action="store_true",
                    help="drop only inverted shells that pair with an outward twin")
    args = ap.parse_args()

    stage = Usd.Stage.Open(args.src)
    sig_map = pairing.material_signatures(stage)
    meshes = [p for p in stage.Traverse()
              if p.GetTypeName() == "Mesh" and (args.under is None or str(p.GetPath()).startswith(args.under))]
    lo, hi = np.array([np.inf] * 3), np.array([-np.inf] * 3)
    geo, xform = {}, {}
    for p in meshes:
        xf = UsdGeom.Xformable(p).ComputeLocalToWorldTransform(Usd.TimeCode.Default())
        xform[str(p.GetPath())] = np.array([[xf[i][j] for j in range(4)] for i in range(4)], dtype=np.float64)
        pts = world_points(p, UsdGeom.Mesh(p))
        geo[str(p.GetPath())] = pts
        lo, hi = np.minimum(lo, pts.min(axis=0)), np.maximum(hi, pts.max(axis=0))
    q = args.quantum if args.quantum else max(float(np.linalg.norm(hi - lo)) * 1e-5, 1e-9)
    print(f"weld quantum {q:.3e}")

    manifest = {"meshes": {}, "removed_prims": [], "duplicates": []}
    report = {}
    for p in meshes:
        path = str(p.GetPath())
        mesh = UsdGeom.Mesh(p)
        pts = geo[path]
        counts = list(mesh.GetFaceVertexCountsAttr().Get())
        fvi = list(mesh.GetFaceVertexIndicesAttr().Get())
        tris, face_of_tri = triangulate(counts, fvi)
        if len(tris) == 0:
            continue
        report[path] = {}
        # Removing a duplicate changes what pairs with what, so repeat until the
        # mesh holds no inverted duplicate. Each pass's map composes with the last,
        # so the manifest still names indices in the ORIGINAL mesh.
        composed, passes = None, 0
        for _ in range(6):
            mesh = UsdGeom.Mesh(p)
            counts = list(mesh.GetFaceVertexCountsAttr().Get())
            fvi = list(mesh.GetFaceVertexIndicesAttr().Get())
            raw = mesh.GetPointsAttr().Get()
            if raw is None or len(raw) == 0 or len(counts) == 0:
                # every face of this mesh was an inverted duplicate; the mesh itself goes
                break
            xf = UsdGeom.Xformable(p).ComputeLocalToWorldTransform(Usd.TimeCode.Default())
            m4 = np.array([[xf[i][j] for j in range(4)] for i in range(4)], dtype=np.float64)
            local = np.array([[q[0], q[1], q[2]] for q in raw], dtype=np.float64)
            pts_now = local @ m4[:3, :3].T + m4[:3, 3]
            tris, face_of_tri = triangulate(counts, fvi)
            if len(tris) == 0:
                break
            face_sig = pairing.face_signatures(p, mesh, sig_map)
            entries = pairing.classify(pts_now, tris, shells_of(pts_now, tris, q), face_of_tri, face_sig)
            drop = set()
            for e in entries:
                report[path][e["kind"]] = report[path].get(e["kind"], 0) + 1
                if e["kind"] == "duplicate":
                    drop.update(int(f) for f in e["faces"])
                    manifest["duplicates"].append({"mesh": path, "faces": int(len(e["faces"])),
                                                   "pair_ratio": e.get("pair_ratio")})
            if not drop:
                break
            step = surgery(p, mesh, drop)
            passes += 1
            if composed is None:
                composed = step
            else:
                composed = {
                    "old_points": [composed["old_points"][i] for i in step["old_points"]],
                    "old_faces": [composed["old_faces"][f] for f in step["old_faces"]],
                    "faces_removed": composed["faces_removed"] + step["faces_removed"],
                    "points_kept": step["points_kept"],
                }
        if composed:
            composed["passes"] = passes
            manifest["meshes"][path] = composed
        if len(list(UsdGeom.Mesh(p).GetFaceVertexCountsAttr().Get())) == 0:
            manifest.setdefault("meshes_removed", []).append(path)
            stage.RemovePrim(p.GetPath())

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
    if args.report:
        with open(args.report, "w") as f:
            json.dump(report, f)

    print("meshes stripped:", len(manifest["meshes"]))
    print("faces removed:", sum(m["faces_removed"] for m in manifest["meshes"].values()))
    print("duplicate shells removed:", len(manifest["duplicates"]),
          "faces:", sum(d["faces"] for d in manifest["duplicates"]))
    kept = {}
    for k in report.values():
        for kind, n in k.items():
            kept[kind] = kept.get(kind, 0) + n
    print("shell kinds across passes:", kept)
    print("prims removed:", len(manifest["removed_prims"]))
    print("materials removed:", len(manifest["materials_removed"]))
    print("exported:", args.dst)


if __name__ == "__main__":
    main()
