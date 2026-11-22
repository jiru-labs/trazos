#!/usr/bin/env python3
"""trazos: build a static, private-by-design art archive from a content folder.

    python3 build.py [CONTENT_DIR]          (default: the current directory)

CONTENT_DIR holds:
  trazos.toml            site settings (see example/trazos.toml)
  pieces/<id>.md         front matter + the story in the artist's words
  pieces/<id>.jpg        web version (long side 1600 px, metadata stripped)
  pieces/<id>-thumb.jpg  grid version (long side 600 px)
  site/                  optional extra static files (CNAME, favicon...), copied last
  edits/<id>.json        optional hand edits (the /admin/ page writes them); they win over pieces/<id>.md
  admin-key.json         written by /admin/ on setup: the GitHub token, encrypted with the admin password

Output goes to CONTENT_DIR/public. Standard library only (Python 3.11+).
"""
import html
import json
import re
import shutil
import sys
import tomllib
import zlib
import math
import struct
from pathlib import Path

ENGINE = Path(__file__).resolve().parent
ASSETS = ENGINE / "assets"

FIELDS = ("id", "year", "month", "order", "age", "technique", "title", "tags", "favourite", "hidden", "artists")
# Hand-made ids look like 2026-001; tools/ingest.py uses a short content hash.
ID_RE = re.compile(r"^(\d{4}-\d{3}|[0-9a-f]{10})$")
AGE_RE = re.compile(r"^(\d+)(?:\s*[-–]\s*(\d+))?$")

STRINGS = {
    "es": {
        "by_year": "Por año", "tags": "Etiquetas", "favourites": "Favoritos",
        "by": "De {names}", "and": " y ", "untitled": "Sin título", "empty": "Todavía no hay obras aquí. Pronto.",
        "no_tags": "Sin etiquetas todavía.", "no_favs": "Sin favoritos todavía.",
        "age_one": "{n} año", "age_many": "{n} años", "and": " y ",
        "ages_many": "{list} años", "default_title": "Las obras de {artist}", "enter": "Entrar",
        "lang_name": "Español", "locale": "es_ES", "count": "{n} obras",
        "summary": "{n} dibujos y obras de {artist}, de {first} a {last}.", "summary_one": "{n} dibujos y obras de {artist}, de {first}.",
        "rights": "© {artist}. Todos los derechos reservados. No se autoriza copiar estas obras ni usarlas "
                  "para minería de textos y datos o para entrenar inteligencia artificial "
                  "(art. 4.3 de la Directiva (UE) 2019/790).",
    },
    "en": {
        "by_year": "By year", "tags": "Tags", "favourites": "Favourites",
        "by": "By {names}", "and": " and ", "untitled": "Untitled", "empty": "No pieces here yet. Soon.",
        "no_tags": "No tags yet.", "no_favs": "No favourites yet.",
        "age_one": "age {n}", "age_many": "age {n}", "and": " and ",
        "ages_many": "ages {list}", "default_title": "The art of {artist}", "enter": "Log in",
        "lang_name": "English", "locale": "en_GB", "count": "{n} pieces",
        "summary": "{n} drawings and pieces by {artist}, {first} to {last}.", "summary_one": "{n} drawings and pieces by {artist}, from {first}.",
        "rights": "© {artist}. All rights reserved. Copying these works, or using them for text and data "
                  "mining or to train artificial intelligence, is not permitted "
                  "(Art. 4(3) of Directive (EU) 2019/790).",
    },
}
# Crawlers that only obey a robots.txt group naming them. `User-agent: *` already covers the
# rest; naming them costs nothing and closes that gap. AI training and AI search first.
BLOCKED_BOTS = (
    "GPTBot", "ChatGPT-User", "OAI-SearchBot", "ClaudeBot", "Claude-User", "Claude-SearchBot",
    "anthropic-ai", "Google-Extended", "GoogleOther", "Applebot-Extended", "CCBot", "PerplexityBot",
    "Perplexity-User", "Bytespider", "meta-externalagent", "meta-externalfetcher", "FacebookBot",
    "Amazonbot", "cohere-ai", "cohere-training-data-crawler", "Diffbot", "DuckAssistBot",
    "MistralAI-User", "YouBot", "Timpibot", "ImagesiftBot", "Omgilibot", "img2dataset",
    "AI2Bot", "PetalBot", "Googlebot-Image", "bingbot", "Googlebot",
)
# Link-preview fetchers (WhatsApp, Telegram, Signal goes client-side...): they read one page when
# someone shares a link, to draw its card, and do not index. `protect` lets them in so a shared
# link shows the title and picture; search engines and AI crawlers stay out.
PREVIEW_BOTS = ("facebookexternalhit", "WhatsApp", "TelegramBot", "Slackbot-LinkExpanding",
                "Discordbot", "Twitterbot", "LinkedInBot")
