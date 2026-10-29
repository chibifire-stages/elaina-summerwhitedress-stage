from pxr import Usd, UsdSkel, UsdGeom, UsdShade, Sdf
import zipfile

OUT = "./Elaina_clean.usdz"
stage = Usd.Stage.Open(OUT)
skel = next(p for p in stage.Traverse() if p.IsA(UsdSkel.Skeleton))
joints = list(UsdSkel.Skeleton(skel).GetJointsAttr().Get())

leaf = [j.split("/")[-1] for j in joints]
print("kept joints:", len(joints))
# the deform bones the skin actually uses
for want in ["arm_l", "arm_r", "forearm_l", "forearm_r", "hand_l", "hand_r",
             "thigh_l", "thigh_r", "leg_l", "leg_r", "foot_l", "foot_r",
             "root_x", "spine_01_x", "spine_02_x", "spine_03_x", "neck_x", "head_x"]:
    print(f"  {want:12s} leaf-present={want in leaf}  full-present={any(j.endswith('/'+want) or j==want for j in joints)}")

print()
print("all kept leaf names (first 80):")
print(sorted(set(leaf))[:80])

print()
print("=== do the skin primvars point only at kept joints? ===")
mx = -1; skinned = 0
for p in stage.Traverse():
    if p.IsA(UsdGeom.Mesh):
        a = p.GetAttribute("primvars:skel:jointIndices")
        if a and a.Get() is not None:
            skinned += 1
            vals = [int(x) for x in a.Get()]
            if vals: mx = max(mx, max(vals))
print("skinned meshes:", skinned, "max index:", mx, "(joints:", len(joints), ")")

print()
print("=== texture asset references ===")
refs = set()
for prim in stage.Traverse():
    if prim.IsA(UsdShade.Shader):
        for inp in UsdShade.Shader(prim).GetInputs():
            if inp.GetTypeName() == Sdf.ValueTypeNames.Asset:
                v = inp.Get()
                if v: refs.add(v.path)
for r in sorted(refs):
    print("  ref:", r)
    # try to resolve/read through the package
    try:
        from pxr import Ar
        resolved = Ar.GetResolver().Resolve(r)
        print("     resolved:", resolved)
    except Exception as e:
        print("     resolve error:", e)

print()
print("=== package entries ===")
z = zipfile.ZipFile(OUT)
for n in z.namelist():
    print("  ", n)
