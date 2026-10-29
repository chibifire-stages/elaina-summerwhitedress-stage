set -e
cd "${WORK:?set WORK to the scratch directory holding the source layer}"
Q=7.932246821337585e-05
echo "### 1. strip ###"
python3 usd_strip_shells.py --src elaina_retry/Elaina.usdc --dst elaina_retry/Elaina_v6.usdc \
  --manifest elaina_retry/manifest_v6.json --report elaina_retry/report_v6.json \
  --under /root/char_grp/rig --quantum $Q --remove-cs-gizmos --remove-empty-xforms
echo "### 2. control arm (must FAIL) ###"
python3 usd_paired_check.py --file elaina_retry/Elaina.usdc --quantum $Q 2>&1 | tail -4 || true
echo "### 3. result arm ###"
python3 usd_paired_check.py --file elaina_retry/Elaina_v6.usdc --reference elaina_retry/Elaina.usdc \
  --manifest elaina_retry/manifest_v6.json --quantum $Q 2>&1 | tail -8 || true
echo "### 4. rename ###"
python3 usd_rename_english.py --src elaina_retry/Elaina_v6.usdc --dst elaina_retry/Elaina_en6.usdc 2>&1 | tail -2
echo "### 5. package ###"
python3 usd_package_usdz.py elaina_retry/Elaina_en6.usdc elaina_retry/textures ./Desktop/Elaina_clean.usdz
echo "### 6. gate on the package ###"
python3 usd_paired_check.py --file ./Desktop/Elaina_clean.usdz --quantum $Q 2>&1 | tail -5 || true
echo "### 7. usdchecker ###"
usdchecker ./Desktop/Elaina_clean.usdz 2>&1 | tail -2
echo "### 8. skin audit on the package ###"
python3 - <<'PY'
from pxr import Usd, UsdGeom
import numpy as np
st = Usd.Stage.Open("./Desktop/Elaina_clean.usdz")
rows = bad_len = zero = off = 0
worst = []
for p in st.Traverse():
    if p.GetTypeName() != "Mesh": continue
    ji = p.GetAttribute("primvars:skel:jointIndices"); jw = p.GetAttribute("primvars:skel:jointWeights")
    if not ji or ji.Get() is None: continue
    n = len(UsdGeom.Mesh(p).GetPointsAttr().Get()); el = ji.GetMetadata("elementSize") or 1
    w = np.array([float(x) for x in jw.Get()], float)
    if len(ji.Get()) != el*n or len(w) != el*n:
        bad_len += 1; worst.append((str(p.GetPath()), len(ji.Get()), len(w), el*n)); continue
    sums = w.reshape(n, el).sum(axis=1)
    rows += n; zero += int((sums < 1e-6).sum()); off += int(((sums < 0.999) | (sums > 1.001)).sum())
print(f"   meshes with wrong-length skin arrays: {bad_len}")
for x in worst[:5]: print("     ", x)
print(f"   point rows: {rows}, unweighted: {zero}, weights not summing to 1: {off}")
PY
echo "### 9. digest ###"
python3 - <<'PY'
from pxr import Usd, UsdGeom
import hashlib
def digest(f):
    st = Usd.Stage.Open(f)
    meshes = sorted([x for x in st.Traverse() if x.GetTypeName()=="Mesh"], key=lambda x: str(x.GetPath()))
    h = hashlib.sha256()
    for p in meshes:
        m = UsdGeom.Mesh(p)
        h.update(str(len(m.GetPointsAttr().Get())).encode())
        h.update(b"".join(str(round(v,6)).encode() for q in m.GetPointsAttr().Get() for v in q))
        h.update(b"".join(str(i).encode() for i in m.GetFaceVertexIndicesAttr().Get()))
        h.update(b"".join(str(i).encode() for i in m.GetFaceVertexCountsAttr().Get()))
        for c in sorted(p.GetChildren(), key=lambda x: x.GetName()):
            if c.GetTypeName()=="GeomSubset":
                h.update(b"".join(str(i).encode() for i in UsdGeom.Subset(c).GetIndicesAttr().Get()))
        for nm in ("normals","primvars:st","primvars:st:indices","primvars:skel:jointIndices","primvars:skel:jointWeights"):
            a = p.GetAttribute(nm)
            if a and a.Get() is not None:
                h.update(str(len(a.Get())).encode()); h.update(str(a.Get())[:400000].encode())
    return h.hexdigest()[:16], len(meshes)
print("   packaged:", digest("./Desktop/Elaina_clean.usdz"))
print("   layer   :", digest("elaina_retry/Elaina_en6.usdc"))
PY
ls -la ./Desktop/Elaina_clean.usdz
