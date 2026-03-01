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