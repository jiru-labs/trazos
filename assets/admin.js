// trazos /admin/: log in as admin and edit pieces and settings, with no server.
// The GitHub token (fine-grained, this repo only, Contents read/write; plus Actions read/write on
// the `admin_deploy` repo when the site is published from another one) lives in admin-key.json,
// encrypted with the admin password (PBKDF2-SHA256 600k + AES-GCM). Logging in decrypts it in
// this tab only (sessionStorage); saves are commits through the GitHub API, and GitHub Pages
// rebuilds the site (or, with `admin_deploy`, we ask that repo's pages.yml to run). Edits go to edits/<id>.json and settings to trazos.toml.
"use strict";

const API = "https://api.github.com";
const ITER = 600000;
const S = {
  es: {
    login: "Entrar como admin", user: "Usuario", password: "Contraseña", password2: "Repite la contraseña",
    enter: "Entrar", bad_login: "Usuario o contraseña incorrectos.", back_site: "← Volver a la web",
    setup: "Configurar el admin", setup_help: "Solo una vez. Pega un token de GitHub «fine-grained» con acceso solo a {repo} (permiso Contents: lectura y escritura) y elige la contraseña de admin (12 caracteres o más). El token se guarda cifrado con ella; el usuario es «admin».",
    setup_deploy: " La web se publica desde {deploy}: dale también permiso Actions: lectura y escritura en ese repo.",
    bad_deploy: "El token no puede publicar {deploy} (permiso Actions: lectura y escritura).",
    not_published: "Guardado, pero no se pudo pedir la publicación",
    hidden: "Quitada de la web (no se borra: sigue en el archivo y aquí)", removed: "Quitadas de la web", badge_removed: "quitada",
    sync: "Sincronizar ahora", sync_help: "Trae ya las fotos nuevas de la carpeta de origen, sin esperar a la sincronización diaria.",
    sync_asked: "Pedido. Lo nuevo aparece en la web en unos minutos.",
    token: "Token de GitHub", bad_token: "Ese token no es «fine-grained» (github_pat_…) o no puede escribir en {repo}.",
    bad_pw: "Las contraseñas no coinciden o tienen menos de 12 caracteres.",
    pieces: "Obras", settings: "Ajustes", logout: "Salir", save: "Guardar",
    saved: "Guardado. La web se actualiza en 1–2 minutos.", error: "No se guardó",
    title: "Título", story: "Historia", technique: "Técnica", tags: "Etiquetas (separadas por comas)",
    favourite: "Favorito", year: "Año", month: "Mes (no se muestra; solo ordena)", no_month: "Sin mes",
    age: "Edad (5, o 4-5)", original: "del archivo", reset: "Vacía un campo y vuelve el del archivo.",
    site_title: "Título de la web", artist: "Nombre de la artista", lang: "Idioma",
    rights: "Aviso de derechos (vacío = el de serie)", protect: "Proteger (fuera de buscadores e IA)",
    back: "← Obras", edited: "editada", untitled: "Sin título", loading: "Cargando…",
    change_pw: "Cambiar la contraseña", new_pw: "Contraseña nueva", pw_changed: "Contraseña cambiada.",
    bad_year: "El año tiene que ser de 1900 a 2200.", bad_age: "La edad es un número o un rango como 4-5.",
    need_artist: "El nombre de la artista no puede quedar vacío.",
    months: "enero febrero marzo abril mayo junio julio agosto septiembre octubre noviembre diciembre",
  },
  en: {
    login: "Log in as admin", user: "User", password: "Password", password2: "Repeat the password",
    enter: "Log in", bad_login: "Wrong user or password.", back_site: "← Back to the site",
    setup: "Set up the admin", setup_help: "Only once. Paste a fine-grained GitHub token with access to {repo} only (Contents: read and write) and choose the admin password (12 characters or more). The token is stored encrypted with it; the user is \"admin\".",
    setup_deploy: " The site is published from {deploy}: also give it Actions: read and write on that repo.",
    bad_deploy: "The token cannot publish {deploy} (Actions: read and write).",
    not_published: "Saved, but publishing could not be requested",
    hidden: "Off the site (not deleted: it stays in the archive and here)", removed: "Off the site", badge_removed: "off the site",
    sync: "Sync now", sync_help: "Bring in the new photos from the source folder now, without waiting for the daily sync.",
    sync_asked: "Requested. The new pieces show on the site in a few minutes.",
    token: "GitHub token", bad_token: "That token is not fine-grained (github_pat_…) or cannot write to {repo}.",
    bad_pw: "The passwords differ or are shorter than 12 characters.",
    pieces: "Pieces", settings: "Settings", logout: "Log out", save: "Save",
    saved: "Saved. The site updates in 1–2 minutes.", error: "Not saved",
    title: "Title", story: "Story", technique: "Technique", tags: "Tags (comma separated)",
    favourite: "Favourite", year: "Year", month: "Month (never shown; only orders)", no_month: "No month",
    age: "Age (5, or 4-5)", original: "from the file", reset: "Clear a field to bring back the one from the file.",
    site_title: "Site title", artist: "Artist's name", lang: "Language",
    rights: "Rights notice (empty = the default)", protect: "Protect (no search engines, no AI)",
    back: "← Pieces", edited: "edited", untitled: "Untitled", loading: "Loading…",
    change_pw: "Change the password", new_pw: "New password", pw_changed: "Password changed.",
    bad_year: "The year must be from 1900 to 2200.", bad_age: "The age is a number or a range like 4-5.",
    need_artist: "The artist's name cannot be empty.",
    months: "January February March April May June July August September October November December",
  },
};

