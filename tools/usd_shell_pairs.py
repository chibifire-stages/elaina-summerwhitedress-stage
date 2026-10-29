"""Shell pairing for the Elaina strip: decide which shells are duplicate copies.

A shell is a duplicate when another shell in the same mesh is the same surface
lying on top of it: vertices matching within a quarter of the shell radius AND
the same material signature. The duplicate of a pair is the offset copy (larger
mean radius) or, when the two are coincident, the one whose signed volume is
negative.

Two rules earn their keep here.

Signed volume alone cannot decide orientation. A flat sheet -- a hair card, a
coat panel, a shoe sole -- has a volume of nearly zero, so its sign is rounding
noise, and an absolute "inverted means duplicate" test then deletes real
surface. The pair decides, and a shell with no partner is left alone.

Material matters as much as geometry. On this asset the gold trim is a scaled
copy of the band it sits on (Gold_OL: constant gold, metallic 0.85), and the
outline hull is a copy of its fill with the *same* material as the fill
(Overcoat_OL carries Overcoat_F's texture and parameters). Geometry alone
cannot tell those apart; the signature can. Two shells pair when their
signature sets intersect, because a fill often spans two materials (Overcoat_B
and Overcoat_F) while its hull carries only one.
"""
import numpy as np
from pxr import Usd, UsdGeom, UsdShade


def material_signatures(stage):
    """Material path -> a string of everything that decides how it renders."""
    sig = {}
    for p in stage.Traverse():
        if p.GetTypeName() != "Material":
            continue
        sh = next((c for c in p.GetChildren() if c.IsA(UsdShade.Shader)), None)
        if not sh:
            sig[str(p.GetPath())] = "no-shader"
            continue
        parts = []
        for i in sorted(UsdShade.Shader(sh).GetInputs(), key=lambda x: x.GetBaseName()):
            src = i.GetConnectedSource()
            if src:
                node = UsdShade.Shader(src[0].GetPrim())
                f = (node.GetInput("file") if node and node.GetIdAttr().Get() == "UsdUVTexture" else None)
                parts.append(f"{i.GetBaseName()}<-tex:{f.Get().path if f and f.Get() else '?'}")
            elif i.Get() is not None:
                v = i.Get()
                parts.append(f"{i.GetBaseName()}="
                             f"{tuple(round(float(x), 4) for x in v) if hasattr(v, '__len__') else round(float(v), 4)}")
        sig[str(p.GetPath())] = ";".join(parts)
    return sig


def face_signatures(prim, mesh, sig_map):
    """Per-face material signature, resolving the mesh binding and its subsets."""
    counts = list(mesh.GetFaceVertexCountsAttr().Get())
    rel = prim.GetRelationship("material:binding")
    default = str(rel.GetTargets()[0]) if rel and rel.GetTargets() else None
    out = [default] * len(counts)
    for c in prim.GetChildren():
        if c.GetTypeName() != "GeomSubset":
            continue
        srel = c.GetRelationship("material:binding")
        if not srel or not srel.GetTargets():
            continue
        m = str(srel.GetTargets()[0])
        for f in UsdGeom.Subset(c).GetIndicesAttr().Get():
            out[int(f)] = m
    return [sig_map.get(str(x), str(x)) for x in out]


def shell_entries(pts, tris, tri_root, face_of_tri, face_sig=None):
    entries = []
    for r in np.unique(tri_root):
        tmask = tri_root == r
        t = tris[tmask]
        a, b, c = pts[t[:, 0]], pts[t[:, 1]], pts[t[:, 2]]
        faces = np.unique(face_of_tri[tmask])
        cent = (a + b + c).mean(axis=0) / 3.0
        sigs = tuple(sorted({face_sig[int(f)] for f in faces})) if face_sig is not None else ()
        entries.append({
            "tris": t, "verts": np.unique(t.flatten()), "faces": faces,
            "volume": float(np.sum(np.einsum("ij,ij->i", a, np.cross(b, c))) / 6.0),
            "centroid": cent,
            "radius": float(np.linalg.norm(a - cent, axis=1).mean()),
            "sigs": sigs,
        })
    return entries


def _median_nn(x, y, cap=400):
    if len(x) > cap:
        x = x[:: max(1, len(x) // cap)]
    d = np.linalg.norm(x[:, None, :] - y[None, :, :], axis=2)
    return float(np.median(d.min(axis=1)))


def classify(pts, tris, tri_root, face_of_tri, face_sig=None, tol=0.25):
    """Mark each shell 'surface' (kept) or 'duplicate' (removed)."""
    entries = shell_entries(pts, tris, tri_root, face_of_tri, face_sig)
    for e in entries:
        e["kind"] = "surface"

    pairs = []
    for i in range(len(entries)):
        for j in range(i + 1, len(entries)):
            ei, ej = entries[i], entries[j]
            if len(ei["verts"]) != len(ej["verts"]) or not (set(ei["sigs"]) & set(ej["sigs"])):
                continue
            d = _median_nn(pts[ei["verts"]], pts[ej["verts"]])
            scale = max(ei["radius"], ej["radius"], 1e-12)
            if d / scale < tol:
                pairs.append((d / scale, i, j))
    pairs.sort()

    used = set()
    for ratio, i, j in pairs:
        if i in used or j in used:
            continue
        ei, ej = entries[i], entries[j]
        used.add(i)
        used.add(j)
        if abs(ei["radius"] - ej["radius"]) > 0.001 * max(ei["radius"], ej["radius"]):
            dup, keep = (i, j) if ei["radius"] > ej["radius"] else (j, i)
        else:
            dup, keep = (i, j) if ei["volume"] < ej["volume"] else (j, i)
        entries[dup]["kind"] = "duplicate"
        entries[dup]["pair_ratio"] = ratio
        entries[keep]["kind"] = "surface"
    return entries
