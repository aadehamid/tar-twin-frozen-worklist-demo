import { chainResult, walkResult } from "./queries.js";

const worker = new Worker(new URL("./worker.js", import.meta.url), { type: "module" });
let next = 0;
const waiting = new Map();
worker.onmessage = ({ data }) => {
  const w = waiting.get(data.id);
  waiting.delete(data.id);
  data.ok ? w.resolve(data.result) : w.reject(new Error(data.error));
};
function ask(msg) {
  const id = ++next;
  return new Promise((resolve, reject) => {
    waiting.set(id, { resolve, reject });
    worker.postMessage({ ...msg, id });
  });
}
window.__ask = ask;

const $ = (id) => document.getElementById(id);
function tags(xs) {
  const span = document.createElement("span");
  for (const x of [].concat(xs)) {
    const t = document.createElement("span");
    t.className = "tag";
    t.textContent = x;
    span.append(t);
  }
  return span;
}
function fill(dl, pairs) {
  dl.replaceChildren();
  for (const [k, v] of pairs) {
    const dt = document.createElement("dt");
    dt.textContent = k;
    const dd = document.createElement("dd");
    dd.append(tags(v));
    dl.append(dt, dd);
  }
}

async function run() {
  const params = new URLSearchParams(location.search);
  const script = params.get("script") || "plant.cypher";
  const runs = Math.max(1, Math.min(100, Number(params.get("runs") || 1)));
  const seeded = await ask({ type: "seed", url: new URL(`../${script}`, location.href).href });
  if (seeded.errors.length) throw new Error(`seeding failed: ${seeded.errors[0]}`);
  const texts = await ask({ type: "texts" });
  $("q-chain").textContent = texts.chain.join("\n\n");
  $("q-walk").textContent = texts.walk.join("\n\n");

  const times = [];
  let chain, walk;
  for (let i = 0; i < runs; i++) {
    const c = await ask({ type: "query", name: "chain", params: { request_id: "WR-200-0147" } });
    const w = await ask({ type: "query", name: "walk", params: { tag: "E-201B" } });
    chain = chainResult(c.rows);
    walk = walkResult(w.rows);
    times.push(c.ms + w.ms);
  }
  fill($("chain"), [["Request", chain.request], ["Equipment", chain.equipment],
    ["Nozzles", chain.nozzles], ["Envelope", chain.envelope],
    ["Boundary valves", chain.boundary], ["Other requests", chain.others]]);
  fill($("walk"), [["Block valves reached", walk.boundary], ["Equipment passed", walk.equipment]]);
  times.sort((a, b) => a - b);
  $("status").textContent = `${seeded.nodes} nodes seeded in ${seeded.seed_ms.toFixed(0)} ms. ` +
    `Chain and walk median ${times[Math.floor(times.length / 2)].toFixed(1)} ms over ${runs} run(s).`;
  window.__result = { ok: true, chain, walk, nodes: seeded.nodes, script_bytes: seeded.script_bytes,
    init_ms: seeded.init_ms, fetch_ms: seeded.fetch_ms, seed_ms: seeded.seed_ms, times };
}

run().catch((e) => {
  $("status").textContent = `Failed: ${e.message}`;
  window.__result = { ok: false, error: e.message };
});
