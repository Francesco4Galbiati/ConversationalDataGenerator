"""Evaluate SPARQL competency questions against reference and synthetic RDF graphs."""

import argparse
import json
import random
import re
import sys
from bisect import bisect_right
from collections import Counter, defaultdict
from collections.abc import Mapping
from math import comb, isfinite, log2, sqrt
from pathlib import Path
from statistics import mean, median
from tempfile import TemporaryDirectory
from time import perf_counter
from urllib.parse import urlsplit

import rdflib
from rdflib import BNode, Graph, Literal, OWL, RDF, RDFS, URIRef, Variable, XSD
from rdflib.plugins.sparql.parserutils import CompValue
from rdflib.plugins.sparql.processor import prepareQuery
from rdflib.util import guess_format


def scores(matches, synthetic, reference, *, failed=False):
    """Compute D6 correctness, completeness, and F1 from answer counts.

    Exact scoring passes the intersection size as matches. PQ6 passes the sum
    of the matched pairs' weights.
    """
    if failed:
        correctness = completeness = 0.0
    elif not synthetic or not reference:
        # Two successful empty answers agree. An empty answer on only one side scores zero.
        correctness = completeness = float(synthetic == reference)
    else:
        correctness, completeness = matches / synthetic, matches / reference
    total = correctness + completeness
    return {
        "correctness": correctness,
        "completeness": completeness,
        "f1": 2 * correctness * completeness / total if total else 0.0,
    }


def canonical_term(term, side):
    """Make a hashable key that retains the RDF term's type and lexical form."""
    if isinstance(term, URIRef):
        return ("iri", str(term))
    if isinstance(term, BNode):
        # Blank-node labels are local to each graph and can coincide by accident.
        return ("blank", side, str(term))
    if isinstance(term, Literal):
        # RDF language tags compare case-insensitively. Plain strings have datatype xsd:string.
        language = term.language.lower() if term.language else None
        datatype = term.datatype or (RDF.langString if language else XSD.string)
        return ("literal", str(term), str(datatype), language)
    if term is None:
        return ("unbound",)
    raise ValueError(f"Unsupported RDF answer term {term!r}")


def query_nodes(node):
    """Walk the parsed query, including terms in VALUES rows."""
    yield node
    if isinstance(node, Mapping):
        for child in node.values():
            yield from query_nodes(child)
    elif isinstance(node, (list, tuple)):
        for child in node:
            yield from query_nodes(child)


def prepare_question(path, bindings=None, *, sample_variables=()):
    query_text = path.read_text(encoding="utf-8")
    if sample_variables:
        # Remove the template's placeholder VALUES row so initBindings can supply it.
        variables = r"\s+".join(r"\?" + re.escape(name) for name in sample_variables)
        terms = r"\s+".join(r"<urn:healtheqkg:replace:[^>]+>" for _ in sample_variables)
        if len(sample_variables) == 2:
            variables = rf"\(\s*{variables}\s*\)"
            terms = rf"\(\s*{terms}\s*\)"
        placeholder = rf"^[ \t]*(?i:VALUES)\s+{variables}\s+\{{\s*{terms}\s*\}}"
        query_text = re.sub(placeholder, "", query_text, flags=re.MULTILINE)
    for name, iri in (bindings or {}).items():
        placeholder = URIRef(f"urn:healtheqkg:replace:{name}").n3()
        if not any(placeholder in line for line in query_text.splitlines()
                   if not line.lstrip().startswith("#")):
            raise ValueError(f"Query has no active placeholder for binding {name!r}")
        query_text = query_text.replace(placeholder, URIRef(iri).n3())
    query = prepareQuery(query_text, base=path.as_uri())
    if query.algebra.name not in {"SelectQuery", "AskQuery"}:
        raise ValueError("Only SELECT and ASK queries are supported")
    if query.algebra.datasetClause:
        # Both executions must get their answers from the graph supplied to the evaluator.
        raise ValueError("FROM, FROM NAMED and SERVICE are outside local graph evaluation")
    for node in query_nodes(query.algebra):
        if isinstance(node, CompValue) and node.name == "ServiceGraphPattern":
            raise ValueError("FROM, FROM NAMED and SERVICE are outside local graph evaluation")
        if (
            isinstance(node, URIRef) and node.startswith("urn:healtheqkg:replace:")
            or isinstance(node, Literal) and str(node) in {
                "REPLACE_WITH_SPECIALTY_S", "REPLACE_WITH_PRIMARY_CARE_SPECIALTY",
            }
        ):
            raise ValueError(f"Replace the unresolved query placeholder {node.n3()} before scoring")
    return query


