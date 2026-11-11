"""Builds the Anansi logo SVGs (Concept 2, the Story Weaver) from one geometry so every variant matches.
Run: python tools/make_logo.py assets/logo. Outputs go to that directory: anansi-mark.svg, anansi-logo.svg (dark), anansi-logo-light.svg, preview.svg."""
import math
import os
import sys

OUT = sys.argv[1]
os.makedirs(OUT, exist_ok=True)

DARK = dict(bg="#0B1020", gold="#F2C14E", mag="#D043A8", cyan="#4CC9F0", fill="#3A1546", glow=True)
LIGHT = dict(bg="#FFFFFF", gold="#2B1B4A", mag="#2B1B4A", cyan="#2B1B4A", fill="#2B1B4A", glow=False, diamond="#FFFFFF")  # one ink on light backgrounds


def pt(r, deg, cx=100, cy=100):
    a = math.radians(deg)
    return cx + r * math.cos(a), cy + r * math.sin(a)


def web(c):
    """Eight spokes and three sagging rings."""
    s = []
    for k in range(8):
        x, y = pt(88, k * 45 - 90)
        s.append(f'<path d="M100 100L{x:.1f} {y:.1f}" stroke="{c["cyan"]}" stroke-width="1.6" fill="none"/>')
    for r in (30, 52, 76):
        pts = [pt(r, k * 45 - 90) for k in range(8)]
        d = f"M{pts[0][0]:.1f} {pts[0][1]:.1f}"
        for k in range(8):
            nx = pts[(k + 1) % 8]
            mx, my = pt(r * 0.86, k * 45 - 90 + 22.5)  # the thread sags toward the centre between spokes
            d += f"Q{mx:.1f} {my:.1f} {nx[0]:.1f} {nx[1]:.1f}"
        s.append(f'<path d="{d}" stroke="{c["mag"]}" stroke-width="1.6" fill="none"/>')
    return "".join(s)


def spider(c):
    g, m = c["gold"], c["mag"]
    legs = ""
    for side in (-1, 1):  # four legs a side: body, knee, tip
        for (y0, kx, ky, tx, ty) in ((90, 26, 62, 46, 50), (96, 38, 86, 52, 90), (104, 36, 120, 50, 124), (110, 26, 140, 40, 156)):
            x0 = 100 + side * 6
            legs += f'<path d="M{x0} {y0}L{100 + side * kx} {ky}L{100 + side * tx} {ty}" stroke="{g}" stroke-width="3.2" fill="none" stroke-linecap="round" stroke-linejoin="round"/>'
    return ('<g transform="translate(100 105) scale(1.1) translate(-100 -105)">' + legs +
            f'<ellipse cx="100" cy="122" rx="19" ry="25" fill="{c["fill"]}" stroke="{g}" stroke-width="3"/>'
            f'<path d="M100 108L109 122L100 136L91 122Z" fill="{c.get("diamond", m)}" stroke="{g}" stroke-width="2.4"/>'
            f'<circle cx="100" cy="88" r="11" fill="{c["fill"]}" stroke="{g}" stroke-width="3"/>'
            f'<path d="M95 80L93 73M105 80L107 73" stroke="{g}" stroke-width="2.4" stroke-linecap="round"/></g>')


def story_icons(c):
    """A speech bubble (dialogue) and a scroll (quest), each pinned to the web by a thread."""
    g, cy, bg = c["gold"], c["cyan"], c["bg"]
    bubble = (f'<path d="M126 46L150 30" stroke="{cy}" stroke-width="1.6"/><circle cx="126" cy="46" r="3" fill="{cy}"/>'
              f'<path d="M146 12h38a8 8 0 0 1 8 8v20a8 8 0 0 1-8 8h-24l-10 9v-9h-4a8 8 0 0 1-8-8V20a8 8 0 0 1 8-8z" fill="{bg}" stroke="{g}" stroke-width="2.6" stroke-linejoin="round"/>'
              f'<circle cx="153" cy="30" r="2.6" fill="{g}"/><circle cx="165" cy="30" r="2.6" fill="{g}"/><circle cx="177" cy="30" r="2.6" fill="{g}"/>')
    scroll = (f'<path d="M72 150L52 166" stroke="{cy}" stroke-width="1.6"/><circle cx="72" cy="150" r="3" fill="{cy}"/>'
              f'<path d="M14 160h36a4 4 0 0 1 4 4v22a4 4 0 0 1-4 4H20a6 6 0 0 1-6-6z" fill="{bg}" stroke="{g}" stroke-width="2.6" stroke-linejoin="round"/>'
              f'<path d="M22 170h24M22 178h24M22 186h14" stroke="{g}" stroke-width="2.2" stroke-linecap="round"/>')
    return bubble + scroll


def mark(c, glow_id="glow"):
    body = web(c) + spider(c) + story_icons(c)
    return f'<g {"filter=%s" % chr(34) + "url(#" + glow_id + ")" + chr(34) if c["glow"] else ""}>{body}</g>'


