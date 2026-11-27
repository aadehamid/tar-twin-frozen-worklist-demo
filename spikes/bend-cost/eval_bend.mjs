// Reads [[shared, [h, ...]], ...] as JSON on stdin and prints Bend's results for each case.
import { readFileSync } from "node:fs";
const C = (await import(process.argv[2])).default;
const list = (xs) => xs.reduceRight((tail, head) => ({ $: "Con", head, tail }), { $: "Nil" });
const cases = JSON.parse(readFileSync(0, "utf8"));
const out = cases.map(([s, xs]) => [C.standalone(s, list(xs)), C.cluster(s, list(xs)),
                                    C.own(list(xs)), C.count(list(xs))]);
process.stdout.write(JSON.stringify(out));
