import os
import yaml
import pydot
from enum import Enum
from rdflib import *
from pydantic import constr
from collections import defaultdict
from pydantic_ai.models.openai import OpenAIChatModel, OpenAIChatModelSettings
from pydantic_ai.providers.ollama import OllamaProvider

# Ontology file read
with open("./resources/HealthEQKG_contract.yaml") as f:
    contract = yaml.safe_load(f)
    ops = contract['intents']
    types = contract['types']
ont_prefix = 'lubm'
ont_uri = 'http://swat.cse.lehigh.edu/onto/univ-bench.owl#'
output_file = open('./resources/output.txt', 'w')
prefixes = f"""
    PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
    PREFIX owl: <http://www.w3.org/2002/07/owl#>
    PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
    PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
    PREFIX {ont_prefix}: <{ont_uri}>
"""
entities = defaultdict(list)
ids = []
chat_history = []
os.environ["PATH"] += os.pathsep + "/opt/homebrew/bin"
img = 0
host = 'http://192.168.0.52:11434/v1'
fuseki = 'http://localhost:3030/lubm_instances/data'
fuseki_headers = {"Content-Type": "text/turtle"}

# Utility classes
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

# Utility variabled
g = Graph()
g.parse('./resources/univ-bench.owl')
newl = '\n'
sq = "'"
id_t = constr(pattern=r'^\S+$')
str_t = constr(min_length=1)
dot_graph = pydot.Dot("dot_graph", graph_type="graph", bgcolor="white")
model_time = 0
parsing_time = 0

# Models
dialogue_model = OpenAIChatModel(
    model_name='mistral-small3.2:24b-instruct-2506-q4_K_M',
    provider=OllamaProvider(base_url=host)
)

task_model = OpenAIChatModel(
    model_name='mistral-nemo:12b-instruct-2407-q8_0',
    provider=OllamaProvider(base_url=host)
)

# Hallucination data structure setup
hallucinations = {
    'unknown_intent': 0,
    'unspecified_slot': 0,
    'false_precondition': 0,
    'total_intents': 0,
    'abox_model_failures': 0,
    'tbox_model_failures': 0
}

# Types definition
types_def = defaultdict()
for t in types:
    if types[t]['type'] == 'str':
        types_def[t] = {'def': constr(pattern=types[t]['pattern']), 'text': types[t]['text']}
    elif types[t]['type'] == 'enum':
        types_def[t] = {'def': Enum(t, dict([(x, x) for x in types[t]['options']])), 'text': types[t]['text']}