let data, T, token = null;
try { token = sessionStorage.getItem("trazos-token"); } catch (_) { /* private mode: log in each time */ }
const app = document.getElementById("app"), nav = document.getElementById("nav");

// ---- small DOM helper: never innerHTML ----
function h(tag, attrs, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === false || v == null) continue;
    if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (v === true) el.setAttribute(k, "");
    else el.setAttribute(k, v);
  }
  for (const k of kids.flat()) if (k != null && k !== false) el.append(k);
  return el;
}
const show = (...kids) => { app.replaceChildren(...kids); window.scrollTo(0, 0); };
const msg = (text, bad) => h("p", { class: bad ? "msg bad" : "msg" }, text);
const fmt = (s) => s.replace("{repo}", data.repo).replace("{deploy}", data.deploy || "");

// ---- encoding and crypto ----
const enc = new TextEncoder(), dec = new TextDecoder();
const b64 = (bytes) => { let x = ""; for (const c of bytes) x += String.fromCharCode(c); return btoa(x); };
const unb64 = (s) => Uint8Array.from(atob(s.replace(/\s/g, "")), (c) => c.charCodeAt(0));

async function keyFrom(pw, salt, iter) {
  const base = await crypto.subtle.importKey("raw", enc.encode(pw), "PBKDF2", false, ["deriveKey"]);
  return crypto.subtle.deriveKey({ name: "PBKDF2", salt, iterations: iter, hash: "SHA-256" },
    base, { name: "AES-GCM", length: 256 }, false, ["encrypt", "decrypt"]);
}
async function seal(secret, pw) {
  const salt = crypto.getRandomValues(new Uint8Array(16)), iv = crypto.getRandomValues(new Uint8Array(12));
  const ct = await crypto.subtle.encrypt({ name: "AES-GCM", iv }, await keyFrom(pw, salt, ITER), enc.encode(secret));
  return JSON.stringify({ v: 1, user: "admin", kdf: "PBKDF2-SHA256", iter: ITER,
    salt: b64(salt), iv: b64(iv), ct: b64(new Uint8Array(ct)) }, null, 1) + "\n";
}
async function unseal(blob, pw) {
  const key = await keyFrom(pw, unb64(blob.salt), blob.iter);
  return dec.decode(await crypto.subtle.decrypt({ name: "AES-GCM", iv: unb64(blob.iv) }, key, unb64(blob.ct)));
}

