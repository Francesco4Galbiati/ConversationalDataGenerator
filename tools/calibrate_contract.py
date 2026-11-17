"""Calibrate an OntoPFAS contract's cardinalities and the preferential-sampling alphas against the reference.

The structure of a generated graph (how many entities of each kind, and how they are linked) is decided by
the code, not by the model: the scheduler picks each intent from the cardinalities, and the precondition
sampling picks which existing IDs are reused. So it can be simulated exactly, with a fake witness that only
creates fresh IDs, in about a second per 10,000-triple run. This script searches the weights and alphas whose
simulated graph is closest to the reference.

Score (lower is better), over the six reference distributions that the contract controls:
  shape = mean over six distributions of:
          concentration (cities per country, sites per dataset, measurements per dataset): 2 x the area between
            the Lorenz curves, which compares the inequality only and not the size (with --unique_slots there are
            always 17 countries, so raw counts per country would depend on the run length)
          intensity (sites per city, measurements per measured substance, per measured location):
            Wasserstein(reference, simulated) / mean(reference)
  size  = mean |log(simulated ratio / reference ratio)| for cities/sites, datasets/sites,
          locations/measurements, substances/measurements                       (reported, optional in the score)

Searched: the cardinalities of the intents the reference has data for, on a relative scale from 0.1 to 8
(RegisterActivity fixed at 5; only ratios matter to the scheduler, so the result is rescaled to integers), and alpha for countries, datasets, and substances in measurements (None = Francesco's least_used).
Fixed: intents with no reference data (DefineEnvironment, LinkActivityToPfas, DefineRegulation,
ReportExposure keep their contract value; the substance attributes follow the substance weight).
Always on: the schedule and --unique_slots country_name.

    python calibrate.py contract.yaml targets.json [--objective shape|shape+size] [--samples 160] [--seeds 2]
"""
import argparse
import collections
import copy
import importlib
import json
import math
import random
import sys
import time
import types as pytypes
from multiprocessing import Pool

import yaml

SEARCHED = ["RegisterPfasSubstance", "RegisterCountry", "PublishDataset", "RegisterCity",
            "DefineSamplingLocation", "RecordMeasurement"]
ATTRIBUTES = []      # substance attributes keep their contract value (1): tying them made substances a cheap filler
ALPHAS = {"country_id": [None, 0.25, 0.5, 0.75, 1.0],
          "dataset_id": [None, 0.5, 0.75, 1.0, 1.25, 1.5],
          "RecordMeasurement.pfas_id": [None, 0.25, 0.5]}
VALUES = [0.1, 0.2, 0.3, 0.5, 1, 2, 3, 5, 8]          # relative weights tried (RegisterActivity = 5)
DISTS = ["cities_per_country", "sites_per_city", "sites_per_dataset", "measurements_per_dataset",
         "measurements_per_substance", "measurements_per_location"]


# ---------------------------------------------------------------- fake runtime (conf + redis)
class FakeRedis:
    def __init__(self):
        self.sets, self.h = {}, {}
    def smembers(self, k): return set(self.sets.get(k, ()))
    def scard(self, k): return len(self.sets.get(k, ()))
    def sadd(self, k, *v): self.sets.setdefault(k, set()).update(v)
    def hmget(self, k, ids): return [self.h.get(k, {}).get(i) for i in ids]
    def hincrby(self, k, f, n): self.h.setdefault(k, {})[f] = int(self.h.get(k, {}).get(f, 0)) + n


def install_conf(contract, pslots, seed):
    c = pytypes.ModuleType("conf")
    c.ops, c.types = contract["intents"], contract["types"]
    c.redis, c.hallucinations = FakeRedis(), {}
    c.intent_selection, c.unique_slots = "schedule", {"country_name"}
    c.precondition_sampling = "preferential" if pslots else "least_used"
    c.preferential_alpha, c.preferential_slots = 1.0, pslots or None
    c.args = pytypes.SimpleNamespace(seed=seed)
    sys.modules["conf"] = c
    for m in ("functions", "intent_schedule"):
        sys.modules.pop(m, None)
    return c, importlib.import_module("functions"), importlib.import_module("intent_schedule")


