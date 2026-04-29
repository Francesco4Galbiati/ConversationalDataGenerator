import yaml
import threading
import os
import redis
from rdflib import *
from ollama import Client, AsyncClient
from datetime import datetime
from itertools import cycle
from collections import defaultdict
from parameters import ConversationType
from pydantic_ai.models.openai import OpenAIChatModel, OpenAIChatModelSettings
from pydantic_ai.providers.ollama import OllamaProvider

# PARAMETERS
parallelization = False
contract_file = "./resources/contracts/LUBM_test.yaml"
querent_llm = 'gpt-oss:120b'
witness_llm = 'gpt-oss:120b'
parser_llm = 'ministral-3:8b'
conversation_type = ConversationType.ONE_TO_ONE
target_triples = 2500
conversation_size = 25
num_of_witnesses = 3

# ONTOLOGY READ
with open(contract_file) as f:
    contract = yaml.safe_load(f)
    ops = contract['intents']
    types = contract['types']
    instructions = contract['instructions']
    subclasses = contract['subclasses']
    precondition_slots = contract['precondition_slots']
ont_prefix = 'ont'
ont_uri = 'http://example.com/ontology#'
instructions_loop = cycle(instructions)
triples_files = []

run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
os.mkdir(f'./resources/output/run_{run_id}')
if conversation_type == ConversationType.ONE_TO_ONE or conversation_type == ConversationType.MANY_TO_ONE:
    triples_file = f"./resources/output/run_{run_id}/triples.json"
else:
    for i in range(num_of_witnesses):
        triples_files.append([])
        triples_files[i] = f"./resources/output/run_{run_id}/triples_{i}.json"
output_file_name = f"./resources/output/run_{run_id}/output.txt"
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
history_dict = []
chat_histories = [[] for _ in range(num_of_witnesses)]
turn_counter = 0
ids = []
chat_history = []
intent_history = []
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
dialogue_generator_host = 'https://ollama-ccdd.pagoda.liris.cnrs.fr/ollama'
parser_host = 'https://ollama-ccdd.pagoda.liris.cnrs.fr/ollama'
if parallelization:
    parser_host = 'https://ollama-ccdd.pagoda.liris.cnrs.fr/ollama'

# OLLAMA MODELS
querent_model = OpenAIChatModel(
    model_name=querent_llm,
    provider=OllamaProvider(base_url=dialogue_generator_host + '/v1')
)

witness_model = OpenAIChatModel(
    model_name=witness_llm,
    provider=OllamaProvider(base_url=dialogue_generator_host + '/v1')
)

task_model = OpenAIChatModel(
    model_name=parser_llm,
    provider=OllamaProvider(
        base_url=parser_host + '/v1',
        api_key='sk-154b7d9623ae424ca9e362e2da0fbfdd'
    ),
    settings=OpenAIChatModelSettings(extra_body={"keep-alive": -1})
)

dialogue_client = Client(
    host=dialogue_generator_host,
    headers={'Authorization': 'Bearer sk-154b7d9623ae424ca9e362e2da0fbfdd'},
    
)
async_dialogue_client = AsyncClient(
    host=dialogue_generator_host,
    headers={'Authorization': 'Bearer sk-154b7d9623ae424ca9e362e2da0fbfdd'}
)

# Fuseki
# fuseki = 'http://localhost:3030/dialogue_gen/data'
# fuseki_query = 'http://localhost:3030/dialogue_gen/query'
# fuseki_headers = {"Content-Type": "text/turtle"}

# Redis
redis = redis.Redis(host='localhost', port=6379, decode_responses=True, db=0)
redis.flushdb()

# PYDANTIC AI CONFIGURATION
types_def = defaultdict()
'''
for t in types:
    if types[t]['type'] == 'str':
        types_def[t] = {'def': Annotated[str, StringConstraints(pattern=types[t]['pattern'])], 'text': types[t]['text']}
    elif types[t]['type'] == 'enum':
        types_def[t] = {'def': Enum(t, dict([(x, x) for x in types[t]['options']])), 'text': types[t]['text']}
'''
querent_time = 0
witness_time = 0
global_lock = threading.Lock()

# HALLUCINATIONS
hallucinations = {
    'dictionary_hallucination': 0,
    'missing_slot': 0,
    'false_precondition': 0
}

# TIMESTAMPS
dialogue_timestamps = list()
parsing_timestamps = list()