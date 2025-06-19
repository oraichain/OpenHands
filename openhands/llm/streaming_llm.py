import asyncio
import warnings
from functools import partial
from typing import Any, Callable

with warnings.catch_warnings():
    warnings.simplefilter('ignore')
    import litellm
from litellm import stream_chunk_builder
from opentelemetry import trace
from traceloop.sdk.decorators import workflow

from openhands.core.exceptions import UserCancelledError
from openhands.core.logger import openhands_logger as logger
from openhands.llm.async_llm import LLM_RETRY_EXCEPTIONS, AsyncLLM
from openhands.llm.fn_call_converter import (
    convert_fncall_messages_to_non_fncall_messages,
)
from openhands.llm.llm import (
    FORMATTED_MODELS,
    MODELS_USING_MAX_COMPLETION_TOKENS,
    REASONING_EFFORT_SUPPORTED_MODELS,
    transform_messages_for_llama,
)


class StreamingLLM(AsyncLLM):
    """Streaming LLM class."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)

        self._async_streaming_completion = partial(
            self._call_acompletion,
            model=self.config.model,
            api_key=self.config.api_key.get_secret_value()
            if self.config.api_key
            else None,
            base_url=self.config.base_url,
            api_version=self.config.api_version,
            custom_llm_provider=self.config.custom_llm_provider,
            max_tokens=self.config.max_output_tokens
            if self.config.model not in MODELS_USING_MAX_COMPLETION_TOKENS
            else None,
            max_completion_tokens=self.config.max_output_tokens
            if self.config.model in MODELS_USING_MAX_COMPLETION_TOKENS
            else None,
            timeout=self.config.timeout,
            temperature=self.config.temperature,
            top_p=self.config.top_p,
            drop_params=self.config.drop_params,
            stream=True,  # Ensure streaming is enabled
        )

        self.async_streaming_completion_unwrapped = self._async_streaming_completion

        @workflow(name='llm_streaming_completion')
        @self.retry_decorator(
            num_retries=self.config.num_retries,
            retry_exceptions=LLM_RETRY_EXCEPTIONS,
            retry_min_wait=self.config.retry_min_wait,
            retry_max_wait=self.config.retry_max_wait,
            retry_multiplier=self.config.retry_multiplier,
        )
        async def async_streaming_completion_wrapper(*args: Any, **kwargs: Any) -> Any:
            messages: list[dict[str, Any]] | dict[str, Any] = []
            mock_function_calling = not self.is_function_calling_active()

            try:
                span = trace.get_current_span()
                if self.session_id:
                    span.set_attribute('session_id', self.session_id)
                if self.user_id:
                    span.set_attribute('user_id', self.user_id)
            except Exception:
                pass

            # some callers might send the model and messages directly
            # litellm allows positional args, like completion(model, messages, **kwargs)
            # see llm.py for more details
            if len(args) > 1:
                messages = args[1] if len(args) > 1 else args[0]
                kwargs['messages'] = messages

                # remove the first args, they're sent in kwargs
                args = args[2:]
            elif 'messages' in kwargs:
                messages = kwargs['messages']

            # ensure we work with a list of messages
            messages = messages if isinstance(messages, list) else [messages]
            # if the agent or caller has defined tools, and we mock via prompting, convert the messages
            if mock_function_calling and 'tools' in kwargs:
                messages = convert_fncall_messages_to_non_fncall_messages(
                    messages,
                    kwargs['tools'],
                    add_in_context_learning_example=bool(
                        'openhands-lm' not in self.config.model
                    ),
                    research_mode=kwargs.get('research_mode', None),
                )
                # logger.debug(f'Messages before transform: {messages}')
                if self.config.model.split('/')[-1] in FORMATTED_MODELS:
                    logger.debug('Transforming messages for llama')
                    messages = transform_messages_for_llama(messages)

                # logger.debug(f'Messages: {messages}')
                kwargs['messages'] = messages

            # if we have no messages, something went very wrong
            if not messages:
                raise ValueError(
                    'The messages list is empty. At least one message is required.'
                )

            # Set reasoning effort for models that support it
            if self.config.model.lower() in REASONING_EFFORT_SUPPORTED_MODELS:
                kwargs['reasoning_effort'] = self.config.reasoning_effort

            self.log_prompt(messages)
            litellm.modify_params = self.config.modify_params

            # if we're not using litellm proxy, remove the extra_body
            if 'litellm_proxy' not in self.config.model:
                kwargs.pop('extra_body', None)

            try:
                # Directly call and await litellm_acompletion

                resp = await self.async_streaming_completion_unwrapped(*args, **kwargs)
                chunks = []
                # For streaming we iterate over the chunks
                async for chunk in resp:
                    # Check for cancellation before yielding the chunk
                    if (
                        hasattr(self.config, 'on_cancel_requested_fn')
                        and self.config.on_cancel_requested_fn is not None
                        and await self.config.on_cancel_requested_fn()
                    ):
                        raise UserCancelledError(
                            'LLM request cancelled due to CANCELLED state'
                        )
                    # with streaming, it is "delta", not "message"!
                    message_back = chunk['choices'][0]['delta'].get('content', '')
                    if message_back:
                        self.log_response(message_back)
                    chunks.append(chunk)
                    yield chunk
                if len(chunks) > 0:
                    resp = stream_chunk_builder(chunks)
                    cost = self._post_completion(resp)
                    if cost and resp.get('usage'):
                        resp['usage']['cost'] = cost
                        span.set_attribute('llm.cost', cost)

                    # Add cost and token usage to the current span
                    usage = resp.get('usage')
                    if usage:
                        prompt_tokens = usage.get('prompt_tokens', 0)
                        completion_tokens = usage.get('completion_tokens', 0)
                        span.set_attribute('llm.usage.prompt_tokens', prompt_tokens)
                        span.set_attribute(
                            'llm.usage.completion_tokens', completion_tokens
                        )

            except UserCancelledError:
                logger.debug('LLM request cancelled by user.')
                raise
            except Exception as e:
                logger.error(f'Completion Error occurred:\n{e}')
                raise

            finally:
                # sleep for 0.1 seconds to allow the stream to be flushed
                if kwargs.get('stream', False):
                    await asyncio.sleep(0.1)

        self._async_streaming_completion = async_streaming_completion_wrapper

    @property
    def async_streaming_completion(self) -> Callable:
        """Decorator for the async litellm acompletion function with streaming."""
        return self._async_streaming_completion
