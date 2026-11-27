// Runs every check and writes results.json.
//   PYTHON=/path/to/python-with-pydexpi node run_spike.mjs
// Run it from a directory other than /tmp so Python doesn't pick up stray modules.
import { execFileSync } from "node:child_process";
import { readFileSync, statSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { createHash } from "node:crypto";

const root = new URL(".", import.meta.url).pathname;
const py = process.env.PYTHON || "python3";
const run = (cmd, args) => execFileSync(cmd, args, { cwd: root, encoding: "utf8", stdio: ["ignore", "pipe", "pipe"] });
const tally = (out) => ({ pass: +(/# pass (\d+)/.exec(out)?.[1] ?? 0), fail: +(/# fail (\d+)/.exec(out)?.[1] ?? 0) });

run(py, ["export_cypher.py"]);
const pyOut = run(py, ["-m", "pytest", "-q", "-p", "no:cacheprovider", "test_export.py"]);
const nodeOut = run(process.execPath, ["--test", "test_relate.mjs"]);
const brOut = run(process.execPath, ["--test", "test_browser.mjs"]);

const pkg = JSON.parse(readFileSync(join(root, "node_modules/@relate/relate-wasm/package.json")));
const wasm = join(root, "node_modules/@relate/relate-wasm/relate_bg.wasm");
const sha = (f) => createHash("sha256").update(readFileSync(join(root, f))).digest("hex");
const nodeTimes = JSON.parse(/\{"W8_node".*\}/.exec(nodeOut)[0]).W8_node;
const browser = JSON.parse(readFileSync(join(root, "browser-results.json")));

const results = {
  package: { name: pkg.name, version: pkg.version, license: pkg.license, wasm_bytes: statSync(wasm).size },
  runtime: { node: process.version, chromium: "playwright chromium-1217, headless" },
  scripts: {
    "plant.cypher": { bytes: statSync(join(root, "plant.cypher")).size, sha256: sha("plant.cypher") },
    "padded.cypher": { bytes: statSync(join(root, "padded.cypher")).size, sha256: sha("padded.cypher") },
  },
  pytest: /(\d+) passed/.exec(pyOut)?.[0] + (/failed/.test(pyOut) ? " (with failures)" : ""),
  node_tests: tally(nodeOut),
  browser_tests: tally(brOut),
  W8_node: nodeTimes,
  ...browser,
};
writeFileSync(join(root, "results.json"), JSON.stringify(results, null, 2) + "\n");
console.log(JSON.stringify(results, null, 2));
