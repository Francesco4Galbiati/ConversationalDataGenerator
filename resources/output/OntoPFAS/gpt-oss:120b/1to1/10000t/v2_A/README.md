# OntoPFAS, gpt-oss:120b, one-to-one, 10,000 triples: v2_A

Contract v2, schedule, A: country names never repeat (--unique_slots country_name).
Contract: resources/contracts/OntoPFAS_contract_v2.yaml. Source run: resources/output/run_20261112_215036.

    python main.py --contract OntoPFAS_contract_v2.yaml --conversation 1 --intent_selection schedule --target 10000 --unique_slots country_name

- dialogue.jsonl: one line per turn: turn, intent, answer (witness). The question field is null: this run
  was launched directly in a terminal, so the querent's questions were printed but not saved.
- triples.json: the witness answers as written by the generator (input of the RDF parser)
- output.ttl: the RDF graph (output_parsing/parser_ontopfas.py --contract resources/contracts/OntoPFAS_contract_v2.yaml)
- output.txt: run summary (error counters, times, models, intent selection, options)
- evaluation/: structural D6 comparison with the reference (evaluate_pragmatic_quality.py)
