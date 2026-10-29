from pxr import Usd, UsdSkel, UsdGeom
import json

USDZ = "./Elaina.usdz"
stage = Usd.Stage.Open(USDZ)

skel_prim = next(p for p in stage.Traverse() if p.IsA(UsdSkel.Skeleton))
joints = list(UsdSkel.Skeleton(skel_prim).GetJointsAttr().Get())
print("skeleton:", skel_prim.GetPath(), "joints:", len(joints))

# find one skinned mesh and print its skin primvars
found = None
for p in stage.Traverse():
    if p.IsA(UsdGeom.Mesh):
        for a in p.GetAttributes():
            if "skel" in a.GetName().lower():
                found = p
                break
    if found:
        break
print("example skinned mesh:", found.GetPath() if found else None)
if found:
    for a in found.GetAttributes():
        nm = a.GetName()
        v = a.Get()
        try:
            n = len(v) if hasattr(v, "__len__") else v
        except Exception:
            n = v
        print("   ", nm, a.GetTypeName(), "len/val=", n)
