// Night status page for sched-prod: the HTML page and status.json, both built per request
// from the live ops feed, so neither can drift from it or from each other (R-R6H: read live, never a copy).
const FEED = "https://hq.mega.dev/challenges/status-for-the-night/api/incidents/7a5169564388";
const TEAL = "#1f9e8f"; // R-R8X: sampled from the screenshot's banner.

const HEADERS = {
  "access-control-allow-origin": "*", // R-M8Z: tram boards read status.json from their own pages.
  "cache-control": "public, max-age=30", // R-Z5H: 30 s or less, the boards poll that often.
};

async function readFeed() {
  const res = await fetch(FEED, { cache: "no-store", headers: { accept: "application/json" } });
  if (!res.ok) throw new Error(`ops feed answered HTTP ${res.status}`);
  const feed = await res.json();
  // R-K9R: newest first.
  const incidents = [...feed.incidents].sort((a, b) => Date.parse(b.opened) - Date.parse(a.opened));
  return { updatedAt: feed.updatedAt, incidents };
}

const pad = (n) => String(n).padStart(2, "0");
// R-Z8K, as product decided: month first, the way the boards show it. Times are UTC (R-Z4M), 24-hour.
const day = (iso) => { const d = new Date(iso); return `${pad(d.getUTCMonth() + 1)}/${pad(d.getUTCDate())}`; };
const time = (iso) => { const d = new Date(iso); return `${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}`; };
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

function page({ updatedAt, incidents }) {
  // R-L9X: every line gets its own row, tram 3 included.
  const lines = [];
  for (const i of incidents) if (!lines.some((l) => l.line === i.line)) lines.push(i);
  const lineRows = lines.map((i) => `<tr><td>${esc(i.line)}</td><td>${day(i.opened)} ${time(i.opened)}</td><td>${esc(i.what)}</td><td>${i.line === "tram 3" ? "shown on tram 3 boards" : ""}</td></tr>`).join("");
  const rows = incidents.map((i) => `<tr><td>${day(i.opened)}</td><td>${time(i.opened)}</td><td>${i.closed ? time(i.closed) : "open"}</td><td>${esc(i.line)}</td><td>${esc(i.what)}</td><td>${esc(i.author)}</td></tr>`).join("");
  return `<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>status for the night</title>
<style>
body{margin:0;font-family:system-ui,sans-serif;color:#1d1d1d;background:#fff}
.banner{background:${TEAL};color:#111;padding:16px 24px;font-weight:600}
main{max-width:900px;margin:0 auto;padding:8px 24px 32px}
h1{font-size:1.6rem;margin:24px 0 8px}h2{font-size:1.1rem;margin:28px 0 8px}
table{width:100%;border-collapse:collapse;font-size:.95rem}
th,td{text-align:left;padding:8px 6px;border-bottom:1px solid #e6e6e6}th{color:#888;font-weight:500}
.scroll{overflow-x:auto}footer{color:#666;font-size:.85rem;margin-top:28px}
</style></head><body>
<div class="banner">Some services had problems overnight.</div>
<main>
<h1>status for the night</h1>
<p>Shown on tram 3 boards.</p>
<h2>Incidents</h2>
<div class="scroll"><table><thead><tr><th>date</th><th>opened</th><th>closed</th><th>line</th><th>what</th><th>ran by</th></tr></thead><tbody>${rows}</tbody></table></div>
<h2>Lines</h2>
<div class="scroll"><table><thead><tr><th>line</th><th>last incident</th><th>what</th><th></th></tr></thead><tbody>${lineRows}</tbody></table></div>
<footer>All times UTC. Data from the ops feed, updated ${esc(updatedAt)}. Also as <a href="/status.json">status.json</a>.</footer>
</main></body></html>`;
}

export default {
  async fetch(request) {
    const { pathname } = new URL(request.url);
    if (request.method === "OPTIONS") return new Response(null, { status: 204, headers: { ...HEADERS, "access-control-allow-methods": "GET, OPTIONS" } });
    if (pathname !== "/" && pathname !== "/status.json") return new Response("not found", { status: 404, headers: HEADERS });
    let data;
    try {
      data = await readFeed();
    } catch (e) {
      return new Response(`ops feed unavailable: ${e.message}`, { status: 502, headers: { ...HEADERS, "cache-control": "no-store" } });
    }
    if (pathname === "/status.json") {
      return new Response(JSON.stringify(data, null, 1), { headers: { ...HEADERS, "content-type": "application/json; charset=utf-8" } });
    }
    return new Response(page(data), { headers: { ...HEADERS, "content-type": "text/html; charset=utf-8" } });
  },
};