// ---- GitHub API ----
async function gh(path, opts = {}) {
  const headers = { Accept: "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28" };
  if (opts.auth !== false && token) headers.Authorization = `Bearer ${token}`;
  if (opts.body) headers["Content-Type"] = "application/json";
  const r = await fetch(API + path, { method: opts.method || "GET", headers, body: opts.body, cache: "no-store" });
  if (r.status === 404 && opts.allow404) return null;
  if (!r.ok) {
    const j = await r.json().catch(() => ({}));
    throw new Error(`GitHub ${r.status}${j.message ? ": " + j.message : ""}`);
  }
  return r.status === 204 ? null : r.json();
}
const repoPath = (p) => `/repos/${data.repo}/contents/${p.split("/").map(encodeURIComponent).join("/")}`;
async function getFile(p, auth) {
  const j = await gh(repoPath(p), { allow404: true, auth });
  return j && { sha: j.sha, text: dec.decode(unb64(j.content)) };
}
function commitBody(message, extra) {
  const m = /^(.+) <(.+)>$/.exec(data.committer || "");
  return JSON.stringify({ message, ...(m ? { committer: { name: m[1], email: m[2] } } : {}), ...extra });
}
const putFile = (p, text, sha, message) => gh(repoPath(p), { method: "PUT",
  body: commitBody(message, { content: b64(enc.encode(text)), ...(sha ? { sha } : {}) }) });
const deleteFile = (p, sha, message) => gh(repoPath(p), { method: "DELETE", body: commitBody(message, { sha }) });
// With `admin_deploy` the site repo does not see our commits: ask its pages.yml to run.
const dispatch = () => gh(`/repos/${data.deploy}/actions/workflows/pages.yml/dispatches`,
  { method: "POST", body: JSON.stringify({ ref: "main" }) });
async function republish() {  // null when fine, else the message to show instead of T.saved
  if (!data.deploy) return null;
  try { await dispatch(); return null; } catch (err) { return `${T.not_published}: ${err.message}`; }
}
// `admin_sync = true`: whoever ingests (a host cron) watches the `sync` branch with a cheap
// `git ls-remote` and runs early when it moves; we move it by rewriting sync-request.json there.
async function requestSync() {
  const base = `/repos/${data.repo}`;
  if (!await gh(`${base}/git/ref/heads/sync`, { allow404: true })) {
    const repo = await gh(base), head = await gh(`${base}/git/ref/heads/${repo.default_branch}`);
    await gh(`${base}/git/refs`, { method: "POST", body: JSON.stringify({ ref: "refs/heads/sync", sha: head.object.sha }) });
  }
  const f = await gh(repoPath("sync-request.json") + "?ref=sync", { allow404: true });
  const text = JSON.stringify({ requested: new Date().toISOString() }) + "\n";
  await gh(repoPath("sync-request.json"), { method: "PUT",
    body: commitBody("Admin: sincronizar", { content: b64(enc.encode(text)), branch: "sync", ...(f ? { sha: f.sha } : {}) }) });
}
function syncBox() {
  const out = h("div"), btn = h("button", { type: "button", onclick: async () => {
    btn.disabled = true;
    try { await requestSync(); out.replaceChildren(msg(T.sync_asked)); }
    catch (err) { out.replaceChildren(msg(`${T.error}: ${err.message}`, true)); btn.disabled = false; }
  } }, T.sync);
  return h("section", { class: "sync" }, h("p", {}, btn, " ", h("small", {}, T.sync_help)), out);
}
const savedMsg = (note) => msg(note || T.saved, !!note);

// The key: the published copy, or straight from the repo when the site has not rebuilt yet.
async function loadKey() {
  try {
    const r = await fetch("key.json", { cache: "no-store" });
    if (r.ok) return await r.json();
  } catch (_) { /* fall through */ }
  const f = await getFile("admin-key.json", false).catch(() => null);
  return f ? JSON.parse(f.text) : null;
}

// ---- session ----
function setToken(t) {
  token = t;
  try { t ? sessionStorage.setItem("trazos-token", t) : sessionStorage.removeItem("trazos-token"); } catch (_) {}
}
function renderNav() {
  nav.replaceChildren(...(token ? [
    h("a", { href: "#/" }, T.pieces), h("a", { href: "#/settings" }, T.settings),
    h("button", { type: "button", onclick: () => { setToken(null); location.hash = "#/"; route(); } }, T.logout),
  ] : []));
}

