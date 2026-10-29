from pxr import Usd, UsdSkel, UsdGeom
import json

USDZ = "./Elaina.usdz"
stage = Usd.Stage.Open(USDZ)

skel_prim = next(p for p in stage.Traverse() if p.IsA(UsdSkel.Skeleton))
skel = UsdSkel.Skeleton(skel_prim)
joints = list(skel.GetJointsAttr().Get())
N = len(joints)
print("skeleton:", skel_prim.GetPath(), "joints:", N)

total_w = [0.0] * N
skinned = []
mesh_names = []
for p in stage.Traverse():
    if not p.IsA(UsdGeom.Mesh):
        continue
    mesh_names.append(p.GetName())
    ji_a = p.GetAttribute("primvars:skel:jointIndices")
    jw_a = p.GetAttribute("primvars:skel:jointWeights")
    if not ji_a or not jw_a:
        continue
    ji = ji_a.Get(); jw = jw_a.Get()
    if not ji or not jw:
        continue
    pts = p.GetAttribute("points").Get()
    npts = len(pts) if pts else 0
    # a mesh may declare its own joint subset via skel:joints; here it is not authored,
    # so indices index the skeleton's joints directly.
    sub = p.GetAttribute("skel:joints").Get()
    skinned.append(str(p.GetPath()))
    for k in range(len(ji)):
        idx = int(ji[k])
        w = float(jw[k])
        if sub:
            if 0 <= idx < len(sub):
                name = sub[idx]
                idx = joints.index(name) if name in joints else -1
            else:
                idx = -1
        if 0 <= idx < N:
            total_w[idx] += w

skinned_idx = [i for i in range(N) if total_w[i] > 1e-6]
zero_idx = [i for i in range(N) if total_w[i] <= 1e-6]
print("skinned meshes:", len(skinned))
print("meshes:", len(mesh_names))
print("joints with >0 total weight:", len(skinned_idx))
print("joints with ZERO weight (harness):", len(zero_idx))

# ancestors of skinned joints must stay (descendant-closed removal)
idx_of = {joints[i]: i for i in range(N)}
def parent(p):
    return p.rsplit("/", 1)[0] if "/" in p else None
keep = set(skinned_idx)
for i in skinned_idx:
    cur = joints[i]
    while True:
        pn = parent(cur)
        if pn is None:
            break
        if pn in idx_of:
            keep.add(idx_of[pn])
        cur = pn
remove = sorted(set(range(N)) - keep)
print("keep (skinned + ancestors):", len(keep), " remove:", len(remove))

# removed joints must have no kept descendant
bad = sum(1 for i in remove for k in keep if joints[k].startswith(joints[i] + "/"))
print("removed joints with a kept descendant (must be 0):", bad)

json.dump({
    "n": N, "skinned": skinned_idx, "keep": sorted(keep), "remove": remove,
    "remove_names": [joints[i] for i in remove],
    "joints": joints,
    "mesh_names": mesh_names,
    "skinned_meshes": skinned,
}, open("./usd_analysis.json", "w"))
print("sample removed:", [joints[i] for i in remove][:10])
print("sample kept   :", [joints[i] for i in sorted(keep)[:6]])
print()
# any 'outline' / duplicate-looking mesh names?
outl = [n for n in mesh_names if "outline" in n.lower() or "copy" in n.lower()]
print("outline/copy-named meshes:", outl[:20])