GLOW = '<filter id="glow" x="-20%" y="-20%" width="140%" height="140%"><feGaussianBlur stdDeviation="2.2" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>'


def word(c):
    """ANANSI as drawn strokes (no font needed, so it looks the same everywhere). Letters are 40 wide, 56 tall."""
    L = {"A": "M0 56L20 0L40 56M8 38H32", "N": "M0 56V0L40 56V0",
         "S": "M37 12C30 0 6 0 3 15C0 30 37 26 37 42C37 58 8 58 0 46", "I": "M12 0H28M20 0V56M12 56H28"}
    x, out = 0, []
    for ch in "ANANSI":
        off = -12 if ch == "I" else 0  # the I is only 16 wide: draw it flush left so spacing looks even
        out.append(f'<path d="{L[ch]}" transform="translate({x + off} 0)" stroke="{c["gold"]}" stroke-width="7" fill="none" stroke-linecap="butt" stroke-linejoin="bevel"/>')
        x += 54
    return "".join(out)  # total width about 262


def svg(w, h, inner, c, bg=True, defs=""):
    r = f'<rect width="{w}" height="{h}" rx="{min(w, h) * 0.04:.0f}" fill="{c["bg"]}"/>' if bg else ""
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}" role="img" aria-label="Anansi">{("<defs>" + defs + "</defs>") if defs else ""}{r}{inner}</svg>\n'


def full(c, bg=True):
    inner = (f'<g transform="translate(70 14) scale(1.3)">{mark(c)}</g>'
             f'<g transform="translate(57 300)">{word(c)}</g>'
             f'<text x="200" y="392" text-anchor="middle" font-family="system-ui,Segoe UI,Helvetica,Arial,sans-serif" font-size="17" letter-spacing="3.4" fill="{c["gold"]}">STORY &amp; QUEST ENGINE</text>')
    return svg(400, 412, inner, c, bg, GLOW if c["glow"] else "")


def only_mark(c, bg=True):
    return svg(200, 200, f'<g transform="translate(0 0)">{mark(c)}</g>', c, bg, GLOW if c["glow"] else "")


def icon(c):
    """For 16 to 48 px: fewer web lines, thick strokes, no side icons."""
    g, m, cy = c["gold"], c["mag"], c["cyan"]
    web_ = "".join(f'<path d="M100 100L{pt(90, k * 45 - 90)[0]:.0f} {pt(90, k * 45 - 90)[1]:.0f}" stroke="{cy}" stroke-width="6"/>' for k in range(8))
    ring = f'<circle cx="100" cy="100" r="62" fill="none" stroke="{m}" stroke-width="6"/>'
    legs = "".join(f'<path d="M{100 + s_ * 8} {y}L{100 + s_ * 62} {ky}L{100 + s_ * 52} {ty}" stroke="{g}" stroke-width="12" fill="none" stroke-linecap="round" stroke-linejoin="round"/>'
                   for s_ in (-1, 1) for (y, ky, ty) in ((88, 56, 30), (100, 92, 78), (110, 128, 142), (118, 160, 176)))
    body = f'<ellipse cx="100" cy="116" rx="26" ry="34" fill="{c["fill"] if c["fill"] != "none" else g}" stroke="{g}" stroke-width="8"/><circle cx="100" cy="76" r="16" fill="{c["fill"]}" stroke="{g}" stroke-width="8"/>'
    return f'<g>{web_}{ring}{legs}{body}</g>'




def write(name, s):
    open(os.path.join(OUT, name), "w", encoding="utf-8", newline="\n").write(s)


write("anansi-favicon.svg", svg(200, 200, icon(DARK), DARK))
write("anansi-mark.svg", only_mark(DARK))
write("anansi-logo.svg", full(DARK))
write("anansi-logo-light.svg", full(LIGHT))

# a preview sheet: dark and light logos, and the mark at the sizes people actually see it
def small(c, size, x, y):
    flat = dict(c, glow=False)
    pic = mark(flat) if size >= 64 else icon(flat)
    return f'<g transform="translate({x} {y}) scale({size / 200:.3f})">{"" if c["bg"] == "none" else ""}<rect width="200" height="200" rx="24" fill="{c["bg"]}"/>{pic}</g>'


def place(markup, x, y):
    return markup.replace("<svg", f'<svg x="{x}" y="{y}"', 1)


sheet = (place(full(DARK), 20, 20) + place(full(LIGHT), 450, 20)
         + '<text x="20" y="460" font-family="system-ui,sans-serif" font-size="14" fill="#8890a8">Mark at 128, 64, 32 and 16 px (dark, then light)</text>'
         + small(DARK, 128, 20, 475) + small(DARK, 64, 170, 475) + small(DARK, 32, 250, 475) + small(DARK, 16, 300, 475)
         + small(LIGHT, 128, 450, 475) + small(LIGHT, 64, 600, 475) + small(LIGHT, 32, 680, 475) + small(LIGHT, 16, 730, 475))
write("preview.svg", f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 630" width="880" height="630"><rect width="880" height="630" fill="#1a1f33"/>{sheet}</svg>\n')
print("ok", os.listdir(OUT))