# WhatsApp drops a preview image heavier than about 300 KB; above that the thumbnail is used.
PREVIEW_MAX_BYTES = 300_000
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
    # `protect` (default on) keeps the site out of search engines and AI crawlers and reserves
    # text-and-data-mining rights. `noindex` is its old name and still works.
    cfg.setdefault("protect", cfg.get("noindex", True))
    t = STRINGS[cfg["lang"]]
    cfg.setdefault("title", t["default_title"].format(artist=cfg["artist"]))
    # `languages = ["es", "en"]`: the site is also built in the other languages, under /<code>/.
    # `lang` stays at the root; `title_<code>` / `rights_<code>` name the others (else the defaults). Only the site's own words change; titles,
    # stories and tags are shown as written.
    langs = cfg.get("languages") or [cfg["lang"]]
    if not isinstance(langs, list) or any(l not in STRINGS for l in langs):
        fail(f"trazos.toml: languages must be a list of {', '.join(STRINGS)}")
    cfg["languages"] = [cfg["lang"]] + [l for l in dict.fromkeys(langs) if l != cfg["lang"]]
    # `url = "https://example.org"`: the public address. Link previews (WhatsApp...) need it to
    # point at the picture, so without it a shared link shows only the title.
    if cfg.get("url"):
        if not re.match(r"^https?://[^\s/]+(/[^\s]*)?$", cfg["url"]):
            fail("trazos.toml: url must look like https://example.org")
        cfg["url"] = cfg["url"].rstrip("/")
    # `admin = "owner/repo"` adds a login page at /admin/ that edits this repo through the GitHub API.
    if cfg.get("admin") and not re.match(r"^[\w.-]+/[\w.-]+$", cfg["admin"]):
        fail("trazos.toml: admin must look like owner/repo")
    if cfg.get("admin_committer") and not re.match(r"^[^<>]+ <[^<>@\s]+@[^<>\s]+>$", cfg["admin_committer"]):
        fail("trazos.toml: admin_committer must look like Name <email>")
    # `admin_deploy = "owner/repo"`: the site is published from another repo (content kept private,
    # see the `site` workflow); after each save the admin asks that repo's pages.yml to run.
    if cfg.get("admin_deploy") and not re.match(r"^[\w.-]+/[\w.-]+$", cfg["admin_deploy"]):
        fail("trazos.toml: admin_deploy must look like owner/repo")
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


def jpeg_size(img):
    """(width, height) from a JPEG's frame header, or None."""
    data = img.read_bytes()
    i = 2
    while i + 9 <= len(data) and data[i] == 0xFF:
        marker = data[i + 1]
        if marker in (0xC0, 0xC1, 0xC2):
            return int.from_bytes(data[i + 7:i + 9], "big"), int.from_bytes(data[i + 5:i + 7], "big")
        if marker == 0xDA:
            return None
        i += 2 + int.from_bytes(data[i + 2:i + 4], "big")
    return None


def sidecar(path):
    """The sidecar as written: (front matter as strings, story text). No edits applied."""
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
    return meta, m.group(2)


