from rdflib.plugins.sparql.processor import prepareQuery
from rdflib.term import Variable
from intents_creation.datatypes import TriplePattern, ParsedCQ, GraphAttribute, GraphNode, GraphPattern, OntologySchema, GraphRelation, IntentSpec
from typing import List, Optional, Set, Dict
from rdflib import RDF, OWL, RDFS, Graph
from dataclasses import asdict
import yaml

def _term_to_str(term):
    if isinstance(term, Variable):
        return f"?{term}"
    return str(term)


def _collect_bgp_triples(node, out):
    if node is None:
        return

    name = getattr(node, "name", None)
    if name == "BGP":
        for s, p, o in node["triples"]:
            out.append(TriplePattern(_term_to_str(s), _term_to_str(p), _term_to_str(o)))

    if hasattr(node, "items"):
        for _, value in node.items():
            if isinstance(value, list):
                for item in value:
                    _collect_bgp_triples(item, out)
            else:
                _collect_bgp_triples(value, out)


def parse_competency_question(name: str, query_text: str) -> ParsedCQ:
    query = prepareQuery(query_text)
    triples: List[TriplePattern] = []
    _collect_bgp_triples(query.algebra, triples)
    select_vars = [f"?{var}" for var in query.algebra.get("PV", [])]
    return ParsedCQ(name=name, select_vars=select_vars, triples=triples)


def _is_var(value: str) -> bool:
    return value.startswith("?")


def _local_name(iri: str) -> str:
    if "#" in iri:
        return iri.rsplit("#", 1)[1]
    return iri.rstrip("/").rsplit("/", 1)[-1]


def _ensure_node(nodes: Dict[str, GraphNode], key: str, constant: Optional[str] = None) -> GraphNode:
    if key not in nodes:
        nodes[key] = GraphNode(var=key, constant=constant)
    elif constant is not None and nodes[key].constant is None:
        nodes[key].constant = constant
    return nodes[key]


def _guess_slot_name(subject_key: str, predicate_iri: str) -> str:
    predicate_name = _local_name(predicate_iri)
    subject_name = subject_key[1:].lower() if subject_key.startswith("?") else subject_key.lower()
    return f"{subject_name}_{predicate_name}"

def _infer_constant_class_from_uri(constant_iri: str, ontology_schema: OntologySchema) -> Optional[str]:
    local = _local_name(constant_iri)

    for class_iri in ontology_schema.classes:
        class_name = _local_name(class_iri)
        if local == class_name or local.startswith(class_name):
            return class_name

    return None


def parsed_cq_to_graph_pattern(parsed_cq: ParsedCQ, ontology_schema: OntologySchema) -> GraphPattern:
    pattern = GraphPattern(name=parsed_cq.name, selected_vars=parsed_cq.select_vars[:])

    for triple in parsed_cq.triples:
        if triple.predicate == str(RDF.type):
            node = _ensure_node(pattern.nodes, triple.subject)
            node.class_name = _local_name(triple.obj)
            node.status = "output" if triple.subject in parsed_cq.select_vars else "context"
            continue

        subject_node = _ensure_node(pattern.nodes, triple.subject)

        if _is_var(triple.obj):
            object_node = _ensure_node(pattern.nodes, triple.obj)

            if triple.predicate in ontology_schema.datatype_properties:
                slot = _guess_slot_name(triple.subject, triple.predicate)
                datatype = ontology_schema.property_ranges.get(triple.predicate, "string")
                pattern.attributes.append(GraphAttribute(triple.subject, triple.predicate, slot, datatype))
                if triple.subject in parsed_cq.select_vars and subject_node.status == "unknown":
                    subject_node.status = "output"
            else:
                pattern.relations.append(GraphRelation(triple.subject, triple.predicate, triple.obj))
                if subject_node.status == "unknown":
                    subject_node.status = "output" if triple.subject in parsed_cq.select_vars else "context"
                if object_node.status == "unknown":
                    object_node.status = "output" if triple.obj in parsed_cq.select_vars else "context"
        else:
            constant_key = f"const:{triple.obj}"
            object_node = _ensure_node(pattern.nodes, constant_key, constant=triple.obj)
            if object_node.class_name is None:
                inferred_range = ontology_schema.property_ranges.get(triple.predicate)
                if inferred_range is not None:
                    object_node.class_name = _local_name(inferred_range)
                else:
                    inferred_class = _infer_constant_class_from_uri(triple.obj, ontology_schema)
                    if inferred_class is not None:
                        object_node.class_name = inferred_class
            object_node.status = "existing"

            pattern.relations.append(GraphRelation(triple.subject, triple.predicate, constant_key))
            if subject_node.status == "unknown":
                subject_node.status = "output" if triple.subject in parsed_cq.select_vars else "context"

    return pattern

def print_parsed_cq(parsed):
    print(f"\nParsedCQ: {parsed.name}")
    print("  Select vars:")
    for var in parsed.select_vars:
        print(f"    - {var}")

    print("  Triples:")
    for t in parsed.triples:
        print(f"    - ({t.subject}, {t.predicate}, {t.obj})")


def print_graph_pattern(pattern):
    print(f"\nGraphPattern: {pattern.name}")

    print("  Selected vars:")
    for var in pattern.selected_vars:
        print(f"    - {var}")

    print("  Nodes:")
    for key, node in pattern.nodes.items():
        print(
            f"    - {key}: class={node.class_name}, "
            f"status={node.status}, constant={node.constant}"
        )

    print("  Relations:")
    for rel in pattern.relations:
        print(f"    - ({rel.subject}) -[{rel.predicate}]-> ({rel.obj})")

    print("  Attributes:")
    for attr in pattern.attributes:
        print(
            f"    - ({attr.subject}) -[{attr.predicate}]-> "
            f"{attr.slot}:{attr.datatype}"
        )

