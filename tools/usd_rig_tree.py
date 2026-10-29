from pxr import Usd, UsdSkel, UsdGeom

stage = Usd.Stage.Open("./Elaina.usdz")
skelroot = next(p for p in stage.Traverse() if p.IsA(UsdSkel.Root))
print("SkelRoot:", skelroot.GetPath())
print("=== direct children of the SkelRoot ===")
for c in skelroot.GetChildren():
    n = len(list(c.GetChildren()))
    print("  ", c.GetPath(), c.GetTypeName(), "children:", n)

skel_prim = next(p for p in stage.Traverse() if p.IsA(UsdSkel.Skeleton))
print()
print("=== children of the Skeleton prim ===")
kids = list(skel_prim.GetChildren())
print("count:", len(kids))
for c in kids[:10]:
    print("  ", c.GetPath(), c.GetTypeName())

print()
print("=== animations ===")
anims = [p for p in stage.Traverse() if p.IsA(UsdSkel.Animation)]
print("UsdSkel.Animation prims:", len(anims))
for a in anims[:5]:
    an = UsdSkel.Animation(a)
    j = an.GetJointsAttr().Get()
    print("  ", a.GetPath(), "joints:", len(j) if j else 0)

print()
print("=== meshes under the skeleton vs elsewhere ===")
und = sum(1 for p in stage.Traverse() if p.IsA(UsdGeom.Mesh) and str(p.GetPath()).startswith(str(skel_prim.GetPath())))
tot = sum(1 for p in stage.Traverse() if p.IsA(UsdGeom.Mesh))
print("meshes total:", tot, "under skeleton:", und)

print()
print("=== a skinned mesh's element size (body) ===")
for p in stage.Traverse():
    if p.IsA(UsdGeom.Mesh):
        ji = p.GetAttribute("primvars:skel:jointIndices")
        if ji and ji.Get() is not None:
            pts = p.GetAttribute("points").Get()
            npts = len(pts) if pts else 0
            nji = len(ji.Get())
            print("  ", p.GetPath(), "points:", npts, "jointIndices:", nji,
                  "elementSize:", (nji // npts) if npts else "?")
            break
