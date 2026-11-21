#!/usr/bin/env python3
"""Ingest a folder of originals (photos or scans) into a trazos content folder.

    ingest.py SOURCE_DIR CONTENT_DIR --state STATE.json [--birthdate YYYY-MM-DD] [--no-crop]
    ingest.py SOURCE_DIR --preview OUT_DIR [--no-crop]      (process only, write nothing else)

The source folder is the archive and is never modified. Each run makes the site match it:
  * a new image becomes a piece; a deleted one is removed; a renamed one is updated in place
    (pieces are keyed by the content hash of the original, so URLs survive a rename);
  * only files directly in SOURCE_DIR count: anything in a subfolder is ignored, so a
    subfolder such as "no publicar/" holds what must stay private.

File name convention (everything optional):
    "<date> <anything> - <title>.<ext>"   e.g. "2025-06 Dibujo - el gato.heic"
  <date> is YYYY-MM-DD, YYYY-MM or YYYY. Without it, the photo's own date (EXIF) is used.
  A sibling "<same name>.txt" holds the story; its first lines may set fields:
    técnica: ceras / etiquetas: gato, casa / favorito: sí / año: 2025 / mes: junio

Month: a piece only gets one when the date says so honestly. "YYYY-MM" in the name and a
`mes:` line always count. A full date (a camera's) counts unless SESSION_MIN or more pieces
share that same day: that is a photo session of older work, so the day says when it was
photographed, not when it was made. Those pieces, and any dated only by `año:` or by the
file's mtime, stay "without month", and their age is computed from the year alone.

Images are decoded (HEIC too), turned upright, cropped to the sheet of paper when one is
found (OpenCV), resized to 1600/600 px and written as JPEG WITHOUT any metadata.
The birthdate (for ages) is read from --birthdate or $TRAZOS_BIRTHDATE and never written
anywhere: only the resulting age is.

Needs: Pillow, pillow-heif, opencv-python-headless, numpy (see tools/requirements.txt).
Prints a JSON summary on the last line: {"added": [...], "updated": [...], "removed": [...]}.
"""
import argparse
import datetime as dt
import hashlib
import json
import os
import re
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageOps
from pillow_heif import register_heif_opener

register_heif_opener()

IMAGE_EXT = {".heic", ".heif", ".jpg", ".jpeg", ".png", ".webp"}
NAME_RE = re.compile(r"^(?P<date>\d{4}(?:-\d{2}(?:-\d{2})?)?)?\s*(?P<rest>.*?)$")
FIELD_RE = re.compile(r"^\s*(técnica|tecnica|technique|etiquetas|tags|favorito|favourite|año|year|mes|month)\s*:\s*(.*)$", re.I)
FIELD_MAP = {"técnica": "technique", "tecnica": "technique", "technique": "technique",
             "etiquetas": "tags", "tags": "tags", "favorito": "favourite", "favourite": "favourite",
             "año": "year", "year": "year", "mes": "month", "month": "month"}
SESSION_MIN = 6  # this many pieces on one exact day = a photo session of older work
MONTHS = {name: i + 1 for names in (
    "enero febrero marzo abril mayo junio julio agosto septiembre octubre noviembre diciembre",
    "january february march april may june july august september october november december")
    for i, name in enumerate(names.split())}
MONTHS["setiembre"] = 9


def month_of(value):
    """'6', '06', 'junio', 'Jun', 'june' -> 6; anything else -> None."""
    v = value.strip().lower()
    if v.isdigit():
        return int(v) if 1 <= int(v) <= 12 else None
    hits = {m for name, m in MONTHS.items() if len(v) >= 3 and name.startswith(v)}
    return hits.pop() if len(hits) == 1 else None


# ---------- image pipeline ----------

def load(path):
    im = Image.open(path)
    im = ImageOps.exif_transpose(im)  # upright, then the EXIF is dropped with the object
    return im.convert("RGB")


def find_paper(im):
    """Return the 4 corners of the sheet of paper, or None if there is no clear sheet.

    Two cues, tried in order: (1) bright, unsaturated paper; (2) for a sheet painted edge to
    edge (blue sea, black night), everything that is not wood-coloured floor. The first is
    tried first because an orange drawing can look like wood. A candidate counts only if it
    covers 20-95 % of the photo: a scan or a digital drawing is ~100 % and is left as is.
    """
    rgb = np.asarray(im)
    scale = 800 / max(rgb.shape[:2])
    small = cv2.resize(rgb, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    hsv = cv2.cvtColor(small, cv2.COLOR_RGB2HSV)
    h, s, v = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    paper = (v > 150) & (s < 60)
    wood = (h >= 5) & (h <= 25) & (s > 50) & (v > 40) & (v < 225)
    for cue in (paper, ~wood):
        quad = _sheet(cue.astype(np.uint8) * 255, small.shape[0] * small.shape[1])
        if quad is not None:
            return quad / scale
    return None


def _sheet(mask, total):
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((9, 9), np.uint8))     # floor grain
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((25, 25), np.uint8))  # the drawing itself
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None
    c = max(contours, key=cv2.contourArea)
    if not 0.20 <= cv2.contourArea(c) / total <= 0.95:
        return None
    hull = cv2.convexHull(c)
    for eps in (0.02, 0.03, 0.045, 0.06, 0.08):  # crumpled or torn sheet: loosen until 4 corners
        approx = cv2.approxPolyDP(hull, eps * cv2.arcLength(hull, True), True)
        if len(approx) == 4:
            return np.array(approx, dtype=np.float32).reshape(4, 2)
    return np.array(cv2.boxPoints(cv2.minAreaRect(hull)), dtype=np.float32)


