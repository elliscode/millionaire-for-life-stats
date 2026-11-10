// Headless-Chrome smoke test of the generated site (no npm dependencies).
//
//   node tests/js/browser-smoke.mjs [public-dir] [screenshot-dir]
//
// Serves public/ on a random localhost port, then via the Chrome DevTools
// Protocol: records EVERY network request, checks the chart rendered,
// toggles daily/cumulative, runs the ticket checker, emulates a phone
// viewport, and writes screenshots. Exits non-zero on any failure.
import { spawn } from "node:child_process";
import { createServer } from "node:http";
import { mkdtempSync, readFileSync, writeFileSync, existsSync, mkdirSync } from "node:fs";
import { join, extname, resolve } from "node:path";
import { tmpdir } from "node:os";

const PUBLIC = resolve(process.argv[2] || "public");
const SHOTS = resolve(process.argv[3] || join(PUBLIC, "..", "screenshots"));
mkdirSync(SHOTS, { recursive: true });
const CHROME = process.env.CHROME ||
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const TYPES = { ".html": "text/html", ".css": "text/css", ".js": "text/javascript",
  ".json": "application/json", ".svg": "image/svg+xml", ".txt": "text/plain" };

const server = createServer((req, res) => {
  let p = decodeURIComponent(new URL(req.url, "http://x").pathname);
  if (p.endsWith("/")) p += "index.html";
  const f = join(PUBLIC, p);
  if (!f.startsWith(PUBLIC) || !existsSync(f)) { res.writeHead(404); return res.end(); }
  res.writeHead(200, { "content-type": TYPES[extname(f)] || "application/octet-stream" });
  res.end(readFileSync(f));
});
await new Promise((r) => server.listen(0, "127.0.0.1", r));
const ORIGIN = `http://127.0.0.1:${server.address().port}`;

const profile = mkdtempSync(join(tmpdir(), "m4l-chrome-"));
const chrome = spawn(CHROME, ["--headless=new", "--remote-debugging-port=0", "--no-first-run",
  "--no-default-browser-check", `--user-data-dir=${profile}`, "about:blank"],
  { stdio: ["ignore", "ignore", "pipe"] });
const wsUrl = await new Promise((res, rej) => {
  let buf = "";
  chrome.stderr.on("data", (d) => {
    buf += d; const m = buf.match(/DevTools listening on (ws:\/\/\S+)/); if (m) res(m[1]);
  });
  setTimeout(() => rej(new Error("chrome did not start")), 15000);
});

const browser = new WebSocket(wsUrl);
await new Promise((r) => browser.addEventListener("open", r));
let id = 0; const pending = new Map(); const listeners = [];
browser.addEventListener("message", (ev) => {
  const msg = JSON.parse(ev.data);
  if (msg.id && pending.has(msg.id)) {
    const { res, rej } = pending.get(msg.id); pending.delete(msg.id);
    msg.error ? rej(new Error(JSON.stringify(msg.error))) : res(msg.result);
  } else listeners.forEach((l) => l(msg));
});
const send = (method, params = {}, sessionId) => new Promise((res, rej) => {
  const mid = ++id; pending.set(mid, { res, rej });
  browser.send(JSON.stringify({ id: mid, method, params, sessionId }));
});

const { targetId } = await send("Target.createTarget", { url: "about:blank" });
const { sessionId } = await send("Target.attachToTarget", { targetId, flatten: true });
const S = (m, p) => send(m, p, sessionId);
const requests = []; const consoleErrors = [];
listeners.push((m) => {
  if (m.sessionId !== sessionId) return;
  if (m.method === "Network.requestWillBeSent") requests.push(m.params.request.url);
  if (m.method === "Runtime.exceptionThrown") consoleErrors.push(m.params.exceptionDetails.text +
    " " + (m.params.exceptionDetails.exception?.description || ""));
  if (m.method === "Log.entryAdded" && m.params.entry.level === "error") consoleErrors.push(m.params.entry.text);
});
await S("Network.enable"); await S("Runtime.enable"); await S("Page.enable"); await S("Log.enable");

