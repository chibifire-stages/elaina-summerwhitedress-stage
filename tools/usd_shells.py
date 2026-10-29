"""Explode a USD into its shells and classify each shell's orientation.

The rule is the model-explorer exploder's (addons/model_explode/explode.gd):
vertices closer than 1e-5 of the model size are one vertex, and a shell is the
triangles that share vertices, union-find over triangle corners. Nothing is cut,
so every shell boundary is an edge the artist made.

Two orientation measures per shell:

  signed volume  sum over triangles of (a . (b x c)) / 6, positive when the
                 winding faces outward
  radial dot     mean of dot(face normal, face centroid - shell centroid),
                 positive outward; it survives an open shell where volume does
                 not

An outline hull is an inverted shell that is an *offset* copy of an outward one:
same face count, mean radius slightly larger. A double-sided sheet is the
degenerate case -- two coincident shells of opposite sign and equal radius --
and both of its sides are real surface, so the report separates them.
"""
from pxr import Usd, UsdGeom
import argparse, json
import numpy as np


def world_points(prim, mesh):
    pts = np.array([[p[0], p[1], p[2]] for p in mesh.GetPointsAttr().Get()], dtype=np.float64)
    xf = UsdGeom.Xformable(prim).ComputeLocalToWorldTransform(Usd.TimeCode.Default())
    m = np.array([[xf[i][j] for j in range(4)] for i in range(4)], dtype=np.float64)
    return pts @ m[:3, :3].T + m[:3, 3]


def triangulate(mesh):
    """Triangles as point indices, and as face-vertex positions (for faceVarying data)."""
    counts = list(mesh.GetFaceVertexCountsAttr().Get())
    fvi = list(mesh.GetFaceVertexIndicesAttr().Get())
    tris, corners, face_of_tri = [], [], []
    off = 0
    for f, c in enumerate(counts):
        for k in range(1, c - 1):
            tris.append((fvi[off], fvi[off + k], fvi[off + k + 1]))
            corners.append((off, off + k, off + k + 1))
            face_of_tri.append(f)
        off += c
    if not tris:
        return (np.zeros((0, 3), np.int64), np.zeros((0, 3), np.int64),
                np.zeros((0,), np.int64), counts, fvi)
    return (np.array(tris, np.int64), np.array(corners, np.int64),
            np.array(face_of_tri, np.int64), counts, fvi)


def weld_ids(pts, q):
    keys = np.round(pts / q).astype(np.int64)
    _, ids = np.unique(keys, axis=0, return_inverse=True)
    return ids


def roots_of(w, tris):
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
    return np.array([find(int(i)) for i in range(len(parent))])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", required=True)
    ap.add_argument("--json", default=None)
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    stage = Usd.Stage.Open(args.file)
    meshes = [p for p in stage.Traverse() if p.GetTypeName() == "Mesh"]

    lo, hi = np.array([np.inf] * 3), np.array([-np.inf] * 3)
    geo = {}
    for p in meshes:
        pts = world_points(p, UsdGeom.Mesh(p))
        geo[str(p.GetPath())] = pts
        lo, hi = np.minimum(lo, pts.min(axis=0)), np.maximum(hi, pts.max(axis=0))
    size = float(np.linalg.norm(hi - lo))
    q = max(size * 1e-5, 1e-9)
    print(f"model size {size:.4f}  weld quantum {q:.3e}")

    report = {"size": size, "quantum": q, "meshes": {}}
    tally = {"shells": 0, "inverted": 0, "outline_hulls": 0, "double_sided": 0}
    for p in meshes:
        path = str(p.GetPath())
        m = UsdGeom.Mesh(p)
        pts = geo[path]
        tris, corners, face_of_tri, counts, fvi = triangulate(m)
        subs = {c.GetName(): set(int(i) for i in UsdGeom.Subset(c).GetIndicesAttr().Get())
                for c in p.GetChildren() if c.GetTypeName() == "GeomSubset"}
        if len(tris) == 0:
            report["meshes"][path] = []
            continue
        nrm = m.GetPrim().GetAttribute("normals")
        nrm = (np.array([[n[0], n[1], n[2]] for n in nrm.Get()], np.float64)
               if nrm and nrm.Get() is not None else None)

        w = weld_ids(pts, q)
        root = roots_of(w, tris)
        tri_root = root[w[tris[:, 0]]]

        entries = []
        for r in np.unique(tri_root):
            tmask = tri_root == r
            t = tris[tmask]
            a, b, c = pts[t[:, 0]], pts[t[:, 1]], pts[t[:, 2]]
            vol = float(np.sum(np.einsum("ij,ij->i", a, np.cross(b, c))) / 6.0)
            cent = (a + b + c).mean(axis=0) / 3.0
            rad = float(np.linalg.norm(a - cent, axis=1).mean())
            rdot = None
            if nrm is not None:
                fc = (nrm[corners[tmask][:, 0]] + nrm[corners[tmask][:, 1]]
                      + nrm[corners[tmask][:, 2]]) / 3.0
                rdot = float(np.mean(np.einsum("ij,ij->i", fc, (a + b + c) / 3.0 - cent)))
            fset = set(int(x) for x in face_of_tri[tmask])
            entries.append({"faces": len(fset), "tris": int(len(t)), "volume": vol,
                            "radial_dot": rdot, "radius": rad, "centroid": cent.tolist(),
                            "subsets": sorted(n for n, idx in subs.items() if idx & fset)})
        entries.sort(key=lambda e: -e["tris"])

        outward = [e for e in entries if e["volume"] > 0]
        for e in entries:
            if e["volume"] > 0:
                e["kind"] = "outward"
                continue
            twin = next((o for o in outward if o["faces"] == e["faces"]), None)
            if twin is None:
                e["kind"] = "inverted (no twin)"
                continue
            ratio = e["radius"] / twin["radius"] if twin["radius"] else 0.0
            e["twin_radius_ratio"] = ratio
            e["kind"] = "outline hull" if ratio > 1.001 else "double-sided twin"
            tally["outline_hulls" if ratio > 1.001 else "double_sided"] += 1

        tally["shells"] += len(entries)
        tally["inverted"] += sum(1 for e in entries if e["volume"] <= 0)
        report["meshes"][path] = entries
        if not args.quiet:
            print(f"\n{path}: {len(entries)} shells")
            for e in entries:
                extra = (f" ratio={e['twin_radius_ratio']:.4f}" if "twin_radius_ratio" in e else "")
                print(f"   {e['kind']:20s} faces={e['faces']:6d} vol={e['volume']: .6f} "
                      f"r={e['radius']:.5f} subsets={','.join(e['subsets']) or '-'}{extra}")

    print(f"\n{tally}")
    if args.json:
        with open(args.json, "w") as f:
            json.dump(report, f)


if __name__ == "__main__":
    main()