function busy(form, on) { for (const b of form.querySelectorAll("button")) b.disabled = on; }

// ---- views ----
async function loginView() {
  show(h("p", {}, T.loading));
  const key = await loadKey();
  const back = h("p", {}, h("a", { href: "../index.html" }, T.back_site));
  if (!key) return setupView(back);
  const out = h("div");
  const form = h("form", { onsubmit: async (ev) => {
    ev.preventDefault();
    busy(form, true);
    const user = form.elements.namedItem("user").value.trim().toLowerCase();
    try {
      if (user !== (key.user || "admin")) throw new Error("user");
      setToken(await unseal(key, form.elements.namedItem("password").value));
      route();
    } catch (_) {
      out.replaceChildren(msg(T.bad_login, true));
      busy(form, false);
    }
  } },
    h("label", {}, T.user, h("input", { type: "text", name: "user", autocomplete: "username", autocapitalize: "none", spellcheck: "false", required: true })),
    h("label", {}, T.password, h("input", { type: "password", name: "password", autocomplete: "current-password", required: true })),
    h("button", {}, T.enter));
  show(h("section", { class: "login" }, h("h1", {}, T.login), out, form, back));
  form.elements.namedItem("user").focus();
}

function setupView(back) {
  const out = h("div");
  const form = h("form", { onsubmit: async (ev) => {
    ev.preventDefault();
    const pw = form.elements.namedItem("password").value, tk = form.elements.namedItem("token").value.trim();
    if (pw.length < 12 || pw !== form.elements.namedItem("password2").value) return out.replaceChildren(msg(T.bad_pw, true));
    busy(form, true);
    try {
      token = tk;
      const repo = await gh(`/repos/${data.repo}`);
      if (!tk.startsWith("github_pat_") || !repo.permissions || !repo.permissions.push) throw new Error(fmt(T.bad_token));
      if (data.deploy) await dispatch().catch((err) => { throw new Error(`${fmt(T.bad_deploy)} (${err.message})`); });
      const old = await getFile("admin-key.json");
      await putFile("admin-key.json", await seal(tk, pw), old && old.sha, "Admin: clave cifrada");
      await republish();
      setToken(tk);
      route();
    } catch (err) {
      token = null;
      out.replaceChildren(msg(err.message.startsWith("GitHub") ? fmt(T.bad_token) + ` (${err.message})` : err.message, true));
      busy(form, false);
    }
  } },
    h("label", {}, T.user, h("input", { type: "text", name: "user", value: "admin", autocomplete: "username", readonly: true })),
    h("label", {}, T.token, h("input", { type: "password", name: "token", autocomplete: "off", required: true })),
    h("label", {}, T.password, h("input", { type: "password", name: "password", autocomplete: "new-password", minlength: "12", required: true })),
    h("label", {}, T.password2, h("input", { type: "password", name: "password2", autocomplete: "new-password", minlength: "12", required: true })),
    h("button", {}, T.save));
  show(h("section", { class: "login" }, h("h1", {}, T.setup), h("p", {}, h("small", {}, fmt(T.setup_help) + (data.deploy ? fmt(T.setup_deploy) : ""))), out, form, back));
}

