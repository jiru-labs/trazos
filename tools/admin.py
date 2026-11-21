#!/usr/bin/env python3
"""trazos admin: edit titles, stories and basic settings from a browser.

    admin.py CONTENT_DIR [--bind 127.0.0.1] [--port 8765] [--publish] [--lock FILE]
                         [--require-tailscale-user] [--site-url URL]

Each piece can be edited (title, story, technique, tags, favourite, year, month) and so can
the basic settings in trazos.toml (title, artist, language, rights notice, protection).
Piece edits go to CONTENT_DIR/edits/<id>.json, never to pieces/<id>.md: the ingest rewrites
those, and an edit must survive it. Only what differs from the ingested piece is stored, so
clearing a field brings back the original. Every save rebuilds the site to check it; a save
that would break the build is undone. With --publish, a save is also committed and pushed
(git), so the site updates on its own.

Accounts (--users FILE): user name and password, stored as PBKDF2 hashes in FILE (keep it
out of git). Nobody types a password for someone else: `--invite NAME` prints a one-time
link (valid 48 h) where that person picks their own; the same link resets a forgotten one.
`--remove-user NAME` takes access away. Changing a password logs that user out everywhere.
Without --users there is no login: then bind to localhost behind an authenticating proxy,
e.g. `tailscale serve` with --require-tailscale-user (tagged servers carry no user). The two
can be combined. Cross-site form posts are refused and the session cookie is SameSite=Strict.
Year or month edits recompute the age when TRAZOS_BIRTHDATE is set (it is never written).
Standard library only (Python 3.11+).
"""
import argparse
import datetime as dt
import fcntl
import hashlib
import hmac
import html
import re
import secrets
import json
import os
import subprocess
import sys
import time
import threading
import tomllib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import build  # noqa: E402  (the engine: same parsing and validation as the real build)

WRITE = threading.Lock()  # reads run in parallel (thumbnails); saves one at a time
EDITABLE = ("title", "story", "technique", "tags", "favourite", "year", "month")
UI = {
    "es": {"pieces": "Obras", "settings": "Ajustes", "save": "Guardar", "saved": "Guardado.",
           "published": "Guardado y publicado: la web se actualiza en 1-2 minutos.",
           "title": "Título", "story": "Historia", "technique": "Técnica", "tags": "Etiquetas (separadas por comas)",
           "favourite": "Favorito", "year": "Año", "month": "Mes (no se muestra; solo ordena)", "no_month": "Sin mes",
           "original": "del archivo", "reset": "Vacía un campo y vuelve el del archivo.",
           "site_title": "Título de la web", "artist": "Nombre de la artista", "lang": "Idioma",
           "rights": "Aviso de derechos (vacío = el de serie)", "protect": "Proteger (fuera de buscadores e IA)",
           "view": "Ver en la web", "back": "← Obras", "error": "No se guardó",
           "edited": "editada", "untitled": "Sin título", "user": "Usuario", "password": "Contraseña",
           "password2": "Repite la contraseña", "login": "Entrar", "logout": "Salir",
           "bad_login": "Usuario o contraseña incorrectos.", "locked": "Demasiados intentos: espera 15 minutos.",
           "welcome": "Hola, {user}. Elige tu contraseña (mínimo 10 caracteres).",
           "bad_invite": "Este enlace ya se usó o caducó.", "mismatch": "Las contraseñas no coinciden o son cortas."},
    "en": {"pieces": "Pieces", "settings": "Settings", "save": "Save", "saved": "Saved.",
           "published": "Saved and published: the site updates in 1-2 minutes.",
           "title": "Title", "story": "Story", "technique": "Technique", "tags": "Tags (comma separated)",
           "favourite": "Favourite", "year": "Year", "month": "Month (never shown; only orders)", "no_month": "No month",
           "original": "from the file", "reset": "Clear a field to bring back the one from the file.",
           "site_title": "Site title", "artist": "Artist's name", "lang": "Language",
           "rights": "Rights notice (empty = the default)", "protect": "Protect (no search engines, no AI)",
           "view": "View on the site", "back": "← Pieces", "error": "Not saved",
           "edited": "edited", "untitled": "Untitled", "user": "User", "password": "Password",
           "password2": "Repeat the password", "login": "Log in", "logout": "Log out",
           "bad_login": "Wrong user or password.", "locked": "Too many attempts: wait 15 minutes.",
           "welcome": "Hi, {user}. Choose your password (at least 10 characters).",
           "bad_invite": "This link was already used or has expired.", "mismatch": "The passwords differ or are too short."},
}
MONTHS = {"es": "enero febrero marzo abril mayo junio julio agosto septiembre octubre noviembre diciembre",
          "en": "January February March April May June July August September October November December"}
