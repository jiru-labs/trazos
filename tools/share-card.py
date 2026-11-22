#!/usr/bin/env python3
"""Make the picture a shared link to the archive shows (Open Graph, 1200x630).

A bare drawing in a WhatsApp or Telegram preview reads as a link to an image. This card
says what the link is: the archive's title, a line under it, and up to three drawings
pinned like paper on the archive's own colours.

Needs ImageMagick 7 (`magick`). It runs where you have it, not in the site build, which
stays standard-library Python. Save the result as `site/share.jpg` (or `site/share-<lang>.jpg`
for one language); build.py then uses it for the archive pages, while each piece's own page
keeps its drawing.

    python3 tools/share-card.py SITE_DIR --pieces ID ID ID --title "The art of Ada" \\
        --line "Drawings, 2019 to 2024" -o SITE_DIR/site/share.jpg
"""
import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

W, H = 1200, 630
BG, FG, MUTED, CARD = "#faf6ee", "#2e2a26", "#6f655c", "#fffdf8"
STRIPES = ["#c2462a", "#e9a91f", "#2f6fa8", "#3f8a4f", "#7d4a92"]
# Where each pinned drawing sits: centre x, centre y, box it fits in, tilt in degrees.
SLOTS = [(890, 340, 440, 370, -3), (1085, 140, 240, 200, 7), (700, 505, 250, 200, -6)]
FONT_BOLD, FONT = "DejaVu-Sans-Bold", "DejaVu-Sans"


def magick(*args):
    subprocess.run(["magick", *map(str, args)], check=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("site", type=Path, help="the archive folder (with pieces/)")
    ap.add_argument("--pieces", nargs="+", required=True, help="1-3 piece ids; the first is the big one")
    ap.add_argument("--title", required=True)
    ap.add_argument("--line", default="", help="the smaller line under the title")
    ap.add_argument("--domain", default="", help="shown at the bottom left, e.g. art.example.org")
    ap.add_argument("-o", "--out", type=Path, required=True)
    a = ap.parse_args()
    if not 1 <= len(a.pieces) <= 3:
        sys.exit("share-card: give 1 to 3 piece ids")

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        stripe = W // len(STRIPES)
        draw = [f"fill {c} rectangle {i * stripe},{H - 14} {(i + 1) * stripe},{H}" for i, c in enumerate(STRIPES)]
        cmd = ["-size", f"{W}x{H}", f"xc:{BG}", "-draw", " ".join(draw)]
        # Smaller drawings first, so the big one lies on top.
        for n in reversed(range(len(a.pieces))):
            src = a.site / "pieces" / f"{a.pieces[n]}.jpg"
            if not src.exists():
                sys.exit(f"share-card: no {src}")
            x, y, bw, bh, tilt = SLOTS[n]
            pinned = tmp / f"p{n}.png"
            pad = max(8, bw // 30)
            magick(src, "-resize", f"{bw - 2 * pad}x{bh - 2 * pad}", "-bordercolor", CARD, "-border", pad,
                   "-background", "none", "-rotate", tilt,
                   "(", "+clone", "-background", "#00000040", "-shadow", "60x6+0+5", ")",
                   "+swap", "-background", "none", "-layers", "merge", "+repage", pinned)
            cmd += ["(", pinned, ")", "-gravity", "center", "-geometry", f"{x - W // 2:+d}{y - H // 2:+d}",
                    "-composite"]
        cmd += ["-gravity", "northwest", "-fill", FG, "-font", FONT_BOLD]
        text = tmp / "title.png"
        magick("-background", "none", "-fill", FG, "-font", FONT_BOLD, "-size", "560x", "-pointsize", 64,
               f"caption:{a.title}", text)
        cmd += ["(", text, ")", "-geometry", "+64+150", "-composite"]
        if a.line:
            line = tmp / "line.png"
            magick("-background", "none", "-fill", MUTED, "-font", FONT, "-size", "540x", "-pointsize", 32,
                   f"caption:{a.line}", line)
            title_h = int(subprocess.run(["magick", "identify", "-format", "%h", text], capture_output=True,
                                         text=True, check=True).stdout)
            cmd += ["(", line, ")", "-geometry", f"+66+{150 + title_h + 24}", "-composite"]
        if a.domain:
            cmd += ["-font", FONT, "-fill", MUTED, "-pointsize", 26, "-annotate", "+66+540", a.domain]
        a.out.parent.mkdir(parents=True, exist_ok=True)
        magick(*cmd, "-strip", "-quality", 85, a.out)
    print(f"share-card: {a.out} ({a.out.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
