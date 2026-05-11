import yaml
import threading
import os
import redis
import argparse
from rdflib import *
from ollama import Client
from datetime import datetime
from itertools import cycle
from collections import defaultdict
from parameters import ConversationType
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.ollama import OllamaProvider

# PARAMETERS
parser = argparse.ArgumentParser()
parser.add_argument("--conversation", type=int, default=1)
parser.add_argument("--target", type=int, default=1000)
parser.add_argument("--witnesses_n", type=int, default=3)
parser.add_argument("--model_host", type=str, default='')
parser.add_argument("--api_key", type=str, default='')
parser.add_argument("--querent_model", type=str, default='gpt-oss:120b')
parser.add_argument("--qwitness_model", type=str, default='gpt-oss:120b')
parser.add_argument("--contract", type=str, default='LUBM_contract.yaml')

args = parser.parse_args()

contract_file = f"./resources/contracts/{args.contract}"
querent_llm = args.querent_model
witness_llm = args.witness_model
target_triples = args.target
num_of_witnesses = args.witnesses_number
model_host = args.model_host
api_key = args.api_key
if args.conversation == 1:
    conversation_type = ConversationType.ONE_TO_ONE
elif args.conversation == 2:
    conversation_type = ConversationType.MANY_TO_ONE
elif args.conversation == 3:
    conversation_type = ConversationType.ONE_TO_MANY
elif args.conversation == 4:
    conversation_type = ConversationType.MANY_TO_MANY
else:
    exit("Invalid conversation type")

# ONTOLOGY READ
with open(contract_file) as f:
    contract = yaml.safe_load(f)
    ops = contract['intents']
    types = contract['types']
    instructions = contract['instructions']
    subclasses = contract['subclasses']
    precondition_slots = contract['precondition_slots']
    repeatable_terms = contract['repeatable_terms']
ont_prefix = 'ont'
ont_uri = 'http://example.com/ontology#'
instructions_loop = cycle(instructions)
triples_files = []

run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
os.makedirs(f'./resources/output/run_{run_id}', exist_ok=True)
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
dialogue_generator_host = model_host
parser_host = model_host

# OLLAMA MODELS
querent_model = OpenAIChatModel(
    model_name=querent_llm,
    provider=OllamaProvider(base_url=dialogue_generator_host + '/v1')
)

witness_model = OpenAIChatModel(
    model_name=witness_llm,
    provider=OllamaProvider(base_url=dialogue_generator_host + '/v1')
)
dialogue_client = Client(
    host=dialogue_generator_host,
    headers={'Authorization': f'Bearer {api_key}'},
    
)

# Redis
redis = redis.Redis(host='localhost', port=6379, decode_responses=True, db=0)
redis.flushdb()

# PYDANTIC AI CONFIGURATION
types_def = defaultdict()
querent_time = 0
witness_times = [0 for _ in range(num_of_witnesses)]
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
