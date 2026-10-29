# chibifire-stages

The cleaned OpenUSD stage of **Elaina - The Witch's Journey (Summer White Dress)**
by [ScarletJadeDream](https://sketchfab.com/ScarletJadeDream) (CC-BY-4.0), with the
pipeline that made it.

| directory | what it is |
|---|---|
| `elaina-clean/` | the model's FBX converted to OpenUSD, then stripped of its duplicated outline shells and controller rig, prim names in English, materials repaired. `Elaina_clean.usda` plus its nine texture files. 120 meshes, 13 materials, 292 joints. |
| `tools/` | the pipeline and the checks, with the run order and the defects they exist to avoid |

The upstream is **not** redistributed here. The artist's own Sketchfab conversion of
the same model — 241 meshes, 23 materials, a 624-joint skeleton with its reference
animation — is at
<https://sketchfab.com/3d-models/elaina-the-witchs-journeysummerwhitedress-216ade78547a483fa055b15dae0c4ab0>;
credit it as [ATTRIBUTION.md](ATTRIBUTION.md) requires when you use this stage.

Nothing here is a package: the layer is `.usda` (text, so it diffs and reads
without a tool) and the images are the original PNG files. The stage opens with its
images from the directory it sits in.

    usdcat elaina-clean/Elaina_clean.usda | head
    usdview elaina-clean/Elaina_clean.usda

## What our derivative changed

The Blender export of this model shipped a second copy of most of its geometry as
a toon outline hull — a shell that duplicates a fill surface, offset a millimetre
outward. The cleanup removes the duplicate shells and the controller harness, and
repairs three defects that make the export misbehave in strict viewers:

- **Duplicate shells removed by pairing, not by name.** Shells are found with the
  model-explorer exploder's rule (weld by world position at 1e-5 of the model
  size, union-find over triangle corners) and paired by coincident geometry *and*
  intersecting material signature. 344 shells and 126,606 faces went. A
  name-based sweep (`_OL`) would have taken `Gold_OL` with them, which is not an
  outline at all but the real gold trim (constant 0.8, metallic 0.85) sitting on
  the white band; a geometry-only pairing would have taken hair cards and coat
  panels, whose flat sheets have a signed volume of nearly zero.
- **Skin arrays kept whole.** `primvars:skel:jointIndices` and `jointWeights` are
  `vertex`-interpolated with `elementSize` influences per point, so a kept point
  keeps a run of `elementSize` values. Slicing them one-per-point truncates the
  arrays and silently unweights the mesh: it renders in its bind pose in
  `usdview` and stretches into bars in Quick Look. All 181,436 point rows now sum
  to 1.
- **Material UV readers repointed.** Blender wrote
  `UsdPrimvarReader_float2.varname = "_"` — a placeholder for an unnamed UV map —
  while the meshes carry `primvars:st`, so every textured material rendered
  black. All twelve readers now name `st`.

Also gone: the `cs_*` controller gizmos (277 prims), seven empty Xforms, and 16
unused materials. 120 prims were renamed from Blender's Chinese UI defaults
(`平面_053` → `Plane_053`, `NURBS_路径_073` → `NURBS_Path_073`, …). The camera and
the dome light stay.

Per-file sizes and sha256 are in [MANIFEST.md](MANIFEST.md). The pipeline that
produced the cleaned stage — and the checks that say it is intact — is in
[tools/](tools/), with the run order and the defects it exists to avoid.

## Licence and attribution

The artwork is **CC-BY-4.0** ([ScarletJadeDream](https://sketchfab.com/3d-models/elaina-the-witchs-journeysummerwhitedress-216ade78547a483fa055b15dae0c4ab0),
Sketchfab). Our derivative is a modification of it and carries the same licence.
See [ATTRIBUTION.md](ATTRIBUTION.md) for the credit line to reproduce and
[LICENSE.md](LICENSE.md) for the licence text and scope.

The character is fan art of Elaina from *Wandering Witch: The Journey of Elaina*;
the character and its designs belong to their rights holders, and this repository
claims no rights in them.

Cite this repository and the upstream artwork with the metadata in
[CITATION.cff](CITATION.cff).
