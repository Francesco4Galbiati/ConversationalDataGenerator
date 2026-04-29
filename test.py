from ollama import Client

client = Client(
    host='https://ollama-ccdd.pagoda.liris.cnrs.fr/ollama',
    headers={'Authorization': 'Bearer sk-154b7d9623ae424ca9e362e2da0fbfdd'}
)

response = client.chat(
    'gpt-oss:120b',
    messages= [
        {
            'role': 'user',
            'content': 'Hi!'
        }
    ]
)

print(response)