const evaluate = async (expr) => {
  const r = await S("Runtime.evaluate", { expression: expr, awaitPromise: true, returnByValue: true });
  if (r.exceptionDetails) throw new Error(r.exceptionDetails.exception?.description || r.exceptionDetails.text);
  return r.result.value;
};
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const shot = async (name) => {
  const { data } = await S("Page.captureScreenshot", { format: "png", captureBeyondViewport: true });
  writeFileSync(join(SHOTS, name), Buffer.from(data, "base64"));
};
async function load(width, height, dark = false, mobile = false) {
  await S("Emulation.setDeviceMetricsOverride", { width, height, deviceScaleFactor: 1, mobile });
  await S("Emulation.setEmulatedMedia", { features: [{ name: "prefers-color-scheme", value: dark ? "dark" : "light" }] });
  await S("Page.navigate", { url: ORIGIN + "/" });
  await sleep(1200);
}

const failures = [];
const check = (cond, msg) => { if (!cond) failures.push(msg); console.log((cond ? "PASS " : "FAIL ") + msg); };

// "Every drawing" rows are NOT in the HTML; "Load all drawings" builds them
// from the embedded data. Verifies before/after state; returns nothing.
const checkHistory = async (label) => {
  const before = await evaluate(`(() => ({
    rows: document.querySelectorAll('#history-body tr').length,
    wrapHidden: document.getElementById('history-wrap').hidden,
    hasButton: !!document.getElementById('history-load') }))()`);
  check(before.rows === 0 && before.wrapHidden && before.hasButton,
    `${label}: history table empty and hidden until requested (${JSON.stringify(before)})`);
  await evaluate("document.getElementById('history-load').click()");
  await sleep(200);
  const after = await evaluate(`(() => {
    const data = JSON.parse(document.getElementById('m4l-data').textContent);
    const rows = [...document.querySelectorAll('#history-body tr')];
    const wins = data.series.topDaily.reduce((n, t, i) => n + ((t || data.series.secondDaily[i]) ? 1 : 0), 0);
    return { rows: rows.length, expected: data.drawings.length,
      firstDate: rows[0] && rows[0].querySelector('time').getAttribute('datetime'), lastDate: data.lastDate,
      firstText: rows[0] && rows[0].textContent,
      winRows: rows.filter(r => r.classList.contains('is-win')).length, wins,
      buttonGone: !document.getElementById('history-load'),
      wrapShown: !document.getElementById('history-wrap').hidden,
      focusInFirstRow: !!rows[0] && rows[0].contains(document.activeElement),
      fits: document.documentElement.scrollWidth <= innerWidth }; })()`);
  check(after.rows === after.expected && after.firstDate === after.lastDate && after.winRows === after.wins &&
        after.buttonGone && after.wrapShown && after.focusInFirstRow && after.fits,
    `${label}: Load all drawings builds every row, newest first, focus on first row (${JSON.stringify(after)})`);
};

