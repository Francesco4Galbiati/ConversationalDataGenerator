import csv
from rdflib import Graph, URIRef, Literal

g = Graph()

with open("resources/output/LEONARDO/dataset.csv", newline="", encoding="utf-8") as f:
    reader = csv.DictReader(f)
    for row in reader:
        s = URIRef(row["subj"])
        p = URIRef(row["pred"])

        obj = row["obj"]

        # Decide if object is URI or literal
        if obj.startswith("http://") or obj.startswith("https://"):
            o = URIRef(obj)
        else:
            o = Literal(obj)

        g.add((s, p, o))

# Serialize to RDF (Turtle example)
g.serialize("dataset.ttl", format="turtle")

# Other common formats:
# format="xml"    -> RDF/XML
# format="nt"     -> N-Triples
# format="json-ld"