import json
import tempfile
import unittest
from pathlib import Path

from rdflib import BNode, Graph, Literal, RDFS, URIRef, XSD

from evaluate_pragmatic_quality import (
    HierarchyScorer,
    aggregate,
    canonical_term,
    compare,
    evaluate_question,
    main,
    scores,
)


class BrokenGraph(Graph):
    def query(self, *args, **kwargs):
        raise RuntimeError("test query failure")


def numeric_answers(*values):
    return {(canonical_term(Literal(value), "test"),) for value in values}


class PragmaticQualityTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)

    def evaluate(self, query, reference=None, synthetic=None):
        path = self.directory / "question.rq"
        path.write_text(query, encoding="utf-8")
        question = {"id": "test", "query": str(path), "categories": {"difficulty": "basic"}}
        return evaluate_question(
            question,
            Graph() if reference is None else reference,
            Graph() if synthetic is None else synthetic,
            {"literal": {}},
            None,
        )

    def test_intersection_and_empty_answers(self):
        result = compare(numeric_answers(1, 2, 3), numeric_answers(2, 3), {})
        self.assertEqual(result["intersection_count"], 2)
        self.assertAlmostEqual(result["scores"]["correctness"], 2 / 3)
        self.assertEqual(result["scores"]["completeness"], 1)
        self.assertAlmostEqual(result["scores"]["f1"], 0.8)
        for synthetic, reference, expected, label in (
            (set(), set(), 1, "both"),
            (set(), numeric_answers(1), 0, "synthetic"),
            (numeric_answers(1), set(), 0, "reference"),
        ):
            result = compare(synthetic, reference, {})
            self.assertEqual(result["empty_answers"], label)
            self.assertTrue(all(score == expected for score in result["scores"].values()))

    def test_canonical_rdf_terms(self):
        def canonical(term):
            return canonical_term(term, "reference")

        self.assertNotEqual(canonical(Literal("01", datatype=XSD.integer, normalize=False)),
                            canonical(Literal("1", datatype=XSD.integer)))
        self.assertNotEqual(canonical(Literal("1", datatype=XSD.integer)), canonical(Literal("1")))
        self.assertEqual(canonical(Literal("word", lang="EN")), canonical(Literal("word", lang="en")))
        self.assertNotEqual(canonical(Literal("word", lang="en")), canonical(Literal("word", lang="fr")))
        self.assertEqual(canonical(Literal("word")), canonical(Literal("word", datatype=XSD.string)))
        self.assertNotEqual(canonical(BNode("node")), canonical_term(BNode("node"), "synthetic"))

    def test_select_deduplicates_and_keeps_unbound(self):
        row = self.evaluate("SELECT ?x ?y WHERE { VALUES (?x ?y) { (1 UNDEF) (1 UNDEF) (1 2) } }")
        self.assertEqual(row["query_type"], "SELECT")
        self.assertEqual(row["comparisons"]["literal"]["intersection_count"], 2)
        unbound = self.evaluate("SELECT ?x WHERE { VALUES ?x { UNDEF } }")
        self.assertEqual(unbound["comparisons"]["literal"]["intersection_count"], 1)
        empty = self.evaluate("SELECT ?s WHERE { ?s <urn:missing> ?o }")
        self.assertEqual(empty["comparisons"]["literal"]["empty_answers"], "both")

    def test_ask_is_a_boolean_singleton_even_when_false(self):
        query = "ASK WHERE { <urn:s> <urn:p> <urn:o> }"
        false = self.evaluate(query)["comparisons"]["literal"]
        self.assertEqual(false["reference_count"], 1)
        self.assertEqual(false["empty_answers"], "neither")
        self.assertTrue(false["exact_match"])
        graph = Graph().add(tuple(map(URIRef, ("urn:s", "urn:p", "urn:o"))))
        different = self.evaluate(query, reference=graph)["comparisons"]["literal"]
        self.assertEqual(different["synthetic_count"], 1)
        self.assertEqual(different["scores"]["f1"], 0)

    def test_query_failures(self):
        query = "SELECT ?x WHERE { ?x <urn:p> ?y }"
        failed = self.evaluate(query, synthetic=BrokenGraph())
        self.assertEqual(failed["status"], "synthetic_failed")
        self.assertIn("test query failure", failed["errors"]["synthetic"])
        row = failed["comparisons"]["literal"]
        self.assertIsNone(row["synthetic_count"])
        self.assertEqual(row["reference_count"], 0)
        self.assertEqual(row["scores"], scores(0, 0, 1))
        self.assertFalse(row["exact_match"])
        self.assertEqual(aggregate([failed], "literal")["PQ4"]["f1"], 0)

        excluded = self.evaluate(query, reference=BrokenGraph())
        self.assertEqual(excluded["status"], "reference_failed")
        self.assertIsNone(excluded["comparisons"]["literal"]["scores"])
        self.assertIsNone(aggregate([excluded], "literal")["PQ3"])
        self.assertEqual(self.evaluate("not a query")["status"], "reference_failed")
        self.assertIn("outside local", self.evaluate(
            "ASK WHERE { SERVICE <urn:service> { ?x ?p ?o } }"
        )["errors"]["reference"])

    def test_unresolved_question_bindings_are_excluded(self):
        query = "ASK WHERE { VALUES (?x ?y) { (<urn:real> <urn:healtheqkg:replace:doctor-y>) } }"
        row = self.evaluate(query)
        self.assertIn("unresolved query placeholder", row["errors"]["reference"])
        self.assertIsNone(row["comparisons"]["literal"]["scores"])
        resolved = self.evaluate("ASK {}\n# <urn:healtheqkg:replace:optional>")
        self.assertEqual(resolved["status"], "scored")

    def test_macro_micro_exact_and_stratified_aggregation(self):
        def question(synthetic, reference, status, category):
            return {
                "comparisons": {"literal": compare(synthetic, reference, {})},
                "errors": {
                    "reference": "failed" if reference is None else None,
                    "synthetic": "failed" if synthetic is None else None,
                },
                "status": status,
                "categories": {"difficulty": category},
            }

        rows = [
            question(numeric_answers(1, 2, 3), numeric_answers(1, 2), "scored", "hard"),
            question(set(), set(), "scored", "easy"),
            question(None, numeric_answers(4), "synthetic_failed", "hard"),
            question(numeric_answers(9), None, "reference_failed", "easy"),
        ]
        result = aggregate(rows, "literal")
        self.assertEqual(result["scored_questions"], 3)
        self.assertAlmostEqual(result["PQ1"], 5 / 9)
        self.assertAlmostEqual(result["PQ2"], 2 / 3)
        self.assertAlmostEqual(result["PQ3"], 0.6)
        self.assertEqual(result["PQ4"], scores(2, 3, 3))
        self.assertAlmostEqual(result["PQ5"], 1 / 3)
        self.assertAlmostEqual(result["stratified_macro_f1"]["difficulty"]["hard"]["macro_f1"], 0.4)

    def test_hierarchy_maximum_weight_and_direction(self):
        root, parent, left, right = map(URIRef, ("urn:root", "urn:parent", "urn:left", "urn:right"))
        ontology = Graph()
        for child, ancestor in ((parent, root), (left, parent), (right, parent)):
            ontology.add((child, RDFS.subClassOf, ancestor))
        scorer = HierarchyScorer(ontology, {"urn:generated": str(left)}, 1, 2)
        spec = {"kind": "class", "root": str(root)}

        def answers(*terms):
            return {(("iri", str(term)),) for term in terms}

        # The exact match for left leaves the parent available as a match for right.
        result = scorer.score(spec, answers("urn:generated", parent), answers(left, right))
        self.assertAlmostEqual(result["scores"]["f1"], (1 + 2 / 3) / 2)
        descendant = scorer.score(spec, answers(left), answers(parent))
        self.assertAlmostEqual(descendant["scores"]["f1"], 1 / 3)
        siblings = scorer.score(spec, answers(left), answers(right))
        self.assertEqual(siblings["scores"]["f1"], 0)

    def test_cli_reports_literal_and_aligned_results(self):
        for name, data in {
            "reference.ttl": '<urn:gold> <urn:p> "01"^^<http://www.w3.org/2001/XMLSchema#integer> .',
            "synthetic.ttl": '<urn:generated> <urn:p> "01"^^<http://www.w3.org/2001/XMLSchema#integer> .',
            "question.rq": "SELECT ?x WHERE { ?x <urn:p> 01 }",
            "manifest.json": json.dumps([{"id": "entities", "query": "question.rq",
                                         "categories": {"difficulty": "basic"}}]),
            "alignment.json": json.dumps({"urn:generated": "urn:gold"}),
        }.items():
            (self.directory / name).write_text(data, encoding="utf-8")
        output = self.directory / "output"
        output.mkdir()
        (output / "results.json").write_text("previous results", encoding="utf-8")
        (output / "report.txt").write_text("previous report", encoding="utf-8")
        (output / "notes.txt").write_text("keep me", encoding="utf-8")
        main([
            "--reference", str(self.directory / "reference.ttl"),
            "--synthetic", str(self.directory / "synthetic.ttl"),
            "--questions", str(self.directory / "manifest.json"),
            "--identity-map", str(self.directory / "alignment.json"),
            "--output-dir", str(output),
        ])
        results = json.loads((output / "results.json").read_text(encoding="utf-8"))
        self.assertEqual(results["aggregates"]["literal"]["PQ3"], 0)
        self.assertEqual(results["aggregates"]["aligned"]["PQ3"], 1)
        self.assertEqual(results["aggregates"]["literal"]["potentially_unaligned_questions"], 1)
        self.assertEqual(results["aggregates"]["aligned"]["potentially_unaligned_questions"], 0)
        self.assertEqual(results["PQ6"]["status"], "not_applicable")
        self.assertIn("Literal comparison matches IRI spellings",
                      (output / "report.txt").read_text(encoding="utf-8"))
        self.assertEqual((output / "notes.txt").read_text(encoding="utf-8"), "keep me")

    def test_cli_reports_hierarchy_score_only_with_inputs(self):
        for name, data in {
            "reference.ttl": "<urn:s> <urn:p> <urn:child> .",
            "synthetic.ttl": "<urn:s> <urn:p> <urn:generated-parent> .",
            "ontology.ttl": "<urn:child> <http://www.w3.org/2000/01/rdf-schema#subClassOf> <urn:parent> .",
            "question.rq": "SELECT ?term WHERE { <urn:s> <urn:p> ?term }",
            "manifest.json": json.dumps([{
                "id": "terms", "query": "question.rq",
                "hierarchy": {"kind": "class", "root": "urn:parent"},
            }]),
            "alignment.json": json.dumps({"urn:generated-parent": "urn:parent"}),
        }.items():
            (self.directory / name).write_text(data, encoding="utf-8")
        common = [
            "--reference", str(self.directory / "reference.ttl"),
            "--synthetic", str(self.directory / "synthetic.ttl"),
            "--questions", str(self.directory / "manifest.json"),
        ]
        main(common + ["--output-dir", str(self.directory / "without")])
        main(common + [
            "--output-dir", str(self.directory / "with"),
            "--ontology", str(self.directory / "ontology.ttl"),
            "--ontology-alignment", str(self.directory / "alignment.json"),
            "--lambda-ancestor", "1",
            "--lambda-descendant", "2",
        ])
        unavailable = json.loads((self.directory / "without" / "results.json").read_text())
        self.assertEqual(unavailable["PQ6"]["status"], "unavailable")
        scored = json.loads((self.directory / "with" / "results.json").read_text())
        self.assertEqual(scored["aggregates"]["literal"]["PQ3"], 0)
        self.assertEqual(scored["PQ6"], {"status": "scored", "scored_questions": 1, "macro_f1": 0.5})

    def test_cli_repeats_questions_with_verified_entity_bindings(self):
        files = {
            "reference.ttl": '<urn:doctor:ref> <urn:works-at> <urn:facility:ref> .\n'
                             '<urn:doctor:shared> <urn:works-at> <urn:facility:shared> .',
            "synthetic.ttl": '<urn:doctor:syn> <urn:works-at> <urn:facility:syn> .\n'
                             '<urn:doctor:shared> <urn:works-at> <urn:facility:shared> .',
            "question.rq": "SELECT ?facility WHERE {\n"
                           "  VALUES ?doctor { <urn:healtheqkg:replace:doctor-d> }\n"
                           "  ?doctor <urn:works-at> ?facility .\n}",
            "manifest.json": json.dumps([{
                "id": "CQ1", "query": "question.rq",
                "instances": [
                    {"id": "mapped", "bindings": {"doctor-d": "urn:doctor:ref"}},
                    {"id": "shared", "bindings": {"doctor-d": "urn:doctor:shared"}},
                    {"id": "absent", "bindings": {"doctor-d": "urn:doctor:missing"}},
                ],
            }]),
            "alignment.json": json.dumps({
                "urn:doctor:syn": "urn:doctor:ref",
                "urn:facility:syn": "urn:facility:ref",
            }),
        }
        for filename, content in files.items():
            (self.directory / filename).write_text(content, encoding="utf-8")
        output = self.directory / "output"
        main([
            "--reference", str(self.directory / "reference.ttl"),
            "--synthetic", str(self.directory / "synthetic.ttl"),
            "--questions", str(self.directory / "manifest.json"),
            "--identity-map", str(self.directory / "alignment.json"),
            "--output-dir", str(output), "--no-progress",
        ])
        result = json.loads((output / "results.json").read_text())
        mapped, shared, absent = result["questions"]
        self.assertEqual(mapped["synthetic_bindings"], {"doctor-d": "urn:doctor:syn"})
        self.assertFalse(mapped["comparisons"]["literal"]["exact_match"])
        self.assertTrue(mapped["comparisons"]["aligned"]["exact_match"])
        self.assertTrue(shared["comparisons"]["literal"]["exact_match"])
        self.assertIn("absent", absent["errors"]["reference"])
        self.assertEqual(
            result["aggregates"]["aligned"]["stratified_macro_f1"]["question"]["CQ1"],
            {"scored_questions": 2, "macro_f1": 1.0},
        )

    def test_cli_keeps_independent_structural_samples_out_of_d6(self):
        files = {
            "reference.ttl": "<urn:r1> a <urn:Physician>; <urn:works-at> <urn:facility> .\n"
                             "<urn:r2> a <urn:Physician>; <urn:works-at> <urn:facility> .",
            "synthetic.ttl": "<urn:s1> a <urn:Physician>; <urn:works-at> <urn:other-facility> .\n"
                             "<urn:s2> a <urn:Physician> .",
            "question.rq": "SELECT ?facility WHERE {\n"
                           "  VALUES ?physician { <urn:healtheqkg:replace:doctor-d> }\n"
                           "  ?physician <urn:works-at> ?facility .\n}",
            "manifest.json": json.dumps([{
                "id": "CQ1", "query": "question.rq",
                "structural_sample": {"variable": "physician", "types": ["urn:Physician"], "size": 5},
            }]),
        }
        for filename, content in files.items():
            (self.directory / filename).write_text(content, encoding="utf-8")
        output = self.directory / "output"
        main([
            "--reference", str(self.directory / "reference.ttl"),
            "--synthetic", str(self.directory / "synthetic.ttl"),
            "--questions", str(self.directory / "manifest.json"),
            "--output-dir", str(output), "--no-progress",
        ])
        result = json.loads((output / "results.json").read_text())
        comparison, = result["structural_comparisons"]
        self.assertEqual(comparison["reference"]["histogram"], {"1": 2})
        self.assertEqual(comparison["synthetic"]["histogram"], {"0": 1, "1": 1})
        self.assertEqual(comparison["synthetic"]["coverage"], 0.5)
        self.assertAlmostEqual(comparison["jensen_shannon_distance"], 0.5579230453)
        self.assertEqual(result["aggregates"]["literal"]["scored_questions"], 0)
        self.assertIn("Structural comparisons", (output / "report.txt").read_text())

    def test_health_eqkg_manifest_samples_all_seven_questions(self):
        graph = self.directory / "health.ttl"
        graph.write_text("""
@prefix gen: <http://example.org/> .
@prefix schema: <http://schema.org/> .
@prefix ex: <urn:fixture:> .
ex:p1 a gen:Physician ; gen:graduateFrom ex:school ; gen:medicalSpecialty "Cardiology" .
ex:p2 a gen:Physician .
ex:p3 a gen:Physician .
ex:f a gen:Facility ; schema:address [ schema:postalCode "01234" ] .
ex:j1 gen:placementFor ex:p1 ; gen:hasFacility ex:f ; gen:hasTimeReference 2020 .
ex:j2 gen:placementFor ex:p2 ; gen:hasFacility ex:f ; gen:hasTimeReference 2020 .
ex:zip gen:zipCodeValue "01234" ; gen:hasADIScore ex:score .
ex:score gen:scoredIn 2020 ; gen:nationalScore "high" .
""", encoding="utf-8")
        manifest = (Path(__file__).resolve().parents[1] / "competency_questions"
                    / "healtheqkg" / "manifest_generation.json")
        output = self.directory / "output"
        main([
            "--reference", str(graph), "--synthetic", str(graph),
            "--questions", str(manifest), "--output-dir", str(output), "--no-progress",
        ])
        result = json.loads((output / "results.json").read_text(encoding="utf-8"))
        expected_histograms = {
            "CQ1": {"0": 1, "1": 2},
            "CQ2": {"0": 2, "1": 1},
            "CQ3": {"0": 2, "1": 1},
            "CQ5": {"false": 2, "true": 1},
            "CQ6": {"1": 1},
            "CQ9-categorical-adi": {"1": 1},
            "CQ11-categorical-adi": {"1": 1},
        }
        self.assertEqual(result["questions"], [])
        self.assertEqual({
            item["id"]: item["reference"]["histogram"] for item in result["structural_comparisons"]
        }, expected_histograms)
        for item in result["structural_comparisons"]:
            self.assertEqual(item["status"], "compared")
            self.assertEqual(item["jensen_shannon_distance"], 0)


if __name__ == "__main__":
    unittest.main()