try {
  await load(1280, 900);
  check(await evaluate("typeof Chart === 'function'"), "Chart.js loaded from local asset");
  check(await evaluate("!!Chart.getChart('winners-chart') && Chart.getChart('winners-chart').data.datasets.length === 2"),
    "winners chart rendered with 2 datasets");
  check(await evaluate("Chart.getChart('winners-chart').config.type === 'line' || Chart.getChart('winners-chart').data.datasets[0].type === 'line'"),
    "default view is cumulative (line)");
  const lastCum = await evaluate("Chart.getChart('winners-chart').data.datasets.map(d => d.data[d.data.length-1])");
  console.log("     cumulative totals:", lastCum);
  await shot("desktop-light.png");

  await evaluate("document.querySelector('[data-view=daily]').click()");
  await sleep(200);
  check(await evaluate("Chart.getChart('winners-chart').data.datasets[0].type === 'bar'"), "toggle switches to per-drawing bars");
  check(await evaluate("document.querySelector('[data-view=daily]').getAttribute('aria-pressed') === 'true'"), "toggle aria-pressed updated");
  await evaluate("document.querySelector('[data-view=cumulative]').click()");

  // Ticket checker: run every case in the shared fixture through the UI
  const fixture = JSON.parse(readFileSync(new URL("../fixtures/checker_cases.json", import.meta.url)));
  for (const c of fixture.uiCases) {
    const text = await evaluate(`(() => {
      const f = document.getElementById('checker-form');
      f.querySelector('#ck-date').value = ${JSON.stringify(c.date)};
      const balls = f.querySelectorAll('.balls .ball');
      ${JSON.stringify(c.whites)}.forEach((n, i) => balls[i].value = String(n));
      f.querySelector('#ck-mb').value = ${JSON.stringify(String(c.mb))};
      f.querySelector('button[type=submit]').click();
      return document.getElementById('checker-result').textContent;
    })()`);
    check(text.includes(c.expectText), `checker UI: ${c.name} -> "${c.expectText}"`);
  }
  // Real keystrokes: type each number and press Enter to advance; Enter on the
  // Millionaire Ball submits.
  await evaluate(`(() => { const f = document.getElementById('checker-form');
    f.querySelectorAll('.ball').forEach(b => b.value = ''); f.querySelector('#ck-date').value = '2026-08-06';
    document.getElementById('checker-result').textContent = ''; f.querySelector('#ck-date').focus(); })()`);
  const pressEnter = async () => {
    for (const type of ["keyDown", "keyUp"])
      await S("Input.dispatchKeyEvent", { type, key: "Enter", code: "Enter", windowsVirtualKeyCode: 13,
        nativeVirtualKeyCode: 13, text: type === "keyDown" ? "\r" : undefined });
  };
  const focusedName = () => evaluate("document.activeElement.name || document.activeElement.id");
  await pressEnter();
  check(await focusedName() === "w1", "Enter in date field moves to white ball 1");
  const typed = ["7", "20", "42", "48", "51", "3"];
  const expectNext = ["w2", "w3", "w4", "w5", "mb"];
  for (let i = 0; i < 5; i++) {
    await S("Input.insertText", { text: typed[i] });
    await pressEnter();
    check(await focusedName() === expectNext[i], `Enter in white ball ${i + 1} moves to ${expectNext[i]}`);
  }
  check(await evaluate("document.getElementById('checker-result').textContent === ''"),
    "Enter on white balls does not submit early");
  await S("Input.insertText", { text: typed[5] });
  await pressEnter();
  await sleep(100);
  check((await evaluate("document.getElementById('checker-result').textContent")).includes("TOP PRIZE"),
    "Enter on Millionaire Ball submits the check");

  // tel inputs (KaiOS number inputs swallow Backspace); a real Backspace edits the value
  check(await evaluate("[...document.querySelectorAll('#checker-form .ball')].every(b => b.type === 'tel')"),
    "checker ball inputs are type=tel");
  await evaluate("(() => { const b = document.getElementById('ck-mb'); b.focus(); b.setSelectionRange(1, 1); })()");
  for (const type of ["keyDown", "keyUp"])
    await S("Input.dispatchKeyEvent", { type, key: "Backspace", code: "Backspace",
      windowsVirtualKeyCode: 8, nativeVirtualKeyCode: 8 });
  check(await evaluate("document.getElementById('ck-mb').value === ''"), "Backspace deletes a typed digit");

  // Stale-data warning: shown exactly when the newest drawing on the page is
  // older than yesterday (ET); results count as due at 12:00 a.m. ET.
  const yesterdayET = (() => {
    const t = new Intl.DateTimeFormat("en-CA", { timeZone: "America/New_York" }).format(new Date());
    const d = new Date(t + "T00:00:00Z"); d.setUTCDate(d.getUTCDate() - 1);
    return d.toISOString().slice(0, 10);
  })();
  const staleInfo = await evaluate(`(() => { const n = document.getElementById('ck-stale');
    return { hidden: n.hidden, text: n.textContent,
             last: JSON.parse(document.getElementById('m4l-data').textContent).lastDate }; })()`);
  check(staleInfo.hidden === !(staleInfo.last < yesterdayET),
    `stale warning ${staleInfo.hidden ? "hidden" : "shown"} (newest ${staleInfo.last}, expected ${yesterdayET}): ${staleInfo.text}`);

  await evaluate("document.getElementById('check').scrollIntoView()");
  await shot("desktop-light-checker.png");

  await checkHistory("desktop");
  await evaluate("document.getElementById('history-wrap').scrollIntoView()");
  await shot("desktop-history.png");

  await load(1280, 900, true);
  await shot("desktop-dark.png");

  await load(390, 844, false, true);
  check(await evaluate("document.documentElement.scrollWidth <= window.innerWidth"), "no horizontal page scroll at 390px");
  await shot("mobile-light.png");

  // ---- flip phone: 240x320 ------------------------------------------
  const viewShot = async (name) => {
    const { data } = await S("Page.captureScreenshot", { format: "png" });
    writeFileSync(join(SHOTS, name), Buffer.from(data, "base64"));
  };
  await load(240, 320, false, true);
  check(await evaluate("document.documentElement.scrollWidth <= 240"), "240px: no horizontal page scroll");
  const offenders = await evaluate(`Array.from(document.querySelectorAll('body *'))
    .filter(e => { const r = e.getBoundingClientRect(); const cs = getComputedStyle(e);
      return r.width > 0 && cs.display !== 'none' && cs.visibility !== 'hidden' && (r.right > 240.5 || r.left < -0.5)
        && !e.closest('[hidden]') && !e.closest('details:not([open]) > :not(summary)') && !e.closest('.skip'); })
    .map(e => e.tagName.toLowerCase() + (e.id ? '#' + e.id : '') + (e.className && typeof e.className === 'string' ? '.' + e.className.split(' ')[0] : '') + ' R=' + Math.round(e.getBoundingClientRect().right))
    .slice(0, 15)`);
  check(offenders.length === 0, `240px: every element fits inside 240px (${offenders.join(", ") || "none"})`);
  check(await evaluate("[...document.querySelectorAll('.balls .ball')].every((b, i, a) => b.getBoundingClientRect().top === a[0].getBoundingClientRect().top)"),
    "240px: all five white-ball inputs on one row");
  const jb = await evaluate(`(() => { const b = document.getElementById('jump-check'); const r = b.getBoundingClientRect();
    return { shown: getComputedStyle(b).display !== 'none' && !b.hidden, pos: getComputedStyle(b).position,
             top: r.top, bottom: r.bottom, left: r.left, right: r.right }; })()`);
  check(jb.shown && jb.pos === "absolute", "240px: jump button shown, position absolute (not fixed)");
  check(jb.bottom <= 320 && jb.bottom >= 300 && Math.abs((jb.left + jb.right) / 2 - 120) <= 1,
    `240px: jump button bottom-center of viewport (${JSON.stringify(jb)})`);
  await viewShot("flip-1-top.png");
  await shot("flip-full.png");

  const jumpInfo = `(() => { const b = document.getElementById('jump-check'); const r = b.getBoundingClientRect();
    return { hidden: b.hidden, display: getComputedStyle(b).display, away: b.classList.contains('jump-check--away'),
             top: Math.round(r.top), bottom: Math.round(r.bottom), opacity: +getComputedStyle(b).opacity }; })()`;

  // Leaving the very top: slides out (still displayed, mid-transition), then display:none
  await evaluate("window.scrollTo(0, 1)"); await sleep(60);
  const mid = await evaluate(jumpInfo);
  check(mid.away && !mid.hidden && mid.display !== "none" && mid.opacity < 1 && mid.opacity > 0,
    `240px: scrolling 1px starts the slide-out transition (${JSON.stringify(mid)})`);
  check(mid.top >= 286 - 2, `240px: sliding button stays anchored to viewport bottom, not riding up (${JSON.stringify(mid)})`);
  await sleep(300);
  const gone = await evaluate(jumpInfo);
  check(gone.hidden && gone.display === "none", `240px: after the slide, button is display:none (${JSON.stringify(gone)})`);

  await evaluate("window.scrollTo(0, 900)"); await sleep(300);
  check((await evaluate(jumpInfo)).display === "none", "240px: stays hidden while scrolled down");
  await viewShot("flip-2-scrolled.png");

  // Back to the very top: slides back in at bottom center
  await evaluate("window.scrollTo(0, 0)"); await sleep(300);
  const back = await evaluate(jumpInfo);
  check(!back.hidden && !back.away && back.opacity === 1 && back.bottom <= 320 && back.bottom >= 300,
    `240px: returning to the top brings the button back (${JSON.stringify(back)})`);

  await evaluate("document.getElementById('jump-check').click()"); await sleep(300);
  const after = await evaluate(`(() => { const r = document.getElementById('check').getBoundingClientRect();
    return { top: Math.round(r.top), hidden: document.getElementById('jump-check').hidden,
             focused: document.activeElement === document.querySelector('.balls .ball') }; })()`);
  check(Math.abs(after.top) <= 2 && after.hidden && after.focused,
    `240px: button jumps to checker, hides itself, focuses first ball (${JSON.stringify(after)})`);
  await viewShot("flip-3-checker.png");

  const res240 = await evaluate(`(() => {
    const f = document.getElementById('checker-form');
    f.querySelector('#ck-date').value = '2026-08-06';
    [51, 48, 42, 20, 7].forEach((n, i) => f.querySelectorAll('.balls .ball')[i].value = String(n));
    f.querySelector('#ck-mb').value = '3';
    f.querySelector('button[type=submit]').click();
    return document.getElementById('checker-result').textContent; })()`);
  await sleep(200);
  check(res240.includes("TOP PRIZE") && await evaluate("document.documentElement.scrollWidth <= 240"),
    "240px: checker result renders and fits");
  await viewShot("flip-4-result.png");

  await evaluate("window.scrollTo(0, document.documentElement.scrollHeight)"); await sleep(300);
  check((await evaluate(jumpInfo)).display === "none", "240px: hidden at page bottom");
  check(await evaluate("document.documentElement.scrollHeight") === await evaluate("Math.round(scrollY) + innerHeight"),
    "240px: hidden button doesn't extend the page");
  await viewShot("flip-5-bottom.png");

  await evaluate("document.getElementById('history-load').scrollIntoView()"); await sleep(200);
  await checkHistory("240px");
  await viewShot("flip-6-history.png");

  // Desktop must not show the flip-phone button
  await load(1280, 900);
  check(await evaluate("getComputedStyle(document.getElementById('jump-check')).display === 'none'"),
    "desktop: jump button hidden");

  const foreign = requests.filter((u) => !u.startsWith(ORIGIN) && !u.startsWith("data:") && u !== "about:blank");
  check(foreign.length === 0, `no requests outside the site's own origin (${foreign.join(", ") || "none"})`);
  const dataFetches = requests.filter((u) => u.endsWith(".json"));
  check(dataFetches.length === 0, "page never fetches a JSON data file");
  check(consoleErrors.length === 0, `no console errors/CSP violations ${consoleErrors.join(" | ")}`);
  console.log(`     ${requests.length} total requests, all same-origin: ${[...new Set(requests.map(u => new URL(u).pathname))].join(" ")}`);
} finally {
  browser.close(); chrome.kill(); server.close();
}
console.log(failures.length ? `\n${failures.length} FAILURE(S)` : "\nALL BROWSER CHECKS PASSED");
console.log(`screenshots: ${SHOTS}`);
process.exit(failures.length ? 1 : 0);
