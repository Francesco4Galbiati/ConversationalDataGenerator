# OntoPFAS competency questions (structural evaluation)

Structural D6 comparison for OntoPFAS runs with `evaluate_pragmatic_quality.py`: each question is
run for a random sample of entities on both graphs, and the histograms of answer counts are
compared with the Jensen-Shannon distance. No identity map is needed.

## Run

```sh
# 1. once: merge the reference files into the contract vocabulary
python output_parsing/normalize_reference_ontopfas.py resources/reference/ontopfas resources/reference/ontopfas_reference.ttl
# 2. per run: triples.json -> Turtle (use triples_0.json for many-to-many)
python output_parsing/parser_ontopfas.py resources/output/run_X/triples.json resources/output/run_X/output.ttl
# 3. evaluate
python evaluate_pragmatic_quality.py --reference resources/reference/ontopfas_reference.ttl \
  --synthetic resources/output/run_X/output.ttl \
  --questions competency_questions/ontopfas/manifest_generation.json --output-dir resources/output/run_X/evaluation
```

## Which questions, and why

The reference data covers activity sites, cities, countries, datasets and 16 measurements of 3
substances. It has no CAS numbers, carbon counts, functional groups, precursors, mobility,
regulations, exposures or outcomes, so CQ2-CQ9, CQ14, CQ16, CQ18-CQ20, CQ22 and CQ29 have no
reference answers. The questions kept are CQ12, CQ15, CQ21, CQ24 and CQ28 (measurements) and
three activity questions adapted from CQ27/CQ30 (CQA1-CQA3). The CSV queries were rewritten:
several use terms absent from the ontology (`ontopfas:value`, `ontopfas:validIn`, `ontopfas:concerLevel`,
`geo:lon`) or typographic quotes.

## Read with care

- Substance questions (CQ12, CQ15, CQ24) sample substances only, not precursors: in the generator only
  substances are measured, so a sampled precursor would always count as an entity with no answers.
- The evaluator samples `min(size, reference population, synthetic population)` entities. With 3
  reference substances, the substance questions (CQ12, CQ15, CQ24) compare 3 against 3: their
  distance is not informative. CQ21 and CQ28 are limited by 16 measurements and 6 datasets.
- The activity questions (CQA1-CQA3) have a large reference population (246 sites, 250 cities,
  33 countries); their sample size is set by the synthetic run, so they become meaningful on long runs.
