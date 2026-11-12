# OntoPFAS, gpt-oss:120b, one-to-one, 10,000 triples: model_choice

Old method: the querent model chooses each intent.
Contract: resources/contracts/OntoPFAS_contract.yaml (full). Source run: resources/output/run_20261111_193235.

- dialogue.jsonl: one line per turn: turn, intent, question (querent), answer (witness), triples so far
- triples.json: the witness answers as written by the generator (input of the RDF parser)
- output.ttl: the RDF graph (output_parsing/parser_ontopfas.py)
- output.txt: run summary (error counters, times, models, intent selection)
- evaluation/: structural D6 comparison with the reference (evaluate_pragmatic_quality.py)
