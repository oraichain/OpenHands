import asyncio
import json
import logging
import os
import time
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


REWRITE_QUERY_PROMPT = get_prompt_template('rewrite_query')
HUMAN_FEEDBACK = get_prompt_template('human_feedback')
PLANNING_PROMPT = get_prompt_template('plan')


async def optimize_prompt(prompt: str) -> str:
    """
    Optimize the prompt using the specified system prompt.

    Args:
        prompt (str): The raw user prompt to be optimized.

    Returns:
        str: The optimized prompt.
    """
    refiner = PromptRefiner()
    start_time = time.perf_counter()
    try:
        decide_to_rewrite = await refiner.generate_response(
            prompt=prompt, system_prompt=HUMAN_FEEDBACK
        )
        result_dict = json.loads(decide_to_rewrite)
        logger.info(
            f'Execution time of decide to rewrite prompt: {time.perf_counter() - start_time:.4f} seconds'
        )
        if result_dict.get('rewrite') == 0:
            logger.info('Prompt does not need rewriting')
            return prompt
        else:
            result = await refiner.generate_response(
                prompt=prompt, system_prompt=REWRITE_QUERY_PROMPT
            )
            logger.info('Prompt need to optimized')
            logger.info(
                f'Execution time of optimize prompt: {time.perf_counter() - start_time:.4f} seconds'
            )
            return result
    except Exception as e:
        logger.error(f'Error optimizing prompt: {e}')
        return f'Error optimizing prompt: {e}'


agent = PromptRefiner(model=REWRITE_LLM_NAME)


async def test_gen_resposne():
    result = await agent.generate_response(
        prompt='give me the top 1 best memecoin', system_prompt=HUMAN_FEEDBACK
    )
    logger.info(f'Generated response: {result}')


asyncio.run(test_gen_resposne())

# asyncio.run(optimize_prompt("Analyze a farming pool on Raydium and assess its risk level."))

# async def main():
#     async for chunk in optimize_prompt_streaming("Analyze a farming pool on Raydium and assess its risk level."):
#         print(chunk, end="", flush=True)

# if __name__ == "__main__":
#     asyncio.run(main())
