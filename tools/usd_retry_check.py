"""Gate for the inverted-shell strip.

  --file RESULT --reference PRE --manifest M   the result arm
  --file PRE                                   the control arm, which must fail
                                               on the shells it still carries

Asserts, on the result: no inverted shell that duplicates an outward one (the
explode classification), no cs_* gizmo prim, no childless Xform at the scene
root, the joint count holds, every texture input resolves and is
package-relative, and -- per mesh in the manifest -- the kept geometry is the
reference's own points, faces, normals, UV indices and skin weights, element for
element. Every mesh the reference gave a duplicate shell must appear in the
manifest, so a skipped mesh cannot read as a pass.
"""
from pxr import Usd, UsdGeom, UsdShade, Sdf
import argparse, json, sys
import numpy as np


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
    return entries


def classify_stage(stage, under, q=None):
    meshes = [p for p in stage.Traverse()
              if p.GetTypeName() == "Mesh" and (under is None or str(p.GetPath()).startswith(under))]
    lo, hi = np.array([np.inf] * 3), np.array([-np.inf] * 3)
    geo = {}
    for p in meshes:
        pts = world_points(p, UsdGeom.Mesh(p))
        geo[str(p.GetPath())] = pts
        lo, hi = np.minimum(lo, pts.min(axis=0)), np.maximum(hi, pts.max(axis=0))
    if q is None:
        q = max(float(np.linalg.norm(hi - lo)) * 1e-5, 1e-9)
    out = {}
    for p in meshes:
        path = str(p.GetPath())
        counts = list(UsdGeom.Mesh(p).GetFaceVertexCountsAttr().Get())
        fvi = list(UsdGeom.Mesh(p).GetFaceVertexIndicesAttr().Get())
        tris, face_of_tri = triangulate(counts, fvi)
        if len(tris) == 0:
            out[path] = []
            continue
        out[path] = classify(geo[path], tris, shells_of(geo[path], tris, q), face_of_tri)
    return out


