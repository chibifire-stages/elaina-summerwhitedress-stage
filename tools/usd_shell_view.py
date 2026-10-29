"""Write a render stage holding only the shells of one orientation class.

Usage:
  usd_shell_view.py SRC --keep inverted|outward|hull|twin --out OUT.usda [--under /root/...]

Shell rule: the model-explorer exploder's (weld by world position at 1e-5 of the
model size, union-find over triangle corners). Class per shell: `outward` when
its signed volume is positive, `hull` when it is an inverted shell with an
outward twin of the same face count and a larger mean radius, `twin` when that
twin is coincident, `inverted` when it has no twin at all.

Each kept shell is written as its own mesh in world space, so a render shows
exactly which surface the class covers. A framing camera and two distant lights
come with it, because usdrecord on a masked stage of the whole file renders
blank.
"""
from pxr import Usd, UsdGeom, UsdShade, UsdLux, Gf, Vt, Sdf
import argparse, math
import numpy as np


def world_points(prim, mesh):
    pts = np.array([[p[0], p[1], p[2]] for p in mesh.GetPointsAttr().Get()], dtype=np.float64)
    xf = UsdGeom.Xformable(prim).ComputeLocalToWorldTransform(Usd.TimeCode.Default())
    m = np.array([[xf[i][j] for j in range(4)] for i in range(4)], dtype=np.float64)
    return pts @ m[:3, :3].T + m[:3, 3]


def triangulate(mesh):
    counts = list(mesh.GetFaceVertexCountsAttr().Get())
    fvi = list(mesh.GetFaceVertexIndicesAttr().Get())
    tris, face_of_tri = [], []
    off = 0
    for f, c in enumerate(counts):
        for k in range(1, c - 1):
            tris.append((fvi[off], fvi[off + k], fvi[off + k + 1]))
            face_of_tri.append(f)
        off += c
    return np.array(tris, np.int64).reshape(-1, 3), np.array(face_of_tri, np.int64), counts, fvi


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


