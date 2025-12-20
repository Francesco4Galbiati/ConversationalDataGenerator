from itertools import cycle
from typing import Annotated
import yaml
from datetime import datetime
from enum import Enum
from rdflib import *
from pydantic import StringConstraints
from collections import defaultdict
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.ollama import OllamaProvider
from ollama import Client, AsyncClient

# ONTOLOGY READ
with open("resources/contracts/LUBM_contract.yaml") as f:
    contract = yaml.safe_load(f)
    ops = contract['intents']
    types = contract['types']
    instructions = contract['instructions']
ont_prefix = 'lubm'
ont_uri = 'http://swat.cse.lehigh.edu/onto/univ-bench.owl#'
instructions_loop = cycle(instructions)

run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
output_file_name = f"resources/output/output_{run_id}.json"
output_file = open(output_file_name, 'w')

# RDFLIB CONFIGURATION
g = Graph()
g.parse('./resources/ontologies/univ-bench.owl')
n = 0
for o in ops:
    n += len(ops[o]['postconditions']['triples'])

# SPARQL PREFIXES
prefixes = f"""
    PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
    PREFIX owl: <http://www.w3.org/2002/07/owl#>
    PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
    PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
    PREFIX {ont_prefix}: <{ont_uri}>
"""

# DATA STRUCTURES
entities = defaultdict(list)
ids = []
chat_history = []
avg_triples = round(n)
default_n = 25
num_abox = 3

# UTILITIES
newl = '\n'
sq = "'"
class bcolors:
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKCYAN = '\033[96m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'

# CONNECTIONS
# Ollama
p_host = 'http://localhost:11434'
d_host = 'http://localhost:11435'

# OLLAMA MODELS
dialogue_model = OpenAIChatModel(
    model_name='mistral-small3.2:24b-instruct-2506-q4_K_M',
    provider=OllamaProvider(base_url=d_host + '/v1')
)

task_model = OpenAIChatModel(
    model_name='qwen2.5:7b-instruct-q4_K_M',
    provider=OllamaProvider(base_url=p_host + '/v1')
)

dialogue_client = Client(host=d_host)
async_dialogue_client = AsyncClient(host=d_host)

# Fuseki
fuseki = 'http://localhost:3030/dialogue_gen/data'
fuseki_headers = {"Content-Type": "text/turtle"}

# PYDANTIC AI CONFIGURATION
types_def = defaultdict()
for t in types:
    if types[t]['type'] == 'str':
        types_def[t] = {'def': Annotated[str, StringConstraints(pattern=types[t]['pattern'])], 'text': types[t]['text']}
    elif types[t]['type'] == 'enum':
        types_def[t] = {'def': Enum(t, dict([(x, x) for x in types[t]['options']])), 'text': types[t]['text']}

model_time = 0
parsing_time = 0

# HALLUCINATIONS
hallucinations = {
    'dictionary_hallucination': 0,
    'unspecified_slot': 0,
    'false_precondition': 0,
    'total_intents': 0,
    'parser_failures': 0,
}

# TIMESTAMPS
dialogue_timestamps = list()
parsing_timestamps = list()