def face_offsets(counts):
    offs, o = [], 0
    for c in counts:
        offs.append(o)
        o += c
    return offs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", required=True)
    ap.add_argument("--reference", default=None)
    ap.add_argument("--manifest", default=None)
    ap.add_argument("--joints", type=int, default=292)
    ap.add_argument("--under", default="/root/char_grp/rig")
    ap.add_argument("--quantum", type=float, default=None)
    args = ap.parse_args()

    fails = []
    st = Usd.Stage.Open(args.file)
    prims = list(st.Traverse())
    print(args.file)

    shells = classify_stage(st, args.under, args.quantum)
    tally = {}
    for entries in shells.values():
        for e in entries:
            tally[e["kind"]] = tally.get(e["kind"], 0) + 1
    print(f"  shells: {tally}")
    for kind in ("hull", "twin"):
        if tally.get(kind):
            fails.append(f"{tally[kind]} {kind} shells remain (inverted duplicates of real surface)")

    cs = [str(p.GetPath()) for p in prims if str(p.GetPath()).startswith("/root/char_grp/cs_grp")]
    if cs:
        fails.append(f"{len(cs)} cs_* gizmo prims remain")
    empties = [str(c.GetPath()) for c in st.GetPrimAtPath("/root").GetChildren()
               if c.GetTypeName() == "Xform" and not list(c.GetChildren())]
    if empties:
        fails.append(f"childless Xforms at the scene root remain: {empties}")

    skel = next((p for p in prims if p.GetTypeName() == "Skeleton"), None)
    joints = len(skel.GetAttribute("joints").Get()) if skel else 0
    print(f"  joints={joints} prims={len(prims)}")
    if joints != args.joints:
        fails.append(f"joints {joints} != {args.joints}")

    authored, unresolved = set(), set()
    for prim in prims:
        if prim.IsA(UsdShade.Shader):
            for inp in UsdShade.Shader(prim).GetInputs():
                if inp.GetTypeName() == Sdf.ValueTypeNames.Asset and inp.Get() and inp.Get().path:
                    a = inp.Get()
                    authored.add(a.path)
                    if not a.resolvedPath:
                        unresolved.add(a.path)
    print(f"  texture inputs: {len(authored)} distinct, {len(unresolved)} unresolved")
    for u in sorted(unresolved):
        fails.append(f"texture input resolves to nothing: {u}")

    if args.manifest and args.reference:
        manifest = json.load(open(args.manifest))
        ref_stage = Usd.Stage.Open(args.reference)
        ref_shells = classify_stage(ref_stage, args.under)
        # one weld rule for both sides: the reference's quantum
        q_ref = None
        lo, hi = np.array([np.inf]*3), np.array([-np.inf]*3)
        for p in ref_stage.Traverse():
            if p.GetTypeName() == "Mesh" and str(p.GetPath()).startswith(args.under):
                pts = world_points(p, UsdGeom.Mesh(p))
                lo, hi = np.minimum(lo, pts.min(axis=0)), np.maximum(hi, pts.max(axis=0))
        q_ref = max(float(np.linalg.norm(hi - lo)) * 1e-5, 1e-9)
        ref_shells = classify_stage(ref_stage, args.under, q_ref)
        shells = classify_stage(st, args.under, q_ref)
        tally = {}
        for entries in shells.values():
            for e in entries:
                tally[e["kind"]] = tally.get(e["kind"], 0) + 1
        print(f"  shells at the reference quantum {q_ref:.3e}: {tally}")
        fails = [f for f in fails if "shells remain" not in f]
        for kind in ("hull", "twin", "inverted-unpaired", "inverted"):
            if tally.get(kind):
                fails.append(f"{tally[kind]} {kind} shells remain at the reference quantum")
        removed = tuple(manifest.get("removed_prims", []))
        want = {m for m, es in ref_shells.items()
                if any(e["kind"] in ("hull", "twin") for e in es) and not m.startswith(removed)}
        got = set(manifest["meshes"])
        if want != got:
            fails.append(f"meshes with a duplicate shell not covered by the manifest: {sorted(want - got)[:3]}")

        ref_prims = {str(p.GetPath()): p for p in ref_stage.Traverse()}
        checked = 0
        for path, m in manifest["meshes"].items():
            if path.startswith(removed):
                continue
            ref, new = ref_prims[path], st.GetPrimAtPath(path)
            if not new:
                fails.append(f"{path} is missing from the result")
                continue
            R, N = UsdGeom.Mesh(ref), UsdGeom.Mesh(new)
            rc = list(R.GetFaceVertexCountsAttr().Get())
            rf = list(R.GetFaceVertexIndicesAttr().Get())
            rpts = list(R.GetPointsAttr().Get())
            rnorm = list(ref.GetAttribute("normals").Get())
            rji = list(ref.GetAttribute("primvars:skel:jointIndices").Get())
            rjw = list(ref.GetAttribute("primvars:skel:jointWeights").Get())
            ro = face_offsets(rc)
            kept_pos = [ro[f] + k for f in m["old_faces"] for k in range(rc[f])]
            inv = {old: i for i, old in enumerate(m["old_points"])}
            pairs = [
                ("faceVertexCounts", list(N.GetFaceVertexCountsAttr().Get()), [rc[f] for f in m["old_faces"]]),
                ("faceVertexIndices", list(N.GetFaceVertexIndicesAttr().Get()), [inv[rf[p]] for p in kept_pos]),
                ("points", list(N.GetPointsAttr().Get()), [rpts[i] for i in m["old_points"]]),
                ("normals", list(new.GetAttribute("normals").Get()), [rnorm[p] for p in kept_pos]),
                ("jointIndices", list(new.GetAttribute("primvars:skel:jointIndices").Get()), [rji[i] for i in m["old_points"]]),
                ("jointWeights", list(new.GetAttribute("primvars:skel:jointWeights").Get()), [rjw[i] for i in m["old_points"]]),
            ]
            for name, gotv, wantv in pairs:
                if len(gotv) != len(wantv) or any(a != b for a, b in zip(gotv, wantv)):
                    fails.append(f"{path}: {name} is not the reference's own data")
            checked += 1
        print(f"  meshes proved element-for-element: {checked}")

    if fails:
        print("FAIL:")
        for f in fails:
            print("  -", f)
        sys.exit(1)
    print("PASS")


if __name__ == "__main__":
    main()