def warp(im, quad):
    rgb = np.asarray(im)
    s, d = quad.sum(1), np.diff(quad, axis=1).ravel()
    tl, br, tr, bl = quad[np.argmin(s)], quad[np.argmax(s)], quad[np.argmin(d)], quad[np.argmax(d)]
    w = int(max(np.linalg.norm(br - bl), np.linalg.norm(tr - tl)))
    h = int(max(np.linalg.norm(tr - br), np.linalg.norm(tl - bl)))
    m = cv2.getPerspectiveTransform(np.float32([tl, tr, br, bl]), np.float32([[0, 0], [w, 0], [w, h], [0, h]]))
    out = cv2.warpPerspective(rgb, m, (w, h), flags=cv2.INTER_CUBIC)
    # Trim a thin margin: the warped edge often keeps a sliver of floor.
    mx, my = int(w * 0.012), int(h * 0.012)
    return Image.fromarray(out[my:h - my, mx:w - mx])


def process(path, crop=True):
    im = load(path)
    cropped = False
    if crop:
        quad = find_paper(im)
        if quad is not None:
            im, cropped = warp(im, quad), True
    return im, cropped


def save_web(im, dest_dir, pid):
    big = im.copy()
    big.thumbnail((1600, 1600), Image.LANCZOS)
    big.save(dest_dir / f"{pid}.jpg", "JPEG", quality=82, optimize=True, progressive=True)
    thumb = im.copy()
    thumb.thumbnail((600, 600), Image.LANCZOS)
    thumb.save(dest_dir / f"{pid}-thumb.jpg", "JPEG", quality=78, optimize=True, progressive=True)


# ---------- metadata ----------

def photo_date(path):
    try:
        exif = Image.open(path).getexif()
        raw = exif.get_ifd(0x8769).get(36867) or exif.get(306)  # DateTimeOriginal, DateTime
        if raw:
            return raw[:10].replace(":", "-")
    except Exception:
        pass
    return None


def parse_name(path):
    m = NAME_RE.match(path.stem)
    date, rest = m.group("date"), m.group("rest")
    title = rest.split(" - ", 1)[1].strip() if " - " in rest else ""
    if re.fullmatch(r"[\d_.:-]*", title):  # "1430", "142817": a camera time, not a title
        title = ""
    return date, (title[:1].upper() + title[1:]) if title else ""


def read_txt(path):
    fields, story = {}, []
    txt = path.with_suffix(".txt")
    if not txt.exists():
        return fields, ""
    lines = txt.read_text(encoding="utf-8", errors="replace").splitlines()
    i = 0
    while i < len(lines) and (m := FIELD_RE.match(lines[i])):
        fields[FIELD_MAP[m.group(1).lower()]] = m.group(2).strip()
        i += 1
    story = "\n".join(lines[i:]).strip()
    return fields, story


def age_label(date, birth):
    """date is YYYY, YYYY-MM or YYYY-MM-DD; returns '4' or a range '3–4' when imprecise."""
    if not birth or not date:
        return ""
    parts = [int(x) for x in date.split("-")]
    y = parts[0]
    lo = dt.date(y, parts[1] if len(parts) > 1 else 1, parts[2] if len(parts) > 2 else 1)
    if len(parts) == 3:
        hi = lo
    elif len(parts) == 2:
        nxt = dt.date(y + (parts[1] == 12), parts[1] % 12 + 1, 1)
        hi = nxt - dt.timedelta(days=1)
    else:
        hi = dt.date(y, 12, 31)
    age = lambda d: d.year - birth.year - ((d.month, d.day) < (birth.month, birth.day))
    a, b = max(age(lo), 0), max(age(hi), 0)
    return str(a) if a == b else f"{a}–{b}"


def sidecar(pid, year, month, age, title, fields, story, order):
    fav = fields.get("favourite", "").lower() in ("sí", "si", "yes", "true")
    lines = ["---", f"id: {pid}", f"year: {year}"]
    if month:
        lines.append(f"month: {month}")
    lines.append(f"order: {order}")
    if age:
        lines.append(f"age: {age}")
    if fields.get("technique"):
        lines.append(f"technique: {fields['technique']}")
    lines.append(f'title: "{title.replace(chr(34), "")}"')
    if fields.get("tags"):
        lines.append(f"tags: {fields['tags']}")
    lines += [f"favourite: {'yes' if fav else 'no'}", "---"]
    return "\n".join(lines) + "\n" + (story + "\n" if story else "")


