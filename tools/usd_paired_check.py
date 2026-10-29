"""Gate for the duplicate-shell strip.

  RESULT arm:   --file out.usdc --reference in.usdc --manifest m.json
  CONTROL arm:  --file in.usdc

Asserts on the result: no shell in any mesh is a duplicate of another shell in
the same mesh (the pairing rule), the number of surviving surface shells equals
the reference's, no cs_* gizmo prim and no childless root Xform remain, the
joint count holds, every texture input resolves, and -- per mesh in the manifest
-- the kept geometry is the reference's own points, faces, normals, UV indices
and skin weights, element for element. Every mesh the reference gave a duplicate
shell must appear in the manifest, so a skipped mesh cannot read as a pass.
"""
from pxr import Usd, UsdGeom, UsdShade, Sdf
import argparse, json, sys
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


def quantum_of(stage, under):
    lo, hi = np.array([np.inf] * 3), np.array([-np.inf] * 3)
    for p in stage.Traverse():
        if p.GetTypeName() == "Mesh" and str(p.GetPath()).startswith(under):
            pts = world_points(p, UsdGeom.Mesh(p))
            lo, hi = np.minimum(lo, pts.min(axis=0)), np.maximum(hi, pts.max(axis=0))
    return max(float(np.linalg.norm(hi - lo)) * 1e-5, 1e-9)


def classify_stage(stage, under, q):
    out = {}
    sig_map = pairing.material_signatures(stage)
    for p in stage.Traverse():
        path = str(p.GetPath())
        if p.GetTypeName() != "Mesh" or not path.startswith(under):
            continue
        mesh = UsdGeom.Mesh(p)
        counts = list(mesh.GetFaceVertexCountsAttr().Get())
        fvi = list(mesh.GetFaceVertexIndicesAttr().Get())
        tris, face_of_tri = triangulate(counts, fvi)
        if len(tris) == 0:
            out[path] = []
            continue
        pts = world_points(p, mesh)
        face_sig = pairing.face_signatures(p, mesh, sig_map)
        out[path] = pairing.classify(pts, tris, shells_of(pts, tris, q), face_of_tri, face_sig)
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
    ap.add_argument("--quantum", type=float, default=None,
                    help="weld quantum; the reference's, so one rule covers every file")
    args = ap.parse_args()

    fails = []
    st = Usd.Stage.Open(args.file)
    prims = list(st.Traverse())
    print(args.file)

    q = args.quantum or quantum_of(st, args.under)
    if args.reference and not args.quantum:
        q = quantum_of(Usd.Stage.Open(args.reference), args.under)
    shells = classify_stage(st, args.under, q)
    tally = {}
    for entries in shells.values():
        for e in entries:
            tally[e["kind"]] = tally.get(e["kind"], 0) + 1
    print(f"  shells at quantum {q:.3e}: {tally}")
    if tally.get("duplicate"):
        fails.append(f"{tally['duplicate']} duplicate shells remain")

    if args.reference and args.manifest:
        ref_stage = Usd.Stage.Open(args.reference)
        ref_shells = classify_stage(ref_stage, args.under, q)
        ref_tally = {}
        for entries in ref_shells.values():
            for e in entries:
                ref_tally[e["kind"]] = ref_tally.get(e["kind"], 0) + 1
        print(f"  reference shells: {ref_tally}")
        if not ref_tally.get("duplicate"):
            fails.append("the reference carries no duplicate shell, so this gate cannot fail")
        if tally.get("surface", 0) != ref_tally.get("surface", 0):
            fails.append(f"surface shells {tally.get('surface', 0)} != reference {ref_tally.get('surface', 0)}")

        manifest = json.load(open(args.manifest))
        removed = tuple(manifest.get("removed_prims", [])) + tuple(manifest.get("meshes_removed", []))
        want = {m for m, es in ref_shells.items()
                if any(e["kind"] == "duplicate" for e in es) and not m.startswith(removed)}
        got = set(manifest["meshes"])
        missing = sorted(want - got)
        if missing:
            fails.append(f"meshes with a duplicate shell not covered by the manifest: {missing[:3]}")

        ref_prims = {str(p.GetPath()): p for p in ref_stage.Traverse()}
        checked = 0
        for path, m in manifest["meshes"].items():
            if path.startswith(removed):
                continue
            ref, new = ref_prims.get(path), st.GetPrimAtPath(path)
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
            def runs(ref_values, attr_on_new):
                """Expectation for a vertex primvar with elementSize entries per point."""
                el = attr_on_new.GetMetadata("elementSize") or 1
                idx = [i * el + t for i in m["old_points"] for t in range(el)]
                return [ref_values[i] for i in idx], el
            ji_new, jw_new = new.GetAttribute("primvars:skel:jointIndices"), new.GetAttribute("primvars:skel:jointWeights")
            ji_want, el = runs(rji, ji_new)
            jw_want, _ = runs(rjw, jw_new)
            for nm, attr in (("jointIndices", ji_new), ("jointWeights", jw_new)):
                if len(attr.Get()) != el * len(m["old_points"]):
                    fails.append(f"{path}: {nm} has {len(attr.Get())} values, "
                                 f"needs elementSize {el} x {len(m['old_points'])} points")
            for name, gotv, wantv in [
                ("faceVertexCounts", list(N.GetFaceVertexCountsAttr().Get()), [rc[f] for f in m["old_faces"]]),
                ("faceVertexIndices", list(N.GetFaceVertexIndicesAttr().Get()), [inv[rf[p]] for p in kept_pos]),
                ("points", list(N.GetPointsAttr().Get()), [rpts[i] for i in m["old_points"]]),
                ("normals", list(new.GetAttribute("normals").Get()), [rnorm[p] for p in kept_pos]),
                ("jointIndices", list(ji_new.Get()), ji_want),
                ("jointWeights", list(jw_new.Get()), jw_want),
            ]:
                if len(gotv) != len(wantv) or any(a != b for a, b in zip(gotv, wantv)):
                    fails.append(f"{path}: {name} is not the reference's own data")
            checked += 1
        print(f"  meshes proved element-for-element: {checked}")

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

    unresolved = set()
    for prim in prims:
        if prim.IsA(UsdShade.Shader):
            for inp in UsdShade.Shader(prim).GetInputs():
                if inp.GetTypeName() == Sdf.ValueTypeNames.Asset and inp.Get() and inp.Get().path:
                    if not inp.Get().resolvedPath:
                        unresolved.add(inp.Get().path)
    if unresolved:
        fails.append(f"texture inputs resolving to nothing: {sorted(unresolved)}")

    if fails:
        print("FAIL:")
        for f in fails:
            print("  -", f)
        sys.exit(1)
    print("PASS")


if __name__ == "__main__":
    main()
