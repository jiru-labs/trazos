// The admin's framing editor, end to end, against an in-memory fake of the GitHub API (nothing leaves
// the machine). SITE_DIR: a copy of example/ with `admin = "test/content"` and
// `admin_committer = "Test <t@example.invalid>"` in trazos.toml, and pieces/2021-001.jpg (+ -thumb)
// replaced by a 1600x1200 grey image with a red 200 px square in the top-left corner and a blue one
// in the middle; built with build.py and served at http://127.0.0.1:8766/. Then:
//   PLAYWRIGHT=/path/to/node_modules/playwright/index.mjs node tests/admin-frame.mjs SITE_DIR OUT_DIR
// and check the saved JPEGs in OUT_DIR: no red at zoom 2 centred, red back after the corner drag.
const { chromium } = await import(process.env.PLAYWRIGHT || 'playwright');
import { readFileSync, readdirSync, writeFileSync, mkdirSync } from 'fs';
import { createHash } from 'crypto';
const [site, outDir] = process.argv.slice(2);
const R = 'test/content', ID = '2021-001';
const gitSha = (b) => createHash('sha1').update(Buffer.concat([Buffer.from(`blob ${b.length}\0`), b])).digest('hex');
const blobs = new Map(); const put = (b) => { const s = gitSha(b); blobs.set(s, b); return s; };
let files = new Map();  // path -> blob sha (the "main" tree)
for (const f of readdirSync(site + '/pieces')) files.set('pieces/' + f, put(readFileSync(site + '/pieces/' + f)));
files.set('trazos.toml', put(readFileSync(site + '/trazos.toml')));
const trees = new Map(), commits = new Map(); let n = 0;
const snap = (m) => { const s = 't' + (++n); trees.set(s, new Map(m)); return s; };
let head = 'c0'; commits.set('c0', { tree: snap(files), message: 'init' });
const log = []; let failures = 0;
const ok = (cond, what) => { console.log((cond ? 'PASS ' : 'FAIL ') + what); if (!cond) failures++; };

const b = await chromium.launch(); const p = await b.newPage({ viewport: { width: 1100, height: 1400 } });
p.on('pageerror', (e) => console.log('pageerror', e.message));
await p.addInitScript(() => sessionStorage.setItem('trazos-token', 'fake'));
await p.route('https://api.github.com/**', async (r) => {
  const u = new URL(r.request().url()), m = r.request().method(), path = u.pathname.replace(`/repos/${R}`, '');
  const body = r.request().postData() ? JSON.parse(r.request().postData()) : null;
  log.push(`${m} ${path}`);
  const json = (j, status = 200) => r.fulfill({ status, json: j });
  if (path === '' && m === 'GET') return json({ default_branch: 'main' });
  if (path.startsWith('/contents/')) {
    const fp = decodeURIComponent(path.slice(10)), sha = files.get(fp);
    if (m === 'GET') {
      if (!sha) return json({ message: 'Not Found' }, 404);
      if ((r.request().headers()['accept'] || '').includes('raw')) return r.fulfill({ status: 200, body: blobs.get(sha), contentType: 'application/octet-stream' });
      return json({ sha, content: blobs.get(sha).toString('base64') });
    }
    if (m === 'PUT') { files.set(fp, put(Buffer.from(body.content, 'base64'))); head = 'c' + (++n); commits.set(head, { tree: snap(files), message: body.message }); return json({ content: { sha: files.get(fp) } }); }
    if (m === 'DELETE') { files.delete(fp); head = 'c' + (++n); commits.set(head, { tree: snap(files), message: body.message }); return json({}); }
  }
  if (path === '/git/ref/heads/main') return json({ object: { sha: head } });
  if (path.startsWith('/git/commits/') && m === 'GET') return json({ tree: { sha: commits.get(path.slice(13)).tree } });
  if (path === '/git/blobs') return json({ sha: put(Buffer.from(body.content, 'base64')) });
  if (path === '/git/trees' && m === 'POST') {
    const t = new Map(trees.get(body.base_tree));
    for (const e of body.tree) { if (e.sha === null) { if (!t.has(e.path)) return json({ message: 'path not in tree' }, 422); t.delete(e.path); } else t.set(e.path, e.sha); }
    return json({ sha: snap(t) });
  }
  if (path === '/git/commits' && m === 'POST') { const s = 'c' + (++n); commits.set(s, { tree: body.tree, message: body.message, parent: body.parents[0], committer: body.committer }); return json({ sha: s }); }
  if (path === '/git/refs/heads/main' && m === 'PATCH') {
    if (commits.get(body.sha).parent !== head) return json({ message: 'not fast forward' }, 422);
    head = body.sha; files = new Map(trees.get(commits.get(head).tree)); return json({ object: { sha: head } });
  }
  if (m === 'POST' && path.endsWith('/dispatches')) return r.fulfill({ status: 204, body: '' });
  return json({ message: 'Not Found' }, 404);
});
const commitsN = () => log.filter((l) => l === 'PATCH /git/refs/heads/main').length;
const saved = async (before) => { for (let i = 0; i < 100 && commitsN() === before; i++) await p.waitForTimeout(100); await p.waitForSelector('text=Framing saved'); };
const shaOf = (fp) => files.get(fp);
const save = (fp) => { const s = shaOf(fp); if (!s) return null; mkdirSync(outDir, { recursive: true }); const f = `${outDir}/${n}-${fp.replace(/\//g, '_')}`; writeFileSync(f, blobs.get(s)); return f; };
const orig = { jpg: shaOf(`pieces/${ID}.jpg`), thumb: shaOf(`pieces/${ID}-thumb.jpg`) };