def parse(path, pieces_dir):
    meta, body = sidecar(path)
    # Hand edits (the /admin/ page) win over the ingested sidecar, which a re-ingest rewrites.
    edits = pieces_dir.parent / "edits" / f"{path.stem}.json"
    if edits.exists():
        for key, value in json.loads(edits.read_text(encoding="utf-8")).items():
            if key == "story":
                body = value
            elif key in FIELDS and key not in ("id", "order"):
                meta[key] = str(value)
            else:
                fail(f"{edits.name}: unknown field {key!r}")
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
    # The month is never shown: it only orders a year from December back to January.
    if meta.get("month"):
        if not meta["month"].isdigit() or not 1 <= int(meta["month"]) <= 12:
            fail(f"{path.name}: month must be a number from 1 to 12")
        meta["month"] = int(meta["month"])
    else:
        meta["month"] = None
    if meta.get("order") and not meta["order"].isdigit():
        fail(f"{path.name}: order must be a whole number")
    meta["order"] = int(meta.get("order") or 0)
    meta["tags"] = [t.strip().lower() for t in meta.get("tags", "").split(",") if t.strip()]
    # `artists`: who made this piece when it is not (only) the site's artist, comma separated.
    meta["artists"] = [a.strip() for a in meta.get("artists", "").split(",") if a.strip()]
    meta["favourite"] = meta.get("favourite", "").lower() in ("yes", "sí", "si", "true")
    # `hidden: yes` takes a piece off the site (pages, images and the admin's public data.json)
    # without deleting it: it stays in the repo, and the admin lists it from there to bring it back.
    meta["hidden"] = meta.get("hidden", "").lower() in ("yes", "sí", "si", "true")
    meta["story"] = [p.strip() for p in body.strip().split("\n\n") if p.strip()]
    return meta


def slug(t):
    return re.sub(r"[^\w-]+", "-", t, flags=re.U).strip("-")


def e(s):
    return html.escape(str(s), quote=True)


