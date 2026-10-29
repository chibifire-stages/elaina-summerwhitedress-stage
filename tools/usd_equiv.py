"""Equivalence check: the cleaned skin must be identical to the original under the
keep mapping. For every skinned mesh, every influence slot's weight is unchanged,
and its joint index maps through keep_sorted to the same joint name."""
from pxr import Usd, UsdSkel, UsdGeom
import json

ORIG = "./Elaina.usdc"
CLEAN = "./Elaina_clean.usdz"

a = json.load(open("./usd_analysis.json"))
keep_sorted = a["keep"]
old_joints = a["joints"]

def skins(path):
    st = Usd.Stage.Open(path)
    out = {}
    for p in st.Traverse():
        if not p.IsA(UsdGeom.Mesh):
            continue
        ji = p.GetAttribute("primvars:skel:jointIndices")
        jw = p.GetAttribute("primvars:skel:jointWeights")
        if ji and jw and ji.Get() is not None and jw.Get() is not None:
            out[str(p.GetPath())] = (list(map(int, ji.Get())), list(map(float, jw.Get())))
    return out

so = skins(ORIG)
sc = skins(CLEAN)
print("skinned meshes  orig:", len(so), " clean:", len(sc))
print("same mesh set:", set(so) == set(sc))

bad_w = bad_i = 0
checked = 0
for path in so:
    jo, wo = so[path]
    jc, wc = sc[path]
    if len(jo) != len(jc) or len(wo) != len(wc):
        print("LENGTH MISMATCH", path, len(jo), len(jc)); bad_i += 1; continue
    for k in range(len(jo)):
        checked += 1
        if abs(wo[k] - wc[k]) > 1e-9:
            bad_w += 1
        # the new index must name the same joint the old index named
        if keep_sorted[jc[k]] != jo[k]:
            bad_i += 1
print("influences checked:", checked)
print("weight mismatches:", bad_w, " index mismatches:", bad_i)

# and every nonzero-weight influence still points at the same joint name
mism = 0
for path in so:
    jo, wo = so[path]
    jc, wc = sc[path]
    for k in range(len(jo)):
        if wo[k] > 1e-9:
            if old_joints[keep_sorted[jc[k]]] != old_joints[jo[k]]:
                mism += 1
print("nonzero-weight name mismatches:", mism)
print()
print("RESULT:", "DEFORMATION-NEUTRAL" if (bad_w == 0 and bad_i == 0 and mism == 0) else "MISMATCH")
