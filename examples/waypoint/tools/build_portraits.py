"""Build assets/portraits/<id>.png (64x64) for the cast entries marked "portrait": the head and shoulders of the
south-facing walk frame, recoloured by build_sprites.py's helpers and enlarged 2x with no smoothing.

python tools/build_portraits.py [--cache DIR] [id ...]
"""
import argparse, csv, io, json, os
from PIL import Image
import build_sprites as bs

OUT = os.path.join(bs.OUT, "portraits")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", default=os.path.join(bs.HERE, "..", "..", "..", "..", "_assets_dl", "lpc-cache"))
    ap.add_argument("ids", nargs="*")
    a = ap.parse_args()
    cast = {k: v for k, v in json.load(open(os.path.join(bs.HERE, "cast.json"), encoding="utf8")).items() if isinstance(v, dict) and v.get("portrait")}
    os.makedirs(OUT, exist_ok=True)
    credits = {}
    for cid in a.ids or cast:
        spec, layers = cast[cid], []
        for def_path, colour in spec["layers"]:
            d = json.loads(bs.fetch("sheet_definitions/" + def_path, a.cache))
            cmap = bs.palette_map(d["recolors"], colour, a.cache) if "recolors" in d and colour not in d.get("variants", []) else None
            if cmap is None and colour not in d.get("variants", []):
                raise SystemExit(f"{def_path}: no colour {colour!r} (variants: {d.get('variants')})")
            for key in sorted(k for k in d if k.startswith("layer_")):
                base = d[key][spec["body"]]
                tmpl = f"spritesheets/{base}walk/{colour.replace(' ', '_')}.png" if cmap is None else f"spritesheets/{base}walk.png"
                layers.append((d[key]["zPos"], tmpl, cmap))
                for c in d.get("credits", []):
                    credits[(c["file"], tuple(c["authors"]))] = c
        sheet = Image.new("RGBA", (64, 64))
        for _, tmpl, cmap in sorted(layers, key=lambda l: l[0]):
            data = bs.fetch(tmpl, a.cache)
            if data:
                sheet.alpha_composite(bs.recolour(Image.open(io.BytesIO(data)).convert("RGBA"), cmap).crop((0, 128, 64, 192)))  # walk row 3: facing down, frame 1
        sheet.crop((16, 8, 48, 40)).resize((64, 64), Image.NEAREST).save(os.path.join(OUT, cid + ".png"))
        print("built", cid)
    with open(os.path.join(bs.OUT, "CREDITS_PORTRAITS.csv"), "w", newline="", encoding="utf8") as f:
        w = csv.writer(f); w.writerow(["file", "authors", "licenses", "urls"])
        for c in sorted(credits.values(), key=lambda c: c["file"]):
            w.writerow([c["file"], "; ".join(c["authors"]), "; ".join(c["licenses"]), " ".join(c.get("urls", []))])

if __name__ == "__main__":
    main()
