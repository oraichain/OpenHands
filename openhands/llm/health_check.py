# This file runs a health check for the LLM, used on litellm/proxy
import random

import litellm
from pydantic import SecretStr

from openhands.core.logger import openhands_logger as logger


def _get_random_llm_message():
    """
    Get a random message from the LLM.
    """
    messages = ["Hey how's it going?", "What's 1 + 1?"]

    return [{'role': 'user', 'content': random.choice(messages)}]


# NOTE: are default values sufficient?
async def perform_health_check(
    model_params: dict,
    min_remaining_requests: int = 20,
    min_remaining_tokens: int = 20000,
):
    """
    Perform a health check for each model in the list.
    model_params must have the following keys:
    - model
    - api_key
    - base_url (optional)
    """
    model_params['messages'] = _get_random_llm_message()
    api_key: SecretStr = model_params.get('api_key', None)
    if api_key is None:
        raise ValueError('api_key is required')
    if model_params.get('model', None) is None:
        raise ValueError('model is required')
    api_key_str = api_key.get_secret_value()
    model_params['api_key'] = api_key_str
    try:
        result = await litellm.ahealth_check(
            model_params=model_params,
            mode='chat',
        )
        remaining_requests = int(result.get('x-ratelimit-remaining-requests', 0))
        remaining_tokens = int(result.get('x-ratelimit-remaining-tokens', 0))
        if (
            remaining_requests > min_remaining_requests
            and remaining_tokens > min_remaining_tokens
        ):
            return remaining_requests, remaining_tokens
        else:
            return None, None
    except Exception as e:
        logger.error(f'Error performing health check: {e}')
        return None, None
