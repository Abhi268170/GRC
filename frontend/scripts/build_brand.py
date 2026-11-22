"""Build TrustUp logo SVGs (wordmark converted to outlines) in the app's palette.

Usage (from frontend/):
  curl -sL -o /tmp/SpaceGrotesk.ttf "https://github.com/google/fonts/raw/main/ofl/spacegrotesk/SpaceGrotesk%5Bwght%5D.ttf"
  uv run --python 3.13 --with fonttools python -I scripts/build_brand.py /tmp/SpaceGrotesk.ttf /tmp/brand-out
Then copy /tmp/brand-out/trustup-*.svg to public/brand/, trustup-app-icon-small.svg to src/app/icon.svg,
and regenerate src/components/app/brand-paths.ts from /tmp/brand-out/paths.json.
Colours mirror frontend/src/app/globals.css; update both together.
Space Grotesk is licensed under the SIL Open Font License 1.1.
"""
import json, math, sys
from fontTools.ttLib import TTFont
from fontTools.varLib.instancer import instantiateVariableFont
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen

font_path, out = sys.argv[1], sys.argv[2]
font = instantiateVariableFont(TTFont(font_path), {"wght": 700})
upm = font["head"].unitsPerEm
gs, cmap, hmtx = font.getGlyphSet(), font.getBestCmap(), font["hmtx"]
asc, desc = font["hhea"].ascent, font["hhea"].descent  # desc is negative

F = 50.0                      # wordmark font size (design's small lockup)
LS = -2.0                     # letter-spacing at that size (design: -2px @ 50px)
s = F / upm

def word_paths(text, x0):
    """Return (path_d, x_after) for text starting at x0; baseline y computed below."""
    pen = SVGPathPen(gs)
    x = x0
    for ch in text:
        g = cmap[ord(ch)]
        tp = TransformPen(pen, (s, 0, 0, -s, x, BASE))  # flip y, scale to F
        gs[g].draw(tp)
        x += hmtx[g][0] * s + LS
    return pen.getCommands(), x

# CSS line-height:1 box of height F; baseline sits where the content area is centred in it.
content = (asc - desc) * s
BASE_IN_BOX = (F - content) / 2 + asc * s
MARK = 1.2 * F               # 60px mark for 50px text, as in the design
GAP = 0.2 * F                # 10px gap
H = max(MARK, F)
BOX_TOP = (H - F) / 2
BASE = BOX_TOP + BASE_IN_BOX
TX = MARK + GAP
trust_d, x_mid = word_paths("trust", TX)
up_d, x_end = word_paths("up", x_mid)
W = x_end - LS               # no trailing letter-spacing

def oklch_hex(L, C, h):
    a, b = C * math.cos(math.radians(h)), C * math.sin(math.radians(h))
    l_, m_, s_ = L + .3963377774*a + .2158037573*b, L - .1055613458*a - .0638541728*b, L - .0894841775*a - 1.2914855480*b
    l, m, s3 = l_**3, m_**3, s_**3
    rgb = (4.0767416621*l - 3.3077115913*m + .2309699292*s3, -1.2684380046*l + 2.6097574011*m - .3413193965*s3, -.0041960863*l - .7034186147*m + 1.7076147010*s3)
    f = lambda c: max(0, min(1, 12.92*c if c <= .0031308 else 1.055*c**(1/2.4) - .055))
    return "#%02X%02X%02X" % tuple(round(f(c)*255) for c in rgb)

# App palette (frontend/src/app/globals.css)
INK = oklch_hex(0.17, 0, 0)               # --primary (light)
OFF = oklch_hex(0.96, 0, 0)               # --primary (dark) / off-white
LIME = oklch_hex(0.85, 0.2, 145)          # --brand
STRONG = oklch_hex(0.52, 0.15, 145)       # --brand-strong (new): lime family, readable on white

MARK_INNER = '<g transform="rotate(-45 32 32)"><rect x="5" y="23" width="32" height="18" rx="9" fill="none" stroke="{a}" stroke-width="{w}"/><rect x="27" y="23" width="32" height="18" rx="9" fill="none" stroke="{b}" stroke-width="{w}"/></g>'

def r(v): return f"{v:.2f}".rstrip("0").rstrip(".")

def lockup(name, link1, link2, trust, up, title):
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {r(W)} {r(H)}" width="{r(W)}" height="{r(H)}" role="img" aria-label="{title}">'
           f'<title>{title}</title>'
           f'<svg x="0" y="{r((H-MARK)/2)}" width="{r(MARK)}" height="{r(MARK)}" viewBox="0 0 64 64">{MARK_INNER.format(a=link1, b=link2, w=5.5)}</svg>'
           f'<path fill="{trust}" d="{trust_d}"/><path fill="{up}" d="{up_d}"/></svg>')
    open(f"{out}/{name}", "w").write(svg)

def mark(name, link1, link2, title):
    open(f"{out}/{name}", "w").write(
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" width="64" height="64" role="img" aria-label="{title}"><title>{title}</title>{MARK_INNER.format(a=link1, b=link2, w=5.5)}</svg>')

def icon(name, stroke):
    open(f"{out}/{name}", "w").write(
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" width="100" height="100" role="img" aria-label="TrustUp"><title>TrustUp</title>'
        f'<rect width="100" height="100" rx="23" fill="{INK}"/><g transform="translate(18 18)">{MARK_INNER.format(a=OFF, b=LIME, w=stroke)}</g></svg>')

lockup("trustup-logo-light.svg", INK, LIME, INK, STRONG, "TrustUp")   # on white / light backgrounds
lockup("trustup-logo-dark.svg", OFF, LIME, OFF, LIME, "TrustUp")      # on ink / dark backgrounds
lockup("trustup-logo-lime.svg", INK, OFF, INK, INK, "TrustUp")        # on lime backgrounds
mark("trustup-mark-light.svg", INK, LIME, "TrustUp")
mark("trustup-mark-dark.svg", OFF, LIME, "TrustUp")
mark("trustup-mark-lime.svg", INK, OFF, "TrustUp")
icon("trustup-app-icon.svg", 5.5)        # 120px+ uses
icon("trustup-app-icon-small.svg", 7)    # favicon / small sizes (thicker strokes, as in the design)

json.dump({"width": W, "height": H, "mark": MARK, "markY": (H - MARK) / 2, "trust": trust_d, "up": up_d,
           "colors": {"ink": INK, "off": OFF, "lime": LIME, "strong": STRONG}}, open(f"{out}/paths.json", "w"))
print(json.dumps({"W": round(W, 2), "H": H, "colors": {"ink": INK, "off": OFF, "lime": LIME, "strong": STRONG}}))
