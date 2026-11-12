"""Merge the OntoPFAS reference files into one graph written in the contract's vocabulary.

The published reference TTLs use a few IRIs that differ from the OntoPFAS ontology (and so
from what the generator produces): http://schema/org/ instead of https://schema.org/,
ontopfas:source_text instead of ontopfas:sourceText, dc: instead of dcterms:, an OLS URL for
RO_0001025, geo:location instead of geo:SpatialThing, and substance IRIs that are bare CAS
numbers (they resolve to local file paths). Without this step, every query would find nothing
on one of the two sides. Entity IRIs are also prefixed with their file name, because each file
numbers its entities from _0 and they would otherwise collide when merged.

    python output_parsing/normalize_reference_ontopfas.py resources/reference/ontopfas \
        resources/reference/ontopfas_reference.ttl
"""
import argparse
import re
from pathlib import Path

from rdflib import Graph, Literal, Namespace, OWL, RDF, URIRef, XSD

ONTOPFAS = Namespace("https://w3id.org/OntoPFAS#")
SCHEMA = Namespace("https://schema.org/")
REF = Namespace("https://w3id.org/OntoPFAS/reference/")
GEO = Namespace("http://www.w3.org/2003/01/geo/wgs84_pos#")

TERMS = {
    "http://schema/org/Country": SCHEMA.Place,            # the contract types countries as schema:Place
    "http://purl.org/dc/elements/1.1/source": URIRef("http://purl.org/dc/terms/source"),
    "https://www.ebi.ac.uk/ols4/ontologies/ro/RO_0001025": URIRef("http://purl.obolibrary.org/obo/RO_0001025"),
    "https://www.w3.org/2003/01/geo/location": GEO.SpatialThing,
    "https://www.w3.org/ns/dcat#Dataset": URIRef("http://www.w3.org/ns/dcat#Dataset"),
    str(ONTOPFAS.source_text): ONTOPFAS.sourceText,
    str(ONTOPFAS.source_type): ONTOPFAS.sourceType,
    str(ONTOPFAS.source_url): ONTOPFAS.sourceUrl,
}
ENTITY = re.compile(r"^(.*?)([A-Za-z]+)_(\d+)$")      # .../City_3 -> city 3
CAS = re.compile(r"(\d{2,7}-\d{2}-\d)$")


def term(node, file_stem):
    if not isinstance(node, URIRef):
        return node
    text = str(node)
    if text.startswith("file:") and CAS.search(text):        # substance given by its CAS number
        return REF[f"pfas/{CAS.search(text).group(1)}"]
    if text in TERMS:
        return TERMS[text]
    if text == "http://purl.obolibrary.org/obo/ENVO_01000408":    # the class itself, not an instance
        return node
    match = ENTITY.match(text)
    if match:                                                   # an instance: City_3, Observation_00 ...
        return REF[f"{file_stem}/{match.group(2).lower()}/{match.group(3)}"]
    if text.startswith("http://schema/org/"):
        return SCHEMA[text.removeprefix("http://schema/org/")]
    return node


def normalize(folder):
    out = Graph()
    out.bind("ontopfas", ONTOPFAS); out.bind("schema", SCHEMA); out.bind("ref", REF)
    for path in sorted(folder.glob("*.ttl")):
        g = Graph(); g.parse(path)
        declarations = set(g.subjects(RDF.type, OWL.DatatypeProperty)) | set(g.subjects(RDF.type, OWL.ObjectProperty))
        locations = set(g.subjects(RDF.type, URIRef("https://www.w3.org/2003/01/geo/location")))
        for s, p, o in g:
            if s in declarations:
                continue
            if str(p) == "http://schema/org/containedInPlace":
                # city -> country is isContainedInPlace; sampling location -> city is locationInPlace
                p2 = ONTOPFAS.locationInPlace if s in locations else ONTOPFAS.isContainedInPlace
            else:
                p2 = term(p, path.stem)
            out.add((term(s, path.stem), p2, term(o, path.stem)))
        for node in set(g.objects(None, ONTOPFAS.measuredPfas)):   # keep the CAS number as data
            ref = term(node, path.stem)
            out.add((ref, ONTOPFAS.casId, Literal(CAS.search(str(node)).group(1), datatype=XSD.string)))
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("folder", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    graph = normalize(args.folder)
    graph.serialize(destination=args.output, format="turtle")
    print(f"Wrote {len(graph)} triples to {args.output}")


if __name__ == "__main__":
    main()
