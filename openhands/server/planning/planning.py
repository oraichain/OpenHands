import logging
import os
from typing import AsyncGenerator

from dotenv import load_dotenv
from openai import AsyncOpenAI, OpenAIError

from openhands.server.planning.template import get_prompt_template

# Set up basic logging config
logging.basicConfig(
    level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)
load_dotenv()

REWRITE_LLM_URL = os.getenv('LITELLM_BASE_URL')
REWRITE_LLM_API_KEY = os.getenv('LITELLM_API_KEY')
REWRITE_LLM_NAME = os.getenv('REWRITE_LLM_NAME')


class PromptRefiner:
    def __init__(
        self,
        base_url=REWRITE_LLM_URL,
        api_key=REWRITE_LLM_API_KEY,
        model=REWRITE_LLM_NAME,
    ):
        self.client = AsyncOpenAI(
            base_url=base_url,
            api_key=api_key,
        )
        self.model = model

    async def generate_response(self, prompt: str, system_prompt: str) -> str:
        try:
            completion = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {'role': 'system', 'content': system_prompt},
                    {'role': 'user', 'content': prompt},
                ],
                stream=False,
                max_tokens=20000,
                temperature=1,
            )
            return completion.choices[0].message.content.strip()

        except OpenAIError as e:
            logger.exception(f'Chat completion failed with Error: {e}')
            return f'Error: {e}'

    async def generate_streaming_response(
        self, prompt: str, system_prompt: str
    ) -> AsyncGenerator[str, None]:
        try:
            logger.info(f'Streaming chat request to model: {self.model}')
            stream = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {'role': 'system', 'content': system_prompt},
                    {'role': 'user', 'content': prompt},
                ],
                stream=True,
            )
            response = ''
            async for chunk in stream:  # ✅ FIXED: use async for here
                delta = chunk.choices[0].delta
                if hasattr(delta, 'content') and delta.content:
                    response += delta.content
                    yield delta.content
            logger.debug('Streaming complete.')

        except OpenAIError as e:
            logger.exception(f'Streaming chat failed with Error: {e}')
            yield f'Error: {e}'


HUMAN_FEEDBACK = get_prompt_template('human_feedback')
PLANNING_PROMPT = get_prompt_template('plan')

agent = PromptRefiner(model=REWRITE_LLM_NAME)


async def human_feedback(prompt: str) -> str:
    result = await agent.generate_response(prompt=prompt, system_prompt=HUMAN_FEEDBACK)
    return result


# asyncio.run(optimize_prompt("Analyze a farming pool on Raydium and assess its risk level."))

# async def main():
#     async for chunk in optimize_prompt_streaming("Analyze a farming pool on Raydium and assess its risk level."):
#         print(chunk, end="", flush=True)

# if __name__ == "__main__":
#     asyncio.run(main())