# ---------------------------------------------------------------- one simulated run
def simulate(contract, pslots, seed, target_triples=10000):
    c, F, S = install_conf(contract, pslots, seed)
    ops, rnd = c.ops, random.Random(seed + 7)
    made = collections.defaultdict(list)
    links = {k: collections.Counter() for k in DISTS}
    triples, t = 0, 0
    while triples < target_triples:
        intent = S.next_intent()
        offered = F.least_used_precondition_ids({intent: ops[intent]})[intent]
        ans = {}
        for slot, ids in offered.items():
            v = ids[0] if len(ids) == 1 else rnd.choice(ids)
            ans[slot] = v
            c.redis.hincrby(f"precondition_usage:one_to_one:{intent}:{slot}", v, 1)
        for slot in ops[intent]["postconditions"]["slots"]:
            if slot.endswith("_id"):
                ans[slot] = f"{slot}{t}"
                made[slot].append(ans[slot])
        if "country_name" in ops[intent]["postconditions"]["slots"]:
            rem = S.remaining_options("country_name")
            ans["country_name"] = rnd.choice(rem) if rem else "X"
        if intent == "RegisterCity": links["cities_per_country"][ans["country_id"]] += 1
        if intent == "RegisterActivity":
            links["sites_per_city"][ans["city_id"]] += 1
            links["sites_per_dataset"][ans["dataset_id"]] += 1
        if intent == "RecordMeasurement":
            links["measurements_per_dataset"][ans["dataset_id"]] += 1
            links["measurements_per_substance"][ans["pfas_id"]] += 1
            links["measurements_per_location"][ans["location_id"]] += 1
        for slot, v in ans.items():
            c.redis.sadd(f"entities:{slot}", v)
        triples += len(ops[intent]["postconditions"]["triples"])
        t += 1
    over = {"cities_per_country": made["country_id"], "sites_per_city": made["city_id"],
            "sites_per_dataset": made["dataset_id"], "measurements_per_dataset": made["dataset_id"]}
    dists = {k: [links[k].get(x, 0) for x in over[k]] if k in over else list(links[k].values()) for k in DISTS}
    pops = {"sites": len(made["activity_id"]), "cities": len(made["city_id"]), "countries": len(made["country_id"]),
            "datasets": len(made["dataset_id"]), "measurements": len(made["measurement_id"]),
            "substances": len(links["measurements_per_substance"]), "locations": len(links["measurements_per_location"])}
    return dists, pops, t


# ---------------------------------------------------------------- score
def wasserstein(a, b):
    a, b = sorted(a), sorted(b)
    if not a or not b:
        return float("inf")
    grid = sorted({k / len(a) for k in range(len(a) + 1)} | {k / len(b) for k in range(len(b) + 1)})
    q = lambda xs, u: xs[min(int(u * len(xs)), len(xs) - 1)]
    return sum((u1 - u0) * abs(q(a, u0) - q(b, u0)) for u0, u1 in zip(grid, grid[1:]))


RATIOS = [("cities", "sites"), ("datasets", "sites"), ("locations", "measurements"), ("substances", "measurements")]


CONCENTRATION = ["cities_per_country", "sites_per_dataset", "measurements_per_dataset"]


def lorenz_distance(a, b):
    """Area between the two Lorenz curves (0 = same inequality, regardless of size or count; max 0.5)."""
    def curve(xs, u):
        xs = sorted(xs); n = len(xs); total = sum(xs) or 1
        k = u * n; i = int(k)
        part = sum(xs[:i]) + (xs[i] * (k - i) if i < n else 0)
        return part / total
    grid = [j / 400 for j in range(401)]
    return sum(abs(curve(a, u) - curve(b, u)) for u in grid) / len(grid)


def score(ref, dists, pops):
    # concentration: shape of the inequality only (Lorenz curves, scale-free), times 2 to span 0..1;
    # intensity: Wasserstein distance between counts, divided by the reference mean
    per = {}
    for k in DISTS:
        r = ref["distributions"][k]
        per[k] = (2 * lorenz_distance(r, dists[k]) if k in CONCENTRATION
                  else wasserstein(r, dists[k]) / (sum(r) / len(r)))
    rp = ref["populations"]
    size = {f"{a}/{b}": abs(math.log(max(pops[a], 1) / max(pops[b], 1) / (rp[a] / rp[b]))) for a, b in RATIOS}
    return sum(per.values()) / len(per), sum(size.values()) / len(size), per, size


