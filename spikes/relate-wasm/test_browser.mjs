// W7, W8 and the browser half of W9. Run: node --test test_browser.mjs
// Serves this folder over HTTP and drives the page in headless Chromium.
import { test, before, after } from "node:test";
import assert from "node:assert/strict";
import { createServer } from "node:http";
import { readFileSync, existsSync, writeFileSync } from "node:fs";
import { extname, join, normalize } from "node:path";
import { homedir } from "node:os";
import { chromium } from "playwright-core";

const root = new URL(".", import.meta.url).pathname;
const KEY = JSON.parse(readFileSync(join(root, "expected.json")));
const TYPES = { ".html": "text/html", ".js": "text/javascript", ".mjs": "text/javascript",
  ".wasm": "application/wasm", ".cypher": "text/plain", ".json": "application/json" };
const CHROME = process.env.CHROME ||
  join(homedir(), ".cache/ms-playwright/chromium-1217/chrome-linux64/chrome");

let server, browser, base;
before(async () => {
  server = createServer((req, res) => {
    const path = normalize(decodeURIComponent(new URL(req.url, "http://x").pathname));
    const file = join(root, path);
    if (!file.startsWith(root) || !existsSync(file)) { res.writeHead(404); return res.end(); }
    res.writeHead(200, { "content-type": TYPES[extname(file)] || "application/octet-stream" });
    res.end(readFileSync(file));
  });
  await new Promise((r) => server.listen(0, "127.0.0.1", r));
  base = `http://127.0.0.1:${server.address().port}`;
  browser = await chromium.launch({ executablePath: CHROME, headless: true });
});
after(async () => { await browser?.close(); server?.close(); });

async function openPage(query = "") {
  const page = await browser.newPage({ viewport: { width: 1200, height: 900 } });
  const problems = [];
  page.on("console", (m) => { if (m.type() === "error") problems.push(m.text()); });
  page.on("pageerror", (e) => problems.push(String(e)));
  page.on("response", (r) => { if (r.status() >= 400) problems.push(`${r.status()} ${r.url()}`); });
  await page.goto(`${base}/web/index.html${query}`);
  await page.waitForFunction(() => window.__result !== undefined, null, { timeout: 60_000 });
  return { page, problems, result: await page.evaluate(() => window.__result) };
}

const out = {};

test("W7 page seeds in a worker and shows the chain and walk", async () => {
  const { page, problems, result } = await openPage();
  assert.equal(result.ok, true, result.error);
  assert.deepEqual(result.chain, KEY["chain_WR-200-0147"]);
  assert.deepEqual(result.walk, KEY["walk_from_E-201B"]);
  assert.equal(result.nodes, Object.values(KEY.nodes).reduce((a, b) => a + b, 0));
  const text = await page.innerText("main");
  for (const t of [...result.chain.boundary, ...result.chain.others, "ENV-200-02", "E-201B"]) {
    assert.ok(text.includes(t), `page shows ${t}`);
  }
  assert.match(await page.innerText("#q-chain"), /RESOLVES_TO/);
  assert.match(await page.innerText("#q-walk"), /CONNECTED_TO\|HAS_NOZZLE/);
  assert.deepEqual(problems, []);
  await page.screenshot({ path: join(root, "panel.png"), fullPage: true });
  out.W7 = { nodes: result.nodes, init_ms: +result.init_ms.toFixed(1),
    seed_ms: +result.seed_ms.toFixed(1), query_ms: +result.times[0].toFixed(2) };
  await page.close();
});

test("W8 padded graph in the browser", async () => {
  const { page, problems, result } = await openPage("?script=padded.cypher&runs=20");
  assert.equal(result.ok, true, result.error);
  assert.equal(result.nodes, KEY.padded_nodes);
  assert.deepEqual(result.chain, KEY["chain_WR-200-0147"]);
  assert.deepEqual(result.walk, KEY["walk_from_E-201B"]);
  assert.equal(result.times.length, 20);
  const median = result.times[10], worst = result.times[19];
  out.W8_browser = { nodes: result.nodes, script_bytes: result.script_bytes,
    init_ms: +result.init_ms.toFixed(1), fetch_ms: +result.fetch_ms.toFixed(1),
    seed_ms: +result.seed_ms.toFixed(1), median_ms: +median.toFixed(2), worst_ms: +worst.toFixed(2) };
  assert.ok(result.seed_ms <= KEY.speed_limits_ms.seed, `seed ${result.seed_ms} ms`);
  assert.ok(median <= KEY.speed_limits_ms.median_query, `median ${median} ms`);
  assert.deepEqual(problems, []);
  await page.close();
});

test("W9 the worker refuses query text it doesn't know", async () => {
  const { page, result } = await openPage();
  assert.equal(result.ok, true);
  const refused = await page.evaluate(() =>
    window.__ask({ type: "query", name: "MATCH (n) DETACH DELETE n", params: {} })
      .then(() => "ran", (e) => e.message));
  assert.match(refused, /unknown query/);
  const extra = await page.evaluate(() =>
    window.__ask({ type: "query", name: "chain", params: { request_id: "WR-200-0147", x: "1" } })
      .then(() => "ran", (e) => e.message));
  assert.match(extra, /takes request_id/);
  const still = await page.evaluate(() =>
    window.__ask({ type: "query", name: "chain", params: { request_id: "WR-200-0147" } }));
  assert.equal(still.rows[0].length, 1, "store unchanged after refusals");
  out.W9_browser = { refused, extra };
  writeFileSync(join(root, "browser-results.json"), JSON.stringify(out, null, 2) + "\n");
  await page.close();
});