def execute(graph, query, side, *, bindings=None):
    """Return a set of answer tuples, or None and an error on execution failure."""
    try:
        result = graph.query(query, initBindings=bindings)
        if result.type == "ASK":
            # D6 represents each Boolean as one answer tuple, including false.
            return {(("boolean", bool(result.askAnswer)),)}, None
        # Sort by projected variable name so columns line up across executions.
        # Bindings retain an all-unbound row, which the regular result iterator drops.
        variables = sorted(result.vars)
        return {
            tuple(canonical_term(binding.get(var), side) for var in variables)
            for binding in result.bindings
        }, None
    except Exception as error:
        return None, f"{type(error).__name__}: {error}"


def jensen_shannon_distance(left, right):
    """Return base-2 Jensen–Shannon distance over discrete answer counts."""
    totals = sum(left.values()), sum(right.values())
    divergence = 0.0
    for count in sorted(left.keys() | right.keys()):
        probabilities = left.get(count, 0) / totals[0], right.get(count, 0) / totals[1]
        midpoint = mean(probabilities)
        divergence += sum(p * log2(p / midpoint) for p in probabilities if p) / 2
    return sqrt(max(0.0, divergence))


def sample_bindings(population, variables, size, seed):
    """Sample entities or distinct unordered pairs without replacement."""
    rng = random.Random(seed)
    if len(variables) == 1:
        for entity in rng.sample(population, size):
            yield {variables[0]: entity}
        return

    # Index pairs in lexicographic order without constructing the quadratic pair list.
    count = len(population)
    starts = [i * (2 * count - i - 1) // 2 for i in range(count)]
    for index in rng.sample(range(comb(count, 2)), size):
        left = bisect_right(starts, index) - 1
        right = left + 1 + index - starts[left]
        yield dict(zip(variables, (population[left], population[right])))


def measure_structure(graph, query, side, population, variables, size, seed):
    is_ask = query.algebra.name == "AskQuery"
    outcomes = []
    for bindings in sample_bindings(population, variables, size, seed):
        answers, error = execute(graph, query, side, bindings=bindings)
        if error:
            raise ValueError(f"{side} query failed for {bindings} ({error})")
        outcome = (("boolean", True),) in answers if is_ask else len(answers)
        outcomes.append((bindings, outcome))
    histogram = Counter(outcome for _, outcome in outcomes)
    result = {"population": len(population), "sample_size": size, "seed": seed}
    if is_ask:
        result.update(
            histogram={"false": histogram[False], "true": histogram[True]},
            true_rate=histogram[True] / size,
            outcomes_by_pair=[{"bindings": bindings, "answer": outcome} for bindings, outcome in outcomes],
        )
    else:
        counts = {str(bindings[variables[0]]): outcome for bindings, outcome in outcomes}
        result.update(
            entities_with_answers=size - histogram[0],
            coverage=(size - histogram[0]) / size,
            mean_answer_count=mean(counts.values()),
            median_answer_count=median(counts.values()),
            histogram=dict(sorted(histogram.items())),
            counts_by_entity=counts,
        )
    return result


def compare_structure(question, graphs, *, show_progress=False):
    """Compare SELECT answer counts or ASK outcomes from independent samples."""
    spec = question["structural_sample"]
    variables = spec["variables"]
    result = {"id": question["id"], "query": question["query"], "settings": spec}
    try:
        query = prepare_question(Path(question["query"]), sample_variables=variables)
        result["query_type"] = query.algebra.name.removesuffix("Query").upper()
        expected = "AskQuery" if len(variables) == 2 else "SelectQuery"
        if query.algebra.name != expected:
            raise ValueError("Structural sampling requires one variable for SELECT or two for ASK")
        query_variables = {node for node in query_nodes(query.algebra) if isinstance(node, Variable)}
        if not set(map(Variable, variables)) <= query_variables:
            raise ValueError("A sample variable is absent from the query")
        populations = {
            side: sorted({
                entity for kind in spec["types"] for entity in graph.subjects(RDF.type, URIRef(kind))
                if isinstance(entity, URIRef)
            })
            for side, graph in graphs.items()
        }
        size = min(spec["size"], *(comb(len(population), len(variables)) for population in populations.values()))
        if not size:
            empty_sides = ", ".join(
                side for side, population in populations.items() if len(population) < len(variables)
            )
            raise ValueError(f"Not enough named entities of the requested types in {empty_sides}")
        for offset, (side, population) in enumerate(populations.items()):
            if show_progress:
                unit = "pairs" if len(variables) == 2 else "entities"
                print(f"{question['id']}: sampling {size} {unit} on the {side} graph",
                      file=sys.stderr, flush=True)
            result[side] = measure_structure(
                graphs[side], query, side, population, variables, size, spec["seed"] + offset,
            )
        result["jensen_shannon_distance"] = jensen_shannon_distance(
            result["reference"]["histogram"], result["synthetic"]["histogram"]
        )
    except Exception as error:
        result.update(status="unavailable", error=str(error))
    else:
        result["status"] = "compared"
    return result


def map_answers(answers, alignment):
    """Map returned synthetic IRIs to reference IRIs and deduplicate the resulting rows."""
    if not alignment:
        return answers
    return {
        tuple(("iri", alignment.get(term[1], term[1])) if term[0] == "iri" else term
              for term in row)
        for row in answers
    }


def potential_unaligned(answers, confirmed):
    """Count distinct blank nodes and IRIs without explicit identity confirmation."""
    return len({
        term for row in answers or () for term in row
        if term[0] == "blank" or (term[0] == "iri" and term[1] not in confirmed)
    })


def compare(synthetic, reference, alignment):
    """Score one question in one comparison mode and retain its answer counts."""
    aligned = map_answers(synthetic, alignment) if synthetic is not None else None
    result = {
        "synthetic_count": None if aligned is None else len(aligned),
        "reference_count": None if reference is None else len(reference),
        "intersection_count": None,
        "empty_answers": None,
        "exact_match": None,
        "scores": None,
        "potentially_unaligned_identifiers": {
            "synthetic": potential_unaligned(synthetic, alignment),
            "reference": potential_unaligned(reference, set(alignment.values())),
        },
    }
    if reference is None:
        # A reference failure leaves no gold set, so this question has no score.
        return result
    if aligned is None:
        # A synthetic failure counts as a miss even when the reference result is empty.
        result.update(intersection_count=0, exact_match=False,
                      scores=scores(0, 0, len(reference), failed=True))
        return result
    matches = len(aligned & reference)
    empty = ("both" if not aligned and not reference else "synthetic" if not aligned
             else "reference" if not reference else "neither")
    result.update(intersection_count=matches, empty_answers=empty,
                  exact_match=aligned == reference, scores=scores(matches, len(aligned), len(reference)))
    return result


class HierarchyScorer:
    """Score ontology-term answers against a caller-supplied hierarchy (PQ6)."""

    def __init__(self, ontology, alignment, lambda_ancestor, lambda_descendant):
        # NetworkX is needed only when hierarchy-aware scoring is requested.
        import networkx as nx

        self.nx = nx
        self.alignment = alignment
        self.penalties = (lambda_ancestor, lambda_descendant)
        self.graphs = {}
        self.distances = {}
        kinds = {
            "class": (RDFS.subClassOf, (RDFS.Class, OWL.Class)),
            "property": (RDFS.subPropertyOf, (
                RDF.Property, OWL.ObjectProperty, OWL.DatatypeProperty, OWL.AnnotationProperty,
            )),
        }
        for kind, (predicate, types) in kinds.items():
            hierarchy = nx.DiGraph()
            hierarchy.add_nodes_from(
                str(term) for term_type in types for term in ontology.subjects(RDF.type, term_type)
                if isinstance(term, URIRef)
            )
            # RDF subclass and subproperty triples point from child to parent.
            # Reverse them so paths from the supplied root give the terms' depths.
            hierarchy.add_edges_from(
                (str(parent), str(child)) for child, parent in ontology.subject_objects(predicate)
                if isinstance(child, URIRef) and isinstance(parent, URIRef) and child != parent
            )
            self.graphs[kind] = hierarchy

    def descendants(self, kind, term):
        """Return shortest downward distances, including distance zero to the term itself."""
        key = (kind, term)
        if key not in self.distances:
            self.distances[key] = self.nx.single_source_shortest_path_length(self.graphs[kind], term)
        return self.distances[key]

    def score(self, spec, synthetic, reference):
        """Find a maximum-weight one-to-one matching of predicted and gold terms."""
        kind, root = spec["kind"], spec["root"]
        hierarchy = self.graphs[kind]
        if root not in hierarchy:
            return {"status": "unavailable", "reason": "Root missing from the supplied hierarchy"}
        depth = self.descendants(kind, root)
        if not self.nx.is_directed_acyclic_graph(hierarchy.subgraph(depth)):
            return {"status": "unavailable", "reason": "Rooted hierarchy contains a cycle"}
        if reference is None:
            return {"status": "unavailable", "reason": "Reference query failed"}
        if any(len(row) != 1 or row[0][0] != "iri"
               for answers in (reference, synthetic or ()) for row in answers):
            return {"status": "unavailable", "reason": "PQ6 requires single-column ontology IRI answers"}
        gold = {row[0][1] for row in reference}
        if not gold <= depth.keys():
            return {"status": "unavailable", "reason": "Gold terms missing from the rooted hierarchy"}
        if synthetic is None:
            return {"status": "scored", "scores": scores(0, 0, len(gold), failed=True)}
        predicted = {row[0][1] for row in map_answers(synthetic, self.alignment)}
        matching = self.nx.Graph()
        # Out-of-hierarchy predictions stay in the denominator and have no matching edges.
        for answer in sorted(predicted & depth.keys()):
            for target in sorted(gold):
                # D6 scales path length by the gold term's depth and applies a
                # different penalty for a broader or narrower prediction.
                if answer == target:
                    weight = 1.0
                elif target in self.descendants(kind, answer):
                    distance = self.descendants(kind, answer)[target]
                    weight = 1 / (1 + self.penalties[0] * distance / max(1, depth[target]))
                elif answer in self.descendants(kind, target):
                    distance = self.descendants(kind, target)[answer]
                    weight = 1 / (1 + self.penalties[1] * distance / max(1, depth[target]))
                else:
                    continue
                # Tag the sides so an identical IRI can appear in both partitions.
                matching.add_edge(("synthetic", answer), ("reference", target), weight=weight)
        pairs = self.nx.max_weight_matching(matching)
        weight = sum(matching.edges[pair]["weight"] for pair in sorted(pairs))
        return {"status": "scored", "scores": scores(weight, len(predicted), len(gold))}


def resolve_bindings(bindings, reference, synthetic, synthetic_aliases):
    """Use reference IRIs as shared IDs and resolve the terms used on each side."""
    resolved = {}
    for name, reference_iri in bindings.items():
        candidates = {reference_iri} | synthetic_aliases.get(reference_iri, set())
        reference_term = URIRef(reference_iri)
        if not ((reference_term, None, None) in reference or (None, None, reference_term) in reference):
            raise ValueError(f"Reference binding {name!r} is absent from the reference graph")
        present = set()
        for candidate in candidates:
            term = URIRef(candidate)
            if (term, None, None) in synthetic or (None, None, term) in synthetic:
                present.add(candidate)
        if len(present) != 1:
            raise ValueError(f"Binding {name!r} needs exactly one synthetic match for {reference_iri}")
        resolved[name] = present.pop()
    return resolved


def evaluate_question(question, reference, synthetic, modes, hierarchy, *,
                      show_progress=False, synthetic_aliases=None):
    """Prepare a single query for both graphs, then score its answers in each mode."""
    if show_progress:
        print(f"{question['id']}: preparing query", file=sys.stderr, flush=True)
    bindings = question.get("bindings")
    synthetic_bindings = None
    try:
        path = Path(question["query"])
        if bindings:
            synthetic_bindings = resolve_bindings(bindings, reference, synthetic, synthetic_aliases or {})
        query = prepare_question(path, bindings)
        synthetic_query = query if bindings == synthetic_bindings else prepare_question(path, synthetic_bindings)
    except Exception as error:
        # A shared query that cannot be prepared leaves both executions without answers.
        reference_answers = synthetic_answers = None
        reference_error = synthetic_error = f"{type(error).__name__}: {error}"
        query_type = None
        if show_progress:
            print(f"{question['id']}: skipped during preparation ({reference_error})",
                  file=sys.stderr, flush=True)
    else:
        query_type = query.algebra.name.removesuffix("Query").upper()
        executions = []
        for side, graph, prepared in (
            ("reference", reference, query), ("synthetic", synthetic, synthetic_query)
        ):
            if show_progress:
                print(f"{question['id']}: querying {side} graph", file=sys.stderr, flush=True)
            started = perf_counter()
            executions.append(execute(graph, prepared, side))
            if show_progress:
                elapsed = perf_counter() - started
                print(f"{question['id']}: {side} query finished in {elapsed:.2f}s",
                      file=sys.stderr, flush=True)
        (reference_answers, reference_error), (synthetic_answers, synthetic_error) = executions

    # PQ6 uses its own ontology alignment, independent of literal and entity-aligned scores.
    if not question.get("hierarchy"):
        pq6 = {"status": "not_applicable", "reason": "Question has no ontology answer metadata"}
    elif hierarchy is None:
        pq6 = {"status": "unavailable", "reason": "Ontology hierarchy or alignment was not supplied"}
    elif query_type == "ASK":
        pq6 = {"status": "not_applicable", "reason": "ASK returns a boolean"}
    else:
        if show_progress:
            print(f"{question['id']}: scoring hierarchy matches", file=sys.stderr, flush=True)
        pq6 = hierarchy.score(question["hierarchy"], synthetic_answers, reference_answers)
    return {
        **question,
        **({"synthetic_bindings": synthetic_bindings} if bindings else {}),
        "query_type": query_type,
        "status": ("reference_failed" if reference_error else
                   "synthetic_failed" if synthetic_error else "scored"),
        "errors": {"reference": reference_error, "synthetic": synthetic_error},
        "comparisons": {
            mode: compare(synthetic_answers, reference_answers, alignment)
            for mode, alignment in modes.items()
        },
        "PQ6": pq6,
    }


def aggregate(questions, mode):
    """Compute PQ1–PQ5 and category-level macro-F1 for a comparison mode."""
    # Reference failures have no scores. Synthetic failures remain as zero-score questions.
    included = [q for q in questions if q["comparisons"][mode]["scores"] is not None]
    rows = [q["comparisons"][mode] for q in included]
    micro = None
    if rows:
        # PQ4 pools tuple counts before dividing. Failed synthetic queries
        # contribute no predictions, but their reference tuples still count.
        synthetic = sum(row["synthetic_count"] or 0 for row in rows)
        reference = sum(row["reference_count"] for row in rows)
        matches = sum(row["intersection_count"] for row in rows)
        # With no tuples on either side, a failure prevents a perfect micro score.
        empty_with_failure = synthetic == reference == 0 and any(
            q["status"] == "synthetic_failed" for q in included
        )
        micro = scores(matches, synthetic, reference, failed=empty_with_failure)

    strata = defaultdict(lambda: defaultdict(list))
    for question in questions:
        row = question["comparisons"][mode]
        for dimension, category in question["categories"].items():
            # Keep categories visible even if all their questions were excluded.
            values = strata[dimension][category]
            if row["scores"] is not None:
                values.append(row["scores"]["f1"])
    return {
        "scored_questions": len(rows),
        "reference_failures": sum(q["errors"]["reference"] is not None for q in questions),
        "synthetic_failures": sum(q["errors"]["synthetic"] is not None for q in questions),
        "potentially_unaligned_questions": sum(
            any(q["comparisons"][mode]["potentially_unaligned_identifiers"].values())
            for q in questions
        ),
        # PQ1–PQ3 give every scored question equal weight, regardless of answer count.
        **{pq: mean(row["scores"][metric] for row in rows) if rows else None
           for pq, metric in zip(("PQ1", "PQ2", "PQ3"), ("correctness", "completeness", "f1"))},
        "PQ4": micro,
        "PQ5": mean(row["exact_match"] for row in rows) if rows else None,
        "stratified_macro_f1": {
            dimension: {
                category: {"scored_questions": len(values), "macro_f1": mean(values) if values else None}
                for category, values in categories.items()
            }
            for dimension, categories in strata.items()
        },
    }


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def is_iri(value):
    return isinstance(value, str) and bool(urlsplit(value).scheme) and not any(
        character.isspace() or character in '<>"{}|^\x60\\' for character in value
    )


def read_alignment(path):
    alignment = read_json(path)
    if not isinstance(alignment, dict) or not all(
        is_iri(source) and is_iri(target) for source, target in alignment.items()
    ):
        raise ValueError(f"{path} must contain a JSON object mapping absolute IRIs to absolute IRIs")
    return alignment


def load_questions(source):
    """Read question metadata and resolve query paths against their directory or manifest."""
    if source.is_dir():
        entries = [
            {"id": path.stem, "query": path.name}
            for path in sorted(source.iterdir()) if path.is_file() and path.suffix.lower() in {".rq", ".sparql"}
        ]
        base = source
    else:
        entries = read_json(source)
        base = source.parent
    if not isinstance(entries, list) or not entries:
        raise ValueError("Supply at least one question in the query directory or JSON manifest")
    questions = []
    template_ids = set()
    instance_ids = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("Each manifest entry must be an object")
        question_id, query = entry.get("id"), entry.get("query")
        if not isinstance(question_id, str) or not question_id or question_id in template_ids:
            raise ValueError("Question IDs must be nonempty, unique strings")
        if not isinstance(query, str) or not query:
            raise ValueError(f"{question_id} needs a query file path")
        categories = entry.get("categories", {})
        if not isinstance(categories, dict) or not all(
            isinstance(value, str) and value for value in categories.values()
        ):
            raise ValueError(f"{question_id} categories must map dimensions to nonempty strings")
        hierarchy = entry.get("hierarchy")
        if hierarchy is not None and (
            not isinstance(hierarchy, dict) or hierarchy.get("kind") not in ("class", "property")
            or not is_iri(hierarchy.get("root"))
        ):
            raise ValueError(f"{question_id} hierarchy needs a class or property kind and an absolute root IRI")
        template_ids.add(question_id)
        question = {"id": question_id, "query": str((base / query).resolve()),
                    "categories": categories, "hierarchy": hierarchy}
        if "structural_sample" in entry:
            spec = entry["structural_sample"]
            if not isinstance(spec, dict) or "instances" in entry or hierarchy is not None:
                raise ValueError(f"{question_id} structural sampling cannot be combined with instances or hierarchy")
            variables = spec.get("variables", [spec.get("variable")])
            types = spec.get("types")
            size, seed = spec.get("size", 200), spec.get("seed", 42)
            if (not isinstance(variables, list) or len(variables) not in (1, 2)
                    or not all(isinstance(name, str) and re.fullmatch(r"[A-Za-z_]\w*", name)
                               for name in variables)
                    or len(set(variables)) != len(variables)
                    or not isinstance(types, list) or not types or not all(map(is_iri, types))
                    or type(size) is not int or size < 1 or type(seed) is not int):
                raise ValueError(f"{question_id} structural sampling requires one or two variables, RDF types, positive size, and integer seed")
            question["structural_sample"] = {"variables": variables, "types": types, "size": size, "seed": seed}
        if "instances" not in entry:
            questions.append(question)
            continue
        instances = entry["instances"]
        if not isinstance(instances, list) or not instances:
            raise ValueError(f"{question_id} instances must be a nonempty list")
        for instance in instances:
            if not isinstance(instance, dict):
                raise ValueError(f"{question_id} instance must be an object")
            label, bindings = instance.get("id"), instance.get("bindings")
            if not isinstance(label, str) or not label:
                raise ValueError(f"{question_id} instance needs a nonempty id")
            if not isinstance(bindings, dict) or not bindings or not all(
                name and is_iri(f"urn:healtheqkg:replace:{name}") and is_iri(iri)
                for name, iri in bindings.items()
            ):
                raise ValueError(f"{question_id}/{label} needs placeholder names and absolute reference IRIs")
            instance_id = f"{question_id}/{label}"
            if instance_id in instance_ids:
                raise ValueError(f"Duplicate question instance {instance_id}")
            instance_ids.add(instance_id)
            questions.append({**question, "id": instance_id, "bindings": bindings,
                              "categories": {**categories, "question": question_id}})
    if template_ids & instance_ids:
        raise ValueError("A question ID conflicts with an expanded instance ID")
    return questions


def render_summary(results):
    """Build the terminal tables from the same results saved in the reports."""
    lines = []
    if results["structural_comparisons"]:
        lines.extend([
            "Structural comparisons",
            "",
            "| Question | Outcome | Reference | Synthetic | JS distance |",
            "| --- | --- | ---: | ---: | ---: |",
        ])
        for row in results["structural_comparisons"]:
            if row["status"] != "compared":
                lines.append(f"| {row['id']} | {row['status']} | — | — | — |")
                continue
            is_ask = row["query_type"] == "ASK"
            rates = []
            for side in ("reference", "synthetic"):
                sample = row[side]
                positives = sample["histogram"]["true"] if is_ask else sample["entities_with_answers"]
                size = sample["sample_size"]
                rates.append(f"{positives}/{size} ({positives / size:.1%})")
            outcome = "True" if is_ask else "Nonempty"
            lines.append(
                f"| {row['id']} | {outcome} | {rates[0]} | {rates[1]} | {row['jensen_shannon_distance']:.3f} |"
            )

    if results["questions"]:
        if lines:
            lines.append("")
        lines.extend([
            "D6 aggregate scores",
            "",
            "| Comparison | Scored | PQ1 Correctness | PQ2 Completeness | PQ3 Macro F1 | PQ4 Micro F1 | PQ5 Exact |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
        ])
        for mode, metrics in results["aggregates"].items():
            micro = (metrics["PQ4"] or {}).get("f1")
            values = [metrics["PQ1"], metrics["PQ2"], metrics["PQ3"], micro, metrics["PQ5"]]
            formatted = " | ".join(f"{value:.3f}" if value is not None else "—" for value in values)
            lines.append(f"| {mode} | {metrics['scored_questions']} | {formatted} |")
        pq6 = results["PQ6"]
        if pq6["status"] == "scored":
            lines.extend(["", f"PQ6 hierarchy-aware macro F1: {pq6['macro_f1']:.3f} "
                          f"({pq6['scored_questions']} questions)"])
    return "\n".join(lines)


def render_report(results):
    lines = [
        "D6 pragmatic quality evaluation",
        "",
        "Literal comparison matches IRI spellings. Unverified identifiers may refer to different",
        "individuals or use different names for the same individual. Blank nodes are graph-local.",
        "Aligned comparison applies only the supplied synthetic-to-reference mapping to returned IRIs.",
        "",
        "Settings",
    ]
    for key, value in results["settings"].items():
        lines.append(f"  {key} = {json.dumps(value)}")
    lines.extend(["", "Aggregate scores"])
    for mode, metrics in results["aggregates"].items():
        lines.append(f"  {mode}")
        for key, value in metrics.items():
            lines.append(f"    {key} = {json.dumps(value)}")
    lines.append(f"  PQ6 = {json.dumps(results['PQ6'])}")
    lines.extend(["", "Questions"])
    for question in results["questions"]:
        lines.append(f"  {question['id']} [{question['query_type'] or 'unknown'}] {question['status']}")
        if question["categories"]:
            lines.append(f"    categories = {json.dumps(question['categories'])}")
        if question.get("bindings"):
            lines.append(f"    reference bindings = {json.dumps(question['bindings'])}")
            lines.append(f"    synthetic bindings = {json.dumps(question['synthetic_bindings'])}")
        for side, error in question["errors"].items():
            if error:
                lines.append(f"    {side} error = {error}")
        for mode, comparison in question["comparisons"].items():
            lines.append(f"    {mode}")
            for key, value in comparison.items():
                lines.append(f"      {key} = {json.dumps(value)}")
        lines.append(f"    PQ6 = {json.dumps(question['PQ6'])}")
    if results["structural_comparisons"]:
        lines.extend(["", "Structural comparisons (independent samples)"])
        for comparison in results["structural_comparisons"]:
            lines.append(f"  {comparison['id']} [{comparison['status']}]")
            if comparison["status"] != "compared":
                lines.append(f"    error = {comparison['error']}")
                continue
            for side in ("reference", "synthetic"):
                summary = {
                    key: value for key, value in comparison[side].items()
                    if key not in {"counts_by_entity", "outcomes_by_pair"}
                }
                lines.append(f"    {side} = {json.dumps(summary)}")
            lines.append(f"    Jensen–Shannon distance = {comparison['jensen_shannon_distance']:.6f}")
    return "\n".join(lines) + "\n"


def parse_args(argv):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--synthetic", type=Path, required=True)
    parser.add_argument("--reference-format", help="RDFLib format, inferred by default")
    parser.add_argument("--synthetic-format", help="RDFLib format, inferred by default")
    parser.add_argument("--questions", type=Path, required=True, help="Query directory or JSON manifest")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--progress", action=argparse.BooleanOptionalAction, default=True,
                        help="Show graph loading and per-query timings on stderr (default)")
    parser.add_argument("--identity-map", type=Path, help="JSON mapping synthetic answer IRIs to reference IRIs")
    parser.add_argument("--comparison", choices=("literal", "aligned", "both"))
    parser.add_argument("--ontology", type=Path, help="RDF hierarchy for PQ6")
    parser.add_argument("--ontology-format")
    parser.add_argument("--ontology-alignment", type=Path, help="JSON mapping into the common ontology hierarchy")
    parser.add_argument("--lambda-ancestor", type=float)
    parser.add_argument("--lambda-descendant", type=float)
    args = parser.parse_args(argv)
    args.comparison = args.comparison or ("both" if args.identity_map else "literal")
    if args.comparison != "literal" and args.identity_map is None:
        parser.error("--comparison aligned or both requires --identity-map")
    if (args.ontology is None) != (args.ontology_alignment is None):
        parser.error("PQ6 requires both --ontology and --ontology-alignment")
    ancestor, descendant = args.lambda_ancestor, args.lambda_descendant
    if args.ontology is not None:
        if (ancestor is None or descendant is None or not isfinite(descendant)
                or not 0 < ancestor < descendant):
            parser.error("PQ6 requires finite penalties with 0 < lambda-ancestor < lambda-descendant")
    elif ancestor is not None or descendant is not None or args.ontology_format is not None:
        parser.error("Ontology format and penalties require --ontology")
    return parser, args


