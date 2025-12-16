from conf import task_model, dialogue_model
from pydantic_ai import Agent
from pydantic_ai.models.openai import OpenAIChatModelSettings

dialogue_agent = Agent(
    dialogue_model,
    model_settings=OpenAIChatModelSettings(temperature=0.6)
)

parser_agent = Agent(task_model,
    model_settings=OpenAIChatModelSettings(temperature=0.15),
    retries=1
)

abox_agent = Agent(task_model,
    model_settings=OpenAIChatModelSettings(temperature=0.15),
    retries=1
)

cluster_agent = Agent(task_model,
    system_prompt="You are a clustering agent, your task is to take a series of intents and group them into areas of"
                  "expertise coherent with their function",
    model_settings=OpenAIChatModelSettings(temperature=0.1),
    retries=3
)

