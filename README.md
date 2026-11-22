# trazos

**A lifelong, private-by-design archive for someone's art.** Scan or photograph a
child's drawings (or your own work) year after year, and trazos turns them into a
quiet static website: a timeline by year and age, tags, favourites, and each piece
with the story in the artist's own words.

[Live demo](https://jirulabs.com/trazos/) · [Español](#en-español)

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

## Languages, link previews and icon

- **Both languages.** `languages = ["es", "en"]` builds the site in each: `lang` at the root,
  the others under `/en/` (or `/es/`), with a link in the menu to switch. Only the site's own
  words change; titles, stories and tags are shown as you wrote them.
- **Link previews.** Set `url = "https://your-site.example"` and a link shared in WhatsApp,
  Telegram, Slack and the like shows the piece's title, picture and facts (Open Graph tags).
  `protect` lets those preview fetchers in (they read the one shared page and do not index);
  search engines and AI crawlers stay out. Without `url` a preview shows the title only.
  The archive's own link shows the newest favourite; `cover = "<piece id>"` picks another.
  A bare drawing there reads as a link to an image, so the archive's pages prefer a card
  made for sharing: `site/share.jpg` (or `site/share-<lang>.jpg`), 1200x630, which
  `tools/share-card.py` composes from up to three pieces, the title and a line (needs
  ImageMagick; run it where you have it, the build itself stays dependency-free). Each
  piece's own page keeps its drawing. The description is `description` /
  `description_<lang>`, or how many pieces and the years they span.
- **Icon.** Every site gets a page icon (a sheet of paper with one crayon stroke) as
  `favicon.svg`, `favicon.ico` and `apple-touch-icon.png`. Put your own files with those
  names in `site/` to replace it.

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
- **Months** are never shown: they only order each year from December back to January,
  newest first. A piece gets one only when the date is honest about it: `2026-05` in the
  name or a `month:` line always count; a full camera date counts unless 6 or more pieces
  share that exact day (a photo session of older work). Pieces without a month go last in
  their year, and their age is computed from the year alone.
- Optional `<same name>.txt` next to it: first lines `technique:`, `tags:`, `favourite: yes`,
  `month: june`, then the story.
- Each photo is turned upright, **cropped to the sheet of paper** when one is found (OpenCV;
  otherwise left whole; `--no-crop` always keeps the whole photo), resized and saved as JPEG
  with no metadata at all. HEIC works. Images are made once: after changing `--no-crop`,
  run once with `--reprocess` to redo them all.
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
month: 5
age: 5
technique: crayons
title: "The house of the sun"
tags: house, sun
favourite: no
---
The story in the artist's words. Blank lines separate paragraphs.
```

Only `id` and `year` are required. `month` is 1–12 (leave it out when you don't know it);
`age` may be a range (`4-5`); `order` sorts pieces inside a month (newest first).

## Admin mode

Add `admin = "owner/repo"` to `trazos.toml` (and, optionally, `admin_committer = "Name <email>"`
for the commits) and the site gets an **Entrar / Log in** link in the footer and a login page
at `/admin/`. There is no server: the page is static, and your browser edits the repo through
the GitHub API, so GitHub Pages republishes the site 1–2 minutes after each save.

- **Set up once.** Create a [fine-grained token](https://github.com/settings/personal-access-tokens/new)
  with access to *only* this repo and the permission *Contents: read and write*. Open `/admin/`,
  paste it and choose the admin password (12+ characters). The token is encrypted in the browser
  with that password (PBKDF2-SHA256, 600 000 rounds, AES-GCM) and committed as `admin-key.json`.
- **Log in** with user `admin` and that password. The token is decrypted in that tab only and
  forgotten when the tab closes. Change the password in *Settings*.
- **Edit** the title, story, artists (one or more, comma separated, shown as «By …» on the piece; empty = only the site's artist), technique, tags, favourite, year, month and age of any piece, and
  the basic settings (site title, artist, language, rights notice, protection). Piece edits go to
  `edits/<id>.json` and win over `pieces/<id>.md`, so a re-ingest never undoes them; clear a
  field and the original comes back.
- **Take a piece off the site** without deleting it: tick *Off the site* (`hidden: yes`). Its
  pages and images are left out of the build and of the admin's public `data.json`; the photo
  stays in the repo, and the admin lists it under *Off the site* (image fetched with the token)
  so you can bring it back.
- **Sync now** (`admin_sync = true`): a button that moves the `sync` branch (it rewrites
  `sync-request.json` there). Whatever ingests the source folder watches that branch with a
  cheap `git ls-remote origin refs/heads/sync` and runs early when its sha changes, so new
  photos need not wait for the scheduled run.
- **Honest limits.** `admin-key.json` is public, so the password is what protects the token:
  use a long one. If it leaks, revoke the token on GitHub; forgot it, delete `admin-key.json`
  and set up again. Public pages stay script-free; only `/admin/` runs a script.

## Content in a private repo

GitHub Pages (free) only publishes public repos, and anything committed to a public repo stays in
its history even after you delete it. To keep the artwork out of every public history, split it:

- **`<site>-contenido`**, private: `trazos.toml`, `pieces/`, `edits/`, `admin-key.json` and
  `site/CNAME`, i.e. everything a normal trazos repo has. Ingest and the admin write here.
- **`<site>`**, public: only `.github/workflows/pages.yml`, which calls the reusable `site`
  workflow of trazos, so the site's repo never holds a single image:

  ```yaml
  name: Pages
  on: { workflow_dispatch: {} }
  permissions: { contents: read, pages: write, id-token: write }
  concurrency: { group: pages, cancel-in-progress: true }
  jobs:
    site:
      uses: jiru-labs/trazos/.github/workflows/site.yml@v0.12.2
      with: { content: owner/site-contenido, trazos_ref: v0.12.2 }
      secrets: { content_key: "${{ secrets.CONTENT_KEY }}" }
  ```

Set up once: add a **read-only deploy key** to the private repo and its private half as the
`CONTENT_KEY` secret of the public one; set Pages to *GitHub Actions* (and the custom domain) on
the public repo. In the private repo's `trazos.toml` put `admin = "owner/site-contenido"` and
`admin_deploy = "owner/site"` (and `admin_sync = true` if a host ingests on request); the admin token then needs *Contents: read and write* on the
private repo and *Actions: read and write* on the public one, and every save asks the public
`pages.yml` to run. Whatever else writes the private repo (an ingest cron) runs the same
dispatch afterwards: `POST /repos/owner/site/actions/workflows/pages.yml/dispatches` with
`{"ref":"main"}`. The built site is kept as an artifact for one day only.

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
El mes no se muestra: solo ordena cada año de diciembre a enero. Lo que no sabemos de qué
mes es va al final de su año, hasta que lo nombres `2025-06 …` o pongas `mes: junio` en su `.txt`.
Pon `lang = "es"` en `trazos.toml` y sigue los pasos de arriba.
Con `languages = ["es", "en"]` la web sale también en inglés, bajo `/en/`, con un enlace para cambiar
de idioma (se traduce la web, no los títulos ni las historias). Con `url = "https://tu-web"` un enlace
compartido por WhatsApp o Telegram muestra el título y el dibujo. La portada es el favorito más reciente, o la obra que digas con `cover = "<id>"`; mejor aún, una tarjeta hecha para compartir en `site/share.jpg` (o `share-<idioma>.jpg`), que `tools/share-card.py` compone con tres dibujos, el título y una línea. Cada web lleva su icono de pestaña;
para usar uno tuyo, pon `favicon.svg`, `favicon.ico` y `apple-touch-icon.png` en `site/`.
Para editar títulos, historias y ajustes desde la propia web: `admin = "usuario/repo"` en `trazos.toml` y el enlace «Entrar» del pie (modo admin, arriba).

## License

MIT