def classify(pts, tris, tri_root, face_of_tri):
    entries = []
    for r in np.unique(tri_root):
        tmask = tri_root == r
        t = tris[tmask]
        a, b, c = pts[t[:, 0]], pts[t[:, 1]], pts[t[:, 2]]
        vol = float(np.sum(np.einsum("ij,ij->i", a, np.cross(b, c))) / 6.0)
        cent = (a + b + c).mean(axis=0) / 3.0
        entries.append({"root": r, "tris": t, "faces": np.unique(face_of_tri[tmask]),
                        "volume": vol, "radius": float(np.linalg.norm(a - cent, axis=1).mean())})
    outward = [e for e in entries if e["volume"] > 0]
    for e in entries:
        if e["volume"] > 0:
            e["kind"] = "outward"
            continue
        twin = next((o for o in outward if len(o["faces"]) == len(e["faces"])), None)
        if twin is None:
            e["kind"] = "inverted"
        elif e["radius"] / twin["radius"] > 1.001:
            e["kind"] = "hull"
        else:
            e["kind"] = "twin"
    return entries


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("--keep", required=True, choices=["inverted", "outward", "hull", "twin", "inverted-all", "all"])
    ap.add_argument("--out", required=True)
    ap.add_argument("--under", default="/root/char_grp/rig")
    args = ap.parse_args()

    stage = Usd.Stage.Open(args.src)
    meshes = [p for p in stage.Traverse()
              if p.GetTypeName() == "Mesh" and str(p.GetPath()).startswith(args.under)]
    lo, hi = np.array([np.inf] * 3), np.array([-np.inf] * 3)
    geo = {}
    for p in meshes:
        pts = world_points(p, UsdGeom.Mesh(p))
        geo[str(p.GetPath())] = pts
        lo, hi = np.minimum(lo, pts.min(axis=0)), np.maximum(hi, pts.max(axis=0))
    q = max(float(np.linalg.norm(hi - lo)) * 1e-5, 1e-9)

    want = {"outward": {"outward"}, "inverted": {"hull", "twin", "inverted"},
            "hull": {"hull"}, "twin": {"twin"},
            "inverted-all": {"hull", "twin", "inverted", "inverted-unpaired"},
            "all": {"outward", "hull", "twin", "inverted", "inverted-unpaired"}}[args.keep]

    out = Usd.Stage.CreateNew(args.out)
    UsdGeom.SetStageMetersPerUnit(out, 1.0)
    UsdGeom.SetStageUpAxis(out, UsdGeom.Tokens.z)
    root = UsdGeom.Xform.Define(out, "/S")
    out.SetDefaultPrim(root.GetPrim())

    n = 0
    allpts = []
    frame_pts = []
    for p in meshes:
        path = str(p.GetPath())
        pts = geo[path]
        tris, face_of_tri, _, _ = triangulate(UsdGeom.Mesh(p))
        if len(tris) == 0:
            continue
        tri_root = shells_of(pts, tris, q)
        for e in classify(pts, tris, tri_root, face_of_tri):
            used = sorted(set(int(x) for x in e["tris"].flatten()))
            frame_pts.extend(pts[i] for i in used)   # every shell frames the camera
            if e["kind"] not in want:
                continue
            t = e["tris"]
            remap = {o: i for i, o in enumerate(used)}
            m = UsdGeom.Mesh.Define(out, f"/S/s{n}")
            m.CreatePointsAttr(Vt.Vec3fArray([Gf.Vec3f(*pts[i]) for i in used]))
            m.CreateFaceVertexCountsAttr(Vt.IntArray([3] * len(t)))
            m.CreateFaceVertexIndicesAttr(Vt.IntArray([remap[int(x)] for x in t.flatten()]))
            mn, mx = UsdGeom.PointBased(m.GetPrim()).ComputeExtent(m.GetPointsAttr().Get())
            m.CreateExtentAttr(Vt.Vec3fArray([mn, mx]))
            m.CreateSubdivisionSchemeAttr("none")
            n += 1
            allpts.extend(pts[i] for i in used)

    mat = UsdShade.Material.Define(out, "/S/mat")
    sh = UsdShade.Shader.Define(out, "/S/mat/s")
    sh.CreateIdAttr("UsdPreviewSurface")
    sh.CreateInput("diffuseColor", Sdf.ValueTypeNames.Color3f).Set(Gf.Vec3f(0.75, 0.76, 0.80))
    sh.CreateInput("roughness", Sdf.ValueTypeNames.Float).Set(0.55)
    sh.CreateInput("metallic", Sdf.ValueTypeNames.Float).Set(0.0)
    mat.CreateSurfaceOutput().ConnectToSource(sh.ConnectableAPI(), "surface")

    for i in range(n):
        UsdShade.MaterialBindingAPI.Apply(out.GetPrimAtPath(f"/S/s{i}")).Bind(mat)

    P = np.array(frame_pts)
    c = P.mean(axis=0)
    r = float(np.linalg.norm(P - c, axis=1).max())
    fov = 2 * math.atan(18.0 / 50.0)
    dist = r / math.sin(fov / 2) * 1.06
    eye = Gf.Vec3d(float(c[0]), float(c[1] - dist), float(c[2]))
    fwd = (Gf.Vec3d(*[float(x) for x in c]) - eye).GetNormalized()
    right = Gf.Vec3d(0, 0, 1).GetCross(fwd).GetNormalized()
    up = fwd.GetCross(right).GetNormalized()
    M = Gf.Matrix4d(right[0], right[1], right[2], 0, up[0], up[1], up[2], 0,
                    -fwd[0], -fwd[1], -fwd[2], 0, eye[0], eye[1], eye[2], 1)
    cam = UsdGeom.Camera.Define(out, "/S/cam")
    cam.CreateFocalLengthAttr(50.0)
    cam.CreateClippingRangeAttr(Gf.Vec2f(dist * 0.01, dist * 10))
    UsdGeom.Xformable(cam.GetPrim()).AddTransformOp().Set(M)

    for i, (d, inten) in enumerate([((0.5, -0.6, 0.7), 900.0), ((-0.7, -0.3, 0.2), 400.0)]):
        li = UsdLux.DistantLight.Define(out, f"/S/light{i}")
        li.CreateIntensityAttr(inten)
        li.CreateAngleAttr(20.0)
        v = Gf.Vec3d(*d).GetNormalized()
        z = -v
        x = Gf.Vec3d(0, 0, 1).GetCross(z)
        if x.GetLength() < 1e-6:
            x = Gf.Vec3d(1, 0, 0)
        x = x.GetNormalized()
        y = z.GetCross(x).GetNormalized()
        UsdGeom.Xformable(li.GetPrim()).AddTransformOp().Set(
            Gf.Matrix4d(x[0], x[1], x[2], 0, y[0], y[1], y[2], 0, z[0], z[1], z[2], 0, 0, 0, 0, 1))

    out.GetRootLayer().Save()
    print(f"wrote {args.out}: {n} shells kept ({args.keep}), radius {r:.3f}, dist {dist:.3f}")


if __name__ == "__main__":
    main()
