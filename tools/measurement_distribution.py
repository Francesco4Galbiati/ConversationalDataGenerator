"""Fair comparison of the measurement questions (CQ15, CQ24, CQ12, and measurements per location) between the reference and generated graphs.

Why a separate script: in the reference a substance exists only because it was measured, while generated
graphs also register substances that are never measured; and the evaluator's JS distance compares exact
counts of only 3 reference substances. Here:
- the population is the MEASURED substances on both sides (all of them, no sampling);
- next to the evaluator's JS, it reports the mean and the Wasserstein (earth mover's) distance, for which
  "3 measurements" is close to "4" and far from "40".

    python tools/measurement_distribution.py resources/reference/ontopfas_reference.ttl run1/output.ttl [run2/output.ttl ...]
"""
import collections
import sys

from rdflib import Graph, RDF, URIRef

O = "https://w3id.org/OntoPFAS#"
SOSA = "http://www.w3.org/ns/sosa/"


def counts(path):
    g = Graph()
    g.parse(path)
    per_substance = collections.defaultdict(set)
    environments = collections.defaultdict(set)
    per_location = collections.Counter()
    for obs in g.subjects(RDF.type, URIRef(SOSA + "Observation")):
        for pfas in g.objects(obs, URIRef(O + "measuredPfas")):
            per_substance[pfas].add(obs)
            environments[pfas].update(g.objects(obs, URIRef(O + "matrix")))
        for loc in g.objects(obs, URIRef(O + "measuredIn")):
            per_location[loc] += 1
    m = [len(v) for v in per_substance.values()]
    e = [len(environments[p]) for p in per_substance]
    return m, e, list(per_location.values())


def wasserstein(a, b):
    """1-D earth mover's distance between two samples of counts (exact, via sorted quantiles)."""
    a, b = sorted(a), sorted(b)
    if not a or not b:
        return float("nan")
    grid = sorted({k / len(a) for k in range(len(a) + 1)} | {k / len(b) for k in range(len(b) + 1)})
    q = lambda xs, t: xs[min(int(t * len(xs)), len(xs) - 1)]
    return sum((t1 - t0) * abs(q(a, t0) - q(b, t0)) for t0, t1 in zip(grid, grid[1:]))


def js(a, b):
    from math import log2
    ca, cb = collections.Counter(a), collections.Counter(b)
    p = {k: v / len(a) for k, v in ca.items()}
    q = {k: v / len(b) for k, v in cb.items()}
    keys = set(p) | set(q)
    m = {k: (p.get(k, 0) + q.get(k, 0)) / 2 for k in keys}
    kl = lambda x: sum(x[k] * log2(x[k] / m[k]) for k in keys if x.get(k, 0) > 0)
    return max(0.0, (kl(p) + kl(q)) / 2) ** 0.5


def describe(label, m, e, l, ref=None, ref_l=None):
    h = dict(sorted(collections.Counter(m).items()))
    line = (f"{label}: {len(m)} measured substances, {sum(m)} measurements, mean {sum(m) / len(m):.1f}, "
            f"max {max(m)}, environments per substance mean {sum(e) / len(e):.1f}")
    line += f"\n    measurements per location: mean {sum(l) / len(l):.1f}, max {max(l)} over {len(l)} locations"
    if ref is not None:
        line += (f"\n    vs reference: per substance Wasserstein {wasserstein(ref, m):.2f}, JS {js(ref, m):.2f}"
                 f" | per location Wasserstein {wasserstein(ref_l, l):.2f}, JS {js(ref_l, l):.2f}")
    print(line + f"\n    measurements per substance: {h if len(h) <= 12 else str(dict(list(h.items())[:12])) + ' ...'}")


if __name__ == "__main__":
    ref_m, ref_e, ref_l = counts(sys.argv[1])
    describe("reference", ref_m, ref_e, ref_l)
    for path in sys.argv[2:]:
        m, e, l = counts(path)
        describe(path, m, e, l, ref_m, ref_l)
