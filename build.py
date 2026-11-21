#!/usr/bin/env python3
"""trazos: build a static, private-by-design art archive from a content folder.

    python3 build.py [CONTENT_DIR]          (default: the current directory)

CONTENT_DIR holds:
  trazos.toml            site settings (see example/trazos.toml)
  pieces/<id>.md         front matter + the story in the artist's words
  pieces/<id>.jpg        web version (long side 1600 px, metadata stripped)
  pieces/<id>-thumb.jpg  grid version (long side 600 px)
  site/                  optional extra static files (CNAME, favicon...), copied last

Output goes to CONTENT_DIR/public. Standard library only (Python 3.11+).
"""
import html
import re
import shutil
import sys
import tomllib
from pathlib import Path

ENGINE = Path(__file__).resolve().parent
ASSETS = ENGINE / "assets"

FIELDS = ("id", "year", "order", "age", "technique", "title", "tags", "favourite")
# Hand-made ids look like 2026-001; tools/ingest.py uses a short content hash.
ID_RE = re.compile(r"^(\d{4}-\d{3}|[0-9a-f]{10})$")
AGE_RE = re.compile(r"^(\d+)(?:\s*[-–]\s*(\d+))?$")

STRINGS = {
    "es": {
        "by_year": "Por año", "tags": "Etiquetas", "favourites": "Favoritos",
        "untitled": "Sin título", "empty": "Todavía no hay obras aquí. Pronto.",
        "no_tags": "Sin etiquetas todavía.", "no_favs": "Sin favoritos todavía.",
        "age_one": "{n} año", "age_many": "{n} años", "and": " y ",
        "ages_many": "{list} años", "default_title": "Las obras de {artist}",
    },
    "en": {
        "by_year": "By year", "tags": "Tags", "favourites": "Favourites",
        "untitled": "Untitled", "empty": "No pieces here yet. Soon.",
        "no_tags": "No tags yet.", "no_favs": "No favourites yet.",
        "age_one": "age {n}", "age_many": "age {n}", "and": " and ",
        "ages_many": "ages {list}", "default_title": "The art of {artist}",
    },
}
# Page slugs stay ASCII and language-neutral so URLs never change with `lang`.
TAGS_PAGE, FAVS_PAGE = "tags.html", "favourites.html"


def fail(msg):
    raise SystemExit(f"trazos: {msg}")


def load_config(root):
    path = root / "trazos.toml"
    if not path.exists():
        fail(f"{path} not found (copy example/trazos.toml)")
    cfg = tomllib.loads(path.read_text(encoding="utf-8"))
    if not cfg.get("artist"):
        fail("trazos.toml: `artist` is required")
    cfg.setdefault("lang", "es")
    if cfg["lang"] not in STRINGS:
        fail(f"trazos.toml: lang must be one of {', '.join(STRINGS)}")
    cfg.setdefault("noindex", True)
    t = STRINGS[cfg["lang"]]
    cfg.setdefault("title", t["default_title"].format(artist=cfg["artist"]))
    return cfg


def has_metadata(img):
    """True if a JPEG still has an EXIF or XMP segment. A built site must never leak them."""
    data = img.read_bytes()
    if data[:2] != b"\xff\xd8":
        fail(f"{img.name}: not a JPEG")
    i = 2
    while i + 4 <= len(data) and data[i] == 0xFF:
        marker = data[i + 1]
        if marker == 0xDA:  # start of scan: no more metadata segments
            return False
        length = int.from_bytes(data[i + 2:i + 4], "big")
        seg = data[i + 4:i + 2 + length]
        if marker == 0xE1 and (seg.startswith(b"Exif\0") or seg.startswith(b"http://ns.adobe.com/xap")):
            return True
        i += 2 + length
    return False


