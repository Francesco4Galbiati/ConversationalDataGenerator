# Conversational Data Generation repository

Here you can find the Python project to execute the Conversational Data Generator (CDG).
This repository is structured as follows:
- ```/one_to_one```: contains the code to execute the one-to-one conversations
- ```/one_to_many```: contains the code to execute the one-to-many conversations
- ```/many_to_one```: contains the code to execute the many-to-one conversations
- ```/many_to_many```: contains the code to execute the many-to-many conversations
- ```/resources```: contains the resources used to run the data generation:
  - ```/ontologies```: contains the ontologies either in RDF/XML or in RDF/Turtle
  - ```/contracts```: contains the conversational contracts derived from the ontologies
  - ```/output```: contains the output files (not present in the repository, it's created at run-time)
- ```agents.py```: contains the definitions of the PydanticAI agents
- ```conf.py```: contains the configuration variables to run the data generation (see below)
- ```csv_to_rdf.py```: contains code to transform the results downloaded from the Fuseki server (in CSV) to RDF/Turtle, which can be re-uploaded into Fuseki
- ```functions.py```: contains the functions used in the code
- ```main.py```: contains the entry point of the code
- ```parameters.py```: contains the definition of configuration parameters.

## Customizing the generation
```conf.py``` contains parameters that can be modified to execute CDG under different circumstances. 
These parameters are found at the top of the file, under the ```PARAMETERS``` section.
The following variables can be edited:
|Variable               |Type                                                      |Effect                                                                            |Default                                          |
|-----------------------|----------------------------------------------------------|----------------------------------------------------------------------------------|-------------------------------------------------|
|```contract_file```    | string                                                   | The conversational contract used to run the CDG                                  |```"resources/contracts/LUBM_contract.yaml"```   |
|```dialogue_llm```     | string                                                   | The name of the model used to run the dialogue generation                        |```"mistral-small3.2:24b-instruct-2506-q4_K_M"```|
|```parsing_llm```      | string                                                   | The name of the model used to run the parsing agent                              |```"qwen2.5:7b-instruct-q4_K_M"```               |
|```conversation_type```| enum(ONE_TO_ONE, ONE_TO_MANY, MANY_TO_ONE, MANY_TO_MANY) | The type of conversation to run                                                  |```ConversationType.ONE_TO_ONE```                |
|```target_triples```   | integer                                                  | The target number of RDF triples to generate                                     |```1000```                                       |
|```conversation_size```| integer                                                  | The size of the conversations used in ONE_TO_ONE and ONE_TO_MANY conversations   |```25```                                         |
|```num_of_witnesses``` | integer                                                  | The number of witness agents to run in ONE_TO_MANY and MANY_TO_MANY conversations|```3```                                          |
|```parallelization```  | boolean                                                  | If the dialogue generation and the parsing should be asynchronous                |```False```                                      |

## Connections
The CDG relies on 2 connections: one to the Ollama service, where the agents run, and the other to the Fuseki instance. In the case of asynchronous generation, there is a third connection for the parser agents.
|URL|Connection|Notes|
|----------------------------|-------------------------------------------|--------------------------------------------------------------------|
|```http://localhost:11434```|Connection to the dialogue generation agent|Connected also to the parsing agent if ```parallelization = False```|
|```http://localhost:11435```|Connection to the dialogue parsing agent   |Present only if ```parallelization = True```                        |
|```http://localhost:3030``` |Connection to the Fuseki database          |Always present                                                      |

These connections are fixed by the code, if they do not correspond to the ones in use on the running machine it's suggested to set up SSH tunnels to map the real ports to the ones in the code.
