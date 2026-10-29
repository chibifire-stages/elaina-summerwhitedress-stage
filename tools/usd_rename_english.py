"""Rename the Blender-exported CJK prim names to English, in place.

Blender wrote its default primitive names in the Chinese UI locale -- 平面 for a
plane, 圆环 for a torus, NURBS_路径 for an NURBS path, 空物体 for an empty. The
rig's bones are already English, so only prim names and the Blender provenance
strings carry CJK.

Renames go through Sdf.BatchNamespaceEdit, deepest first, so the layer's own
relationship and connection targets follow the names. Provenance values keep
Blender's ".NNN" suffix convention.

  --check   report what would change and exit
"""
from pxr import Usd, Sdf
import argparse, re, sys

STEMS = {
    "平面": "Plane",
    "圆环": "Ring",
    "环体": "Torus",
    "贝塞尔圆": "BezierCircle",
    "棱角球": "Icosphere",
    "空物体": "Empty",
    "网格": "Mesh",
    "柱体": "Cylinder",
    "球体": "Sphere",
    "立方体": "Cube",
    "NURBS_路径": "NURBS_Path",
    "NURBS 路径": "NURBS_Path",
}
NONASCII = re.compile(r"[^\x00-\x7F]")


def translate(text):
    out = text
    for zh, en in sorted(STEMS.items(), key=lambda kv: -len(kv[0])):
        out = out.replace(zh, en)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True)
    ap.add_argument("--dst", default=None)
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()

    stage = Usd.Stage.Open(args.src)
    prims = [p for p in stage.Traverse() if NONASCII.search(p.GetName())]
    prims.sort(key=lambda p: -len(str(p.GetPath()).split("/")))
    print(f"prims to rename: {len(prims)}")
    for p in prims[:5]:
        print(f"   {p.GetName()}  ->  {translate(p.GetName())}")

    layer = stage.GetRootLayer()
    renamed = 0
    for p in prims:
        new_name = translate(p.GetName())
        if new_name == p.GetName():
            continue
        old_path = p.GetPath()
        new_path = old_path.GetParentPath().AppendChild(new_name)
        if layer.GetPrimAtPath(new_path):
            print(f"   ! {new_path} already exists, skipped")
            continue
        edit = Sdf.BatchNamespaceEdit()
        edit.Add(old_path, new_path)
        if not layer.Apply(edit):
            print(f"   ! rename refused: {old_path}")
            continue
        renamed += 1

    values = 0
    for p in stage.Traverse():
        for a in p.GetAttributes():
            if a.GetName() in ("points", "normals"):
                continue
            v = a.Get()
            if v is None or not NONASCII.search(str(v)):
                continue
            new = translate(str(v))
            if new != str(v):
                a.Set(type(v)(new))
                values += 1
    print(f"renamed {renamed} prims, rewrote {values} provenance values")

    left = [str(p.GetPath()) for p in stage.Traverse() if NONASCII.search(p.GetName())]
    left += [f"{p.GetPath()}.{a.GetName()}" for p in stage.Traverse() for a in p.GetAttributes()
             if a.Get() is not None and a.GetName() not in ("points", "normals")
             and NONASCII.search(str(a.Get()))]
    print("non-ASCII left:", len(left), left[:3])

    if args.check:
        return
    if not args.dst:
        print("no --dst given")
        sys.exit(1)
    layer.Export(args.dst)
    print("exported", args.dst)
    if left:
        sys.exit(1)


if __name__ == "__main__":
    main()
