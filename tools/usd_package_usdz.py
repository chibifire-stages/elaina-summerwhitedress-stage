"""Package a stripped Elaina layer as a single .usdz.

Use pxr's packager, not a hand-rolled zip. The USDZ spec puts the first file's
data at offset 64 and aligns every file to 64 bytes; `zipfile` does neither, and
while usdchecker and pxr tolerate that, strict loaders refuse the asset. And
usdzip / CreateNewUsdzPackage also rewrite each shader asset input to its
package path (`1/<name>.png`), which is what makes the textures resolve inside
the package.

  usd_package.py LAYER.usdc TEXTURES_DIR OUT.usdz
"""
from pxr import Usd, UsdUtils, UsdShade, Sdf
import os, struct, sys, zipfile

layer, texdir, out = sys.argv[1], sys.argv[2], sys.argv[3]
if os.path.exists(out):
    os.remove(out)
UsdUtils.CreateNewUsdzPackage(os.path.abspath(layer), os.path.abspath(out))
print("wrote", out, os.path.getsize(out), "bytes")

z = zipfile.ZipFile(out)
misaligned = []
for info in z.infolist():
    with open(out, "rb") as f:
        f.seek(info.header_offset)
        hdr = f.read(30)
        n, m = struct.unpack("<HH", hdr[26:30])
    if (info.header_offset + 30 + n + m) % 64:
        misaligned.append(info.filename)
print("entries:", len(z.namelist()), "| not 64-byte aligned:", len(misaligned))

st = Usd.Stage.Open(out)
authored, unresolved = set(), set()
for prim in st.Traverse():
    if prim.IsA(UsdShade.Shader):
        for inp in UsdShade.Shader(prim).GetInputs():
            if inp.GetTypeName() == Sdf.ValueTypeNames.Asset and inp.Get() and inp.Get().path:
                a = inp.Get()
                authored.add(a.path)
                if not a.resolvedPath:
                    unresolved.add(a.path)
print("asset inputs:", len(authored), "distinct:", len(authored),
      "unresolved:", sorted(unresolved))
if misaligned or unresolved:
    sys.exit(1)
