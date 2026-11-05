# HealthEQKG competency questions

The [manifest](manifest.json) contains CQ1–CQ15 from Table 3 on page 193 of the supplied HealthEQKG excerpt. It retains the three focus areas for stratified macro-F1. The SPARQL files are implementations of the question text using the repository's HealthEQKG vocabulary. The excerpt includes Table 3 and refers to a query example in Figure 5b, which is outside the supplied page.

## Set the inputs before scoring

| Questions | Replace in the query |
| --- | --- |
| CQ1–CQ4 | `urn:healtheqkg:replace:doctor-d` with the IRI for Doctor D. CQ3 returns one row per placement by default. Uncomment its placement binding to select a particular placement. |
| CQ5 | The two placeholder IRIs with the IRIs for Doctors X and Y. This query returns an `ASK` Boolean. |
| CQ6–CQ8 | `urn:healtheqkg:replace:facility-f` with the IRI for Facility F. |
| CQ8 | `urn:healtheqkg:replace:state-adi-predicate` with the state rank or decile predicate used by the graphs. The repository ontology does not declare one. |
| CQ10 and CQ12 | `REPLACE_WITH_SPECIALTY_S` with the RDF literal for specialty S. Replace both occurrences in CQ10. |
| CQ12 | `REPLACE_WITH_PRIMARY_CARE_SPECIALTY` with a primary-care specialty literal. Add one `primary_care` row for each additional specialty in your definition. |

Use the graphs' actual literal forms, including any datatype or language tag for specialty labels. The evaluator reports unresolved placeholders as query preparation errors and excludes those questions from scored aggregates. The evaluator's identity map aligns returned answer IRIs. For query input IRIs that differ by graph, bind both known aliases in `VALUES` if each graph uses only its own alias. For CQ5, use a separate two-column row for each graph's doctor pair.

## Query assumptions

- Placement, schooling, and ADI links use the repository ontology predicates and accept the corresponding alternatives named in the generation contract under the same HealthEQKG namespace. The facility-to-ZIP join uses `schema:address/schema:postalCode` and the ZIP area's `heq:zipCodeValue`, matching the ZIP strings so leading zeroes are preserved. Adapt these paths if your graphs use a different representation.
- Placement years use four-digit literals or year nodes linked to a four-digit value with `schema:value`. ADI year values use four-digit literals. CQ4 and CQ11 match the ADI year to the placement year.
- CQ3 uses the physician's recorded specialty for the selected placements because the repository ontology models specialty on the physician.
- CQ9 uses the `National ADI > 80` cutoff stated in CQ11. CQ10 and CQ12–CQ15 use 2020 as a common ADI snapshot. CQ10 reports the mean and median across distinct ZIP-area and score pairs.
- CQ13 counts a physician once in each quintile where they have a practice location. CQ14 counts physicians in the most deprived quintile once and divides by the number with any valid 2020 National ADI score. Both use 20-point bands on the 1–100 National ADI scale.
- CQ15 compares 2020 facilities across quintiles using years from graduation to placement as a proxy for experience. Each facility contributes one mean to its quintile.

## Run the evaluator

From the repository root, after setting the bindings and checking the paths against your graph schema, run:

```sh
python3 evaluate_pragmatic_quality.py \
  --reference /path/to/reference.ttl \
  --synthetic /path/to/synthetic.ttl \
  --questions competency_questions/healtheqkg/manifest.json \
  --output-dir /path/to/healtheqkg-evaluation
```

## Categorical ADI evaluation

Use [manifest_categorical_adi.json](manifest_categorical_adi.json) as the `--questions` input to evaluate CQ9 and CQ11 with categorical ADI. These versions return the same kinds of answers as the originals (facilities and primary specialties) and use a single query per question on both graphs. The deprivation filter accepts a literal `high` or a numeric National ADI rank greater than 80 and at most 100. `low` and `mid` do not qualify. The queries look up ZIP areas by the facility's postal code, preserving leading zeroes and accepting plain and explicit `xsd:string` ZIP values. The year constraints still apply.

This comparison treats the generator's `high` label as the reference category `National ADI > 80`. Check that interpretation before reporting the scores. The generation contract lists the labels without numeric cutoffs. Report the two-question categorical evaluation separately from the original 15-question suite. The original manifest continues to point to the numeric queries.

## Combined structural evaluation

Use [manifest_generation.json](manifest_generation.json) with the evaluator to sample every query in the combined suite. No identity map or manual bindings are needed. CQ1–CQ3 sample physicians, CQ5 samples distinct unordered physician pairs, and CQ6 and the categorical CQ9 and CQ11 sample facilities. CQ9 records whether each sampled facility qualifies. CQ11 counts distinct specialties at each sampled facility.

Pass `--questions competency_questions/healtheqkg/manifest_generation.json` in the run command. The results appear under `structural_comparisons` in both reports. Use the original or categorical manifest for separate D6 answer-set scoring.

These seven queries accept the generator's `http://example.org/` predicates where their equivalents are known. CQ5 and categorical CQ11 also accept placement years on year nodes with `rdfs:label`. The ADI queries still require a structured facility postal code. A free-text address alone does not establish the facility-to-ZIP link.

## Repeat a question with different entity bindings

To evaluate several matched doctors or facilities, add an `instances` list to the question's manifest entry. For paired scoring, use the original manifest as the template or remove `structural_sample` from the combined manifest entry. Keep the placeholders in the SPARQL file. Each instance supplies a stable case ID and the reference IRI for every active placeholder, using the suffix after `urn:healtheqkg:replace:` as the binding name. The IRIs below illustrate the format.

```json
{
  "id": "CQ1",
  "query": "queries/cq01_physician_facilities.rq",
  "categories": {"focus": "physician", "adi": "non_adi"},
  "instances": [
    {"id": "doctor-01", "bindings": {"doctor-d": "urn:reference:doctor-01"}},
    {"id": "doctor-02", "bindings": {"doctor-d": "urn:reference:doctor-02"}}
  ]
}
```

For CQ5, bind `doctor-x` and `doctor-y` together in each instance. For CQ6, use `facility-f`. If the same entity has different IRIs across the graphs, pass a verified synthetic-to-reference `--identity-map`. The evaluator uses the reference IRI as the shared identifier and resolves the corresponding synthetic IRI before executing the query. Both IDs must exist in their respective graphs, and the synthetic match must be unique. The identity map can also align returned IRIs for the aligned comparison. The Turtle files are read as supplied.

Each instance appears in the report with both input bindings and its own scores. Overall metrics count each scored instance as one question. For macro-F1 by query template, see `stratified_macro_f1.question` in the output. Choose the cases before inspecting their scores. If the two graphs have no verified common entities, the entity-bound questions have no valid paired cases.

## Structural sampling settings

Edit `size` and `seed` in any `structural_sample` entry to adjust sampling. Each query uses the same sample size on both sides, capped by the smaller population of eligible entities or pairs. The evaluator uses the configured seed for the reference graph and the next integer for the synthetic graph.

For SELECT queries, the output includes coverage, mean and median counts of distinct answer tuples, and histograms that include zero answers. For CQ5, it includes true and false counts and the proportion of sampled pairs that share a facility in the same year. A sample may contain no positive pairs when the event is rare. Both kinds report base-2 Jensen–Shannon distance from 0 for identical histograms to 1 for no overlap. Individual sample outcomes appear in `results.json`. Structural results do not contribute to D6 aggregates.
