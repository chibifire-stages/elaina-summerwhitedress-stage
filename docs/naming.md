# Naming

One convention, `Prefix_BaseAssetName_Variant`, with the character as the base
name and the part as the variant.

| prefix | what it names | example |
|---|---|---|
| `S_` | a mesh part | `S_Elaina_Hat_Star_01` |
| `SK_` | the skinned character root | `SK_Elaina` |
| `SKEL_` | the rig and the skeleton | `SKEL_Elaina`, `SKEL_Elaina_Skeleton` |
| `M_` | a material | `M_Elaina_Hat` |
| `T_` | an image, suffixed with the map it carries | `T_Elaina_Hat_D` (`D` = diffuse / base colour) |
| `CAM_` | a camera | `CAM_Elaina_Snap` |
| `LGT_` | a light | `LGT_Elaina_Env` |

Rules applied:

- a mesh part is `S_Elaina_<Part>_<NN>`, numbered within its part from `01`
  (`S_Elaina_Hair_01` … `S_Elaina_Hair_50`);
- a material names its part and what distinguishes it
  (`M_Elaina_Overcoat_Front`, `M_Elaina_Hair_Outline`);
- an image names the material variant it serves, and its suffix names the map
  (`T_Elaina_Overcoat_Front_D`);
- names are `[A-Za-z0-9_]` only: no spaces, no non-ASCII;
- the camera and the light are not assets of the usual kind; the prefixes keep the
  stage reading as one set, which is the point of a convention.

The stage tree the convention produces:

    /Elaina
      CAM_Elaina_Snap/CAM_Elaina_Snap_Camera
      LGT_Elaina_Env
      Materials/M_Elaina_<Part>
      SK_Elaina/SKEL_Elaina
        SKEL_Elaina_Skeleton
        S_Elaina_<Part>_<NN>            (120 mesh parts)

`tools/usd_asset_rename.py` applies it to a stage: it renames the prims, collapses
the one-mesh wrapper Xforms Blender leaves behind (baking any transform onto the
mesh part, so a part is a single prim), renames the image files, and then checks
that a path-independent geometry digest, the world bounding box, the material
bindings and the skinning are all unchanged.