def parse(path, pieces_dir):
    text = path.read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---\n?(.*)$", text, re.S)
    if not m:
        fail(f"{path.name}: missing front matter")
    meta = {}
    for line in m.group(1).splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        key, _, value = line.partition(":")
        key, value = key.strip(), value.strip().strip('"')
        if key not in FIELDS:
            fail(f"{path.name}: unknown field {key!r}")
        meta[key] = value
    for key in ("id", "year"):
        if not meta.get(key):
            fail(f"{path.name}: {key} is required")
    if meta["id"] != path.stem or not ID_RE.match(meta["id"]):
        fail(f"{path.name}: id {meta['id']!r} must match the file name and look like 2026-001")
    for suffix in (".jpg", "-thumb.jpg"):
        img = pieces_dir / f"{path.stem}{suffix}"
        if not img.exists():
            fail(f"{path.name}: {img.name} is missing")
        if has_metadata(img):
            fail(f"{img.name}: still carries EXIF/XMP metadata (GPS, camera, date); run tools/prepare.sh")
    meta["year"] = int(meta["year"])
    if meta.get("age"):
        m_age = AGE_RE.match(meta["age"])
        if not m_age:
            fail(f"{path.name}: age must be a whole number or a range like 3-4")
        lo, hi = int(m_age.group(1)), int(m_age.group(2) or m_age.group(1))
        meta["age"] = str(lo) if lo == hi else f"{lo}–{hi}"
        meta["age_span"] = list(range(lo, hi + 1))
    if meta.get("order") and not meta["order"].isdigit():
        fail(f"{path.name}: order must be a whole number")
    meta["order"] = int(meta.get("order") or 0)
    meta["tags"] = [t.strip().lower() for t in meta.get("tags", "").split(",") if t.strip()]
    meta["favourite"] = meta.get("favourite", "").lower() in ("yes", "sí", "si", "true")
    meta["story"] = [p.strip() for p in m.group(2).strip().split("\n\n") if p.strip()]
    return meta


def slug(t):
    return re.sub(r"[^\w-]+", "-", t, flags=re.U).strip("-")


def e(s):
    return html.escape(str(s), quote=True)


class Site:
    def __init__(self, cfg):
        self.cfg = cfg
        self.t = STRINGS[cfg["lang"]]

    def age(self, n):
        """'5' -> '5 años' / 'age 5'; '3–4' -> '3–4 años' / 'ages 3–4'."""
        if not str(n).isdigit():
            return self.t["ages_many"].format(list=n)
        n = int(n)
        return self.t["age_one" if n == 1 else "age_many"].format(n=n)

    def ages(self, ages):
        """[5] -> '5 años' / 'age 5'; [5, 6] -> '5 y 6 años' / 'ages 5 and 6'."""
        if len(ages) == 1:
            return self.age(ages[0])
        joined = ", ".join(map(str, ages[:-1])) + self.t["and"] + str(ages[-1])
        return self.t["ages_many"].format(list=joined)

    def page(self, title, body, depth=0):
        up = "../" * depth
        robots = ('<meta name="robots" content="noindex, noimageindex, noai, noimageai">\n'
                  if self.cfg["noindex"] else "")
        t = self.t
        return f"""<!doctype html>
<html lang="{e(self.cfg['lang'])}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
{robots}<meta http-equiv="Content-Security-Policy" content="default-src 'self'; img-src 'self'; style-src 'self'; script-src 'none'; base-uri 'none'; form-action 'none'">
<meta name="referrer" content="no-referrer">
<meta name="generator" content="trazos">
<title>{e(title)}</title>
<link rel="stylesheet" href="{up}style.css">
</head>
<body>
<header>
<a class="home" href="{up}index.html">{e(self.cfg['title'])}</a>
<nav><a href="{up}index.html">{t['by_year']}</a><a href="{up}{TAGS_PAGE}">{t['tags']}</a><a href="{up}{FAVS_PAGE}">{t['favourites']}</a></nav>
</header>
<main>
{body}
</main>
</body>
</html>
"""

    def grid(self, items, depth=0):
        up = "../" * depth
        cards = []
        for p in items:
            label = p.get("title") or self.t["untitled"]
            cards.append(
                f'<a class="card" href="{up}piece/{e(p["id"])}.html">'
                f'<img src="{up}img/{e(p["id"])}-thumb.jpg" alt="{e(label)}" loading="lazy">'
                f'<span>{e(label)}</span></a>'
            )
        return '<div class="grid">' + "".join(cards) + "</div>"


