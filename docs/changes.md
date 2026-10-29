# What the cleanup changed

The Blender export of this model shipped a second copy of most of its geometry as a
toon outline hull — a shell that duplicates a fill surface, offset about a
millimetre outward. The cleanup removes the duplicate shells and the controller
harness, and repairs three defects that make the export misbehave in strict
viewers.

## Duplicate shells removed by pairing, not by name

Shells are found with the model-explorer exploder's rule (weld by world position at
1e-5 of the model size, union-find over triangle corners) and paired by coincident
geometry *and* intersecting material signature. 344 shells and 126,606 faces went.

Two cheaper rules fail:

- a **name-based** sweep (`_OL`) takes `Gold_OL` with them, which is not an outline
  at all but the real gold trim (constant 0.8, metallic 0.85) sitting on the white
  band;
- a **geometry-only** pairing takes hair cards and coat panels, whose flat sheets
  have a signed volume of nearly zero, so their orientation is rounding noise.

The pair decides which copy goes: the offset copy (larger mean radius) or, when the
two are coincident, the one with negative volume. A shell with no partner stays.

## Skin arrays kept whole

`primvars:skel:jointIndices` and `jointWeights` are `vertex`-interpolated with
`elementSize` influences per point, so a kept point keeps a run of `elementSize`
values. Slicing them one-per-point truncates the arrays and silently unweights the
mesh: it renders in its bind pose in `usdview` and stretches into bars in Quick
Look, which applies the skin. All 181,436 point rows now sum to 1.

## Material UV readers repointed

Blender wrote `UsdPrimvarReader_float2.varname = "_"` — a placeholder for an
unnamed UV map — while the meshes carry `primvars:st`, so every textured material
rendered black in any renderer that honours the reader. All twelve readers now
name `st`.

## Also

- the `cs_*` controller gizmos (277 prims), seven empty Xforms and 16 unused
  materials are gone;
- 120 prims were renamed from Blender's Chinese UI defaults (`平面_053` →
  `Plane_053`, `NURBS_路径_073` → `NURBS_Path_073`) and then to the convention in
  [naming.md](naming.md);
- the one-mesh wrapper Xforms Blender leaves behind were collapsed, so a mesh part
  is a single prim;
- the camera and the dome light stay;
- no geometry was authored and no image was edited: the removed faces were
  duplicates, and the kept surface is element-for-element the source's (checked by
  a path-independent digest of points, faces, subsets and primvars).
