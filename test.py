from ollama import Client

client = Client(
    host='https://ollama-ccdd.pagoda.liris.cnrs.fr/ollama',
    headers={'Authorization': 'Bearer sk-154b7d9623ae424ca9e362e2da0fbfdd'}
)

with open('./resources/contracts/NORIA_contract.yaml', 'r') as f:
    ontology = f.read()

response = client.chat(
    'llama3.3:70b',
    messages= [
        {
            'role': 'user',
            'content': 'Hi'
        }
    ]
)

print(response)