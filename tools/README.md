# tools

The pipeline that produced `elaina-clean/` from the Blender export of this model,
and the checks that say it is intact: duplicate outline shells removed, controller
gizmos and junk empties gone, prim names in English, skin arrays whole, material UV
readers repaired, and a spec-compliant USDZ package. Every script takes its paths
as arguments; the few that still hold a default constant expect it in the working
directory.

## Run order

| step | script | what it does |
|---|---|---|
| 1 | `usd_shells.py` | explodes a mesh into shells and reports each one's orientation and material signature (read-only) |
| 2 | `usd_shell_pairs.py` | the decision rule: which shell is a duplicate of which. Imported by the surgery and the gate |
| 3 | `usd_shell_view.py` | writes a render stage holding only one class of shell, so a removal can be *seen* |
| 4 | `usd_strip_shells.py` | the surgery: drops duplicate shells, remaps every primvar, prunes gizmos, empty Xforms and unused materials, writes a manifest |
| 5 | `usd_rename_english.py` | renames Blender's CJK prim names (`平面_053` → `Plane_053`, …) and their provenance strings |
| 6 | `usd_fix_uv_reader.py` | repoints each material's UV reader at the UV primvar the meshes carry |
| 7 | `usd_layer_clean.py` | rebuilds a layer with a fresh string table, relative image paths and a path-free documentation note |
| 8 | `usd_relativize_textures.py` | points every asset-valued attribute at the copy under the layer's own directory |
| 9 | `usd_package_usdz.py` | packages a layer as a compliant `.usdz`, and checks alignment and resolution |
| 10 | `usd_paired_check.py` | the gate. Both arms: the source must fail, the result must pass |
| 11 | `usd_preview.py` | writes a preview stage (the asset's own materials, a framing camera, two lights) for `usdrecord` |
| 12 | `usd_asset_rename.py` | renames prims and images to the convention in [../docs/naming.md](../docs/naming.md), collapses Blender's one-mesh wrapper Xforms, and checks the geometry, bounds, bindings and skinning are unchanged |
| 13 | `usd_split_layers.py` | splits a flat stage into the layer stack described in [../docs/layers.md](../docs/layers.md), and checks the stack against the flat source |

```sh
Q=7.932246821337585e-05      # weld quantum, fixed from the source file
python3 usd_strip_shells.py --src Elaina.usdc --dst out.usdc \
  --manifest manifest.json --under /root/char_grp/rig --quantum $Q \
  --remove-cs-gizmos --remove-empty-xforms
python3 usd_rename_english.py --src out.usdc --dst out_en.usdc
python3 usd_fix_uv_reader.py  --src out_en.usdc --dst out_uv.usdc
python3 usd_layer_clean.py    --src out_uv.usdc --dst Elaina_clean.usda
python3 usd_package_usdz.py   Elaina_clean.usda 1 Elaina_clean.usdz
python3 usd_paired_check.py   --file Elaina_clean.usda --reference Elaina.usdc \
  --manifest manifest.json --quantum $Q
python3 usd_preview.py        Elaina_clean.usdz preview.usda && usdrecord preview.usda preview.png
```

## Three defects this pipeline exists to avoid

1. **Never decide a duplicate by name or by absolute normal orientation.** Pair
   shells by coincident geometry *and* intersecting material signature. `_OL` in a
   subset name lies: `Gold_OL` is a real gold material (constant 0.8, metallic
   0.85) sitting on a white band, so a name-based sweep takes the gold trim. And a
   flat sheet's signed volume is rounding noise, so "inverted means duplicate"
   deletes hair cards and coat panels.
2. **`vertex`-interpolated primvars carry `elementSize` values per point.** The
   skin arrays (`primvars:skel:jointIndices` / `jointWeights`) must keep a run of
   `elementSize` values per kept point; slicing one-per-point truncates them and
   silently unweights the mesh. It renders fine in `usdview` (bind pose) and
   stretches into bars in Quick Look, which applies the skin. The gate asserts
   `len(arrays) == elementSize x points`, because a checker that slices the same
   wrong way agrees with the bug.
3. **A hand-rolled zip is not a USDZ.** The first file's data must start at offset
   64 and every entry must be 64-byte aligned. `zipfile` gives neither, and
   `usdchecker` still says Success, so use `UsdUtils.CreateNewUsdzPackage` and then
   assert the alignment.

Two more, about publishing a layer rather than rendering one:

- **Setting a field does not remove the old value from a `.usdc` string table.**
  `Save()` keeps unused strings, `Export()` copies that table, and `Flatten()`
  appends "Generated from Composed Stage of root layer &lt;path&gt;" to the
  documentation, so a layer that once held `/Users/&lt;name&gt;/...` keeps those bytes
  after the paths are fixed. `usd_layer_clean.py` builds the output from values
  with `Sdf.CopySpec`, so its table holds only what the content references.
- **`Export()` resolves asset paths as it writes.** A dome light's
  `inputs:texture:file` is an attribute, not a shader input, and it is just as
  likely to come out absolute as a texture path is. Walk every asset-valued
  attribute.

## Also here

- `usd_strip_outline.py`, `usd_outline_check.py`, `usd_sweep_outline.py`,
  `usd_asset_check.py`, `usd_remove_harness.py` — the earlier single-shell and
  full-sweep passes, kept for reference; they carry defect 2, so prefer
  `usd_strip_shells.py`.
- `usd_retry_check.py`, `usd_manifest_chain.py`, `usd_equiv.py`, `usd_verify.py`,
  `usd_tex_check.py`, `usd_weights.py`, `usd_weights2.py`, `usd_inspect.py`,
  `usd_probe_mesh.py`, `usd_rig_tree.py`, `usd_fix_documentation.py` — inspection
  and verification helpers.
- `usd_package3.py` — the old zipfile packager (defect 3). Superseded.
- `elaina_v6_run.sh`, `elaina_final_run.sh` — the end-to-end runs, with their
  original scratch paths scrubbed to relative ones.
