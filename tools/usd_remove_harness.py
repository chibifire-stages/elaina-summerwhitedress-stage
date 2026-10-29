"""Remove the zero-skin-weight harness bones from the Elaina USD.

The criterion is the one the character domain formalizes (Character.HarnessBones):
a joint with no positive skin weight is a harness/controller bone. Ancestors of
skinned joints are kept, so the removal is descendant-closed.

  skeleton: joints / restTransforms / bindTransforms / primvars:blender:bone_lengths  -> filtered
  each skinned mesh: primvars:skel:jointIndices -> remapped to the compact index space
                     (a removed joint has zero weight everywhere, so no weight changes)
"""
from pxr import Usd, UsdSkel, UsdGeom, Vt, UsdUtils
import sys

SRC = "./Elaina.usdc"
DST = "./Elaina_clean.usdc"

stage = Usd.Stage.Open(SRC)
skel_prim = next(p for p in stage.Traverse() if p.IsA(UsdSkel.Skeleton))
skel = UsdSkel.Skeleton(skel_prim)
joints = list(skel.GetJointsAttr().Get())
N = len(joints)
print("joints before:", N)

# --- accumulate per-joint weight, and assert a removed joint has zero everywhere ---
total_w = [0.0] * N
meshes = []
for p in stage.Traverse():
    if not p.IsA(UsdGeom.Mesh):
        continue
    ji_a = p.GetAttribute("primvars:skel:jointIndices")
    jw_a = p.GetAttribute("primvars:skel:jointWeights")
    if not ji_a or not jw_a or ji_a.Get() is None or jw_a.Get() is None:
        continue
    meshes.append((p, ji_a, jw_a))
    ji = ji_a.Get(); jw = jw_a.Get()
    for k in range(len(ji)):
        idx = int(ji[k]); w = float(jw[k])
        if 0 <= idx < N:
            total_w[idx] += w

skinned_idx = [i for i in range(N) if total_w[i] > 1e-6]
idx_of = {joints[i]: i for i in range(N)}
def parent(p): return p.rsplit("/", 1)[0] if "/" in p else None
keep = set(skinned_idx)
for i in skinned_idx:
    cur = joints[i]
    while True:
        pn = parent(cur)
        if pn is None: break
        if pn in idx_of: keep.add(idx_of[pn])
        cur = pn
keep_sorted = sorted(keep)
remove = sorted(set(range(N)) - keep)
print("keep:", len(keep_sorted), " remove:", len(remove))

# a removed joint must carry zero weight in every element (else remapping is unsafe)
bad = 0
for (p, ji_a, jw_a) in meshes:
    ji = ji_a.Get(); jw = jw_a.Get()
    for k in range(len(ji)):
        if int(ji[k]) in set(remove) and float(jw[k]) > 1e-9:
            bad += 1
print("removed-joint influences with nonzero weight (must be 0):", bad)
assert bad == 0

# --- 1. filter the skeleton arrays ---
new_joints = [joints[i] for i in keep_sorted]
skel.GetJointsAttr().Set(Vt.TokenArray(new_joints))
rests = skel.GetRestTransformsAttr().Get()
if rests: skel.GetRestTransformsAttr().Set(Vt.Matrix4dArray([rests[i] for i in keep_sorted]))
binds = skel.GetBindTransformsAttr().Get()
if binds: skel.GetBindTransformsAttr().Set(Vt.Matrix4dArray([binds[i] for i in keep_sorted]))
bl = skel_prim.GetAttribute("primvars:blender:bone_lengths")
if bl and bl.Get() is not None:
    bl.Set(Vt.FloatArray([bl.Get()[i] for i in keep_sorted]))
print("skeleton filtered ->", len(new_joints))

# --- 2. remap every skinned mesh's joint indices ---
remap = {old: new for new, old in enumerate(keep_sorted)}
for (p, ji_a, jw_a) in meshes:
    ji = ji_a.Get()
    ji_a.Set(Vt.IntArray([remap.get(int(x), 0) for x in ji]))
print("meshes remapped:", len(meshes))

# --- 3. export the modified layer ---
stage.Export(DST)
print("exported:", DST)

# --- 4. verify the new layer ---
st2 = Usd.Stage.Open(DST)
sk2 = next(p for p in st2.Traverse() if p.IsA(UsdSkel.Skeleton))
print("verify joints:", len(UsdSkel.Skeleton(sk2).GetJointsAttr().Get()))
print("verify restTransforms:", len(UsdSkel.Skeleton(sk2).GetRestTransformsAttr().Get()))
mx = 0
for p in st2.Traverse():
    if p.IsA(UsdGeom.Mesh):
        a = p.GetAttribute("primvars:skel:jointIndices")
        if a and a.Get() is not None:
            mx = max(mx, max(int(x) for x in a.Get()) if len(a.Get()) else 0)
print("verify max joint index in skins (must be < 292):", mx)
