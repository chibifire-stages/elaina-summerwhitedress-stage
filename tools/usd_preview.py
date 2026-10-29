"""Write a preview stage for a USD file: its own geometry and materials, my camera and lights.

A packaged asset's own camera is often a close-up and its lighting a single
dome, so a plain `usdrecord asset.usdz out.png` comes back dark and cropped and
tells you nothing about the materials. This references the asset's default prim
into a fresh stage, frames it, adds two distant lights, and leaves the asset's
own materials untouched -- so a render shows what the textures actually do.

  usd_preview.py ASSET.usdz OUT.usda [--exclude /root/char_grp/cs_grp] [--keep-all]
"""
from pxr import Usd, UsdGeom, UsdLux, Gf
import argparse, math
import numpy as np


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("asset")
    ap.add_argument("out")
    args = ap.parse_args()

    src = Usd.Stage.Open(args.asset)
    root = src.GetDefaultPrim()
    lo, hi = np.array([np.inf] * 3), np.array([-np.inf] * 3)
    for p in src.Traverse():
        if p.GetTypeName() != "Mesh":
            continue
        pts = UsdGeom.Mesh(p).GetPointsAttr().Get()
        if not pts:
            continue
        xf = UsdGeom.Xformable(p).ComputeLocalToWorldTransform(Usd.TimeCode.Default())
        m = np.array([[xf[i][j] for j in range(4)] for i in range(4)], dtype=np.float64)
        w = np.array([[q[0], q[1], q[2]] for q in pts], dtype=np.float64) @ m[:3, :3].T + m[:3, 3]
        lo, hi = np.minimum(lo, w.min(axis=0)), np.maximum(hi, w.max(axis=0))
    c = (lo + hi) / 2
    r = float(np.linalg.norm(hi - lo) / 2)

    out = Usd.Stage.CreateNew(args.out)
    UsdGeom.SetStageMetersPerUnit(out, UsdGeom.GetStageMetersPerUnit(src))
    UsdGeom.SetStageUpAxis(out, UsdGeom.GetStageUpAxis(src))
    world = UsdGeom.Xform.Define(out, "/W")
    out.SetDefaultPrim(world.GetPrim())
    world.GetPrim().GetReferences().AddReference(args.asset, root.GetPath())

    fov = 2 * math.atan(18.0 / 50.0)
    dist = r / math.sin(fov / 2) * 1.15
    eye = Gf.Vec3d(float(c[0]), float(c[1] - dist), float(c[2] + r * 0.15))
    fwd = (Gf.Vec3d(*[float(x) for x in c]) - eye).GetNormalized()
    right = Gf.Vec3d(0, 0, 1).GetCross(fwd).GetNormalized()
    up = fwd.GetCross(right).GetNormalized()
    cam = UsdGeom.Camera.Define(out, "/W/cam")
    cam.CreateFocalLengthAttr(50.0)
    cam.CreateClippingRangeAttr(Gf.Vec2f(dist * 0.01, dist * 10))
    UsdGeom.Xformable(cam.GetPrim()).AddTransformOp().Set(
        Gf.Matrix4d(right[0], right[1], right[2], 0, up[0], up[1], up[2], 0,
                    -fwd[0], -fwd[1], -fwd[2], 0, eye[0], eye[1], eye[2], 1))

    for i, (d, intensity) in enumerate([((0.4, -0.7, 0.5), 1200.0), ((-0.7, -0.4, 0.3), 500.0)]):
        li = UsdLux.DistantLight.Define(out, f"/W/light{i}")
        li.CreateIntensityAttr(intensity)
        li.CreateAngleAttr(15.0)
        v = Gf.Vec3d(*d).GetNormalized()
        z = -v
        x = Gf.Vec3d(0, 0, 1).GetCross(z)
        x = (Gf.Vec3d(1, 0, 0) if x.GetLength() < 1e-6 else x).GetNormalized()
        y = z.GetCross(x).GetNormalized()
        UsdGeom.Xformable(li.GetPrim()).AddTransformOp().Set(
            Gf.Matrix4d(x[0], x[1], x[2], 0, y[0], y[1], y[2], 0, z[0], z[1], z[2], 0, 0, 0, 0, 1))

    out.GetRootLayer().Save()
    print(f"wrote {args.out}: centre {c.round(3)}, radius {r:.3f}, camera {dist:.3f} back")


if __name__ == "__main__":
    main()
