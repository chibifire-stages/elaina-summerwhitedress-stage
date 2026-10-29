# Attribution

CC-BY-4.0 requires a credit line, a licence reference, and an indication of
changes. Reproduce this, adapting the medium:

> "Elaina - The Witch's Journey (Summer White Dress)" by **ScarletJadeDream**,
> licensed under [CC-BY-4.0](https://creativecommons.org/licenses/by/4.0/).
> Source: <https://sketchfab.com/3d-models/elaina-the-witchs-journeysummerwhitedress-216ade78547a483fa055b15dae0c4ab0>.
> The `elaina-clean/` stage is a modified version: duplicated toon-outline shells,
> controller gizmos and empty Xforms removed; primitive names changed to English;
> material UV readers repaired.

## Per directory

| directory | author | source | licence | retrieved |
|---|---|---|---|---|
| `elaina-clean/` | derivative of the artwork below, modifications by K. S. Ernest (iFire) Lee | this repository | CC-BY-4.0 | 2026-10-29 |

The upstream Sketchfab conversion is **not** redistributed in this repository; only
our derivative of it is. Download the original from the URL above and credit the
artist as this file requires.

## What the upstream is

The Sketchfab model is a fan-made anime character: "The Witch's Journey (Summer
White Dress)" — Elaina. It contains the complete character, textures, a skeleton
and a reference animation, and was made in Blender 3.2. We converted its FBX to
OpenUSD to get the layer this repository's stage was cleaned from.

## What we changed

`elaina-clean/` started as the model's FBX converted to OpenUSD. Changes, all of
them removals or repairs — no geometry was authored, and no image was edited:

- removed 344 duplicate shells (126,606 faces) that re-drew existing surfaces as
  toon outline hulls, by pairing coincident geometry with an intersecting
  material signature;
- removed the `cs_*` controller gizmos (277 prims), seven empty Xforms, and 16
  unused materials;
- renamed 120 prims from Blender's Chinese UI defaults to English;
- repaired `primvars:skel:jointIndices` / `jointWeights`, which had been truncated
  to one value per point instead of `elementSize` values per point;
- repointed all twelve `UsdPrimvarReader_float2` nodes from `"_"` to `st`, the UV
  primvar the meshes carry, which is what made every material render black;
- named every prim and image to the convention in
  [docs/naming.md](docs/naming.md), and collapsed the one-mesh wrapper Xforms
  Blender leaves behind;
- split the stage into the layer stack in [docs/layers.md](docs/layers.md), so an
  edit touches one part instead of one 60 MB file.

The character is fan art of Elaina from *Wandering Witch: The Journey of Elaina*;
the character and its designs belong to their rights holders.
