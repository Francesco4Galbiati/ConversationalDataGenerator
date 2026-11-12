import yaml
import threading
import os
import redis
import argparse
from rdflib import *
from ollama_retry import RetryingOllamaClient
from datetime import datetime
from itertools import cycle
from collections import defaultdict
from parameters import ConversationType
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.ollama import OllamaProvider

# PARAMETERS
parser = argparse.ArgumentParser()
parser.add_argument("--conversation", type=int, default=1)
parser.add_argument("--target", type=int, default=10000)
parser.add_argument("--witnesses_n", type=int, default=3)
parser.add_argument("--model_host", type=str, default='https://ollama-ccdd.pagoda.liris.cnrs.fr/ollama')
parser.add_argument("--api_key", type=str, default='sk-154b7d9623ae424ca9e362e2da0fbfdd')
parser.add_argument("--querent_model", type=str, default='gpt-oss:120b')
parser.add_argument("--witness_model", type=str, default='gpt-oss:120b')
parser.add_argument("--contract", type=str, default='HealthEQKG_contract.yaml')
parser.add_argument("--redis_port", type=int, default=6379)
parser.add_argument("--unique_slots", nargs="*", default=[],
                    help="slots whose values must never repeat (e.g. country_name); with a closed list of options, "
                         "the intent creating them stops being scheduled once every option is used")
parser.add_argument("--precondition_sampling", choices=["least_used", "preferential"], default="least_used",
                    help="least_used: offer the least-used existing IDs (default); preferential: offer one ID drawn "
                         "with probability (uses + 1) ** alpha, so well-connected entities attract more links")
parser.add_argument("--preferential_alpha", type=float, default=1.0,
                    help="strength of preferential sampling: 0 = uniform, 1 = linear (Barabasi-Albert), >1 = stronger")
parser.add_argument("--preferential_slots", nargs="*", default=None,
                    help="precondition slots that use preferential sampling (default: all); the others keep least_used")
parser.add_argument("--seed", type=int, default=0, help="random seed for preferential sampling")
parser.add_argument("--intent_selection", choices=["model", "schedule"], default="model",
                    help="model: the querent chooses the intent (default); schedule: the code chooses it from the cardinalities")

args = parser.parse_args()

contract_file = f"./resources/contracts/{args.contract}"
querent_llm = args.querent_model
witness_llm = args.witness_model
target_triples = args.target
num_of_witnesses = args.witnesses_n
model_host = args.model_host
redis_port = args.redis_port
api_key = args.api_key
intent_selection = args.intent_selection
unique_slots = set(args.unique_slots)
precondition_sampling = args.precondition_sampling
preferential_alpha = args.preferential_alpha
preferential_slots = None if args.preferential_slots is None else set(args.preferential_slots)
if precondition_sampling == "preferential" and args.conversation != 1:
    exit("--precondition_sampling preferential is implemented for --conversation 1 only")
if intent_selection == "schedule" and (args.conversation != 1 or querent_llm == "llama3.3:70b"):
    exit("--intent_selection schedule is implemented for --conversation 1 with the gpt prompts only")
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
dialogue_client = RetryingOllamaClient(
    host=dialogue_generator_host,
    headers={'Authorization': f'Bearer {api_key}'},
    capture_dir=os.getenv('CDG_OLLAMA_CAPTURE_DIR'),
    # without a timeout a dropped connection blocks the run forever (11 Nov: 3.5 h); after this many
    # seconds the request fails with httpx.ReadTimeout, which robustness.py retries like a server error
    timeout=float(os.getenv('CDG_TIMEOUT', '600')),
)

# Redis
redis = redis.Redis(host='localhost', port=redis_port, decode_responses=True, db=0)
redis.flushdb()

# PYDANTIC AI CONFIGURATION
types_def = defaultdict()
querent_time = 0
schedule_overrides = 0
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
