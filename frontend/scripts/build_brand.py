"""Build every TrustUp logo file from the designer's source SVG.

Source: scripts/brand/trustup-logo-source.svg (the stacked logo: the "tu" mark with a tick,
above the "trustup" wordmark). This script takes the mark and the wordmark out of it and writes:

- public/brand/trustup-mark.svg                         the mark on its own
- public/brand/trustup-logo-{light,dark}.svg            mark left, wordmark right (headers)
- public/brand/trustup-logo-stacked-{light,dark}.svg    mark above wordmark (as designed)
- public/brand/trustup-app-icon.svg                     the mark on a white rounded square
- src/app/icon.svg                                      favicon (the same, mark slightly larger)
- src/components/app/brand-paths.ts                     the same shapes for the <Logo> component

"light" files are for light backgrounds, "dark" files for dark ones. The mark's colours never
change. The wordmark is the source's pale green on dark backgrounds; that is too faint on white,
so on light backgrounds it takes the mark's dark green.

Usage (from frontend/, standard library only):  python3 scripts/build_brand.py
Then, for the Apple touch icon (a PNG), render public/brand/trustup-app-icon.svg at 180x180
to src/app/apple-icon.png.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "scripts/brand/trustup-logo-source.svg"
BRAND = ROOT / "public/brand"

# The app icon's tile is white: on a dark tile the mark's dark green arm almost disappears at favicon size.
ICON_BACKGROUND = "#FFFFFF"
WORDMARK_ON_DARK = None    # taken from the source
WORDMARK_ON_LIGHT = None   # the mark's darkest green, taken from the source


def hex_of(fill: str) -> str:
    r, g, b = (int(v) for v in re.match(r"rgb\((\d+),(\d+),(\d+)\)", fill).groups())
    return f"#{r:02X}{g:02X}{b:02X}"


def groups(svg: str) -> list[dict]:
    """The source nests one <svg viewBox> per part; each holds a <g> of filled paths."""
    out = []
    for view_box, body in re.findall(r'viewBox="([\d. -]+)" preserveAspectRatio="none"><g[^>]*>(.*?)</g>', svg, flags=re.S):
        x, y, w, h = (float(v) for v in view_box.split())
        paths = [(hex_of(fill), " ".join(d.split())) for fill, d in re.findall(r'fill="(rgb\([^"]+\))" d="([^"]+)"', body)]
        out.append({"x": x, "y": y, "w": w, "h": h, "paths": paths})
    return out


parts = groups(SOURCE.read_text())
assert len(parts) == 2, "expected the wordmark and the mark"
wordmark, mark = sorted(parts, key=lambda p: len({fill for fill, _ in p["paths"]}))  # the wordmark has one colour
WORDMARK_ON_DARK = wordmark["paths"][0][0]
# Darkest colour of the mark: lowest sum of channels.
WORDMARK_ON_LIGHT = min((fill for fill, _ in mark["paths"]), key=lambda c: sum(int(c[i:i + 2], 16) for i in (1, 3, 5)))


def n(v: float) -> str:
    return f"{v:.2f}".rstrip("0").rstrip(".")


def mark_group(x: float, y: float, height: float) -> tuple[str, float]:
    """The mark drawn `height` tall with its top-left corner at (x, y). Returns (svg, width)."""
    k = height / mark["h"]
    body = "".join(f'<path fill="{fill}" d="{d}"/>' for fill, d in mark["paths"])
    return f'<g transform="translate({n(x - mark["x"] * k)} {n(y - mark["y"] * k)}) scale({k:.5f})">{body}</g>', mark["w"] * k


def wordmark_group(x: float, y: float, height: float, fill: str) -> tuple[str, float]:
    k = height / wordmark["h"]
    body = "".join(f'<path d="{d}"/>' for _, d in wordmark["paths"])
    return f'<g fill="{fill}" transform="translate({n(x - wordmark["x"] * k)} {n(y - wordmark["y"] * k)}) scale({k:.5f})">{body}</g>', wordmark["w"] * k


def svg(width: float, height: float, body: str) -> str:
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {n(width)} {n(height)}" width="{n(width)}" height="{n(height)}" '
            f'role="img" aria-label="TrustUp"><title>TrustUp</title>{body}</svg>\n')


# ---- horizontal lock-up. H is the wordmark's full height (top of the "t" to the bottom of the "p").
# The mark starts level with the top of the "t" and ends just below the baseline, so it sits with
# the letters, not with the tail of the "p". The gap is a fifth of the height.
H = 100.0
GAP = 0.2 * H
MARK_H = 0.86 * H
m, mark_w = mark_group(0, 0, MARK_H)
HORIZONTAL_W = mark_w + GAP + wordmark["w"] * (H / wordmark["h"])


def horizontal(fill: str) -> str:
    w, _ = wordmark_group(mark_w + GAP, 0, H, fill)
    return svg(HORIZONTAL_W, H, m + w)


# ---- stacked lock-up: proportions of the source (mark above, wordmark below, centred)
def stacked(fill: str) -> str:
    text_h = 100.0
    text_w = wordmark["w"] * text_h / wordmark["h"]
    mark_h = text_h * 194 / 136          # the source draws the mark 194 high over a 136 high wordmark
    gap = text_h * 48 / 136              # and leaves 48 between them
    mk, mw = mark_group((text_w - mark["w"] * mark_h / mark["h"]) / 2, 0, mark_h)
    w, _ = wordmark_group(0, mark_h + gap, text_h, fill)
    return svg(text_w, mark_h + gap + text_h, mk + w)


def app_icon(mark_width: float) -> str:
    """The mark centred on a white rounded square, 100 x 100."""
    height = mark_width * mark["h"] / mark["w"]
    mk, _ = mark_group((100 - mark_width) / 2, (100 - height) / 2, height)
    return svg(100, 100, f'<rect width="100" height="100" rx="23" fill="{ICON_BACKGROUND}"/>{mk}')


BRAND.mkdir(parents=True, exist_ok=True)
for old in BRAND.glob("trustup-*.svg"):
    old.unlink()
(BRAND / "trustup-mark.svg").write_text(svg(mark["w"] * 100 / mark["h"], 100, mark_group(0, 0, 100)[0]))
(BRAND / "trustup-logo-light.svg").write_text(horizontal(WORDMARK_ON_LIGHT))
(BRAND / "trustup-logo-dark.svg").write_text(horizontal(WORDMARK_ON_DARK))
(BRAND / "trustup-logo-stacked-light.svg").write_text(stacked(WORDMARK_ON_LIGHT))
(BRAND / "trustup-logo-stacked-dark.svg").write_text(stacked(WORDMARK_ON_DARK))
(BRAND / "trustup-app-icon.svg").write_text(app_icon(62))
(ROOT / "src/app/icon.svg").write_text(app_icon(70))  # small sizes: a little less margin

# ---- the same shapes for the React component. Its two wordmark colours are written out in
# src/components/app/logo.tsx (Tailwind needs them as literal class names): keep them equal to
# WORDMARK_ON_LIGHT and WORDMARK_ON_DARK, which this script prints.
mark_k, word_k = MARK_H / mark["h"], H / wordmark["h"]
ts = f'''// Generated by scripts/build_brand.py from scripts/brand/trustup-logo-source.svg.
// Regenerate rather than hand-edit. Static SVG files live in public/brand/.

export const LOGO_WIDTH = {n(HORIZONTAL_W)};
export const LOGO_HEIGHT = {n(H)};
export const MARK_TRANSFORM = "translate({n(-mark["x"] * mark_k)} {n(-mark["y"] * mark_k)}) scale({mark_k:.5f})";
export const WORDMARK_TRANSFORM = "translate({n(mark_w + GAP - wordmark["x"] * word_k)} {n(-wordmark["y"] * word_k)}) scale({word_k:.5f})";
export const MARK_PATHS: {{ fill: string; d: string }}[] = {json.dumps([{"fill": f, "d": d} for f, d in mark["paths"]], indent=2)};
export const WORDMARK_PATHS: string[] = {json.dumps([d for _, d in wordmark["paths"]], indent=2)};
'''
(ROOT / "src/components/app/brand-paths.ts").write_text(ts)
print(json.dumps({"mark colours": sorted({f for f, _ in mark["paths"]}), "wordmark on dark": WORDMARK_ON_DARK,
                  "wordmark on light": WORDMARK_ON_LIGHT, "horizontal": [round(HORIZONTAL_W, 1), H]}))
