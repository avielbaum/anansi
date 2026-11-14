"""Bake town/dungeon pieces, enemies and battle backgrounds into assets/ from the downloaded packs.

python tools/build_tiles.py [--src DIR]   (DIR: the folder holding the downloads; see SOURCES)

LPC tiles are small modular pieces; the game uses whole objects instead (ground textures, a house front, trees,
dungeon walls) placed in code, each with a solid footprint. Credits for everything copied go to assets/CREDITS_TILES.csv.
"""
import colorsys, argparse, csv, os
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "assets")
BASE = "lpc-base/x/LPC Base Assets/tiles/"
# the backdrops that generated cities pick from (city.js BACKDROPS), each by day and by night: name -> file in the pack
BACKDROPS = {}
for _n, _f in {"dunes": 1, "desert": 2, "beach": 3, "snow": 4, "forest": 6, "ruins": 9, "meadow": 10, "castle": 11, "town": 12}.items():
    BACKDROPS[_n + "_night" if _n == "town" else _n] = f"{_f}-night.png" if _n == "town" else f"{_f}.png"
    if _n != "town": BACKDROPS[_n + "_night"] = f"{_f}-night.png"
SOURCES = [  # (folder, pack, authors, licences, url)
    ("lpc-base", "LPC Base Assets", "Lanea Zimmerman (Sharm); Stephen Challener (Redshrike); Charles Sanchez (CharlesGabriel); Manuel Riecke (MrBeast); Daniel Armstrong (HughSpectrum)",
     "CC-BY-SA 3.0; GPL 3.0", "https://opengameart.org/content/liberated-pixel-cup-lpc-base-assets-sprites-map-tiles"),
    ("lpc-battle", "LPC in battle RPG sprites", "Stephen Challener (Redshrike)", "CC-BY-SA 3.0; GPL 3.0",
     "https://opengameart.org/content/lpc-in-battle-rpg-sprites"),
    ("street-tiles", "Street tiles", "curato", "CC0", "https://opengameart.org/content/street-tiles"),
    ("pixelboy-battlebacks", "Battlebacks Pack", "Pixel-boy", "CC0", "https://tale.itch.io/pixel-boy-battlebacks-pack"),
]
ENEMIES = {  # LPC in-battle sheet: name -> top-left of the sprite on the sheet (shadows are dropped)
    "drone_tank": (6, 31), "bat": (94, 20), "wraith": (181, 10), "vine": (15, 111), "sprout": (113, 111),
    "sprout2": (199, 119), "balloon": (102, 159), "slime": (21, 196), "spider_bot": (176, 195), "drill_beast": (76, 254),
    "minotaur_mage": (164, 245), "snake": (9, 285), "worm": (7, 350), "eyeball": (98, 350), "wasp": (184, 349),
}


# Houses are a wall under a roof, each in a few colours, so a city's houses differ (city.js picks from these; keep the names in step with data.js)
ROOFS = {"slate": {}, "terracotta": dict(to=0.04, s=4, v=1.5), "green": dict(to=0.36, s=4, v=1.3), "blue": dict(to=0.58, s=5, v=1.5), "ochre": dict(to=0.11, s=4, v=1.6)}
WALLS = {"brick": {}, "plaster": dict(to=0.1, s=0.25, v=1.7), "sand": dict(to=0.1, s=0.5, v=1.5), "timber": dict(to=0.08, s=0.8, v=0.8), "snow": dict(to=0.58, s=0.15, v=1.9)}


def shift(img, to=None, s=1.0, v=1.0):
    """Move every visible pixel to hue `to` (0-1; None keeps it), scaling its saturation and brightness."""
    img = img.copy()
    px = img.load()
    for y in range(img.height):
        for x in range(img.width):
            r, g, b, a = px[x, y]
            if a:
                h, ss, vv = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
                px[x, y] = tuple(int(c * 255) for c in colorsys.hsv_to_rgb(h if to is None else to, min(1, ss * s), min(1, vv * v))) + (a,)
    return img


def tile(img, cx, cy, w=1, h=1):
    return img.crop((cx * 32, cy * 32, (cx + w) * 32, (cy + h) * 32))


