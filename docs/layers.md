# Layers

The stage is a layer stack, so an edit touches one small file instead of a 60 MB
one:

    elaina-clean/
      Elaina_clean.usda             manifest: metadata and the sublayer list
      layers/
        Root.usda                   the character root
        Skeleton.usda               the rig chain and the Skeleton prim
        Materials.usda              the materials and their shaders
        Stage.usda                  the camera and the light
        geometry/
          Body.usda  Ear.usda  Eye.usda  Eyebrow.usda  Hair.usda
          Hat.usda   Overcoat.usda  WhiteDress.usda  WhiteShoes.usda
      textures/                     the images

Rules the stack keeps:

- **each prim is defined in exactly one layer.** Nothing is authored twice, so the
  stack composes with no conflicting opinions and layer order does not matter.
- **the manifest holds no prim specs**, only `defaultPrim`, `upAxis`,
  `metersPerUnit` and the sublayer list — opening `Elaina_clean.usda` composes the
  whole stage.
- **ancestors live in the layer that owns them**: `/Elaina` in `Root.usda`, the
  `SK_`/`SKEL_` chain in `Skeleton.usda`. The geometry layers define only their
  `S_` parts, and the material layer only `/Elaina/Materials`.
- **image paths are authored in `Materials.usda`**, relative to that layer
  (`../textures/T_Elaina_Hat_D.png`), so the whole directory can move.

Which file to open for which edit:

| edit | file |
|---|---|
| a mesh part (hat, hair strand, coat panel, shoe) | `layers/geometry/<Family>.usda` |
| a material or a texture reference | `layers/Materials.usda` |
| the skeleton, joints, bind transforms, skin weights | `layers/Skeleton.usda` |
| the camera or the light | `layers/Stage.usda` |
| stage metadata or the sublayer list | `Elaina_clean.usda` |

`tools/usd_split_layers.py` builds the stack from a flat stage and then checks the
result against the flat source: geometry digest, world bounds, material bindings,
skinning, and that every image resolves.