def _add_mapping(mapping: Dict[str, Set[str]], key: str, value: str) -> None:
    if key not in mapping:
        mapping[key] = set()
    mapping[key].add(value)


def load_ontology_schema(path: str, fmt: str = "xml") -> OntologySchema:
    graph = Graph()
    graph.parse(path, format=fmt)

    schema = OntologySchema()

    object_property_types = {
        OWL.ObjectProperty,
        OWL.TransitiveProperty,
        OWL.SymmetricProperty,
        OWL.FunctionalProperty,
        OWL.InverseFunctionalProperty,
    }

    for class_iri in graph.subjects(RDF.type, OWL.Class):
        schema.classes.add(str(class_iri))

    for prop_type in object_property_types:
        for prop_iri in graph.subjects(RDF.type, prop_type):
            schema.object_properties.add(str(prop_iri))

    for prop_iri in graph.subjects(RDF.type, OWL.DatatypeProperty):
        schema.datatype_properties.add(str(prop_iri))

    for prop_iri, domain_iri in graph.subject_objects(RDFS.domain):
        schema.property_domains[str(prop_iri)] = str(domain_iri)

    for prop_iri, range_iri in graph.subject_objects(RDFS.range):
        schema.property_ranges[str(prop_iri)] = str(range_iri)

    for child_iri, parent_iri in graph.subject_objects(RDFS.subClassOf):
        _add_mapping(schema.subclass_of, str(child_iri), str(parent_iri))

    for child_iri, parent_iri in graph.subject_objects(RDFS.subPropertyOf):
        _add_mapping(schema.subproperty_of, str(child_iri), str(parent_iri))

    for prop_iri, inverse_iri in graph.subject_objects(OWL.inverseOf):
        schema.inverse_of[str(prop_iri)] = str(inverse_iri)

    return schema

def _node_alias(node_key: str, node: GraphNode) -> str:
    if node.constant is not None:
        base = node.class_name or "entity"
        return base[:1].lower() + base[1:]

    if node.class_name is not None:
        local = _local_name(node.class_name)
        return local[:1].lower() + local[1:]

    if node_key.startswith("?"):
        return node_key[1:].lower()

    return node_key.lower()


def _id_slot(alias: str) -> str:
    return f"{alias}_id"


def _class_label(node: GraphNode) -> str:
    if node.class_name is None:
        return "Entity"
    return _local_name(node.class_name)


def graph_pattern_to_intent_spec(
    pattern: GraphPattern,
    description: str = "",
    cardinality: int = 1,
) -> IntentSpec:
    pre_classes: Dict[str, str] = {}
    pre_slots: Dict[str, str] = {}
    post_classes: Dict[str, str] = {}
    post_slots: Dict[str, str] = {}
    triples: List[List[str]] = []
    aliases: Dict[str, str] = {}

    for node_key, node in pattern.nodes.items():
        alias = _node_alias(node_key, node)
        aliases[node_key] = alias
        class_label = _class_label(node)

        if node.status == "existing":
            pre_classes[alias] = class_label
            pre_slots[_id_slot(alias)] = "id"
        elif node.status == "context":
            pre_classes[alias] = class_label
            pre_slots[_id_slot(alias)] = "id"
        elif node.status == "output":
            post_classes[alias] = class_label
            post_slots[_id_slot(alias)] = "id"

    for node_key, node in pattern.nodes.items():
        if node.status == "output":
            triples.append([
                _id_slot(aliases[node_key]),
                "type",
                _class_label(node),
            ])

    for relation in pattern.relations:
        subject_alias = aliases[relation.subject]
        object_alias = aliases[relation.obj]
        triples.append([
            _id_slot(subject_alias),
            _local_name(relation.predicate),
            _id_slot(object_alias),
        ])


    for attribute in pattern.attributes:
        subject_alias = aliases[attribute.subject]
        post_slots[attribute.slot] = attribute.datatype
        triples.append([
            _id_slot(subject_alias),
            _local_name(attribute.predicate),
            attribute.slot,
        ])

    return IntentSpec(
        name=pattern.name,
        preconditions={
            "classes": pre_classes,
            "slots": pre_slots,
            "cardinality": cardinality,
            "description": description,
        },
        postconditions={
            "classes": post_classes,
            "slots": post_slots,
            "triples": triples,
        },
    )

class InlineList(list):
    pass

class _InlineTriplesDumper(yaml.SafeDumper):
    pass


def _represent_inline_list(dumper, data):
    return dumper.represent_sequence("tag:yaml.org,2002:seq", data, flow_style=True)


_InlineTriplesDumper.add_representer(InlineList, _represent_inline_list)


def intent_spec_to_yaml(intent: IntentSpec) -> str:
    payload = asdict(intent)
    triples = payload.get("postconditions", {}).get("triples", [])
    payload["postconditions"]["triples"] = [InlineList(triple) for triple in triples]
    named_payload = {
        payload["name"]: {
            "preconditions": payload["preconditions"],
            "postconditions": payload["postconditions"],
        }
    }
    return yaml.dump(named_payload, Dumper=_InlineTriplesDumper, sort_keys=False, allow_unicode=True)