STYLE = """
.admin form { display: grid; gap: .9rem; max-width: 700px; }
.admin label { display: grid; gap: .25rem; font-weight: 600; }
.admin label.check { display: flex; gap: .5rem; align-items: center; }
.admin input[type=text], .admin input[type=number], .admin input[type=password], .admin select, .admin textarea {
  font: inherit; padding: .5rem .6rem; border: 2px solid var(--line); border-radius: 6px;
  background: var(--card); color: var(--fg); font-weight: 400; width: 100%; }
.admin textarea { min-height: 9rem; }
.admin small { color: var(--muted); font-weight: 400; }
.admin button { font: inherit; font-weight: 700; padding: .6rem 1.4rem; border: 0; border-radius: 99px;
  background: var(--accent); color: #fff; cursor: pointer; justify-self: start; }
.admin .msg { padding: .6rem .9rem; border-radius: 6px; background: var(--card); border-left: 4px solid var(--green); }
.admin .msg.bad { border-left-color: var(--red); }
.admin .piece-edit img { max-width: 100%; max-height: 55vh; border-radius: 6px; box-shadow: var(--shadow); }
.admin .card .badge { color: var(--violet); font-size: .8rem; }
.admin nav .logout { display: inline-flex; gap: .4rem; align-items: center; }
.admin nav .logout button { padding: .2rem .8rem; font-size: .85rem; background: var(--muted); }
"""


def e(s):
    return html.escape(str(s), quote=True)


class Users:
    """FILE = {"secret": hex, "users": {name: "pbkdf2_sha256$iters$salt$hash"},
    "invites": {sha256(token): {"user": name, "until": epoch}}}. Mode 0600, never in git."""
    ITER, DAYS, NAME_RE = 600_000, 30, re.compile(r"^[a-z0-9._-]{1,32}$")

    def __init__(self, path):
        self.path, self.fails, self.mutex = path, {}, threading.Lock()

    def load(self):
        if self.path.exists():
            return json.loads(self.path.read_text(encoding="utf-8"))
        return {"secret": secrets.token_hex(32), "users": {}, "invites": {}}

    def save(self, d):
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(d, indent=1), encoding="utf-8")
        os.chmod(tmp, 0o600)
        tmp.replace(self.path)

    @classmethod
    def digest(cls, pw, salt, iters=None):
        return hashlib.pbkdf2_hmac("sha256", pw.encode(), bytes.fromhex(salt), iters or cls.ITER).hex()

    def set_password(self, name, pw):
        with self.mutex:
            d, salt = self.load(), secrets.token_hex(16)
            d["users"][name] = f"pbkdf2_sha256${self.ITER}${salt}${self.digest(pw, salt)}"
            self.save(d)

    def remove(self, name):
        with self.mutex:
            d = self.load()
            found = d["users"].pop(name, None) is not None
            d["invites"] = {k: v for k, v in d.get("invites", {}).items() if v["user"] != name}
            self.save(d)
            return found

    def invite(self, name):
        with self.mutex:
            d, token = self.load(), secrets.token_urlsafe(24)
            d.setdefault("invites", {})[hashlib.sha256(token.encode()).hexdigest()] = \
                {"user": name, "until": int(time.time()) + 48 * 3600}
            self.save(d)
            return token

    def invited(self, token, consume=False):
        with self.mutex:
            d = self.load()
            key = hashlib.sha256(token.encode()).hexdigest()
            inv = d.get("invites", {}).get(key)
            if not inv or inv["until"] < time.time():
                return None
            if consume:
                d["invites"].pop(key)
                self.save(d)
            return inv["user"]

    def check(self, name, pw):
        """(ok, locked). Five failures for a name in 15 minutes lock it for the rest of them."""
        now = time.time()
        recent = [t for t in self.fails.get(name, []) if now - t < 900]
        if len(recent) >= 5:
            return False, True
        rec = self.load()["users"].get(name)
        if rec:
            _, iters, salt, h = rec.split("$")
            ok = hmac.compare_digest(self.digest(pw, salt, int(iters)), h)
        else:
            self.digest(pw, "00" * 16)  # same cost whether or not the user exists
            ok = False
        if not ok:
            self.fails[name] = recent + [now]
            time.sleep(1)
        return ok, False

    def _sig(self, d, name, until):
        # The password hash is in the key: changing a password ends that user's sessions.
        key = (d["secret"] + d["users"][name]).encode()
        return hmac.new(key, f"{name}|{until}".encode(), hashlib.sha256).hexdigest()

    def cookie(self, name):
        d, until = self.load(), int(time.time()) + self.DAYS * 86400
        return f"{name}|{until}|{self._sig(d, name, until)}"

    def who(self, value):
        try:
            name, until, sig = value.split("|")
            d = self.load()
            if int(until) > time.time() and name in d["users"] and hmac.compare_digest(sig, self._sig(d, name, until)):
                return name
        except (ValueError, KeyError):
            pass
        return None


