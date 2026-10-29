"""Compose two strip manifests so the second run's map names indices in the ORIGINAL mesh.

A strip run records, per mesh, the old point and old face index of everything it
kept. Running the strip again on its own output records the same thing relative
to that output. Chaining the two gives one map back to the first run's input,
which is what the element-for-element gate needs.
"""
import json, sys

first, second, out = sys.argv[1], sys.argv[2], sys.argv[3]
a = json.load(open(first))
b = json.load(open(second))
composed = {"meshes": {}, "removed_prims": a.get("removed_prims", []) + b.get("removed_prims", []),
            "duplicates": a.get("duplicates", []) + b.get("duplicates", []),
            "meshes_removed": a.get("meshes_removed", []) + b.get("meshes_removed", [])}
for path, mb in b["meshes"].items():
    if path in a["meshes"]:
        ma = a["meshes"][path]
        composed["meshes"][path] = {
            "old_points": [ma["old_points"][i] for i in mb["old_points"]],
            "old_faces": [ma["old_faces"][f] for f in mb["old_faces"]],
            "faces_removed": ma["faces_removed"] + mb["faces_removed"],
            "points_kept": mb["points_kept"],
            "passes": ma.get("passes", 1) + mb.get("passes", 1),
        }
    else:
        composed["meshes"][path] = mb
for path, ma in a["meshes"].items():
    composed["meshes"].setdefault(path, ma)
json.dump(composed, open(out, "w"))
print(f"composed {len(composed['meshes'])} meshes -> {out}")