def build(root):
    root = root.resolve()
    cfg = load_config(root)
    site = Site(cfg)
    t = site.t
    pieces_dir, out = root / "pieces", root / "public"
    pieces = sorted((parse(p, pieces_dir) for p in pieces_dir.glob("*.md")), key=lambda p: (p["year"], p["order"], p["id"]))

    if out.exists():
        shutil.rmtree(out)
    for d in ("piece", "tag", "img"):
        (out / d).mkdir(parents=True)
    shutil.copy(ASSETS / "style.css", out / "style.css")
    (out / ".nojekyll").write_text("")
    if cfg["noindex"]:
        (out / "robots.txt").write_text("User-agent: *\nDisallow: /\n")
    for p in pieces:
        for suffix in (".jpg", "-thumb.jpg"):
            shutil.copy(pieces_dir / f"{p['id']}{suffix}", out / "img" / f"{p['id']}{suffix}")
    extra = root / "site"
    if extra.is_dir():
        shutil.copytree(extra, out, dirs_exist_ok=True)

    write = lambda rel, html_: (out / rel).write_text(html_, encoding="utf-8")

    # Timeline, newest year first
    if pieces:
        parts = []
        for year in sorted({p["year"] for p in pieces}, reverse=True):
            items = [p for p in pieces if p["year"] == year]
            ages = sorted({a for p in items for a in p.get("age_span", [])})
            sub = f" <small>({e(site.ages(ages))})</small>" if ages else ""
            parts.append(f'<section><h2 id="y{year}">{year}{sub}</h2>{site.grid(items)}</section>')
        body = "\n".join(parts)
    else:
        body = f'<p class="empty">{t["empty"]}</p>'
    write("index.html", site.page(cfg["title"], body))

    for p in pieces:
        label = p.get("title") or t["untitled"]
        facts = " · ".join(x for x in (str(p["year"]), site.age(p["age"]) if p.get("age") else "",
                                       p.get("technique", "")) if x)
        tags = "".join(f'<a href="../tag/{e(slug(x))}.html">{e(x)}</a>' for x in p["tags"])
        story = "".join(f"<p>{e(s)}</p>" for s in p["story"])
        body = (
            f'<article class="piece"><img src="../img/{e(p["id"])}.jpg" alt="{e(label)}">'
            f"<h1>{e(label)}{' ★' if p['favourite'] else ''}</h1><p class=\"facts\">{e(facts)}</p>"
            f"{story}<p class=\"tags\">{tags}</p></article>"
        )
        write(f"piece/{p['id']}.html", site.page(label, body, 1))

    tags = sorted({x for p in pieces for x in p["tags"]})
    for x in tags:
        items = [p for p in pieces if x in p["tags"]]
        write(f"tag/{slug(x)}.html", site.page(x, f"<h1>{e(x)}</h1>{site.grid(items, 1)}", 1))
    links = "".join(
        f'<a href="tag/{e(slug(x))}.html">{e(x)} <small>{sum(x in p["tags"] for p in pieces)}</small></a>'
        for x in tags) or f'<span class="empty">{t["no_tags"]}</span>'
    write(TAGS_PAGE, site.page(t["tags"], f'<h1>{t["tags"]}</h1><p class="tags">{links}</p>'))

    favs = [p for p in pieces if p["favourite"]]
    body = site.grid(favs) if favs else f'<p class="empty">{t["no_favs"]}</p>'
    write(FAVS_PAGE, site.page(t["favourites"], f'<h1>{t["favourites"]}</h1>{body}'))

    print(f"trazos: built {len(pieces)} pieces, {len(tags)} tags -> {out}")


if __name__ == "__main__":
    build(Path(sys.argv[1]) if len(sys.argv) > 1 else Path.cwd())
