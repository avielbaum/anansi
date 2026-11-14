"""Build LPC character sprite sheets from tools/cast.json.

python tools/build_sprites.py [--cache DIR] [character ...]

For each character it fetches the layer images from the Universal LPC Spritesheet Character Generator repository
(cached in --cache, outside the repo), recolours them with the generator's palettes, stacks them by zPos and writes
assets/sprites/<id>/<animation>.png (rows: up, left, down, right; 64x64 frames) plus assets/sprites/manifest.json and
assets/CREDITS.csv. Every layer's authors and licences go into the credits file; LPC art requires that.
"""
import argparse, csv, io, json, os, sys, urllib.error, urllib.request
from PIL import Image

REPO = "https://raw.githubusercontent.com/LiberatedPixelCup/Universal-LPC-Spritesheet-Character-Generator/master/"
ANIMS = ["idle", "walk", "run", "slash", "thrust", "spellcast", "hurt", "combat_idle"]
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "assets")


def fetch(path, cache):
    """Bytes of a repo file, or None if it does not exist (not every layer has every animation)."""
    local = os.path.join(cache, *path.split("/"))
    if os.path.exists(local):
        return open(local, "rb").read() if os.path.getsize(local) else None
    try:
        data = urllib.request.urlopen(REPO + urllib.parse.quote(path), timeout=60).read()
    except urllib.error.HTTPError as e:
        if e.code != 404:
            raise
        data = b""
    os.makedirs(os.path.dirname(local), exist_ok=True)
    open(local, "wb").write(data)  # an empty file remembers a 404
    return data or None


def palette_map(recolors, colour, cache):
    """Pixel map from the layer's base colours to `colour`, using the first recolour slot (skin, hair or cloth)."""
    slot = recolors.get("color_1", recolors)
    material = slot["material"]
    meta = json.loads(fetch(f"palette_definitions/{material}/meta_{material}.json", cache))
    for name in slot.get("palettes", ["ulpc"]):
        where = f"all/all_{name.split('.')[1]}" if name.startswith("all.") else f"{material}/{material}_{name}"
        raw = fetch(f"palette_definitions/{where}.json", cache)
        pal = json.loads(raw) if raw else {}
        if colour in pal and meta["base"] in pal:
            src, dst = pal[meta["base"]], pal[colour]
            hexrgb = lambda h: tuple(int(h.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
            return {hexrgb(a): hexrgb(b) for a, b in zip(src, dst)}
    raise SystemExit(f"colour {colour!r} not in the {material} palettes")


def recolour(img, cmap):
    if not cmap:
        return img
    px = img.load()
    for y in range(img.height):
        for x in range(img.width):
            r, g, b, a = px[x, y]
            if a:
                for (sr, sg, sb), dst in cmap.items():  # the generator matches within +-1 per channel
                    if abs(r - sr) <= 1 and abs(g - sg) <= 1 and abs(b - sb) <= 1:
                        px[x, y] = (*dst, a)
                        break
    return img


def build(cid, spec, cache, credits):
    layers = []  # (zPos, image path template, colour map)
    for def_path, colour in spec["layers"]:
        d = json.loads(fetch("sheet_definitions/" + def_path, cache))
        cmap = palette_map(d["recolors"], colour, cache) if "recolors" in d and colour not in d.get("variants", []) else None
        if "recolors" not in d and colour not in d.get("variants", []):
            raise SystemExit(f"{def_path}: no colour {colour!r} (variants: {d.get('variants')})")
        for key in sorted(k for k in d if k.startswith("layer_")):
            base = d[key].get(spec["body"])
            if base is None:
                raise SystemExit(f"{def_path}: no art for body type {spec['body']}")
            tmpl = f"spritesheets/{base}{{anim}}/{colour.replace(' ', '_')}.png" if cmap is None else f"spritesheets/{base}{{anim}}.png"
            layers.append((d[key]["zPos"], tmpl, cmap))
            used = [c for c in d.get("credits", []) if base.startswith(c["file"].rstrip("/") + "/") or base.rstrip("/") == c["file"].rstrip("/")]
            for c in used or d.get("credits", []):  # no exact match: credit the whole item rather than nobody
                credits[(c["file"], tuple(c["authors"]))] = c
    layers.sort(key=lambda l: l[0])
    out_dir = os.path.join(OUT, "sprites", cid)
    os.makedirs(out_dir, exist_ok=True)
    frames = {}
    for anim in ANIMS:
        sheet, missing = None, []
        for _, tmpl, cmap in layers:
            data = fetch(tmpl.format(anim=anim), cache)
            if data is None:
                missing.append(tmpl.split("/")[2] + "/" + tmpl.split("/")[3])
                continue
            img = recolour(Image.open(io.BytesIO(data)).convert("RGBA"), cmap)
            if sheet is None:
                sheet = Image.new("RGBA", img.size)
            if img.size != sheet.size:  # oversize weapon frames etc.: keep the base grid
                img = img.crop((0, 0, *sheet.size))
            sheet.alpha_composite(img)
        if sheet is None or missing:  # a layer without this animation would leave the character half dressed
            print(f"  {cid}: skipping {anim}, no art in {missing or 'any layer'}", file=sys.stderr)
            continue
        sheet.save(os.path.join(out_dir, anim + ".png"))
        frames[anim] = {"frames": sheet.width // 64, "rows": sheet.height // 64}
    return frames


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", default=os.path.join(HERE, "..", "..", "..", "..", "_assets_dl", "lpc-cache"))
    ap.add_argument("ids", nargs="*")
    a = ap.parse_args()
    cast = {k: v for k, v in json.load(open(os.path.join(HERE, "cast.json"), encoding="utf8")).items() if not k.startswith("_") and not v.get("portrait")}
    manifest, credits = {}, {}
    for cid in a.ids or cast:
        print("building", cid)
        manifest[cid] = {"name": cast[cid]["name"], "anims": build(cid, cast[cid], a.cache, credits)}
    os.makedirs(OUT, exist_ok=True)
    json.dump(manifest, open(os.path.join(OUT, "sprites", "manifest.json"), "w"), indent=1)
    with open(os.path.join(OUT, "CREDITS.csv"), "w", newline="", encoding="utf8") as f:
        w = csv.writer(f)
        w.writerow(["file", "authors", "licenses", "urls", "notes"])
        for c in sorted(credits.values(), key=lambda c: c["file"]):
            w.writerow([c["file"], "; ".join(c["authors"]), "; ".join(c["licenses"]), " ".join(c.get("urls", [])), c.get("notes", "")])
    print("wrote", len(manifest), "characters and", len(credits), "credit entries")


if __name__ == "__main__":
    main()
