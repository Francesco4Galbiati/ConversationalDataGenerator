"""Convert HealthEQKG CDG JSONL records into RDF Turtle."""

import argparse
import json
import re
from pathlib import Path
from urllib.parse import quote

import yaml
from rdflib import Graph, Literal, Namespace, RDF, RDFS, URIRef, XSD


DEFAULT_CONTRACT = Path(__file__).resolve().parents[1] / "resources/contracts/HealthEQKG_contract.yaml"
HEQ = Namespace("http://healtheqkg.example.org/ontology#")
SCHEMA = Namespace("http://schema.org/")
DBPEDIA = Namespace("https://dbpedia.org/")
GEN = Namespace("http://example.org/")

PREDICATES = {
    "affiliatedHospital": SCHEMA.affiliatedHospital,
    "hasFacility": HEQ.worksAt,
    "placementFor": HEQ.hasParticipant,
    "graduateFrom": HEQ.attendedMedSchool,
    "hasADIScore": HEQ.hasADISummary,
    "scoredIn": HEQ.referenceYear,
    "hasTimeReference": HEQ.hasTimeReference,
    "graduationYear": HEQ.graduationYear,
    "zipCodeValue": HEQ.zipCodeValue,
    "credential": HEQ.credential,
    "nationalScore": HEQ.nationalScore,
    "name": SCHEMA.name,
    "address": SCHEMA.address,
    "numberOfBeds": SCHEMA.numberOfBeds,
    "numberOfEmployees": SCHEMA.numberOfEmployees,
    "familyName": SCHEMA.familyName,
    "givenName": SCHEMA.givenName,
    "gender": SCHEMA.gender,
    "usNPI": SCHEMA.usNPI,
    "medicalSpecialty": SCHEMA.medicalSpecialty,
    "abstract": DBPEDIA.abstract,
    "facultySize": DBPEDIA.facultySize,
    "numberOfStudents": DBPEDIA.numberOfStudents,
}


def slot_name(name):
    return re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", name).lower()


def entity(slot, value):
    identifier = quote(str(value).strip(), safe="")
    return GEN[f"{slot.removesuffix('_id')}_{identifier}"]


def year_literal(value):
    if not re.fullmatch(r"[0-9]{4}", str(value).strip()):
        raise ValueError(f"Expected a four-digit year, got {value!r}")
    return Literal(str(value).strip(), datatype=XSD.gYear)


def postal_address(graph, facility):
    address = URIRef(f"{facility}/address")
    graph.add((facility, SCHEMA.address, address))
    graph.add((address, RDF.type, SCHEMA.PostalAddress))
    return address


def add_record(graph, record, intents, facility_zip_areas):
    intent = record.get("intent")
    if not isinstance(intent, str) or intent not in intents:
        raise ValueError(f"Unknown HealthEQKG intent {intent!r}")
    data = {
        slot_name(slot): value for slot, value in record.items()
        if value is not None and (not isinstance(value, str) or value.strip() not in {"", "None", "null"})
    }
    definition = intents[intent]
    slot_types = {
        slot_name(slot): kind
        for phase in ("preconditions", "postconditions")
        for slot, kind in definition[phase]["slots"].items()
    }
    for subject_slot, predicate, object_slot in definition["postconditions"]["triples"]:
        subject_slot = slot_name(subject_slot)
        if subject_slot not in data:
            continue
        subject = entity(subject_slot, data[subject_slot])
        if predicate == "type":
            graph.add((subject, RDF.type, HEQ[object_slot]))
            continue

        object_slot = slot_name(object_slot)
        if object_slot not in data:
            continue
        value = data[object_slot]
        property_iri = PREDICATES.get(predicate, GEN[predicate])
        if object_slot.endswith("_id"):
            obj = entity(object_slot, value)
        elif predicate == "address":
            address = postal_address(graph, subject)
            graph.add((address, SCHEMA.streetAddress, Literal(str(value))))
            continue
        elif predicate == "hasTimeReference":
            year = year_literal(value)
            obj = GEN[f"year_{year}"]
            graph.add((obj, RDF.type, HEQ.Year))
            graph.add((obj, RDFS.label, year))
        elif predicate in {"graduationYear", "scoredIn"}:
            obj = year_literal(value)
        elif predicate == "nationalScore" and str(value).strip().lower() in {"low", "mid", "high"}:
            # The ontology's nationalScore expects an integer. Keep generated categories separately.
            property_iri = GEN.nationalScore
            obj = Literal(str(value).strip().lower())
        elif slot_types.get(object_slot) == "int" or predicate == "nationalScore":
            if not re.fullmatch(r"[+-]?[0-9]+", str(value).strip()):
                raise ValueError(f"{object_slot} must be an integer, got {value!r}")
            obj = Literal(int(value))
        else:
            obj = Literal(str(value))
        graph.add((subject, property_iri, obj))

    if intent == "FindPhysicianPlacement" and {"facility_id", "zip_code_area_id"} <= data.keys():
        facility = entity("facility_id", data["facility_id"])
        zip_area = entity("zip_code_area_id", data["zip_code_area_id"])
        facility_zip_areas.setdefault(facility, set()).add(zip_area)


def parse_jsonl(source, contract_path=DEFAULT_CONTRACT):
    with contract_path.open(encoding="utf-8") as stream:
        intents = yaml.safe_load(stream)["intents"]

    graph = Graph()
    for prefix, namespace in (("heq", HEQ), ("schema", SCHEMA), ("dbpedia", DBPEDIA), ("gen", GEN)):
        graph.bind(prefix, namespace)

    facility_zip_areas = {}
    with source.open(encoding="utf-8") as stream:
        for number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
                if not isinstance(record, dict):
                    raise ValueError("Expected a JSON object")
                add_record(graph, record, intents, facility_zip_areas)
            except ValueError as error:
                raise ValueError(f"{source}:{number}: {error}") from error

    # Resolve ZIP codes after reading all records, including ZIP areas defined later.
    for facility, areas in facility_zip_areas.items():
        codes = {code for area in areas for code in graph.objects(area, HEQ.zipCodeValue)}
        if len(codes) == 1:
            graph.add((postal_address(graph, facility), SCHEMA.postalCode, codes.pop()))
    return graph


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="CDG JSONL file with an intent field per record")
    parser.add_argument("output", type=Path, help="Destination Turtle file")
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT, help="HealthEQKG YAML contract")
    args = parser.parse_args()
    if args.output.resolve() in {args.input.resolve(), args.contract.resolve()}:
        parser.error("The output must differ from the input and contract")
    try:
        graph = parse_jsonl(args.input, args.contract)
        graph.serialize(destination=args.output, format="turtle")
    except (OSError, ValueError, yaml.YAMLError) as error:
        parser.exit(1, f"{error}\n")
    print(f"Wrote {len(graph)} triples to {args.output}")


if __name__ == "__main__":
    main()