# ---------- sync ----------

def sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def sources(src):
    return sorted(p for p in src.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_EXT)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("source", type=Path)
    ap.add_argument("content", type=Path, nargs="?")
    ap.add_argument("--state", type=Path)
    ap.add_argument("--birthdate", default=os.environ.get("TRAZOS_BIRTHDATE"))
    ap.add_argument("--no-crop", action="store_true")
    ap.add_argument("--preview", type=Path)
    a = ap.parse_args()
    files = sources(a.source)
    if not files:
        # A sync that sees ZERO originals must not wipe the site: a missing mount looks the same.
        sys.exit(f"ingest: no images in {a.source}; refusing to treat that as 'delete everything'")

    if a.preview:
        a.preview.mkdir(parents=True, exist_ok=True)
        for p in files:
            im, cropped = process(p, not a.no_crop)
            im.thumbnail((900, 900))
            im.save(a.preview / f"{p.stem}.jpg", "JPEG", quality=80)
            print(f"{'crop' if cropped else 'full'}  {p.name}")
        return

    if not (a.content and a.state):
        ap.error("CONTENT_DIR and --state are required unless --preview")
    birth = dt.date.fromisoformat(a.birthdate) if a.birthdate else None
    pieces = a.content / "pieces"
    pieces.mkdir(parents=True, exist_ok=True)
    state = json.loads(a.state.read_text()) if a.state.exists() else {}
    # state: {hash: {"id": ..., "sig": "<name>|<size>|<mtime>|<txt mtime>", "sort": "<date>"}}
    seen, added, updated = set(), [], []
    entries = []
    for p in files:
        st = p.stat()
        txt = p.with_suffix(".txt")
        sig = f"{p.name}|{st.st_size}|{int(st.st_mtime)}|{int(txt.stat().st_mtime) if txt.exists() else 0}"
        known = next((h for h, v in state.items() if v.get("sig", "").split("|")[1:3] == sig.split("|")[1:3]
                      and v.get("name") == p.name), None)
        h = known or sha(p)
        seen.add(h)
        name_date, title = parse_name(p)
        fields, story = read_txt(p)
        exif = None if fields.get("year") or name_date else photo_date(p)
        date = fields.get("year") or name_date or exif or dt.date.fromtimestamp(st.st_mtime).isoformat()
        # Only a date the name or the photo gave can carry a month; the file's mtime cannot.
        trusted = not fields.get("year") and bool(name_date or exif)
        entries.append((h, p, sig, date, title, fields, story, trusted))

    sessions = {d for d in {e[3] for e in entries}
                if len(d) == 10 and sum(e[3] == d and e[7] for e in entries) >= SESSION_MIN}

    # Stable ordering inside a year: by date, then name. Only the ordinal is published.
    entries.sort(key=lambda e: (e[3], e[1].name))
    per_year = {}
    for h, p, sig, date, title, fields, story, trusted in entries:
        year = int(date[:4])
        per_year[year] = per_year.get(year, 0) + 1
        prev = state.get(h)
        pid = prev["id"] if prev else h[:10]
        if fields.get("month"):
            month = month_of(fields["month"])
            if not month:
                print(f"ingest: {p.name}: mes {fields['month']!r} not understood; left without month", file=sys.stderr)
            when = date if month and date[5:7] == f"{month:02d}" else (f"{year}-{month:02d}" if month else str(year))
        elif trusted and len(date) >= 7 and date not in sessions:
            month, when = int(date[5:7]), date
        else:
            month, when = None, str(year)
        md = sidecar(pid, year, month, age_label(when, birth), title, fields, story, per_year[year])
        md_path = pieces / f"{pid}.md"
        image_missing = not (pieces / f"{pid}.jpg").exists()
        if image_missing:
            im, _ = process(p, not a.no_crop)
            save_web(im, pieces, pid)
        if image_missing or not md_path.exists() or md_path.read_text(encoding="utf-8") != md:
            md_path.write_text(md, encoding="utf-8")
            (added if not prev else updated).append(pid)
        state[h] = {"id": pid, "sig": sig, "name": p.name}

    removed = []
    for h in [h for h in state if h not in seen]:
        pid = state.pop(h)["id"]
        for f in (f"{pid}.md", f"{pid}.jpg", f"{pid}-thumb.jpg"):
            (pieces / f).unlink(missing_ok=True)
        removed.append(pid)

    tmp = a.state.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=1, ensure_ascii=False))
    tmp.replace(a.state)
    print(json.dumps({"added": added, "updated": updated, "removed": removed}))


if __name__ == "__main__":
    main()
