from pxr import Usd, UsdSkel, UsdGeom
import json, collections

USDZ = "./Elaina.usdz"
stage = Usd.Stage.Open(USDZ)

# --- skeleton ---
skel_prim = None
for p in stage.Traverse():
    if p.IsA(UsdSkel.Skeleton):
        skel_prim = p
        break
skel = UsdSkel.Skeleton(skel_prim)
joints = list(skel.GetJointsAttr().Get())
print("skeleton:", skel_prim.GetPath(), "joints:", len(joints))

# --- skin weights: accumulate per joint index ---
total_w = [0.0] * len(joints)
nonzero_count = [0] * len(joints)
skinned = []
mesh_names = []
for p in stage.Traverse():
    if p.IsA(UsdGeom.Mesh):
        mesh_names.append(p.GetName())
        q = UsdSkel.SkinningQuery(p)
        if not q:
            continue
        ji_attr = q.GetJointIndicesAttr()
        jw_attr = q.GetJointWeightsAttr()
        if not ji_attr or not jw_attr:
            continue
        ji = ji_attr.Get()
        jw = jw_attr.Get()
        if not ji or not jw:
            continue
        skinned.append(str(p.GetPath()))
        es = q.GetElementSize() or 1
        for k in range(len(ji)):
            idx = int(ji[k])
            w = float(jw[k])
            if 0 <= idx < len(joints):
                total_w[idx] += w
                if w > 1e-6:
                    nonzero_count[idx] += 1

skinned_joint_idx = [i for i in range(len(joints)) if total_w[i] > 1e-6]
zero_joint_idx = [i for i in range(len(joints)) if total_w[i] <= 1e-6]
print("skinned meshes:", len(skinned))
print("joints with >0 total weight:", len(skinned_joint_idx))
print("joints with ZERO total weight (harness):", len(zero_joint_idx))

# ancestors of skinned joints must be kept
name_of = {i: joints[i] for i in range(len(joints))}
idx_of = {joints[i]: i for i in range(len(joints))}
def parent_name(p):
    if "/" in p:
        return p.rsplit("/", 1)[0]
    return None
keep = set(skinned_joint_idx)
for i in skinned_joint_idx:
    cur = joints[i]
    while True:
        pn = parent_name(cur)
        if pn is None:
            break
        if pn in idx_of:
            keep.add(idx_of[pn])
        cur = pn
print("keep set (skinned + ancestors):", len(keep))
remove = sorted(set(range(len(joints))) - keep)
print("remove set (harness, descendant-closed check):", len(remove))

# descendant-closed check: no removed joint has a kept descendant
removed_set = set(remove)
violations = 0
for i in remove:
    for k in keep:
        if joints[k].startswith(joints[i] + "/"):
            violations += 1
print("removed joints with a kept descendant (must be 0):", violations)

out = {
    "n_joints": len(joints),
    "n_skinned": len(skinned_joint_idx),
    "n_keep": len(keep),
    "n_remove": len(remove),
    "remove_names": [joints[i] for i in remove],
    "keep_idx": sorted(keep),
    "skinned_meshes": skinned,
    "mesh_count": len(mesh_names),
}
with open("./usd_analysis.json", "w") as f:
    json.dump(out, f, indent=1)
print()
print("sample removed:", out["remove_names"][:12])
print("sample kept:", [joints[i] for i in sorted(keep)[:8]])
print("saved usd_analysis.json")
