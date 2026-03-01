import yaml
import threading
from rdflib import *
from ollama import Client, AsyncClient
from datetime import datetime
from itertools import cycle
from collections import defaultdict
from parameters import ConversationType
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.ollama import OllamaProvider

# PARAMETERS
parallelization = False
contract_file = "resources/contracts/LUBM_contract.yaml"
dialogue_llm = 'mistral-small3.2:24b-instruct-2506-q4_K_M'
parser_llm = 'qwen2.5:7b-instruct-q4_K_M'
conversation_type = ConversationType.ONE_TO_ONE
target_triples = 1000
conversation_size = 25
num_of_witnesses = 3

# ONTOLOGY READ
with open(contract_file) as f:
    contract = yaml.safe_load(f)
    ops = contract['intents']
    types = contract['types']
    instructions = contract['instructions']
    subclasses = contract['subclasses']
ont_prefix = 'ont'
ont_uri = 'http://example.com/ontology#'
instructions_loop = cycle(instructions)

run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
output_file_name = f"resources/output/output_{run_id}.json"
output_file = open(output_file_name, 'w')

# RDFLIB CONFIGURATION
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
default_n = conversation_size
num_abox = num_of_witnesses

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
dialogue_generator_host = 'http://localhost:11434'
parser_host = 'http://localhost:11434'
if parallelization:
    parser_host = 'http://localhost:11435'

# OLLAMA MODELS
dialogue_model = OpenAIChatModel(
    model_name=dialogue_llm,
    provider=OllamaProvider(base_url=parser_host + '/v1')
)

task_model = OpenAIChatModel(
    model_name=parser_llm,
    provider=OllamaProvider(base_url=dialogue_generator_host + '/v1')
)

dialogue_client = Client(host=dialogue_generator_host)
async_dialogue_client = AsyncClient(host=dialogue_generator_host)

# Fuseki
fuseki = 'http://localhost:3030/dialogue_gen/data'
fuseki_query = 'http://localhost:3030/dialogue_gen/query'
fuseki_headers = {"Content-Type": "text/turtle"}

# PYDANTIC AI CONFIGURATION
types_def = defaultdict()
'''
for t in types:
    if types[t]['type'] == 'str':
        types_def[t] = {'def': Annotated[str, StringConstraints(pattern=types[t]['pattern'])], 'text': types[t]['text']}
    elif types[t]['type'] == 'enum':
        types_def[t] = {'def': Enum(t, dict([(x, x) for x in types[t]['options']])), 'text': types[t]['text']}
'''
model_time = 0
parsing_time = 0
global_lock = threading.Lock()

# HALLUCINATIONS
hallucinations = {
    'dictionary_hallucination': 0,
    'unspecified_slot': 0,
    'false_precondition': 0
}

# TIMESTAMPS
dialogue_timestamps = list()
parsing_timestamps = list()