// Pieces taken off the site are not in data.json (it is public): read them from the repo.
function frontMatter(text) {
  const m = /^---\n([\s\S]*?)\n---\n?([\s\S]*)$/.exec(text);
  if (!m) return null;
  const meta = {};
  for (const line of m[1].split("\n")) {
    const i = line.indexOf(":");
    if (i > 0 && !line.trim().startsWith("#")) meta[line.slice(0, i).trim()] = line.slice(i + 1).trim().replace(/^"|"$/g, "");
  }
  meta.story = m[2].trim();
  return meta;
}
let removedKnown = false;
async function loadRemoved() {
  const repo = await gh(`/repos/${data.repo}`);
  const tree = await gh(`/repos/${data.repo}/git/trees/${repo.default_branch}?recursive=1`);
  const known = new Set(data.pieces.map((p) => p.id));
  const ids = tree.tree.map((t) => /^pieces\/([^/]+)\.md$/.exec(t.path)).filter(Boolean).map((m) => m[1]).filter((id) => !known.has(id));
  for (const id of ids) {
    const md = await getFile(`pieces/${id}.md`), ed = await getFile(`edits/${id}.json`);
    const base = md && frontMatter(md.text);
    if (!base) continue;
    const cur = { ...base, ...(ed ? JSON.parse(ed.text) : {}) };
    if (!isYes(cur.hidden)) continue;  // not hidden: just not built yet (a fresh ingest)
    data.pieces.push({ id, year: +cur.year || 0, month: cur.month ? +cur.month : null, order: +base.order || 0,
      title: cur.title || "", base, hidden: true, edited: !!ed, fromRepo: true });
  }
}
// The published images of a hidden piece (or one just brought back, until the rebuild) are gone: fetch it from the repo with the token.
function pieceImg(p, suffix, attrs) {
  if (!p.hidden && !p.fromRepo) return h("img", { src: `../img/${p.id}${suffix}.jpg`, alt: "", ...attrs });
  const img = h("img", { alt: "", ...attrs });
  fetch(API + repoPath(`pieces/${p.id}${suffix}.jpg`), { cache: "no-store",
    headers: { Accept: "application/vnd.github.raw", Authorization: `Bearer ${token}` } })
    .then((r) => (r.ok ? r.blob() : null)).then((b) => { if (b) img.src = URL.createObjectURL(b); }).catch(() => {});
  return img;
}

let editedKnown = false;
async function listView() {
  if (!editedKnown) {  // which pieces already carry edits: one cheap listing of edits/
    const list = await gh(repoPath("edits"), { allow404: true }).catch(() => null);
    const ids = new Set((list || []).map((f) => f.name.replace(/\.json$/, "")));
    for (const p of data.pieces) p.edited = ids.has(p.id);
    editedKnown = true;
  }
  if (!removedKnown) { await loadRemoved().catch(() => {}); removedKnown = true; }
  const parts = [], shown = data.pieces.filter((p) => !p.hidden), removed = data.pieces.filter((p) => p.hidden);
  const card = (p) => h("a", { class: "card", href: `#/piece/${p.id}` }, pieceImg(p, "-thumb", { loading: "lazy" }),
    h("span", {}, p.title || T.untitled, p.edited && !p.hidden ? h("small", { class: "badge" }, " · " + T.edited) : null,
      p.hidden ? h("small", { class: "badge" }, " · " + T.badge_removed) : null));
  const years = [...new Set(shown.map((p) => p.year))].sort((a, b) => b - a);
  for (const y of years) {
    const items = shown.filter((p) => p.year === y).sort((a, b) =>
      (a.month == null) - (b.month == null) || (b.month || 0) - (a.month || 0) || b.order - a.order || (a.id < b.id ? -1 : 1));
    parts.push(h("section", {}, h("h2", {}, String(y)), h("div", { class: "grid" }, items.map(card))));
  }
  if (removed.length) parts.push(h("section", {}, h("h2", {}, T.removed), h("div", { class: "grid" }, removed.map(card))));
  show(h("h1", {}, T.pieces), ...(data.sync ? [syncBox()] : []), ...parts);
}

const FIELDS = ["title", "story", "technique", "tags", "favourite", "year", "month", "age"];
const isYes = (v) => ["yes", "sí", "si", "true"].includes(String(v || "").toLowerCase());

