"""Replace a layer's documentation metadata with a path-free provenance note.

Blender's USD export writes the exporter version plus "Generated from Composed
Stage of root layer <absolute path>" into the layer's `documentation` metadata,
so a file that is otherwise clean still carries a home path
(`/Users/<name>/.hermes/...`) into anything that reads its metadata. Publishing
content must not.

  usd_fix_documentation.py --src IN.usdc --dst OUT.usdc --text "..."
"""
from pxr import Usd, Sdf
import argparse

DEFAULT = ("Elaina - The Witch's Journey (Summer White Dress), fan art by "
           "ScarletJadeDream (Sketchfab, CC-BY-4.0), exported from Blender and "
           "cleaned with OpenUSD: duplicate outline shells, controller gizmos and "
           "empty Xforms removed, prim names in English, material UV readers "
           "repointed at primvars:st.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True)
    ap.add_argument("--dst", required=True)
    ap.add_argument("--text", default=DEFAULT)
    args = ap.parse_args()

    layer = Sdf.Layer.FindOrOpen(args.src)
    before = layer.documentation or ""
    layer.documentation = args.text
    layer.Save()
    after = Sdf.Layer.FindOrOpen(args.src).documentation
    print(f"documentation: {len(before)} chars -> {len(after)}")
    print("   was:", before.replace("\n", " | ")[:160])
    print("   now:", after[:160])
    for needle in ("/Users/", "/home/", "ernest"):
        print(f"   {needle!r} in new text: {needle in after}")
    if args.dst != args.src:
        import shutil
        shutil.copyfile(args.src, args.dst)
        print("copied to", args.dst)


if __name__ == "__main__":
    main()
