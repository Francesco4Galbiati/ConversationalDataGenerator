"""Convert an OntoPFAS CDG run (triples.json, one "Intent: {json}" per line) into RDF Turtle.

Each answer is mapped through the postcondition triples of its intent in the contract.
Slots ending in _id become IRIs under SYN (one IRI per class prefix + id), the other
slots become typed literals. A slot whose triple predicate is `type` and whose value is a
CURIE (pfas_family) becomes an rdf:type to that class.

    python output_parsing/parser_ontopfas.py resources/output/run_X/triples.json \
        resources/output/run_X/output.ttl --contract resources/contracts/OntoPFAS_contract.yaml
"""
import argparse
import json
import re
from pathlib import Path
from urllib.parse import quote

import yaml
from rdflib import Graph, Literal, Namespace, RDF, URIRef, XSD

SYN = Namespace("https://w3id.org/OntoPFAS/synthetic/")
LINE = re.compile(r"^\s*(\w+)\s*:\s*(\{.*\})\s*$")


def entity(slot, value):
    """One IRI per (kind of entity, id): pfas_id=PFS001 -> syn:pfas/PFS001."""
    kind = slot.removesuffix("_id")
    # several slots name the same kind of entity (surrounding_environment_id is an environment)
    kind = {"surrounding_environment": "environment"}.get(kind, kind)
    return SYN[f"{kind}/{quote(str(value).strip(), safe='')}"]


def literal(value, kind):
    if isinstance(value, bool):
        return Literal("yes" if value else "no")
    text = str(value).strip()
    if kind == "int" or (kind in {"mobility_degree", "year"} and re.fullmatch(r"-?\d+", text)):
        if re.fullmatch(r"-?\d+", text):
            return Literal(text) if kind == "year" else Literal(int(text))
    if kind in {"float", "latitude", "longitude", "concentration"}:
        try:
            return Literal(str(float(text)), datatype=XSD.decimal)
        except ValueError:
            pass
    if kind == "date" and re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        return Literal(text, datatype=XSD.date)
    return Literal(text, datatype=XSD.string)


def expand(curie, prefixes):
    if ":" in curie and not curie.startswith("http"):
        prefix, local = curie.split(":", 1)
        if prefix in prefixes:
            return URIRef(prefixes[prefix] + local)
    return None


def parse(source, contract_path):
    contract = yaml.safe_load(contract_path.read_text(encoding="utf-8"))
    prefixes, intents = contract["prefixes"], contract["intents"]
    graph = Graph()
    for prefix, namespace in prefixes.items():
        graph.bind(prefix, Namespace(namespace))
    graph.bind("syn", SYN)
    skipped = []
    for number, line in enumerate(source.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        match = LINE.match(line)
        if not match or match.group(1) not in intents:
            skipped.append((number, "unreadable line or unknown intent"))
            continue
        intent = intents[match.group(1)]
        try:
            data = json.loads(match.group(2))
        except json.JSONDecodeError as error:
            skipped.append((number, f"bad JSON ({error})"))
            continue
        data = {k: v for k, v in data.items() if v is not None and str(v).strip() not in {"", "None", "null"}}
        kinds = {slot: kind for phase in ("preconditions", "postconditions")
                 for slot, kind in intent[phase]["slots"].items()}
        for subject_slot, predicate, obj in intent["postconditions"]["triples"]:
            if subject_slot not in data:
                continue
            subject = entity(subject_slot, data[subject_slot])
            if predicate == "type":
                cls = expand(obj, prefixes) if obj not in kinds else expand(str(data.get(obj, "")), prefixes)
                if cls is not None:
                    graph.add((subject, RDF.type, cls))
                continue
            if obj not in data:
                continue
            prop = expand(predicate, prefixes)
            value = data[obj]
            target = entity(obj, value) if obj.endswith("_id") else literal(value, kinds.get(obj, "str"))
            graph.add((subject, prop, target))
    return graph, skipped


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("input", type=Path, help="triples.json of a one-to-one run (or one triples_<i>.json)")
    parser.add_argument("output", type=Path, help="Turtle file to write")
    parser.add_argument("--contract", type=Path,
                        default=Path(__file__).resolve().parents[1] / "resources/contracts/OntoPFAS_contract.yaml")
    args = parser.parse_args()
    graph, skipped = parse(args.input, args.contract)
    graph.serialize(destination=args.output, format="turtle")
    print(f"Wrote {len(graph)} triples to {args.output}")
    for number, reason in skipped:
        print(f"  skipped line {number}: {reason}")


if __name__ == "__main__":
    main()