def load_graph(path, rdf_format):
    # An open file keeps graph inputs local and sets a stable base for relative RDF IRIs.
    with path.open("rb") as stream:
        return Graph().parse(stream, publicID=path.resolve().as_uri(), format=rdf_format)


def run(args):
    """Load the inputs, score the questions, and write both report formats."""
    if args.progress:
        print("Starting evaluation and reading inputs", file=sys.stderr, flush=True)
    modes = {}
    identity_map = read_alignment(args.identity_map) if args.identity_map else {}
    synthetic_aliases = defaultdict(set)
    for synthetic_iri, reference_iri in identity_map.items():
        synthetic_aliases[reference_iri].add(synthetic_iri)
    if args.comparison in ("literal", "both"):
        modes["literal"] = {}
    if args.comparison in ("aligned", "both"):
        modes["aligned"] = identity_map
    questions = load_questions(args.questions.resolve())
    output_dir = args.output_dir.resolve()
    input_paths = {
        path.resolve() for path in (
            args.reference, args.synthetic, args.questions, args.identity_map,
            args.ontology, args.ontology_alignment,
            *(Path(question["query"]) for question in questions),
        ) if path is not None
    }
    for filename in ("results.json", "report.txt"):
        path = output_dir / filename
        if path in input_paths:
            raise ValueError(f"Output would replace an evaluation input: {path}")
        if path.is_dir():
            raise IsADirectoryError(f"Output path is a directory: {path}")

    graph_settings = {}
    for name in ("reference", "synthetic", "ontology"):
        path = getattr(args, name)
        if path is not None:
            rdf_format = getattr(args, f"{name}_format") or guess_format(str(path)) or "turtle"
            graph_settings[name] = {"path": str(path.resolve()), "format": rdf_format}

    # RDFLib otherwise normalizes lexical forms such as "01"^^xsd:integer during parsing.
    previous_normalization = rdflib.NORMALIZE_LITERALS
    rdflib.NORMALIZE_LITERALS = False
    try:
        graphs = {}
        for name, spec in graph_settings.items():
            if args.progress:
                print(f"Loading {name} graph", file=sys.stderr, flush=True)
            graphs[name] = load_graph(Path(spec["path"]), spec["format"])
        hierarchy = None
        if args.ontology:
            hierarchy = HierarchyScorer(graphs["ontology"], read_alignment(args.ontology_alignment),
                                        args.lambda_ancestor, args.lambda_descendant)
        rows = []
        structural = []
        graph_pair = {side: graphs[side] for side in ("reference", "synthetic")}
        for question in questions:
            if "structural_sample" in question:
                structural.append(compare_structure(question, graph_pair, show_progress=args.progress))
            else:
                rows.append(evaluate_question(
                    question, graphs["reference"], graphs["synthetic"], modes, hierarchy,
                    show_progress=args.progress, synthetic_aliases=synthetic_aliases,
                ))
    finally:
        # Restore RDFLib's process-wide setting for callers that import the module.
        rdflib.NORMALIZE_LITERALS = previous_normalization
    # PQ6 averages only questions for which hierarchy scoring was possible.
    hierarchy_scores = [row["PQ6"]["scores"]["f1"] for row in rows if row["PQ6"]["status"] == "scored"]
    pq6_status = ("scored" if hierarchy_scores else
                  "unavailable" if any(row["PQ6"]["status"] == "unavailable" for row in rows)
                  else "not_applicable")
    results = {
        "settings": {
            **graph_settings,
            "questions": str(args.questions.resolve()),
            "comparison": args.comparison,
            "identity_map": str(args.identity_map.resolve()) if args.identity_map else None,
            "ontology_alignment": str(args.ontology_alignment.resolve()) if args.ontology_alignment else None,
            "lambda_ancestor": args.lambda_ancestor,
            "lambda_descendant": args.lambda_descendant,
            "entailment": "none (query the supplied triples)",
            "query_engine": f"RDFLib {rdflib.__version__}",
            "query_base": "query file URI",
            "literal_lexical_normalization": False,
        },
        "aggregates": {mode: aggregate(rows, mode) for mode in modes},
        "PQ6": {"status": pq6_status, "scored_questions": len(hierarchy_scores),
                "macro_f1": mean(hierarchy_scores) if hierarchy_scores else None},
        "questions": rows,
        "structural_comparisons": structural,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    outputs = {
        "results.json": json.dumps(results, indent=2) + "\n",
        "report.txt": render_report(results),
    }
    # Stage both reports before replacing either existing file. Each rename replaces
    # the directory entry without following a symlink or exposing a half-written report.
    with TemporaryDirectory(dir=output_dir) as directory:
        staging = Path(directory)
        for filename, content in outputs.items():
            (staging / filename).write_text(content, encoding="utf-8")
        for filename in outputs:
            (staging / filename).replace(output_dir / filename)
    print(render_summary(results), flush=True)
    if args.progress:
        print(f"Reports written to {args.output_dir}", file=sys.stderr, flush=True)


def main(argv=None):
    parser, args = parse_args(argv)
    try:
        run(args)
    except Exception as error:
        parser.exit(1, f"Evaluation setup or output failed: {type(error).__name__}: {error}\n")


if __name__ == "__main__":
    main()
