# Conversational Data Generation repository

Here you can find the Python project to execute the Conversational Data Generator (CDG).
This repository is structured as follows:
- ```/one_to_one```: contains the code to execute the one-to-one conversations
  - ```/dialogue_gpt.py```: contains the function that generates the dialogue turns with ```gpt-oss:12b0``` as querent
  - ```/dialogue_llama.py```: contains the function that generates the dialogue turns with ```llama3.3:70b``` as querent
  - ```/dialogue_no_intents.py```: the dialogue function used to test the generation without intents
  - ```/dialogue_to_triples.py```: the dialogue function used to test the generation with direct transformation of the output into RDF triples
  - ```/dialogue_subclasses.py```: the dialogue function used to test the subclass constraints in the intents
  - ```/dialogue_intersection.py```: the dialogue function used to test the intersection subclass in the intents
  - ```/dialogue_disjoint.py```: the dialogue function used to test the disjointness constraints in the intents
- ```/one_to_many```: contains the code to execute the one-to-many conversations
  - ```/dialogue_gpt.py```: contains the function that generates the dialogue turns with ```gpt-oss:12b0``` as querent
  - ```/dialogue_llama.py```: contains the function that generates the dialogue turns with ```llama3.3:70b``` as querent
- ```/many_to_one```: contains the code to execute the many-to-one conversations
  - ```/dialogue_gpt.py```: contains the function that generates the dialogue turns with ```gpt-oss:12b0``` as querent
  - ```/dialogue_llama.py```: contains the function that generates the dialogue turns with ```llama3.3:70b``` as querent
- ```/many_to_many```: contains the code to execute the many-to-many conversations
  - ```/dialogue_gpt.py```: contains the function that generates the dialogue turns with ```gpt-oss:12b0``` as querent
  - ```/dialogue_llama.py```: contains the function that generates the dialogue turns with ```llama3.3:70b``` as querent
