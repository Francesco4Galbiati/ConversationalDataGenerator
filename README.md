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
|```--api_ket```              | string  | The api key used to access the model at the specified URL, if needed              |```""```                       |

## Connections
CDG relies on an additional connection to a local Redis instance, which is used to store the compressed chat history. This connection is established with the default Redis port at ```http://localhost:6379```.
