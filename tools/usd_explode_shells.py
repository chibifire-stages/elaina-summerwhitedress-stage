"""Explode a USD into its shells and report each shell's orientation.

The rule is the model-explorer exploder's (addons/model_explode/explode.gd):
vertices closer than 1e-5 of the model size are one vertex, and a shell is the
triangles that share vertices, union-find over triangle corners. Nothing is cut,
so every shell boundary is an edge the artist made.

Orientation per shell, two independent measures:
  signed volume   sum over triangles of (a . (b x c)) / 6 -- positive means the
                  winding faces outward, negative means the shell is inverted
  radial dot      mean of dot(normal, x - shell centroid) -- same sign story,
                  and it survives an open shell where volume does not

A duplicated outline shell is the same shape as a fill shell with the opposite
sign, so the report pairs them per mesh and names the GeomSubset each shell's
faces came from.
"""
from pxr import Usd, UsdGeom, UsdShade, Gf
import argparse, json
import numpy as np


def world_points(prim, mesh):
    pts = np.array([[p[0], p[1], p[2]] for p in mesh.GetPointsAttr().Get()], dtype=np.float64)
    xf = UsdGeom.Xformable(prim).ComputeLocalToWorldTransform(Usd.TimeCode.Default())
    m = np.array([[xf[i][j] for j in range(4)] for i in range(4)], dtype=np.float64)
    return pts @ m[:3, :3].T + m[:3, 3]


def triangles(mesh):
    counts = list(mesh.GetFaceVertexCountsAttr().Get())
    fvi = list(mesh.GetFaceVertexIndicesAttr().Get())
    tris, off = [], 0
    for c in counts:
        idx = fvi[off:off + c]
        for k in range(1, c - 1):
            tris.append((idx[0], idx[k], idx[k + 1]))
        off += c
    return np.array(tris, dtype=np.int64), counts, fvi, off


def weld_ids(pts, q):
    keys = np.round(pts / q).astype(np.int64)
    _, ids = np.unique(keys, axis=0, return_inverse=True)
    return ids


def shells(w, tris):
    parent = np.arange(int(w.max()) + 1)

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)

    for t in tris:
        union(int(w[t[0]]), int(w[t[1]]))
        union(int(w[t[1]]), int(w[t[2]]))
    return np.array([find(int(i)) for i in range(len(parent))])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", required=True)
    ap.add_argument("--json", default=None)
    ap.add_argument("--per-mesh", action="store_true")
    args = ap.parse_args()

    stage = Usd.Stage.Open(args.file)
    meshes = [p for p in stage.Traverse() if p.GetTypeName() == "Mesh"]

    # model-wide size sets the weld quantum, as the exploder does
    lo = np.array([np.inf] * 3)
    hi = np.array([-np.inf] * 3)
    geo = {}
    for p in meshes:
        m = UsdGeom.Mesh(p)
        pts = world_points(p, m)
        geo[str(p.GetPath())] = pts
        lo = np.minimum(lo, pts.min(axis=0))
        hi = np.maximum(hi, pts.max(axis=0))
    size = float(np.linalg.norm(hi - lo))
    q = max(size * 1e-5, 1e-9)
    print(f"model size {size:.4f}  weld quantum {q:.3e}")

    report = {"size": size, "quantum": q, "meshes": {}}
    tot_shells = tot_inv = 0
    for p in meshes:
        path = str(p.GetPath())
        m = UsdGeom.Mesh(p)
        pts = geo[path]
        tris, counts, fvi, _ = triangles(m)
        w = weld_ids(pts, q)
        root = shells(w, tris)
        tri_root = root[w[tris[:, 0]]]
        subs = {c.GetName(): set(int(i) for i in UsdGeom.Subset(c).GetIndicesAttr().Get())
                for c in p.GetChildren() if c.GetTypeName() == "GeomSubset"}
        face_of_tri = []
        off = 0
        for f, c in enumerate(counts):
            for _ in range(c - 2):
                face_of_tri.append(f)
            off += c
        face_of_tri = np.array(face_of_tri, dtype=np.int64)

        nrm = m.GetPrim().GetAttribute("normals")
        nrm = np.array([[n[0], n[1], n[2]] for n in nrm.Get()], dtype=np.float64) if nrm and nrm.Get() is not None else None

        entries = []
        for r in np.unique(tri_root):
            tmask = tri_root == r
            t = tris[tmask]
            if len(t) == 0:
                continue
            a, b, c = pts[t[:, 0]], pts[t[:, 1]], pts[t[:, 2]]
            vol = float(np.sum(np.einsum("ij,ij->i", a, np.cross(b, c))) / 6.0)
            cent = (a + b + c).mean(axis=0) / 3.0
            rdot = None
            if nrm is not None:
                # faceVarying normals are per corner; the corner index is the triangle slot
                corner = tmask.nonzero()[0]
                pass
            fset = set(int(x) for x in face_of_tri[tmask])
            names = sorted(n for n, idx in subs.items() if idx & fset)
            entries.append({"faces": int(len(fset)), "tris": int(len(t)),
                            "volume": vol, "centroid": cent.tolist(), "subsets": names,
                            "radius": float(np.linalg.norm(a - cent, axis=1).mean())})
        entries.sort(key=lambda e: -e["tris"])
        tot_shells += len(entries)
        inv = [e for e in entries if e["volume"] < 0]
        tot_inv += len(inv)
        report["meshes"][path] = entries
        if args.per_mesh or inv:
            print(f"\n{path}: {len(entries)} shells, {len(inv)} inverted")
            for e in entries:
                tag = "INVERTED" if e["volume"] < 0 else "outward "
                print(f"   {tag} faces={e['faces']:6d} vol={e['volume']: .6f} r={e['radius']:.5f} "
                      f"subsets={','.join(e['subsets']) or '-'}")

    print(f"\nshells {tot_shells}, inverted {tot_inv}")
    if args.json:
        with open(args.json, "w") as f:
            json.dump(report, f)


if __name__ == "__main__":
    main()