# ---------------------------------------------------------------- search
def apply(base, weights):
    contract = copy.deepcopy(base)
    for intent, w in weights.items():
        contract["intents"][intent]["preconditions"]["cardinality"] = w
    for intent in ATTRIBUTES:
        contract["intents"][intent]["preconditions"]["cardinality"] = weights["RegisterPfasSubstance"]
    return contract


def evaluate(job):
    base, ref, weights, alphas, seeds, objective = job
    pslots = {k: v for k, v in alphas.items() if v is not None}
    shapes, sizes, per_all, size_all, pops_all = [], [], collections.defaultdict(list), collections.defaultdict(list), []
    for seed in seeds:
        dists, pops, turns = simulate(apply(base, weights), pslots, seed)
        sh, sz, per, size = score(ref, dists, pops)
        shapes.append(sh); sizes.append(sz); pops_all.append(pops)
        for k, v in per.items(): per_all[k].append(v)
        for k, v in size.items(): size_all[k].append(v)
    m = lambda xs: sum(xs) / len(xs)
    total = m(shapes) + (m(sizes) if objective == "shape+size" else 0)
    return {"weights": weights, "alphas": alphas, "score": total, "shape": m(shapes), "size": m(sizes),
            "per": {k: m(v) for k, v in per_all.items()}, "size_terms": {k: m(v) for k, v in size_all.items()},
            "pops": {k: round(m([p[k] for p in pops_all])) for k in pops_all[0]}}


def random_config(rng):
    w = {i: rng.choice(VALUES) for i in SEARCHED}
    return w, {k: rng.choice(v) for k, v in ALPHAS.items()}


def neighbours(weights, alphas):
    for i in SEARCHED:
        j = VALUES.index(weights[i]) if weights[i] in VALUES else min(range(len(VALUES)), key=lambda k: abs(VALUES[k] - weights[i]))
        for d in (-1, 1):
            if 0 <= j + d < len(VALUES):
                yield {**weights, i: VALUES[j + d]}, alphas
    for k, vals in ALPHAS.items():
        j = vals.index(alphas[k])
        for d in (-1, 1):
            if 0 <= j + d < len(vals):
                yield weights, {**alphas, k: vals[j + d]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("contract"); ap.add_argument("targets")
    ap.add_argument("--objective", choices=["shape", "shape+size"], default="shape")
    ap.add_argument("--samples", type=int, default=160)
    ap.add_argument("--seeds", type=int, default=2)
    ap.add_argument("--rounds", type=int, default=12)
    ap.add_argument("--out", default="calibration.json")
    args = ap.parse_args()
    base = yaml.safe_load(open(args.contract))
    for i in ("RegisterActivity",):
        base["intents"][i]["preconditions"]["cardinality"] = 5
    ref = json.load(open(args.targets))
    seeds = list(range(args.seeds))
    rng = random.Random(0)
    start = time.time()
    current = {i: base["intents"][i]["preconditions"]["cardinality"] for i in SEARCHED}
    pool = Pool()
    jobs = [(base, ref, current, {"country_id": 0.75, "dataset_id": 1.0, "RecordMeasurement.pfas_id": None}, seeds, args.objective)]
    jobs += [(base, ref, *random_config(rng), seeds, args.objective) for _ in range(args.samples)]
    results = pool.map(evaluate, jobs)
    results.sort(key=lambda r: r["score"])
    print(f"random search: {len(results)} configurations in {time.time() - start:.0f}s; best {results[0]['score']:.3f}", flush=True)
    best = results[0]
    for rnd in range(args.rounds):                      # local refinement around the best
        cand = [(base, ref, w, a, seeds, args.objective) for w, a in neighbours(best["weights"], best["alphas"])]
        res = pool.map(evaluate, cand)
        top = min(res, key=lambda r: r["score"])
        print(f"refine round {rnd + 1}: best {min(top['score'], best['score']):.3f}", flush=True)
        if top["score"] >= best["score"]:
            break
        best = top
    final = evaluate((base, ref, best["weights"], best["alphas"], list(range(100, 108)), args.objective))
    current_cfg = evaluate((base, ref, current, {"country_id": 0.75, "dataset_id": 1.0, "RecordMeasurement.pfas_id": None},
                            list(range(100, 108)), args.objective))
    json.dump({"objective": args.objective, "best": final, "contract_as_is": current_cfg,
               "top10_random": results[:10]}, open(args.out, "w"), indent=1)
    print(json.dumps({"best": final, "contract_as_is": current_cfg}, indent=1))


if __name__ == "__main__":
    main()