await p.goto(`http://127.0.0.1:8766/admin/#/piece/${ID}`);
await p.waitForFunction(() => (document.querySelector('canvas.frame-view')?.width || 300) !== 300);
ok(await p.$eval('canvas.frame-view', (c) => c.width === 900 && c.height === 675), 'editor shows the image (900x675 preview of 1600x1200)');
ok(await p.locator('text=Back to the original').count() === 0, 'no restore button before any framing');
// zoom 2 + turn right; centred: the red corner must be outside
await p.click('text=Turn ↻');
await p.$eval('input[type=range]', (z) => { z.value = '2'; z.dispatchEvent(new Event('input')); });
const commitsBefore = log.filter((l) => l === 'PATCH /git/refs/heads/main').length;
await p.screenshot({ path: `${outDir}/editor.png` });
await p.click('text=Save framing');
await p.waitForSelector('text=Framing saved');
ok(log.filter((l) => l === 'PATCH /git/refs/heads/main').length === commitsBefore + 1, 'one commit for the whole framing');
ok(shaOf(`pieces/${ID}-master.jpg`) === orig.jpg && shaOf(`pieces/${ID}-master-thumb.jpg`) === orig.thumb, 'original kept as master, same blobs');
ok(shaOf(`pieces/${ID}.jpg`) !== orig.jpg, 'published image replaced');
const ed = JSON.parse(blobs.get(shaOf(`edits/${ID}.json`)));
ok(ed.frame && ed.frame.rotate === 90 && ed.frame.zoom === 2, `frame saved in the edit ${JSON.stringify(ed.frame)}`);
ok(commits.get(head).committer?.email === 't@example.invalid', 'commit uses admin_committer');
console.log('FILES', save(`pieces/${ID}.jpg`), save(`pieces/${ID}-thumb.jpg`));
writeFileSync(`${outDir}/edit1.json`, blobs.get(shaOf(`edits/${ID}.json`)));
// reopen: loads the master, restore offered, slider at 2
await p.reload();
await p.waitForFunction(() => (document.querySelector('canvas.frame-view')?.width || 300) !== 300);
ok(await p.locator('text=Back to the original').count() === 1, 'restore offered after framing');
ok(await p.$eval('input[type=range]', (z) => z.value) === '2', 'editor reopens at the saved zoom');
ok(await p.$eval('canvas.frame-view', (c) => c.width === 675 && c.height === 900), 'reopened preview is turned (675x900)');
// text form save keeps the frame
await p.fill('input[name=title]', 'Framed');
await p.$eval('form', (f) => f.requestSubmit());
await p.waitForSelector('text=Saved.');
const ed2 = JSON.parse(blobs.get(shaOf(`edits/${ID}.json`)));
ok(ed2.title === 'Framed' && ed2.frame?.zoom === 2, 'saving the text form keeps the frame');
writeFileSync(`${outDir}/edit2.json`, blobs.get(shaOf(`edits/${ID}.json`)));
// zoom back out from the master: whole picture again but turned
await p.$eval('input[type=range]', (z) => { z.value = '1'; z.dispatchEvent(new Event('input')); });
{ const c = commitsN(); await p.click('text=Save framing'); await saved(c); }
console.log('FILES2', save(`pieces/${ID}.jpg`));
ok(shaOf(`pieces/${ID}-master.jpg`) === orig.jpg, 'reframing renders from the same master');
// restore
{ const c = commitsN(); await p.click('text=Back to the original'); await saved(c); }
ok(shaOf(`pieces/${ID}.jpg`) === orig.jpg && shaOf(`pieces/${ID}-thumb.jpg`) === orig.thumb, 'restore puts back the exact original bytes');
ok(!shaOf(`pieces/${ID}-master.jpg`) && !shaOf(`pieces/${ID}-master-thumb.jpg`), 'restore removes the master files');
const ed3 = JSON.parse(blobs.get(shaOf(`edits/${ID}.json`)));
ok(!ed3.frame && ed3.title === 'Framed', 'restore drops the frame, keeps the title');
// Centre + save with no master: nothing committed
const c0 = log.filter((l) => l === 'PATCH /git/refs/heads/main').length;
await p.click('text=Save framing'); await p.waitForTimeout(800);
ok(log.filter((l) => l === 'PATCH /git/refs/heads/main').length === c0, 'saving an untouched frame commits nothing');
// drag: zoom 2, turned right (red now top-right); dragging left+down shows the top-right corner
await p.click('text=Turn ↻');
await p.$eval('input[type=range]', (z) => { z.value = '2'; z.dispatchEvent(new Event('input')); });
{ const bx = await p.locator('canvas.frame-view').boundingBox(), cx = bx.x + bx.width / 2, cy = bx.y + bx.height / 2;
  await p.mouse.move(cx, cy); await p.mouse.down(); await p.mouse.move(cx - 600, cy + 600, { steps: 8 }); await p.mouse.up(); }
{ const c = commitsN(); await p.click('text=Save framing'); await saved(c); }
const ed4 = JSON.parse(blobs.get(shaOf(`edits/${ID}.json`)));
ok(ed4.frame.x === 0.75 && ed4.frame.y === 0.25, `drag pans to the clamped corner ${JSON.stringify(ed4.frame)}`);
console.log('FILES3', save(`pieces/${ID}.jpg`));
console.log(failures ? `${failures} FAIL` : 'ALL PASS');
await b.close();