def age_label(year, month, birth):
    """Same rule as tools/ingest.py: a whole month or a whole year can span two ages."""
    lo = dt.date(year, month or 1, 1)
    hi = (dt.date(year + (month == 12), month % 12 + 1, 1) - dt.timedelta(days=1)) if month else dt.date(year, 12, 31)
    age = lambda d: max(d.year - birth.year - ((d.month, d.day) < (birth.month, birth.day)), 0)
    a, b = age(lo), age(hi)
    return str(a) if a == b else f"{a}-{b}"


class Admin:
    def __init__(self, root, publish, lock, site_url, users=None):
        self.root, self.publish, self.lock, self.site_url = root, publish, lock, site_url.rstrip("/")
        self.users, self.ctx = users, threading.local()
        self.pieces, self.edits = root / "pieces", root / "edits"
        bd = os.environ.get("TRAZOS_BIRTHDATE")
        self.birth = dt.date.fromisoformat(bd) if bd else None

    # ---- data ----
    def cfg(self):
        return build.load_config(self.root)

    def ui(self):
        return UI.get(self.cfg()["lang"], UI["en"])

    def base(self, pid):
        """The ingested piece, before edits: {field: str} plus 'story'."""
        path = self.pieces / f"{pid}.md"
        text = path.read_text(encoding="utf-8")
        head, _, body = text.partition("\n---\n")
        meta = {}
        for line in head.splitlines()[1:]:
            k, _, v = line.partition(":")
            meta[k.strip()] = v.strip().strip('"')
        meta["story"] = body.strip()
        return meta

    def edit_of(self, pid):
        f = self.edits / f"{pid}.json"
        return json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}

    def all_pieces(self):
        out = []
        for md in self.pieces.glob("*.md"):
            p = build.parse(md, self.pieces)
            p["edited"] = (self.edits / f"{md.stem}.json").exists()
            out.append(p)
        return sorted(out, key=lambda p: (-p["year"], p["month"] is None, -(p["month"] or 0), -p["order"], p["id"]))

    # ---- writes ----
    def save_piece(self, pid, form):
        base, old = self.base(pid), self.edit_of(pid)
        new = {}
        for k in EDITABLE:
            v = form.get(k, "").replace("\r\n", "\n").strip()
            if k == "favourite":
                v = "yes" if v else "no"
                b = "yes" if base.get(k, "").lower() in ("yes", "sí", "si", "true") else "no"
            else:
                b = base.get(k, "")
            if k == "year" and not v:
                v = b  # the year is required: empty means "the original"
            if v != b:
                new[k] = v
        if not new.get("year", base["year"]).isdigit() or not 1900 <= int(new.get("year", base["year"])) <= 2200:
            return False, "year"
        if ("year" in new or "month" in new) and self.birth:
            y, m = new.get("year", base["year"]), new.get("month", base.get("month", ""))
            if y.isdigit() and (not m or m.isdigit()):
                age = age_label(int(y), int(m) if m else None, self.birth)
                if age != base.get("age", "").replace("–", "-"):
                    new["age"] = age
        path = self.edits / f"{pid}.json"
        self.edits.mkdir(exist_ok=True)
        if new:
            path.write_text(json.dumps(new, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        else:
            path.unlink(missing_ok=True)
        return self.commit(lambda: (path.write_text(json.dumps(old, ensure_ascii=False, indent=1) + "\n",
                                                    encoding="utf-8") if old else path.unlink(missing_ok=True)),
                           f"Edición: {pid}")

    def save_settings(self, form):
        path = self.root / "trazos.toml"
        old_text = path.read_text(encoding="utf-8")
        cfg = tomllib.loads(old_text)
        for k in ("title", "artist", "rights"):
            v = form.get(k, "").strip()
            if v:
                cfg[k] = v
            else:
                cfg.pop(k, None)
        cfg["lang"] = form.get("lang") if form.get("lang") in build.STRINGS else cfg.get("lang", "es")
        cfg["protect"] = bool(form.get("protect"))
        cfg.pop("noindex", None)
        lines = []
        for k, v in cfg.items():
            if isinstance(v, bool):
                lines.append(f"{k} = {'true' if v else 'false'}")
            elif isinstance(v, (int, float)):
                lines.append(f"{k} = {v}")
            else:
                lines.append(f"{k} = {json.dumps(str(v), ensure_ascii=False)}")
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return self.commit(lambda: path.write_text(old_text, encoding="utf-8"), "Ajustes de la web")

    def commit(self, undo, message):
        """Rebuild to validate; undo on failure; with --publish, commit and push.
        The lock (shared with the ingest) covers the build too: both write public/ and git."""
        lock = open(self.lock, "w") if self.lock else None
        try:
            if lock:
                for _ in range(240):  # the daily ingest may hold it for a minute or two
                    try:
                        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        break
                    except BlockingIOError:
                        time.sleep(0.5)
                else:
                    undo()
                    return False, "the ingest is running; try again in a minute"
            try:
                build.build(self.root)
            except (SystemExit, Exception) as err:  # anything the build rejects leaves no trace
                undo()
                try:
                    build.build(self.root)
                except (SystemExit, Exception):
                    pass
                return False, str(err) or type(err).__name__
            if not self.publish:
                return True, ""
            git = lambda *a: subprocess.run(["git", "-C", str(self.root), *a], capture_output=True, text=True)
            git("add", "--", "edits", "trazos.toml")
            if git("diff", "--cached", "--quiet").returncode == 0:
                return True, "published"
            r = git("commit", "-q", "-m", message)
            if r.returncode:
                return False, r.stderr.strip()[-300:]
            r = git("push", "-q")
            if r.returncode:
                return False, "saved locally, push failed: " + r.stderr.strip()[-300:]
            return True, "published"
        finally:
            if lock:
                lock.close()

    # ---- pages ----
    def page(self, title, body):
        cfg, t = self.cfg(), self.ui()
        return f"""<!doctype html><html lang="{e(cfg['lang'])}"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><meta name="robots" content="noindex, nofollow">
<title>{e(title)} · admin</title><link rel="stylesheet" href="/style.css"><style>{STYLE}</style></head>
<body class="admin"><header><a class="home" href="/">{e(cfg['title'])} · admin</a>
<nav><a href="/">{t['pieces']}</a><a href="/settings">{t['settings']}</a>{f'<a href="{e(self.site_url)}/">{t["view"]}</a>' if self.site_url else ''}{self.logout_form()}</nav>
</header><main>{body}</main></body></html>"""

    def logout_form(self):
        user = getattr(self.ctx, "user", None)
        if not (self.users and user):
            return ""
        return (f'<form class="logout" method="post" action="/logout"><small>{e(user)}</small> '
                f'<button>{self.ui()["logout"]}</button></form>')

    def login(self, nxt, error=""):
        t = self.ui()
        err = f'<p class="msg bad">{e(error)}</p>' if error else ""
        body = f"""<h1>{t['login']}</h1>{err}<form method="post" action="/login">
<input type="hidden" name="next" value="{e(nxt)}">
<label>{t['user']}<input type="text" name="user" autocomplete="username" autocapitalize="none" required></label>
<label>{t['password']}<input type="password" name="password" autocomplete="current-password" required></label>
<button>{t['login']}</button></form>"""
        return self.page(t["login"], body)

    def invite_page(self, user, error=""):
        t = self.ui()
        err = f'<p class="msg bad">{e(error)}</p>' if error else ""
        body = f"""<h1>{t['welcome'].format(user=e(user))}</h1>{err}<form method="post">
<input type="text" name="user" value="{e(user)}" autocomplete="username" hidden>
<label>{t['password']}<input type="password" name="password" minlength="10" autocomplete="new-password" required></label>
<label>{t['password2']}<input type="password" name="password2" minlength="10" autocomplete="new-password" required></label>
<button>{t['save']}</button></form>"""
        return self.page(t["login"], body)

    def msg(self, q):
        t = self.ui()
        if "ok" in q:
            return f'<p class="msg">{t["published"] if q["ok"][0] == "published" else t["saved"]}</p>'
        if "err" in q:
            return f'<p class="msg bad">{t["error"]}: {e(q["err"][0])}</p>'
        return ""

    def index(self, q):
        t, parts, year = self.ui(), [], None
        items = self.all_pieces()
        for p in items:
            if p["year"] != year:
                if year is not None:
                    parts.append("</div></section>")
                year = p["year"]
                parts.append(f'<section><h2>{year}</h2><div class="grid">')
            label = p.get("title") or t["untitled"]
            badge = f' <small class="badge">· {t["edited"]}</small>' if p["edited"] else ""
            parts.append(f'<a class="card" href="/piece/{e(p["id"])}"><img src="/img/{e(p["id"])}-thumb.jpg" alt="" loading="lazy">'
                         f'<span>{e(label)}{badge}</span></a>')
        if items:
            parts.append("</div></section>")
        return self.page(t["pieces"], self.msg(q) + "".join(parts))

    def piece(self, pid, q):
        t, lang = self.ui(), self.cfg()["lang"]
        base, cur = self.base(pid), {**self.base(pid), **self.edit_of(pid)}
        fav = cur.get("favourite", "").lower() in ("yes", "sí", "si", "true")
        months = MONTHS.get(lang, MONTHS["en"]).split()
        opts = f'<option value="">{t["no_month"]}</option>' + "".join(
            f'<option value="{i}"{" selected" if cur.get("month") == str(i) else ""}>{e(m)}</option>'
            for i, m in enumerate(months, 1))
        hint = lambda k: f' <small>({t["original"]}: {e(base.get(k) or "—")})</small>' if base.get(k, "") != cur.get(k, "") else ""
        link = f'<p><a href="{e(self.site_url)}/piece/{e(pid)}.html">{t["view"]}</a></p>' if self.site_url else ""
        body = f"""<p><a href="/">{t['back']}</a></p>{self.msg(q)}<div class="piece-edit">
<img src="/img/{e(pid)}.jpg" alt="">{link}
<form method="post">
<label>{t['title']}{hint('title')}<input type="text" name="title" value="{e(cur.get('title', ''))}" placeholder="{e(base.get('title', ''))}"></label>
<label>{t['story']}<textarea name="story">{e(cur.get('story', ''))}</textarea></label>
<label>{t['technique']}{hint('technique')}<input type="text" name="technique" value="{e(cur.get('technique', ''))}"></label>
<label>{t['tags']}{hint('tags')}<input type="text" name="tags" value="{e(cur.get('tags', ''))}"></label>
<label class="check"><input type="checkbox" name="favourite" value="1"{' checked' if fav else ''}> {t['favourite']}</label>
<label>{t['year']}{hint('year')}<input type="number" name="year" min="1900" max="2200" value="{e(cur.get('year', ''))}"></label>
<label>{t['month']}{hint('month')}<select name="month">{opts}</select></label>
<small>{t['reset']}</small>
<button>{t['save']}</button></form></div>"""
        return self.page(cur.get("title") or t["untitled"], body)

    def settings(self, q):
        t, cfg = self.ui(), self.cfg()
        raw = tomllib.loads((self.root / "trazos.toml").read_text(encoding="utf-8"))
        langs = "".join(f'<option{" selected" if cfg["lang"] == k else ""}>{k}</option>' for k in build.STRINGS)
        body = f"""{self.msg(q)}<h1>{t['settings']}</h1><form method="post">
<label>{t['site_title']}<input type="text" name="title" value="{e(raw.get('title', ''))}" placeholder="{e(cfg['title'])}"></label>
<label>{t['artist']}<input type="text" name="artist" value="{e(cfg['artist'])}" required></label>
<label>{t['lang']}<select name="lang">{langs}</select></label>
<label>{t['rights']}<textarea name="rights">{e(raw.get('rights', ''))}</textarea></label>
<label class="check"><input type="checkbox" name="protect" value="1"{' checked' if cfg['protect'] else ''}> {t['protect']}</label>
<button>{t['save']}</button></form>"""
        return self.page(t["settings"], body)


def handler(admin, require_ts):
    users = admin.users

    class H(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            who = getattr(admin.ctx, "user", None) or self.headers.get("Tailscale-User-Login", "-")
            sys.stderr.write("admin: %s %s\n" % (who, fmt % args))

        def allowed(self):
            admin.ctx.user = None
            if require_ts and not self.headers.get("Tailscale-User-Login"):
                self.send_error(403, "tailnet users only")
                return False
            return True

        def session(self):
            for part in self.headers.get("Cookie", "").split(";"):
                k, _, v = part.strip().partition("=")
                if k == "trazos_admin":
                    return users.who(v)
            return None

        def cookie_header(self, value, max_age):
            local = self.headers.get("Host", "").split(":")[0] in ("localhost", "127.0.0.1")
            return (f"trazos_admin={value}; Path=/; HttpOnly; SameSite=Strict; Max-Age={max_age}"
                    + ("" if local else "; Secure"))

        def send(self, body, ctype="text/html; charset=utf-8", code=200, cookie=None):
            data = body if isinstance(body, bytes) else body.encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Referrer-Policy", "no-referrer")  # invite tokens never leak
            if cookie:
                self.send_header("Set-Cookie", cookie)
            self.end_headers()
            self.wfile.write(data)

        def redirect(self, to, cookie=None):
            self.send_response(303)
            self.send_header("Location", to)
            if cookie:
                self.send_header("Set-Cookie", cookie)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def gate(self, path):
            """True when the request may go on; otherwise it has been answered (login page)."""
            if not users:
                return True
            admin.ctx.user = self.session()
            if admin.ctx.user:
                return True
            self.redirect("/login?next=" + quote(path))
            return False

        def do_GET(self):
            if not self.allowed():
                return
            u = urlparse(self.path)
            q, parts = parse_qs(u.query), u.path.strip("/").split("/")
            if u.path == "/style.css":
                return self.send((build.ASSETS / "style.css").read_bytes(), "text/css")
            if users and u.path == "/login":
                return self.send(admin.login(q.get("next", ["/"])[0]))
            if users and len(parts) == 2 and parts[0] == "invite":
                who = users.invited(parts[1])
                return self.send(admin.invite_page(who) if who else admin.login("/", admin.ui()["bad_invite"]))
            if not self.gate(u.path):
                return
            if u.path == "/":
                return self.send(admin.index(q))
            if u.path == "/settings":
                return self.send(admin.settings(q))
            if len(parts) == 2 and parts[0] == "piece" and (admin.pieces / f"{parts[1]}.md").exists() \
                    and build.ID_RE.match(parts[1]):
                return self.send(admin.piece(parts[1], q))
            if len(parts) == 2 and parts[0] == "img":
                name = parts[1]
                stem = name.removesuffix(".jpg").removesuffix("-thumb")
                if build.ID_RE.match(stem) and name in (f"{stem}.jpg", f"{stem}-thumb.jpg") and (admin.pieces / name).exists():
                    return self.send((admin.pieces / name).read_bytes(), "image/jpeg")
            self.send_error(404)

        def do_POST(self):
            if not self.allowed():
                return
            # Refuse posts that another site's page could forge (CSRF).
            origin, host = self.headers.get("Origin"), self.headers.get("Host", "")
            if self.headers.get("Sec-Fetch-Site", "same-origin") not in ("same-origin", "none") or \
                    (origin and urlparse(origin).netloc != host):
                return self.send_error(403, "cross-site post refused")
            n = int(self.headers.get("Content-Length") or 0)
            if n > 200_000:
                return self.send_error(413)
            form = {k: v[0] for k, v in parse_qs(self.rfile.read(n).decode("utf-8"), keep_blank_values=True).items()}
            path, parts = urlparse(self.path).path, urlparse(self.path).path.strip("/").split("/")
            t = admin.ui()
            if users and path == "/login":
                name, nxt = form.get("user", "").strip().lower(), form.get("next", "/")
                nxt = nxt if nxt.startswith("/") and not nxt.startswith("//") else "/"
                ok, locked = users.check(name, form.get("password", ""))
                if not ok:
                    return self.send(admin.login(nxt, t["locked"] if locked else t["bad_login"]), code=401)
                return self.redirect(nxt, self.cookie_header(users.cookie(name), Users.DAYS * 86400))
            if users and path == "/logout":
                return self.redirect("/login", self.cookie_header("", 0))
            if users and len(parts) == 2 and parts[0] == "invite":
                who = users.invited(parts[1])
                if not who:
                    return self.send(admin.login("/", t["bad_invite"]), code=410)
                pw = form.get("password", "")
                if len(pw) < 10 or pw != form.get("password2"):
                    return self.send(admin.invite_page(who, t["mismatch"]), code=400)
                if not users.invited(parts[1], consume=True):
                    return self.send(admin.login("/", t["bad_invite"]), code=410)
                users.set_password(who, pw)
                return self.redirect("/", self.cookie_header(users.cookie(who), Users.DAYS * 86400))
            if not self.gate(path):
                return
            if path == "/settings":
                with WRITE:
                    ok, info = admin.save_settings(form)
            elif len(parts) == 2 and parts[0] == "piece" and build.ID_RE.match(parts[1]) \
                    and (admin.pieces / f"{parts[1]}.md").exists():
                with WRITE:
                    ok, info = admin.save_piece(parts[1], form)
            else:
                return self.send_error(404)
            self.redirect(f"{path}?ok={quote(info or 'saved')}" if ok else f"{path}?err={quote(info)}")
    return H


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("content", type=Path, nargs="?")
    ap.add_argument("--bind", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--publish", action="store_true", help="commit and push every save")
    ap.add_argument("--lock", type=Path, help="flock this file while committing (share it with the ingest)")
    ap.add_argument("--require-tailscale-user", action="store_true")
    ap.add_argument("--site-url", default="", help="public site, for 'view' links")
    ap.add_argument("--users", type=Path, help="accounts file (JSON, mode 0600, never in git)")
    ap.add_argument("--invite", metavar="NAME", help="print a one-time link for NAME to set a password, and exit")
    ap.add_argument("--remove-user", metavar="NAME", help="remove NAME's access, and exit")
    ap.add_argument("--base-url", default="", help="where the admin is reached, for --invite links")
    a = ap.parse_args()
    users = Users(a.users) if a.users else None
    if a.invite or a.remove_user:
        if not users:
            ap.error("--invite and --remove-user need --users")
        if a.remove_user:
            print("removed" if users.remove(a.remove_user) else "no such user")
            return
        if not Users.NAME_RE.match(a.invite):
            ap.error("user names are lowercase letters, digits, '.', '_' or '-'")
        print(f"{a.base_url.rstrip('/') or f'http://{a.bind}:{a.port}'}/invite/{users.invite(a.invite)}")
        return
    if not a.content:
        ap.error("CONTENT_DIR is required")
    root = a.content.resolve()
    build.load_config(root)  # fail early on a bad content folder
    if users and not users.path.exists():
        users.save(users.load())  # creates the secret; still nobody can log in until invited
    admin = Admin(root, a.publish, a.lock, a.site_url, users)
    print(f"trazos admin: http://{a.bind}:{a.port}/ -> {root}{' (login required)' if users else ''}", flush=True)
    ThreadingHTTPServer((a.bind, a.port), handler(admin, a.require_tailscale_user)).serve_forever()


if __name__ == "__main__":
    main()
