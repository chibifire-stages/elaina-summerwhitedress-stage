"""Point every asset input at the copy of that file which sits under the layer.

`Usd.Stage.Export()` resolves asset paths as it writes, so a layer can end up
naming its textures absolutely (`/abs/stage/1/tex.png`) -- it works on the machine
that wrote it and nowhere else -- and a hand-fixed path can end up relative but
wrong (`../../../../abs/stage/1/tex.png`). This finds each referenced file by
basename under the layer's own directory (the directory itself, or one level
down) and writes that relative path.

Idempotent: a path that already resolves inside the layer's directory is left
alone. Reports anything it cannot place, and fails on it.

  usd_relativize_textures.py --src LAYER.usdc [--check-only]
"""
from pxr import Usd, UsdShade, Sdf
import argparse, os


def place(layer_dir, path):
    """The relative path to use for `path`, or None if it is not under layer_dir."""
    base = os.path.basename(path)
    here = os.path.join(layer_dir, base)
    if os.path.exists(here):
        return base
    for sub in sorted(os.listdir(layer_dir)):
        cand = os.path.join(layer_dir, sub)
        if os.path.isdir(cand) and os.path.exists(os.path.join(cand, base)):
            return os.path.join(sub, base)
    return None


def inputs(stage):
    for p in stage.Traverse():
        if not p.IsA(UsdShade.Shader):
            continue
        for inp in UsdShade.Shader(p).GetInputs():
            if inp.GetTypeName() == Sdf.ValueTypeNames.Asset:
                yield inp


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True)
    ap.add_argument("--check-only", action="store_true")
    args = ap.parse_args()

    src = os.path.abspath(args.src)
    layer_dir = os.path.dirname(os.path.realpath(src))
    stage = Usd.Stage.Open(src)

    kept, changed, unplaced = 0, 0, []
    for inp in inputs(stage):
        a = inp.Get()
        if not a or not a.path:
            continue
        rel = place(layer_dir, a.path)
        if rel is None:
            unplaced.append(a.path)
            continue
        if rel == a.path:
            kept += 1
            continue
        if not args.check_only:
            inp.Set(Sdf.AssetPath(rel))
        changed += 1

    if not args.check_only and changed:
        stage.GetRootLayer().Save()

    stage = Usd.Stage.Open(src)
    authored, unresolved = set(), set()
    for inp in inputs(stage):
        a = inp.Get()
        if a and a.path:
            authored.add(a.path)
            if not a.resolvedPath:
                unresolved.add(a.path)
    print(f"inputs: {len(authored)} distinct | left alone {kept} | rewritten {changed} | unplaced {len(unplaced)}")
    print("   sample:", sorted(authored)[:3])
    if unresolved:
        print("   UNRESOLVED:", sorted(unresolved))
    if unplaced:
        print("   UNPLACED:", unplaced)
    if unresolved or unplaced:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