async function pieceView(id) {
  const p = data.pieces.find((x) => x.id === id);
  if (!p) return listView();  // unknown id: back to the list
  show(h("p", {}, T.loading));
  const file = await getFile(`edits/${id}.json`);
  const edits = file ? JSON.parse(file.text) : {};
  const base = p.base, cur = { ...base, ...edits };
  const months = T.months.split(" ");
  const hint = (k, shown) => (String(base[k] || "") !== String(cur[k] || "")
    ? h("small", {}, ` (${T.original}: ${shown !== undefined ? shown : base[k] || "—"})`) : null);
  const out = h("div");
  const text = (k, label) => h("label", {}, label, hint(k), h("input", { type: "text", name: k, value: cur[k] || "" }));
  const form = h("form", { onsubmit: async (ev) => {
    ev.preventDefault();
    const v = {
      title: form.elements.namedItem("title").value.trim(), story: form.elements.namedItem("story").value.trim(), technique: form.elements.namedItem("technique").value.trim(),
      tags: form.elements.namedItem("tags").value.trim(), year: form.elements.namedItem("year").value.trim(), age: form.elements.namedItem("age").value.trim(), month: form.elements.namedItem("month").value,
    };
    if (v.year && !(/^\d{4}$/.test(v.year) && +v.year >= 1900 && +v.year <= 2200)) return out.replaceChildren(msg(T.bad_year, true));
    if (v.age && !/^\d+(\s*[-–]\s*\d+)?$/.test(v.age)) return out.replaceChildren(msg(T.bad_age, true));
    const next = {};
    for (const k of ["title", "story", "technique", "tags", "year", "age"]) {
      if (v[k] && v[k] !== String(base[k] || "").trim()) next[k] = v[k];  // empty = back to the original
    }
    if (v.month !== String(base.month || "")) next.month = v.month;
    if (form.elements.namedItem("favourite").checked !== isYes(base.favourite)) next.favourite = form.elements.namedItem("favourite").checked ? "yes" : "no";
    const off = form.elements.namedItem("hidden").checked;
    if (off !== isYes(base.hidden)) next.hidden = off ? "yes" : "no";
    busy(form, true);
    try {
      if (Object.keys(next).length) await putFile(`edits/${id}.json`, JSON.stringify(next, null, 1) + "\n", file && file.sha, `Admin: ${id}`);
      else if (file) await deleteFile(`edits/${id}.json`, file.sha, `Admin: ${id} (original)`);
      p.title = next.title || base.title;
      p.edited = Object.keys(next).length > 0;
      p.hidden = off;
      const note = await republish();
      await pieceView(id);
      app.querySelector("form").before(savedMsg(note));
    } catch (err) {
      out.replaceChildren(msg(`${T.error}: ${err.message}`, true));
      busy(form, false);
    }
  } },
    text("title", T.title),
    h("label", {}, T.story, hint("story", "…"), h("textarea", { name: "story" }, cur.story || "")),
    text("technique", T.technique), text("tags", T.tags),
    h("label", { class: "check" }, h("input", { type: "checkbox", name: "favourite", checked: isYes(cur.favourite) }), T.favourite),
    h("label", {}, T.year, hint("year"), h("input", { type: "number", name: "year", min: "1900", max: "2200", value: cur.year || "" })),
    h("label", {}, T.month, hint("month", base.month ? months[base.month - 1] : T.no_month),
      h("select", { name: "month" }, h("option", { value: "", selected: !cur.month }, T.no_month),
        months.map((m, i) => h("option", { value: String(i + 1), selected: String(cur.month) === String(i + 1) }, m)))),
    text("age", T.age),
    h("label", { class: "check" }, h("input", { type: "checkbox", name: "hidden", checked: isYes(cur.hidden) }), T.hidden),
    h("small", {}, T.reset),
    h("button", {}, T.save));
  show(h("p", {}, h("a", { href: "#/" }, T.back)),
    h("div", { class: "piece-edit" }, pieceImg(p, "", {})), out, form);
}