- ```/resources```: contains the resources used to run the data generation:
  - ```/ontologies```: contains the ontologies either in RDF/XML or in RDF/Turtle
  - ```/contracts```: contains the conversational contracts derived from the ontologies
  - ```/output```: contains the output files (not present in the repository, it's created at run-time)
- ```/output_parsing```: contains the code used ot parse the JSONL output files and transform them into valid RDF/TTL
- ```/intent_creation```: contains the code used to transform SPARQL competency questions into intents
- ```conf.py```: contains the configuration variables to run the data generation (see below)
- ```functions.py```: contains the functions used in the code
- ```main.py```: contains the entry point of the code
- ```parameters.py```: contains the definition of configuration parameters.

## Running the generation
To run the CDG, it's sufficient to run the ```main.py``` file.

## Customizing the generation
Parameters used to run the code can be manually set through the command line when launching the ```main.py``` file. This is the list of the supported parameters:
|Variable                     |Type     |Effect                                                                             |Default                        |
|-----------------------------|---------|-----------------------------------------------------------------------------------|-------------------------------|
|```--contract```             | string  | The conversational contract used to run the CDG                                   |```"LUBM_contract.yaml"```     |
|```--querent_model```        | string  | The name of the model used to run the querent agent                               |```"gpt-oss:120b"```           |
|```--witness_model```        | string  | The name of the model used to run the witness agent                               |```"gpt-oss:120b"```           |
|```--conversation```         | integer | The type of conversation to run (1: 1-to-1, 2: M-to-1, 3: 1-to-M, 4: M-to-M)      |```1```                        |
|```--target```               | integer | The target number of RDF triples to generate                                      |```1000```                     |
|```--model_host```           | string  | The url of the ollama instance that runs the querent and witness agents           |```"http://localhost:11434"``` |
|```--witnesses_n```          | integer | The number of witness agents to run in ONE_TO_MANY and MANY_TO_MANY conversations |```3```                        |
|```--api_key```              | string  | The api key used to access the model at the specified URL, if needed              |```""```                       |
|```--redis_port```           | integer | The port used to establish the redis connection                                   |```6379```                     |

## Connections
CDG relies on an additional connection to a local Redis instance, which is used to store the compressed chat history. This connection is established with the default Redis URL at ```http://localhost:{redis_port}```.

## Evaluating pragmatic quality

Run `evaluate_pragmatic_quality.py` with two RDF graphs and your executable SPARQL competency questions. The script implements the D6 metrics from [§4.2.6 of Benchmarking Automated Knowledge Graph Construction from Semi-Structured Data](https://arxiv.org/html/2609.26985#S4.SS2.SSS6).

```sh
python3 -m pip install 'rdflib>=7.2,<8'
python3 evaluate_pragmatic_quality.py \
  --reference /path/to/reference.ttl --reference-format turtle \
  --synthetic /path/to/synthetic.ttl --synthetic-format turtle \
  --questions /path/to/questions \
  --output-dir /path/to/evaluation
```

The format flags accept RDFLib graph formats and default to extension-based detection with a Turtle fallback. Both graphs use the same RDFLib SPARQL query and the same explicit-triples evaluation without entailment. Relative IRIs in queries resolve against the query file URI. Use local `SELECT` and `ASK` queries with explicit prefixes. `FROM`, `FROM NAMED`, and `SERVICE` are outside this evaluation because they can change where answers come from.

`--questions` accepts a directory of `.rq` or `.sparql` files or a JSON manifest. The manifest lists unique question IDs and query file paths relative to the manifest. Optional `categories` assign one category per named dimension for stratified macro-F1.

```json
[
  {
    "id": "cq-01",
    "query": "queries/cq-01.rq",
    "categories": {
      "complexity": "basic",
      "reasoning": "explicit"
    }
  }
]
```

The output directory receives `report.txt` and `results.json`. Rerunning with the same output directory replaces those two reports. Both report settings, per-question scores and counts, and aggregate scores. The JSON distinguishes an empty successful result (count 0) from a failed execution (count `null`). Either Boolean `ASK` answer counts as one tuple. Synthetic failures score zero and retain any reference tuples in the micro denominator. Reference failures are excluded from scored aggregates. Micro scores are one when all included results are empty and every query succeeded, zero when all tuple totals are zero and a synthetic query failed, and unavailable when no questions were scored.

### Identity and literal comparison

By default, `--comparison literal` compares RDF answer tuples by term spelling. It preserves literal lexical forms and datatypes, compares language tags case-insensitively, treats plain strings as `xsd:string`, and keeps blank nodes local to each graph. Literal IRI matches establish a shared spelling only. The reports flag questions with blank nodes or answer IRIs whose identity has not been explicitly confirmed. The flag is conservative and can include vocabulary IRIs.

Pass `--identity-map /path/to/identity.json` to compare returned synthetic IRIs using a JSON object such as `{"urn:synthetic:entity-42": "urn:reference:entity-7"}`. The map applies to returned IRIs before answer deduplication and leaves the graph and query inputs intact. With a map, both literal and aligned results are written by default. Use `--comparison aligned` or `--comparison literal` to select one mode. Unmapped IRIs in aligned mode retain their spelling and are flagged as unverified.

### Hierarchy-aware PQ6

For each single-column ontology-term question, add a `hierarchy` field to its manifest entry. Use `"hierarchy": {"kind": "class", "root": "urn:example:Root"}` for an `rdfs:subClassOf` hierarchy or `"kind": "property"` for `rdfs:subPropertyOf`. Supply these additional CLI arguments.

```sh
--ontology /path/to/hierarchy.ttl --ontology-format turtle \
--ontology-alignment /path/to/ontology-alignment.json \
--lambda-ancestor 1 --lambda-descendant 2
```

The ontology alignment is a separate JSON object mapping synthetic ontology IRIs to the hierarchy used by the reference answers. Supply `{}` to explicitly declare that the two graphs already use the same ontology vocabulary. Omitted synthetic terms are interpreted in that shared vocabulary. Predictions outside the rooted hierarchy earn zero credit. The two positive penalties are caller-supplied, with the ancestor penalty smaller than the descendant penalty. The values above are examples. The hierarchy serves scoring only. The evaluator computes maximum-weight one-to-one matching and reports macro-F1 over the applicable scored questions. PQ6 reports its availability separately from literal and identity-aligned scores.

Run the self-contained tests with the optional PQ6 dependency installed.

```sh
python3 -m pip install 'rdflib>=7.2,<8' 'networkx>=3,<4'
python3 -B -m unittest discover -s tests -v
```
