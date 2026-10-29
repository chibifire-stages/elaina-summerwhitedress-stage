from pxr import Usd, UsdShade, Ar, Sdf

def refs(path):
    stage = Usd.Stage.Open(path)
    out = []
    for prim in stage.Traverse():
        if prim.IsA(UsdShade.Shader):
            for inp in UsdShade.Shader(prim).GetInputs():
                if inp.GetTypeName() == Sdf.ValueTypeNames.Asset:
                    v = inp.Get()
                    if v and v.path:
                        out.append(v.path)
    return sorted(set(out)), stage

orig_refs, _ = refs("./Elaina.usdc")
print("=== ORIGINAL usdc texture refs ===")
for r in orig_refs: print("  ", r)

new_refs, st = refs("./Elaina_clean.usdz")
print("=== NEW usdz texture refs ===")
for r in new_refs: print("  ", r)

# Can the packaged usdz actually read its textures?
print("=== read-through test on the packaged usdz ===")
resolver = Ar.GetResolver()
root_id = st.GetRootLayer().identifier
print("root layer:", root_id)
for r in new_refs:
    try:
        resolved = resolver.CreateIdentifier(r, Ar.ResolvedPath(root_id))
        asset = resolver.OpenAsset(Ar.ResolvedPath(resolved)) if resolved else None
        n = asset.GetSize() if asset else None
        print(f"  {r} -> resolved={resolved!r} size={n}")
    except Exception as e:
        print(f"  {r} -> ERROR {e}")
