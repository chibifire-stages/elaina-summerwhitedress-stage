"""Gate on the Elaina body mesh: no outline copy, and the kept half is unchanged.

Arms:
  --file <usdz>                     assert the body mesh carries no *_OL subset
  --file <usdz> --reference <usdc>  also assert the kept geometry is a prefix
                                    slice of the reference (points, faceVertex
                                    indices, normals, st:indices, skin arrays)

Run against the pre-strip file the outline assertion must fail; that is the
control proving the gate can report the other outcome.
"""
from pxr import Usd, UsdGeom
import argparse, sys

BODY = "/root/char_grp/rig/Body/圆环_017"


def body(stage):
    return UsdGeom.Mesh(stage.GetPrimAtPath(BODY))


def attr(schema, name):
    return schema.GetPrim().GetAttribute(name)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", required=True)
    ap.add_argument("--reference", default=None)
    args = ap.parse_args()

    fails = []
    st = Usd.Stage.Open(args.file)
    m = body(st)
    if not m:
        print("FAIL: no body mesh at", BODY)
        sys.exit(1)

    subsets = [c.GetName() for c in m.GetPrim().GetChildren() if c.GetTypeName() == "GeomSubset"]
    ol = [s for s in subsets if s.endswith("_OL")]
    faces = len(m.GetFaceVertexCountsAttr().Get())
    points = len(m.GetPointsAttr().Get())
    fvi = len(m.GetFaceVertexIndicesAttr().Get())
    print(f"{args.file}")
    print(f"  body faces={faces} points={points} fvi={fvi} subsets={subsets}")
    if ol:
        fails.append(f"body still carries the outline copy: {ol}")
    if fvi != 4 * faces:
        fails.append(f"faceVertexIndices {fvi} != 4 x faces {faces}")

    if args.reference:
        ref_stage = Usd.Stage.Open(args.reference)   # keep the stage alive for the prim
        ref = body(ref_stage)
        if not ref:
            print("FAIL: reference has no body mesh")
            sys.exit(1)
        rp = list(ref.GetPointsAttr().Get())
        rf = list(ref.GetFaceVertexIndicesAttr().Get())
        rn = list(attr(ref, "normals").Get())
        ri = list(attr(ref, "primvars:st:indices").Get())
        rj = list(attr(ref, "primvars:skel:jointIndices").Get())
        rw = list(attr(ref, "primvars:skel:jointWeights").Get())
        rs = list(attr(ref, "primvars:st").Get())
        checks = [
            ("points", list(m.GetPointsAttr().Get()), rp[:points]),
            ("faceVertexIndices", list(m.GetFaceVertexIndicesAttr().Get()), rf[:fvi]),
            ("normals", list(attr(m, "normals").Get()), rn[:fvi]),
            ("primvars:st:indices", list(attr(m, "primvars:st:indices").Get()), ri[:fvi]),
            ("primvars:st values kept whole", list(attr(m, "primvars:st").Get()), rs),
            ("jointIndices", list(attr(m, "primvars:skel:jointIndices").Get()), rj[:points]),
            ("jointWeights", list(attr(m, "primvars:skel:jointWeights").Get()), rw[:points]),
        ]
        for name, got, want in checks:
            same = len(got) == len(want) and all(a == b for a, b in zip(got, want))
            print(f"  prefix-slice {name}: {'ok' if same else 'DIFFERS'} (len {len(got)})")
            if not same:
                fails.append(f"{name} is not the reference's prefix")

    skel = next((p for p in st.Traverse() if p.GetTypeName() == "Skeleton"), None)
    if skel:
        print("  joints:", len(skel.GetAttribute("joints").Get()))

    from pxr import UsdShade, Sdf
    authored, unresolved = set(), set()
    for prim in st.Traverse():
        if prim.IsA(UsdShade.Shader):
            for inp in UsdShade.Shader(prim).GetInputs():
                if inp.GetTypeName() == Sdf.ValueTypeNames.Asset and inp.Get() and inp.Get().path:
                    a = inp.Get()
                    authored.add(a.path)
                    if not a.resolvedPath:
                        unresolved.add(a.path)
    print(f"  texture inputs: {len(authored)} distinct, {len(unresolved)} unresolved")
    for u in sorted(unresolved):
        fails.append(f"texture input resolves to nothing: {u}")
    if authored and all(not p.startswith("./textures/") for p in authored):
        fails.append(f"texture inputs are not package-relative: {sorted(authored)[:1]}")

    if fails:
        print("FAIL:")
        for f in fails:
            print("  -", f)
        sys.exit(1)
    print("PASS")


if __name__ == "__main__":
    main()
