# Spike: proving the cluster cost rule in Bend 2

Status: passed on 2026-11-27. All five checks pass. Bend 2 stays an optional extra, as decision D10 says, and the Hypothesis properties stay the main check on the cost rules.

This is the optional phase 0 spike in [design.md](../design.md) section 10 and the Bend paragraph in [verification.md](../verification.md). Can we state one of the cost rules as a Bend law, prove it, and check that Bend's code and the Python the twin will run give the same answers?

## 1. Which rule

The clusters rule from verification.md section 3: a cluster's cost is never more than the sum of its items' standalone costs, and each shared cost is counted exactly once. It's the rule behind the cluster panel in design.md section 5.5, where items in one isolation envelope share one blinding and isolation cost.

The spike uses a simple version. Each item has its own cost in whole hours, and every item in the cluster needs the same setup of `s` hours. Done one by one, each item pays the setup. Done as a cluster, the setup is paid once. The real twin has several shared costs per cluster and costs in money as well as hours. The proof would grow, but the idea is the same.

## 2. What's in the folder

`spikes/bend-cost/` follows Bend's own convention of a laws file that a person writes and a proof file that the code's author writes.

- `cost.bend` is the code: `own`, `count`, `standalone` and `cluster` over a list of item costs.
- `LAWS.bend` states three laws. `never_more` says some `d` exists with `cluster + d == standalone`, which is "never more" for natural numbers. `shared_once` says a cluster of one or more items costs its items plus the setup once. `saving` says the saving is the setup times the number of items after the first.
- `PROOF.bend` proves them. The real work is a lemma that standalone cost equals the items' own costs plus the setup once per item, proved by induction over the list. `saving` follows from it, and `never_more` uses the saving as its `d`. `shared_once` holds by unfolding the code, so its proof is one step.
- `nat.bend` proves the four facts about addition the lemma needs, such as associativity and commutativity. Bend's Base library doesn't have them yet.
- `cost.py` is the same rule in Python, as the twin's cluster code would compute it.
- `run_spike.py` runs the checks and writes `results.json`.

## 3. The checks

| Check | Passes when |
|---|---|
| B1 | The Bend 2.0.40 archive for linux-x64 matches the sha256 in that release's install script. It's unpacked into the run's folder with telemetry off |
| B2 | `bend LAWS.bend` alone reports the laws open (SOME PROOFS FAIL), and `bend PROOF.bend` reports ALL PROOFS CHECK. No file uses `@unsafe` or `?TODO` |
| B3 | `bend PROOF.bend --verdict` passes. That reruns the proofs through BendTT, a small kernel written in Lean with its own proof. The kernel also rejects a translation where the cluster code was changed to count the setup twice and the proofs left as they were |
| B4 | Bend compiles `cost.bend` to JavaScript, and on 5,000 seeded random clusters it gives the same standalone and cluster costs as `cost.py`. All three laws hold on every case |
| B5 | Each of four seeded bugs in `cluster` makes `bend PROOF.bend` fail inside a proof, not in the code, and the bugged code really breaks at least one law on the random cases |

B3 needs Lean 4.34.0 on the path. The script records B3 as not run if Lean is missing, because the plan treats the kernel as optional. Run it with:

```
python3 spikes/bend-cost/run_spike.py --work /tmp/bendrun
```

## 4. Results

From the run that produced `results.json`. The whole script took about a minute, most of it building the Lean kernel.

| Check | Result |
|---|---|
| B1 | Pass |
| B2 | Pass. The proofs check in under half a second |
| B3 | Pass. The kernel build and check took 54 s, and the kernel rejected the tampered cluster |
| B4 | Pass. No differences on 5,000 cases, 1,220 of them empty clusters |
| B5 | Pass. All four bugs fail at a proof |

What the bugs break, from running the bugged code on the same cases:

| Bug | What goes wrong | Laws it breaks |
|---|---|---|
| B-M1 | Every item pays the setup, as if done alone | shared_once, saving |
| B-M2 | The setup is left out of the cluster | shared_once, saving |
| B-M3 | The setup is counted twice | never_more, shared_once, saving |
| B-M4 | The first item's own cost is dropped | shared_once, saving |

## 5. Findings

1. **"Never more" on its own is a weak rule.** Three of the four bugs keep a cluster at or below the standalone total, so `never_more` still holds for them. Leaving the setup out entirely even makes clusters look cheaper. What catches them is "counted exactly once", which is why verification.md section 3 has both halves and why the Hypothesis property for clusters needs both as well.
2. **Bend reports only the first failing proof.** Every bug stopped at `shared_once`, because it comes first. That's why B5 also runs the bugged code against all three laws.
3. **The Lean kernel is real, and it's separate.** bend2 rejects a bad proof before the kernel ever sees it, so the only way to test the kernel by itself was to edit the translation it reads. It refused the edited file and named the failing law. The translation from Bend to the kernel isn't proven, as the [Bend README](https://github.com/bendlang/bend) says, so the kernel guards the proofs and not the parsing.
4. **Proofs are cheap to check and slow to write.** Checking takes under a second. Writing the induction took most of the spike, mostly on rewrite steps and on Bend's rule that a value is used at most once unless it's marked reusable. Base has no lemmas for addition yet, so `nat.bend` proves them.
5. **There's no Python target yet,** so Python can't call the proven code. B4 compares Bend's JavaScript output with Python instead, which shows the two agree on the same inputs and doesn't prove the Python. The Hypothesis properties stay the check on the Python itself.

## 6. Effect on the plan

- D10 stands. Bend 2 isn't in the build path. The proof and B4 can run as an optional nightly job, and they make a short slide for an architect audience: the cluster rule, its proof, and the bug the proof refused.
- When clusters land in phase 5, their Hypothesis property checks both halves, never more and counted once, because the first half alone missed three of four bugs here.
- Revisit Bend when it ships a Python target, as D10 already says.
