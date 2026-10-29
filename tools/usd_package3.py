"""Package a stripped Elaina layer as a single .usdz (root layer first, stored).

The layer is copied into the package first and the copy is rewritten and saved,
so the deliverable's shader inputs are ./textures/<name> and resolve inside the
package. Rewriting the source stage without saving it ships absolute paths that
resolve to nothing -- the defect this shape exists to avoid.
"""
from pxr import Usd, UsdShade, Sdf
import os, shutil, sys, zipfile

src, tex, out = sys.argv[1], sys.argv[2], sys.argv[3]

pkg = sys.argv[4] if len(sys.argv) > 4 else "./elaina_pkg_out"
shutil.rmtree(pkg, ignore_errors=True)
os.makedirs(pkg)
shutil.copy(src, os.path.join(pkg, "Elaina.usdc"))
shutil.copytree(tex, os.path.join(pkg, "textures"))

layer = os.path.join(pkg, "Elaina.usdc")
stage = Usd.Stage.Open(layer)
rewritten = 0
for prim in stage.Traverse():
    if prim.IsA(UsdShade.Shader):
        for inp in UsdShade.Shader(prim).GetInputs():
            if inp.GetTypeName() == Sdf.ValueTypeNames.Asset:
                v = inp.Get()
                if v and v.path:
                    rel = "./textures/" + os.path.basename(v.path)
                    if v.path != rel:
                        inp.Set(Sdf.AssetPath(rel))
                        rewritten += 1
stage.GetRootLayer().Save()
print("texture refs rewritten:", rewritten)

if os.path.exists(out):
    os.remove(out)
z = zipfile.ZipFile(out, "w", zipfile.ZIP_STORED)
z.write(layer, "Elaina.usdc")
for name in sorted(os.listdir(os.path.join(pkg, "textures"))):
    z.write(os.path.join(pkg, "textures", name), "textures/" + name)
z.close()
print("wrote", out, os.path.getsize(out), "bytes")

st = Usd.Stage.Open(out)
unresolved, authored = [], []
for prim in st.Traverse():
    if prim.IsA(UsdShade.Shader):
        for inp in UsdShade.Shader(prim).GetInputs():
            if inp.GetTypeName() == Sdf.ValueTypeNames.Asset and inp.Get() and inp.Get().path:
                a = inp.Get()
                authored.append(a.path)
                if not a.resolvedPath:
                    unresolved.append(a.path)
print("asset inputs:", len(authored), "distinct:", len(set(authored)), "unresolved:", sorted(set(unresolved)))
print("sample authored:", sorted(set(authored))[:2])