class Site:
    def __init__(self, cfg, lang, pieces_dir):
        self.cfg, self.lang, self.pieces_dir = cfg, lang, pieces_dir
        self.t = STRINGS[lang]
        self.primary = lang == cfg["lang"]
        # Pages of another language live under /<lang>/ and share the root's images and style.
        self.sub = "" if self.primary else f"{lang}/"
        self.base = "" if self.primary else "../"
        if self.primary:
            self.title = cfg["title"]
        else:
            self.title = cfg.get(f"title_{lang}") or self.t["default_title"].format(artist=cfg["artist"])

    def href(self, lang, path, up):
        """Relative link from the current page to `path` in `lang`."""
        root = up + self.base
        return root + ("" if lang == self.cfg["lang"] else f"{lang}/") + path

    def preview(self, title, path, piece, desc):
        """Open Graph tags: what WhatsApp, Telegram and the like draw when the link is shared."""
        cfg, t = self.cfg, self.t
        tags = [("og:type", "article" if path.startswith("piece/") else "website"), ("og:title", title),
                ("og:site_name", self.title), ("og:locale", t["locale"])]
        tags += [("og:locale:alternate", STRINGS[l]["locale"]) for l in cfg["languages"] if l != self.lang]
        if desc:
            tags.append(("og:description", desc))
        card = "summary"
        if cfg.get("url"):
            page = "" if path == "index.html" else path
            tags.append(("og:url", f"{cfg['url']}/{self.sub}{page}"))
            # The archive's own pages show a made-for-sharing card when the site has one
            # (tools/share-card.py): a bare drawing there reads as a link to an image.
            share = next((f for f in (f"share-{self.lang}.jpg", "share.jpg")
                          if (self.pieces_dir.parent / "site" / f).is_file()), None)
            if share and not path.startswith("piece/"):
                img = self.pieces_dir.parent / "site" / share
                tags.append(("og:image", f"{cfg['url']}/{share}"))
                size = jpeg_size(img)
                if size:
                    tags += [("og:image:width", str(size[0])), ("og:image:height", str(size[1]))]
                tags.append(("og:image:alt", self.title))
                card = "summary_large_image"
            elif piece:
                img = self.pieces_dir / f"{piece['id']}.jpg"
                if img.stat().st_size > PREVIEW_MAX_BYTES:
                    img = self.pieces_dir / f"{piece['id']}-thumb.jpg"
                tags.append(("og:image", f"{cfg['url']}/img/{img.name}"))
                size = jpeg_size(img)
                if size:
                    tags += [("og:image:width", str(size[0])), ("og:image:height", str(size[1]))]
                tags.append(("og:image:alt", piece.get("title") or t["untitled"]))
                card = "summary_large_image"
        out = "".join(f'<meta property="{k}" content="{e(v)}">\n' for k, v in tags)
        out += f'<meta name="twitter:card" content="{card}">\n'
        if desc:
            out += f'<meta name="description" content="{e(desc)}">\n'
        if cfg.get("url") and len(cfg["languages"]) > 1:
            for l in cfg["languages"]:
                sub = "" if l == cfg["lang"] else f"{l}/"
                page = "" if path == "index.html" else path
                out += f'<link rel="alternate" hreflang="{l}" href="{e(cfg["url"])}/{sub}{e(page)}">\n'
        return out

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

    def page(self, title, body, path, piece=None, desc=""):
        depth = path.count("/")
        up = "../" * depth
        res = up + self.base
        t = self.t
        robots = ('<meta name="robots" content="noindex, nofollow, noarchive, nosnippet, noimageindex, noai, noimageai">\n'
                  '<meta name="tdm-reservation" content="1">\n'
                  if self.cfg["protect"] else "")
        custom = self.cfg.get("rights") if self.primary else self.cfg.get(f"rights_{self.lang}")
        rights = custom or (t["rights"].format(artist=self.cfg["artist"]) if self.cfg["protect"] else "")
        enter = f' <a class="enter" href="{res}admin/">{t["enter"]}</a>' if self.cfg.get("admin") else ""
        switch = "".join(f'<a class="lang" lang="{l}" hreflang="{l}" href="{e(self.href(l, path, up))}">'
                         f'{STRINGS[l]["lang_name"]}</a>' for l in self.cfg["languages"] if l != self.lang)
        footer = f'<footer><p>{e(rights)}{enter}</p></footer>\n' if rights or enter else ""
        return f"""<!doctype html>
<html lang="{e(self.lang)}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
{robots}{self.preview(title, path, piece, desc)}<meta http-equiv="Content-Security-Policy" content="default-src 'self'; img-src 'self'; style-src 'self'; script-src 'none'; base-uri 'none'; form-action 'none'">
<meta name="referrer" content="no-referrer">
<meta name="generator" content="trazos">
<title>{e(title)}</title>
<link rel="icon" href="{res}favicon.svg" type="image/svg+xml">
<link rel="icon" href="{res}favicon.ico" sizes="32x32">
<link rel="apple-touch-icon" href="{res}apple-touch-icon.png">
<link rel="stylesheet" href="{res}style.css">
</head>
<body>
<header>
<a class="home" href="{up}index.html">{e(self.title)}</a>
<nav><a href="{up}index.html">{t['by_year']}</a><a href="{up}{TAGS_PAGE}">{t['tags']}</a><a href="{up}{FAVS_PAGE}">{t['favourites']}</a>{switch}</nav>
</header>
<main>
{body}
</main>
{footer}</body>
</html>
"""

    def grid(self, items, depth=0):
        up = "../" * depth
        res = up + self.base
        cards = []
        for p in items:
            label = p.get("title") or self.t["untitled"]
            cards.append(
                f'<a class="card" href="{up}piece/{e(p["id"])}.html">'
                f'<img src="{res}img/{e(p["id"])}-thumb.jpg" alt="{e(label)}" loading="lazy">'
                f'<span>{e(label)}</span></a>'
            )
        return '<div class="grid">' + "".join(cards) + "</div>"


