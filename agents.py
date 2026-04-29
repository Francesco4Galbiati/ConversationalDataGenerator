from conf import task_model, querent_model, witness_model
from pydantic_ai import Agent
from pydantic_ai.models.openai import OpenAIChatModelSettings

querent_agent = Agent(
    querent_model,
    model_settings=OpenAIChatModelSettings(temperature=0.6)
)

witness_agent = Agent(
    witness_model,
    model_settings=OpenAIChatModelSettings(temperature = 0.8)
)

parser_agent = Agent(
    task_model,
    model_settings=OpenAIChatModelSettings(
        temperature=0,
        max_tokens=200
    ),
    retries=1
)