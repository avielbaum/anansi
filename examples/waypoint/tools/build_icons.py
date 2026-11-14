"""Build assets/icons (one 24x24 icon per piece of equipment) from the Ninja Adventure pack (CC0, by Pixel-boy and AAA).

python tools/build_icons.py [--src DIR]   (DIR: the pack's root folder)

tools/icons.json says which picture each piece uses. Weapons are sprites from the pack's Items/Weapons, set on a coloured
square with a dark edge so that they look like the pack's own icons; the rest are its Ui/Skill Icon icons, with their
colours rotated for the higher tiers. CREDITS_ICONS.csv lists every source file.
"""
import argparse, colorsys, csv, json, os
from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "assets", "icons")
PACK = "https://pixel-boy.itch.io/ninja-adventure-asset-pack"
FRAMES = {"orange": (236, 150, 70), "blue": (86, 140, 214), "purple": (126, 96, 196)}


def frame(colour):
    """A 24x24 tile: a dark edge, the colour, and a lighter line along the top and left."""
    r, g, b = FRAMES[colour]
    tile = Image.new("RGBA", (24, 24), (0, 0, 0, 0))
    d = ImageDraw.Draw(tile)
    d.rounded_rectangle((0, 0, 23, 23), radius=3, fill=(int(r * 0.35), int(g * 0.35), int(b * 0.35), 255))
    d.rounded_rectangle((1, 1, 22, 22), radius=2, fill=(r, g, b, 255))
    d.line((3, 1, 20, 1), fill=(min(255, r + 40), min(255, g + 40), min(255, b + 40), 255))
    d.line((1, 3, 1, 20), fill=(min(255, r + 40), min(255, g + 40), min(255, b + 40), 255))
    return tile


def rotate_hue(img, degrees):
    img = img.convert("RGBA")
    px = img.load()
    for y in range(img.height):
        for x in range(img.width):
            r, g, b, a = px[x, y]
            if a:
                h, s, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
                r, g, b = (int(c * 255) for c in colorsys.hsv_to_rgb((h + degrees / 360) % 1, s, v))
                px[x, y] = (r, g, b, a)
    return img


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=os.path.join(HERE, "..", "..", "..", "..", "_assets_dl", "ninja", "x", "Ninja Adventure - Asset Pack"))
    src = ap.parse_args().src
    cfg = {k: v for k, v in json.load(open(os.path.join(HERE, "icons.json"), encoding="utf8")).items() if not k.startswith("_")}
    os.makedirs(OUT, exist_ok=True)
    for f in os.listdir(OUT):
        os.remove(os.path.join(OUT, f))
    credits = []
    for key, spec in cfg.items():
        if "weapon" in spec:
            rel = f"Items/Weapons/{spec['weapon']}/Sprite.png"
            sprite = Image.open(os.path.join(src, rel)).convert("RGBA")
            if sprite.height <= 12:
                sprite = sprite.resize((sprite.width * 2, sprite.height * 2), Image.NEAREST)
            icon = frame(spec["frame"])
            icon.alpha_composite(sprite, ((24 - sprite.width) // 2, (24 - sprite.height) // 2))
        else:
            rel = f"Ui/Skill Icon/{spec.get('dir', 'Items & Weapon')}/{spec['skill']}.png"
            icon = Image.open(os.path.join(src, rel)).convert("RGBA")
            if spec.get("hue"):
                icon = rotate_hue(icon, spec["hue"])
        icon.save(os.path.join(OUT, key + ".png"))
        credits.append([f"icons/{key}.png", rel, "Pixel-boy; AAA", "CC0", PACK])
    with open(os.path.join(OUT, "..", "CREDITS_ICONS.csv"), "w", newline="", encoding="utf8") as f:
        w = csv.writer(f)
        w.writerow(["file", "source file in the pack", "authors", "licence", "url"])
        w.writerows(credits)
    print(f"{len(cfg)} icons")


if __name__ == "__main__":
    main()