# The page icon: a sheet of drawing paper with one crayon stroke, in the palette of style.css.
# A content folder can bring its own (site/favicon.svg, site/favicon.ico,
# site/apple-touch-icon.png): site/ is copied last and replaces these.
PAPER, CRAYON, EDGE = (0xFA, 0xF6, 0xEE), (0xC2, 0x46, 0x2A), (0xE8, 0xE0, 0xD2)
ICON_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
<style>.p{fill:#faf6ee;stroke:#e8e0d2}.s{stroke:#c2462a}
@media (prefers-color-scheme: dark){.p{fill:#26231f;stroke:#3a352f}.s{stroke:#f07a5a}}</style>
<rect class="p" x="2" y="2" width="60" height="60" rx="14" stroke-width="2"/>
<path class="s" d="M14 38 C22 18, 30 18, 32 32 S42 46, 50 26" fill="none" stroke-width="8" stroke-linecap="round"/>
</svg>
"""


def icon_png(size):
    """The same icon as a PNG, drawn with the standard library (supersampled)."""
    pts = []  # the stroke as a polyline, in 0..64 units, sampled from the SVG's two curves
    def bez(p0, p1, p2, p3, n=24):
        for i in range(n + 1):
            t = i / n
            pts.append(tuple((1-t)**3*a + 3*(1-t)**2*t*b + 3*(1-t)*t**2*c + t**3*d for a, b, c, d in zip(p0, p1, p2, p3)))
    bez((14, 38), (22, 18), (30, 18), (32, 32))
    bez((32, 32), (34, 46), (42, 46), (50, 26))
    segs = list(zip(pts, pts[1:]))
    def dist(x, y):
        best = 1e9
        for (ax, ay), (bx, by) in segs:
            dx, dy = bx - ax, by - ay
            t = max(0.0, min(1.0, ((x - ax) * dx + (y - ay) * dy) / (dx * dx + dy * dy or 1)))
            best = min(best, (x - ax - t * dx) ** 2 + (y - ay - t * dy) ** 2)
        return best
    def inside(x, y, inset=2.0, r=14.0):
        cx, cy = min(max(x, inset + r), 64 - inset - r), min(max(y, inset + r), 64 - inset - r)
        return (x - cx) ** 2 + (y - cy) ** 2 <= r * r and inset <= x <= 64 - inset and inset <= y <= 64 - inset
    k, rows = (4 if size <= 64 else 2), []
    for py in range(size):
        row = bytearray(b"\0")
        for px in range(size):
            acc = [0, 0, 0, 0]
            for sy in range(k):
                for sx in range(k):
                    x, y = (px + (sx + .5) / k) * 64 / size, (py + (sy + .5) / k) * 64 / size
                    if not inside(x, y, 1.0, 15.0):
                        continue
                    c = EDGE if not inside(x, y) else (CRAYON if dist(x, y) <= 16 else PAPER)
                    acc[0] += c[0]; acc[1] += c[1]; acc[2] += c[2]; acc[3] += 255
            n = k * k
            a = acc[3] // n
            row += bytes((acc[0] * 255 // acc[3] if acc[3] else 0, acc[1] * 255 // acc[3] if acc[3] else 0,
                          acc[2] * 255 // acc[3] if acc[3] else 0, a))
        rows.append(bytes(row))
    chunk = lambda tag, data: struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(b"".join(rows), 9)) + chunk(b"IEND", b""))


def icons(out):
    (out / "favicon.svg").write_text(ICON_SVG)
    png = icon_png(32)
    # An .ico that simply wraps the 32 px PNG (supported everywhere since Windows Vista).
    (out / "favicon.ico").write_bytes(struct.pack("<HHH", 0, 1, 1) + struct.pack("<BBBBHHII", 32, 32, 0, 0, 1, 32, len(png), 22) + png)
    (out / "apple-touch-icon.png").write_bytes(icon_png(180))


def protect(out):
    """Every machine-readable 'no' there is. Polite bots obey; the rest meet the legal reservation."""
    named = "".join(f"User-agent: {b}\nDisallow: /\n\n" for b in BLOCKED_BOTS)
    preview = "".join(f"User-agent: {b}\n" for b in PREVIEW_BOTS) + "Allow: /\n\n"
    (out / "robots.txt").write_text(named + preview + "User-agent: *\nDisallow: /\n")
    # Spawning's ai.txt, read by image dataset tools (img2dataset honours it).
    (out / "ai.txt").write_text("User-Agent: *\nDisallow: /\nDisallow: *\n")
    # W3C TDMRep: the machine-readable form of the EU text-and-data-mining opt-out.
    (out / ".well-known").mkdir(exist_ok=True)
    (out / ".well-known" / "tdmrep.json").write_text('[{"location": "/*", "tdm-reservation": 1}]\n')


def admin_page(root, out, cfg, pieces):
    """/admin/: a static login page. The browser does the rest against the GitHub API: the token is
    stored encrypted with the admin password (admin-key.json), so there is no server at all."""
    d = out / "admin"
    d.mkdir()
    shutil.copy(ASSETS / "admin.js", d / "admin.js")
    shutil.copy(ASSETS / "admin.css", d / "admin.css")
    key = root / "admin-key.json"
    if key.exists():
        shutil.copy(key, d / "key.json")
    raw = tomllib.loads((root / "trazos.toml").read_text(encoding="utf-8"))
    items = []
    for p in pieces:
        meta, story = sidecar(root / "pieces" / f"{p['id']}.md")
        base = {k: meta.get(k, "") for k in FIELDS if k not in ("id", "order")}
        base["story"] = story.strip()
        items.append({"id": p["id"], "year": p["year"], "month": p["month"], "order": p["order"],
                      "title": p.get("title", ""), "base": base})
    data = {"repo": cfg["admin"], "deploy": cfg.get("admin_deploy", ""), "sync": cfg.get("admin_sync") is True,
            "lang": cfg["lang"],
            "committer": cfg.get("admin_committer", ""),
            "settings": {k: raw.get(k) for k in ("title", "artist", "lang", "rights", "protect") if k in raw},
            "pieces": items}
    (d / "data.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    (d / "index.html").write_text(f"""<!doctype html>
<html lang="{e(cfg['lang'])}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' blob:; connect-src 'self' https://api.github.com; base-uri 'none'; form-action 'none'">
<meta name="referrer" content="no-referrer">
<title>admin · {e(cfg['title'])}</title>
<link rel="icon" href="../favicon.svg" type="image/svg+xml">
<link rel="icon" href="../favicon.ico" sizes="32x32">
<link rel="stylesheet" href="../style.css">
<link rel="stylesheet" href="admin.css">
</head>
<body class="admin">
<header><a class="home" href="../index.html">{e(cfg['title'])}</a><nav id="nav"></nav></header>
<main id="app"><noscript>JavaScript</noscript></main>
<script src="admin.js"></script>
</body>
</html>
""", encoding="utf-8")


def summary(site, pieces):
    """The archive's one-line description: `description_<lang>` / `description` in trazos.toml, or
    what and how much, with the years it spans."""
    cfg = site.cfg
    own = cfg.get(f"description_{site.lang}") or (cfg.get("description") if site.primary else None)
    if own or not pieces:
        return own or ""
    years = sorted({p["year"] for p in pieces})
    key = "summary" if years[0] != years[-1] else "summary_one"
    return site.t[key].format(artist=cfg["artist"], n=len(pieces), first=years[0], last=years[-1])


def write_language(site, pieces, out):
    """Every public page in one language; returns the tags."""
    t = site.t
    d = out / site.sub
    for sub in ("piece", "tag"):
        (d / sub).mkdir(parents=True, exist_ok=True)
    write = lambda rel, html_: (d / rel).write_text(html_, encoding="utf-8")
    # The picture a shared link to the archive shows: `cover = "<id>"` in trazos.toml, else the
    # newest favourite, else the newest piece.
    favs_all = [p for p in pieces if p["favourite"]]
    cover = next((p for p in pieces if p["id"] == site.cfg.get("cover")), None)
    if site.cfg.get("cover") and not cover and site.primary:
        print(f"trazos: cover {site.cfg['cover']!r} is not a visible piece; using the default", file=sys.stderr)
    cover = cover or ((favs_all or pieces)[-1] if pieces else None)

    # Timeline, newest year first
    if pieces:
        parts = []
        for year in sorted({p["year"] for p in pieces}, reverse=True):
            # Newest first inside the year too: December back to January, undated months last.
            items = sorted((p for p in pieces if p["year"] == year),
                           key=lambda p: (p["month"] is None, -(p["month"] or 0), -p["order"], p["id"]))
            ages = sorted({a for p in items for a in p.get("age_span", [])})
            sub = f" <small>({e(site.ages(ages))})</small>" if ages else ""
            parts.append(f'<section><h2 id="y{year}">{year}{sub}</h2>{site.grid(items)}</section>')
        body = "\n".join(parts)
    else:
        body = f'<p class="empty">{t["empty"]}</p>'
    write("index.html", site.page(site.title, body, "index.html", cover, summary(site, pieces)))

    for p in pieces:
        label = p.get("title") or t["untitled"]
        names = p["artists"]
        by = t["by"].format(names=", ".join(names[:-1]) + t["and"] + names[-1] if len(names) > 1 else names[0]) if names else ""
        facts = " · ".join(x for x in (by, str(p["year"]), site.age(p["age"]) if p.get("age") else "",
                                       p.get("technique", "")) if x)
        tags = "".join(f'<a href="../tag/{e(slug(x))}.html">{e(x)}</a>' for x in p["tags"])
        story = "".join(f"<p>{e(s)}</p>" for s in p["story"])
        body = (
            f'<article class="piece"><img src="../{site.base}img/{e(p["id"])}.jpg" alt="{e(label)}">'
            f"<h1>{e(label)}{' ★' if p['favourite'] else ''}</h1><p class=\"facts\">{e(facts)}</p>"
            f"{story}<p class=\"tags\">{tags}</p></article>"
        )
        write(f"piece/{p['id']}.html", site.page(label, body, f"piece/{p['id']}.html", p, facts))

    tags = sorted({x for p in pieces for x in p["tags"]})
    for x in tags:
        items = [p for p in pieces if x in p["tags"]]
        write(f"tag/{slug(x)}.html", site.page(x, f"<h1>{e(x)}</h1>{site.grid(items, 1)}", f"tag/{slug(x)}.html", items[-1]))
    links = "".join(
        f'<a href="tag/{e(slug(x))}.html">{e(x)} <small>{sum(x in p["tags"] for p in pieces)}</small></a>'
        for x in tags) or f'<span class="empty">{t["no_tags"]}</span>'
    write(TAGS_PAGE, site.page(t["tags"], f'<h1>{t["tags"]}</h1><p class="tags">{links}</p>', TAGS_PAGE, cover))

    favs = [p for p in pieces if p["favourite"]]
    body = site.grid(favs) if favs else f'<p class="empty">{t["no_favs"]}</p>'
    write(FAVS_PAGE, site.page(t["favourites"], f'<h1>{t["favourites"]}</h1>{body}', FAVS_PAGE, favs[-1] if favs else cover))

    return tags


def build(root):
    root = root.resolve()
    cfg = load_config(root)
    pieces_dir, out = root / "pieces", root / "public"
    pieces = sorted((parse(p, pieces_dir) for p in pieces_dir.glob("*.md")), key=lambda p: (p["year"], p["order"], p["id"]))
    pieces = [p for p in pieces if not p["hidden"]]

    if out.exists():
        shutil.rmtree(out)
    for d in ("piece", "tag", "img"):
        (out / d).mkdir(parents=True)
    shutil.copy(ASSETS / "style.css", out / "style.css")
    (out / ".nojekyll").write_text("")
    icons(out)
    if cfg["protect"]:
        protect(out)
    for p in pieces:
        for suffix in (".jpg", "-thumb.jpg"):
            shutil.copy(pieces_dir / f"{p['id']}{suffix}", out / "img" / f"{p['id']}{suffix}")
    extra = root / "site"
    if extra.is_dir():
        shutil.copytree(extra, out, dirs_exist_ok=True)

    for lang in cfg["languages"]:
        tags = write_language(Site(cfg, lang, pieces_dir), pieces, out)

    if cfg.get("admin"):
        admin_page(root, out, cfg, pieces)

    print(f"trazos: built {len(pieces)} pieces, {len(tags)} tags -> {out}")


if __name__ == "__main__":
    build(Path(sys.argv[1]) if len(sys.argv) > 1 else Path.cwd())
