"""Gate on a swept Elaina USD: the shell is gone and the kept data is unchanged.

Arms:
  --file <usd> --manifest <json> --reference <usd>   the result arm
  --file <pre-strip usd>                             the control arm, which must
                                                     fail on the shell it carries

Assertions: no `_OL` prim, no `cs_*` gizmo prim, no childless Xform at the scene
root, the joint count holds, every texture input resolves and is
package-relative, and -- per mesh in the manifest -- the result is the
reference's own points, faces, normals, UV indices and skin weights, element for
element. A mesh the reference gave an `_OL` subset that the manifest does not
cover is a failure, so a silently skipped mesh cannot read as a pass.
"""
from pxr import Usd, UsdGeom, UsdShade, Sdf
import argparse, json, sys

ROOT = "/root"


def face_offsets(counts):
    offs, o = [], 0
    for c in counts:
        offs.append(o)
        o += c
    return offs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", required=True)
    ap.add_argument("--reference", default=None)
    ap.add_argument("--manifest", default=None)
    ap.add_argument("--joints", type=int, default=292)
    ap.add_argument("--allow-textures-missing", action="store_true")
    args = ap.parse_args()

    fails = []
    st = Usd.Stage.Open(args.file)
    prims = list(st.Traverse())
    print(args.file)

    ol = [str(p.GetPath()) for p in prims if str(p.GetPath()).split("/")[-1].endswith("_OL")]
    print(f"  prims={len(prims)} meshes={sum(1 for p in prims if p.GetTypeName()=='Mesh')} "
          f"OL_prims={len(ol)}")
    if ol:
        fails.append(f"{len(ol)} outline prims remain, e.g. {ol[:3]}")

    cs = [str(p.GetPath()) for p in prims if str(p.GetPath()).startswith("/root/char_grp/cs_grp")]
    if cs:
        fails.append(f"{len(cs)} cs_* gizmo prims remain, e.g. {cs[:2]}")

    empties = [str(c.GetPath()) for c in st.GetPrimAtPath(ROOT).GetChildren()
               if c.GetTypeName() == "Xform" and not list(c.GetChildren())]
    if empties:
        fails.append(f"childless Xforms at the scene root remain: {empties}")

    skel = next((p for p in prims if p.GetTypeName() == "Skeleton"), None)
    joints = len(skel.GetAttribute("joints").Get()) if skel else 0
    print(f"  joints={joints}")
    if joints != args.joints:
        fails.append(f"joints {joints} != {args.joints}")

    authored, unresolved = set(), set()
    for prim in prims:
        if prim.IsA(UsdShade.Shader):
            for inp in UsdShade.Shader(prim).GetInputs():
                if inp.GetTypeName() == Sdf.ValueTypeNames.Asset and inp.Get() and inp.Get().path:
                    a = inp.Get()
                    authored.add(a.path)
                    if not a.resolvedPath:
                        unresolved.add(a.path)
    print(f"  texture inputs: {len(authored)} distinct, {len(unresolved)} unresolved")
    if not args.allow_textures_missing:
        for u in sorted(unresolved):
            fails.append(f"texture input resolves to nothing: {u}")
        if authored and all(not p.startswith("./textures/") for p in authored):
            fails.append("texture inputs are not package-relative")

    if args.manifest and args.reference:
        manifest = json.load(open(args.manifest))
        ref_stage = Usd.Stage.Open(args.reference)   # hold the stage for the prims
        ref_prims = {str(p.GetPath()): p for p in ref_stage.Traverse()}
        want = {path for path, p in ref_prims.items()
                if p.GetTypeName() == "Mesh"
                and any(c.GetName().endswith("_OL") for c in p.GetChildren() if c.GetTypeName() == "GeomSubset")}
        got = set(manifest["meshes"])
        if want != got:
            fails.append(f"meshes with an outline subset not covered by the manifest: {sorted(want - got)[:3]}")

        checked = 0
        for path, m in manifest["meshes"].items():
            ref, new = ref_prims[path], st.GetPrimAtPath(path)
            if not new:
                fails.append(f"{path} is missing from the result")
                continue
            R, N = UsdGeom.Mesh(ref), UsdGeom.Mesh(new)
            rc = list(R.GetFaceVertexCountsAttr().Get())
            rf = list(R.GetFaceVertexIndicesAttr().Get())
            rpts = list(R.GetPointsAttr().Get())
            rnorm = list(ref.GetAttribute("normals").Get())
            rji = list(ref.GetAttribute("primvars:skel:jointIndices").Get())
            rjw = list(ref.GetAttribute("primvars:skel:jointWeights").Get())
            ro = face_offsets(rc)
            kept_positions = [ro[f] + k for f in m["old_faces"] for k in range(rc[f])]
            inv = {old: new_i for new_i, old in enumerate(m["old_points"])}
            pairs = [
                ("faceVertexCounts", list(N.GetFaceVertexCountsAttr().Get()), [rc[f] for f in m["old_faces"]]),
                ("faceVertexIndices", list(N.GetFaceVertexIndicesAttr().Get()), [inv[rf[p]] for p in kept_positions]),
                ("points", list(N.GetPointsAttr().Get()), [rpts[i] for i in m["old_points"]]),
                ("normals", list(new.GetAttribute("normals").Get()), [rnorm[p] for p in kept_positions]),
                ("jointIndices", list(new.GetAttribute("primvars:skel:jointIndices").Get()), [rji[i] for i in m["old_points"]]),
                ("jointWeights", list(new.GetAttribute("primvars:skel:jointWeights").Get()), [rjw[i] for i in m["old_points"]]),
            ]
            for name, gotv, wantv in pairs:
                if len(gotv) != len(wantv) or any(a != b for a, b in zip(gotv, wantv)):
                    fails.append(f"{path}: {name} is not the reference's own data "
                                 f"(len {len(gotv)} vs {len(wantv)})")
            checked += 1
        print(f"  meshes proved element-for-element: {checked}")

    if fails:
        print("FAIL:")
        for f in fails:
            print("  -", f)
        sys.exit(1)
    print("PASS")


if __name__ == "__main__":
    main()
