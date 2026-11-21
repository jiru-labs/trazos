# trazos

**A lifelong, private-by-design archive for someone's art.** Scan or photograph a
child's drawings (or your own work) year after year, and trazos turns them into a
quiet static website: a timeline by year and age, tags, favourites, and each piece
with the story in the artist's own words.

[Live demo](https://nyakojiru.github.io/trazos/) · [Español](#en-español)

- **Anonymous by default.** The site shows one first name or pseudonym. Ages and
  years, never birthdays or places.
- **Protected from crawlers by default** (`protect = true`). Every machine-readable "no"
  there is: `noindex`/`noai`/`noimageai` meta tags, a `robots.txt` that names ~30 AI and
  image crawlers one by one (some only obey their own group), Spawning's `ai.txt`, the
  W3C TDMRep opt-out (`tdm-reservation` meta and `/.well-known/tdmrep.json`), and a rights
  notice on every page reserving text-and-data mining under Art. 4(3) of the EU DSM
  Directive. Honest limit: these are requests plus a legal reservation. A static host
  cannot *block* a rude bot; for that, put a proxy with bot blocking (e.g. Cloudflare) in front.
- **Nothing leaks from the photo.** `tools/prepare.sh` strips EXIF/GPS/camera data
  and OCRs the image, which catches printed text such as a school stamp. OCR does
  **not** read a child's handwriting, so a signed surname or a dedication is only
  caught by looking: always review the image itself. The build *refuses* any JPEG
  that still carries EXIF or XMP.
- **No scripts, no trackers, no third parties.** A Content-Security-Policy forbids them.
- **Built to last decades.** Plain text sidecars next to plain JPEGs, one Python file
  with no dependencies. If trazos disappears, your archive is still readable.
- **Originals stay with you.** Only web-sized copies enter git, because git history is
  forever and Pages has size limits. Keep the full-resolution originals in your own backups.

## Start your archive

1. Create a repo and copy `example/` into it (it includes the Pages workflow).
2. Edit `trazos.toml`: `artist`, `lang` (`en` or `es`), `protect` (default `true`), and
   optionally `rights` to replace the default notice.
3. Delete the demo pieces, add your own (below) and push. In the repo settings, set
   Pages to deploy from **GitHub Actions**. For a custom domain, add `site/CNAME`.

## Sync from a folder (recommended)

Keep your originals in one folder (a synced cloud folder works well) and let
`tools/ingest.py` turn it into pieces. The folder is the approval: what is in it is
published, what you move into a subfolder (e.g. `private/`) is not.

```sh
python3 -m venv ~/.trazos && ~/.trazos/bin/pip install -r tools/requirements.txt
TRAZOS_BIRTHDATE=2019-06-01 ~/.trazos/bin/python tools/ingest.py ~/Art path/to/your-archive --state ~/.trazos/state.json
python3 build.py path/to/your-archive
```

- Name files `<date> <anything> - <title>.<ext>`, where `<date>` is `2026-05-14`, `2026-05`
  or `2026` (`2025 Dibujo - el gato.heic`). Without a date, the photo's EXIF date is used.
  A year alone gives an age range (`ages 4–5`).
- Optional `<same name>.txt` next to it: first lines `technique:`, `tags:`, `favourite: yes`,
  then the story.
- Each photo is turned upright, **cropped to the sheet of paper** when one is found (OpenCV;
  otherwise left whole), resized and saved as JPEG with no metadata at all. HEIC works.
- Ids are a short hash of the original, so renaming a file updates the piece in place, and
  deleting it removes the piece. An empty source folder is refused, never read as "delete all".
- The birthdate is only used to compute ages; it is never written to the archive.
- Run it from cron to publish by just dropping a photo into the folder.

## Add a piece by hand

```sh
tools/prepare.sh IMG_1234.HEIC 2026-001   # web copies + empty sidecar + OCR, in ~/trazos-staging
# look at the image and the OCR text; fill in the sidecar
tools/publish.sh 2026-001 path/to/your-archive
git -C path/to/your-archive add pieces && git -C path/to/your-archive commit -m "Add 2026-001" && git -C path/to/your-archive push
```

`prepare.sh` needs ImageMagick (with HEIC support for iPhone photos), exiftool and
tesseract. Set `TRAZOS_OCR_LANGS=spa+eng` for Spanish text.

A piece is three files in `pieces/`, named `<year>-<nnn>` (or a 10-character hash when ingested):

```
2026-001.md         the sidecar
2026-001.jpg        long side 1600 px
2026-001-thumb.jpg  long side 600 px
```

```
---
id: 2026-001
year: 2026
age: 5
technique: crayons
title: "The house of the sun"
tags: house, sun
favourite: no
---
The story in the artist's words. Blank lines separate paragraphs.
```

Only `id` and `year` are required. `age` may be a range (`4-5`); `order` sorts pieces inside a year.

## Build locally

```sh
python3 build.py path/to/your-archive    # writes path/to/your-archive/public
```

Python 3.11+, standard library only.

## En español

**Un archivo para toda la vida del arte de alguien, privado desde el diseño.** Escanea
o fotografía los dibujos de tu hija, de tu hijo o los tuyos, año tras año, y trazos
los convierte en una web estática: una línea de tiempo por año y edad, etiquetas,
favoritos y, en cada obra, la historia contada por quien la hizo.

Es anónimo por defecto: solo un nombre de pila o un seudónimo, con edades y años y
nunca lugares. Y viene protegido por defecto: fuera de buscadores y rastreadores de IA
(robots.txt con ~30 bots por nombre, `ai.txt`, TDMRep) y con una reserva de derechos de
minería de datos en cada página (art. 4.3 de la Directiva (UE) 2019/790). Quita los metadatos de las
fotos y lee el texto de la imagen para que revises que no se vea un apellido o el
nombre de un colegio. El build se niega a publicar una imagen con EXIF. Sin scripts ni
rastreadores. Los originales se quedan contigo y en git solo entran las copias para la web.

Lo más cómodo: una carpeta con los originales y `tools/ingest.py` (arriba). Lo que está en la
carpeta se publica; lo que metes en una subcarpeta, no. Recorta la hoja sola y acepta HEIC.
Pon `lang = "es"` en `trazos.toml` y sigue los pasos de arriba.

## License

MIT