def unwhite(img):
    """White background to transparent, flood-filling only from the edges so white inside a sprite stays."""
    img = img.convert("RGBA")
    px, (w, h) = img.load(), img.size
    stack = [(x, y) for x in range(w) for y in (0, h - 1)] + [(x, y) for y in range(h) for x in (0, w - 1)]
    seen = set()
    while stack:
        x, y = stack.pop()
        if (x, y) in seen or not (0 <= x < w and 0 <= y < h):
            continue
        seen.add((x, y))
        r, g, b, a = px[x, y]
        if r > 245 and g > 245 and b > 245:
            px[x, y] = (0, 0, 0, 0)
            stack += [(x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)]
    return img


def recolour(img, hue=None, sat=1.0, val=1.0):
    """Change an image's hue (PIL scale 0-255; None keeps it), saturation and brightness, keeping its transparency."""
    alpha = img.getchannel("A")
    h, s, v = img.convert("RGB").convert("HSV").split()
    if hue is not None:
        h = h.point(lambda _: hue)
    s, v = s.point(lambda x: min(255, int(x * sat))), v.point(lambda x: min(255, int(x * val)))
    out = Image.merge("HSV", (h, s, v)).convert("RGB").convert("RGBA")
    out.putalpha(alpha)
    return out


def shapes(img, reach=3):
    """Bounding boxes of the opaque shapes, joining pixels up to `reach` apart (so a wasp keeps its stinger)."""
    w, h = img.size
    a = img.getchannel("A").load()
    seen, boxes = set(), []
    for y in range(h):
        for x in range(w):
            if a[x, y] and (x, y) not in seen:
                seen.add((x, y)); st, box = [(x, y)], [x, y, x, y]
                while st:
                    cx, cy = st.pop()
                    box = [min(box[0], cx), min(box[1], cy), max(box[2], cx), max(box[3], cy)]
                    for nx in range(cx - reach, cx + reach + 1):
                        for ny in range(cy - reach, cy + reach + 1):
                            if 0 <= nx < w and 0 <= ny < h and a[nx, ny] and (nx, ny) not in seen:
                                seen.add((nx, ny)); st.append((nx, ny))
                boxes.append(box)
    return [b for b in boxes if b[3] - b[1] >= 12 and b[2] - b[0] >= 12]  # flat blobs are shadows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=os.path.join(HERE, "..", "..", "..", "..", "_assets_dl"))
    src = ap.parse_args().src
    S = lambda p: Image.open(os.path.join(src, p)).convert("RGBA")
    os.makedirs(os.path.join(OUT, "tiles"), exist_ok=True)
    os.makedirs(os.path.join(OUT, "enemies"), exist_ok=True)
    save = lambda im, name: im.save(os.path.join(OUT, name))

    grass, cement, house, top, trunk = (S(BASE + n + ".png") for n in ("grass", "cement", "house", "treetop", "trunk"))
    floors, dungeon, chests = S(BASE + "castlefloors.png"), S(BASE + "dungeon.png"), S(BASE + "chests.png")
    street = S("street-tiles/street.png")

    # ground textures, 32x32
    # grass: plain and tufted tiles in a fixed 4x4 mix, so the repeat is less obvious than one tile
    mix = Image.new("RGBA", (128, 128))
    pattern = ["0100", "0020", "3000", "0001"]  # 0 plain, 1-3 tufts
    for y, row in enumerate(pattern):
        for x, c in enumerate(row):
            mix.alpha_composite(tile(grass, 1, 3) if c == "0" else tile(grass, int(c) - 1, 5), (x * 32, y * 32))
    save(mix, "tiles/grass.png")
    # climate grounds for generated cities: the same grass with its hue, saturation and brightness changed
    save(recolour(mix, hue=28, sat=0.7, val=1.7), "tiles/ground_sand.png")
    save(recolour(mix, hue=150, sat=0.22, val=1.85), "tiles/ground_snow.png")
    save(recolour(mix, hue=62, sat=1.15, val=1.3), "tiles/ground_lush.png")
    save(tile(cement, 1, 3), "tiles/paving.png")
    save(tile(cement, 1, 5), "tiles/flagstone.png")
    save(tile(street, 3, 3), "tiles/road.png")
    save(tile(street, 0, 3), "tiles/road_line.png")
    save(tile(street, 6, 1), "tiles/sidewalk.png")
    save(tile(floors, 6, 6), "tiles/cobble.png")
    save(tile(dungeon, 1, 1), "tiles/brick.png")

    # house front: brick wall (3x3) under a gabled slate roof (3x4); the roof's open tile shows the wall behind
    h = Image.new("RGBA", (96, 192))
    h.alpha_composite(tile(house, 0, 0, 3, 3), (0, 96))
    h.alpha_composite(tile(house, 0, 3, 3, 4), (0, 0))
    h.alpha_composite(tile(house, 3, 0), (32, 160))  # door
    save(h, "tiles/house.png")

    for rn, rk in ROOFS.items():
        for wn, wk in WALLS.items():
            hv = Image.new("RGBA", (96, 192))
            hv.alpha_composite(shift(tile(house, 0, 0, 3, 3), **wk), (0, 96))
            hv.alpha_composite(shift(tile(house, 0, 3, 3, 4), **rk), (0, 0))
            hv.alpha_composite(tile(house, 3, 0), (32, 160))
            save(hv, f"tiles/house_{rn}_{wn}.png")

    # water for the harbours and rivers: LPC's rippling water in three looks; planks for quays and bridges; barrels
    water, bridges, barrels = S(BASE + "water.png"), S(BASE + "bridges.png"), S(BASE + "barrel.png")
    wmix = Image.new("RGBA", (64, 64))
    for i, (cx, cy) in enumerate([(0, 5), (1, 5), (2, 5), (0, 5)]):
        wmix.alpha_composite(tile(water, cx, cy), ((i % 2) * 32, (i // 2) * 32))
    save(wmix, "tiles/water.png")
    save(recolour(wmix, hue=140, sat=0.35, val=1.5), "tiles/water_ice.png")
    save(recolour(wmix, hue=122, sat=0.9, val=1.35), "tiles/water_lagoon.png")
    save(tile(bridges, 0, 3), "tiles/plank.png")
    save(barrels.crop((0, 0, 32, 64)), "tiles/barrel.png")
    save(barrels.crop((64, 0, 128, 64)), "tiles/barrels.png")

    # trees: canopy over trunk
    for name, (cy, ch) in {"tree": (0, 3), "pine": (3, 4)}.items():
        t = Image.new("RGBA", (96, ch * 32 + 64))
        t.alpha_composite(tile(trunk, 0, 0, 3, 3), (0, ch * 32 - 32))
        t.alpha_composite(tile(top, 0, cy, 3, ch), (0, 0))
        save(t, f"tiles/{name}.png")

    save(tile(dungeon, 0, 0, 3, 4), "tiles/dungeon_wall.png")
    save(tile(chests, 0, 0, 1, 1), "tiles/chest.png")
    save(tile(dungeon, 0, 5, 1, 2), "tiles/gate.png")

    # enemies: one pose each, cut from the in-battle sheet, background removed, cropped to content
    sheet = unwhite(S("lpc-battle/sprites1.png"))
    boxes = shapes(sheet)
    assert len(boxes) == len(ENEMIES), f"expected {len(ENEMIES)} enemies on the sheet, found {len(boxes)}"
    for name, (x, y) in ENEMIES.items():
        b = min(boxes, key=lambda b: abs(b[0] - x) + abs(b[1] - y))
        save(sheet.crop((b[0], b[1], b[2] + 1, b[3] + 1)), f"enemies/{name}.png")

    # battle backgrounds, cropped to 640x360
    for name, file in {"town": "12.png", "dungeon": "5-night.png", **BACKDROPS}.items():
        bb = S("pixelboy-battlebacks/x/pb/640x480/" + file)
        save(bb.crop((0, 60, 640, 420)), f"tiles/battle_{name}.png")

    with open(os.path.join(OUT, "CREDITS_TILES.csv"), "w", newline="", encoding="utf8") as f:
        w = csv.writer(f)
        w.writerow(["pack", "authors", "licenses", "url"])
        w.writerows(s[1:] for s in SOURCES)
    print("ok")


if __name__ == "__main__":
    main()
