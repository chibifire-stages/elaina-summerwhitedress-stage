from pxr import Usd, UsdSkel, UsdGeom, Sdf
import sys, collections

USDZ = "./Elaina.usdz"
print("opening", USDZ)
stage = Usd.Stage.Open(USDZ)
print("default prim:", stage.GetDefaultPrim().GetPath() if stage.GetDefaultPrim() else None)

skelroots = []
skeletons = []
meshes = []
skinned = []
for prim in stage.Traverse():
    if prim.IsA(UsdSkel.Root):
        skelroots.append(prim)
    if prim.IsA(UsdSkel.Skeleton):
        skeletons.append(prim)
    if prim.IsA(UsdGeom.Mesh):
        meshes.append(prim)
        if prim.HasAPI(UsdSkel.BindingAPI):
            skinned.append(prim)

print("SkelRoot:", [str(p.GetPath()) for p in skelroots])
print("Skeleton:", [str(p.GetPath()) for p in skeletons])
print("meshes:", len(meshes), " skinned meshes:", len(skinned))

for sk in skeletons:
    s = UsdSkel.Skeleton(sk)
    joints = s.GetJointsAttr().Get()
    rests = s.GetRestTransformsAttr().Get()
    print()
    print("SKELETON", sk.GetPath())
    print("  joints:", len(joints) if joints else 0)
    print("  restTransforms:", len(rests) if rests else 0)
    # list other attrs on the prim
    for a in sk.GetAttributes():
        print("   attr:", a.GetName(), a.GetTypeName(), "->", "value" if a.HasAuthoredValue() else "no-value")
    print("  first 5 joints:", list(joints)[:5] if joints else None)

print()
print("=== skinned meshes ===")
for m in skinned[:40]:
    b = UsdSkel.BindingAPI(m)
    jn = b.GetJointsAttr().Get()
    w = b.GetWeightsAttr().Get()
    skel_rel = b.GetSkeletonRel().GetTargets()
    print(str(m.GetPath()), "| joints primvar:", len(jn) if jn else 0,
          "| weights:", len(w) if w else 0, "| skeleton:", [str(t) for t in skel_rel])