// trazos.toml: only top-level `key = value` lines are read or written; everything else is kept.
function tomlGet(text, key) {
  const m = new RegExp(`^${key}\\s*=\\s*(.*)$`, "m").exec(text);
  if (!m) return undefined;
  const v = m[1].trim();
  if (v.startsWith('"')) { const s = /^"((?:[^"\\]|\\.)*)"/.exec(v); return s ? JSON.parse(`"${s[1]}"`) : ""; }
  return /^true\b/.test(v) ? true : /^false\b/.test(v) ? false : v.replace(/\s*#.*$/, "");
}
function tomlSet(text, key, value) {
  const re = new RegExp(`^${key}\\s*=.*$\\n?`, "m");
  if (value === null) return text.replace(re, "");
  const line = `${key} = ${typeof value === "boolean" ? value : JSON.stringify(value)}`;
  if (re.test(text)) return text.replace(re, line + "\n");
  const table = /^\[/m.exec(text);
  return table ? text.slice(0, table.index) + line + "\n" + text.slice(table.index)
    : text.replace(/\n?$/, "\n") + line + "\n";
}

async function settingsView() {
  show(h("p", {}, T.loading));
  const file = await getFile("trazos.toml");
  const toml = file.text, get = (k) => tomlGet(toml, k);
  const out = h("div");
  const form = h("form", { onsubmit: async (ev) => {
    ev.preventDefault();
    const artist = form.elements.namedItem("artist").value.trim();
    if (!artist) return out.replaceChildren(msg(T.need_artist, true));
    let t = toml;
    t = tomlSet(t, "artist", artist);
    t = tomlSet(t, "title", form.elements.namedItem("site_title").value.trim() || null);
    t = tomlSet(t, "lang", form.elements.namedItem("lang").value);
    t = tomlSet(t, "rights", form.elements.namedItem("rights").value.trim() || null);
    t = tomlSet(t, "protect", form.elements.namedItem("protect").checked);
    busy(form, true);
    try {
      let note = null;
      if (t !== toml) { await putFile("trazos.toml", t, file.sha, "Admin: ajustes"); note = await republish(); }
      await settingsView();
      app.querySelector("form").before(savedMsg(note));
    } catch (err) {
      out.replaceChildren(msg(`${T.error}: ${err.message}`, true));
      busy(form, false);
    }
  } },
    h("label", {}, T.site_title, h("input", { type: "text", name: "site_title", value: get("title") || "" })),
    h("label", {}, T.artist, h("input", { type: "text", name: "artist", value: get("artist") || "", required: true })),
    h("label", {}, T.lang, h("select", { name: "lang" },
      ["es", "en"].map((l) => h("option", { value: l, selected: (get("lang") || "es") === l }, l)))),
    h("label", {}, T.rights, h("textarea", { name: "rights" }, get("rights") || "")),
    h("label", { class: "check" }, h("input", { type: "checkbox", name: "protect", checked: get("protect") !== false }), T.protect),
    h("button", {}, T.save));

  const pwOut = h("div");
  const pw = h("form", { onsubmit: async (ev) => {
    ev.preventDefault();
    const np = pw.elements.namedItem("password").value;
    if (np.length < 12 || np !== pw.elements.namedItem("password2").value) return pwOut.replaceChildren(msg(T.bad_pw, true));
    busy(pw, true);
    try {
      const old = await getFile("admin-key.json");
      await putFile("admin-key.json", await seal(token, np), old && old.sha, "Admin: contraseña cambiada");
      const note = await republish();
      pw.reset();
      pwOut.replaceChildren(msg(note || T.pw_changed, !!note));
    } catch (err) {
      pwOut.replaceChildren(msg(`${T.error}: ${err.message}`, true));
    }
    busy(pw, false);
  } },
    h("input", { type: "text", name: "user", value: "admin", autocomplete: "username", hidden: true }),
    h("label", {}, T.new_pw, h("input", { type: "password", name: "password", autocomplete: "new-password", minlength: "12", required: true })),
    h("label", {}, T.password2, h("input", { type: "password", name: "password2", autocomplete: "new-password", minlength: "12", required: true })),
    h("button", {}, T.change_pw));
  show(h("h1", {}, T.settings), out, form, h("h2", {}, T.change_pw), pwOut, pw);
}

async function route() {
  renderNav();
  if (!token) return loginView();
  const m = /^#\/(piece\/([\w-]+)|settings)?$/.exec(location.hash || "#/");
  try {
    if (m && m[2]) await pieceView(m[2]);
    else if (m && m[1] === "settings") await settingsView();
    else await listView();
  } catch (err) {
    if (/GitHub 401/.test(err.message)) { setToken(null); return route(); }  // token revoked or expired
    show(msg(`${T.error}: ${err.message}`, true));
  }
}

(async () => {
  data = await (await fetch("data.json", { cache: "no-store" })).json();
  T = S[data.lang] || S.es;
  window.addEventListener("hashchange", route);
  await route();
})();
