import os
from typing import Any, Awaitable, Callable

import httpx

from openhands.core.schema import AgentState


def _json_serialize(data):
    """Converts data to a JSON-serializable format.

    Args:
        data: The data to convert. Can be any type.

    Returns:
        A JSON-serializable representation of the data.
    """
    if data is None:
        return None
    elif isinstance(data, (str, int, float, bool)):
        return data
    elif isinstance(data, (list, tuple)):
        return [_json_serialize(item) for item in data]
    elif isinstance(data, dict):
        return {str(k): _json_serialize(v) for k, v in data.items()}
    elif hasattr(data, 'to_dict') and callable(data.to_dict):
        return _json_serialize(data.to_dict())
    elif hasattr(data, '__dict__'):
        serialized = {}
        for attr_name, attr_value in data.__dict__.items():
            if not attr_name.startswith('_'):
                serialized[attr_name] = _json_serialize(attr_value)
        return serialized
    else:
        return str(data)


async def call_evaluation_endpoint(
    session_id: str,
    log_func: Callable[[str, str], None],
    set_agent_state_func: Callable[[AgentState], Awaitable[None]],
    add_event_func: Callable[[Any, str], None],
    message_source: str,
):
    """
    Call the evaluation endpoint to assess the agent's outputs.

    Args:
        session_id: The ID of the current session
        log_func: Function to log messages
        set_agent_state_func: Function to set the agent state
        add_event_func: Function to add an event to the event stream
        message_source: The source identifier for the agent events
    """
    evaluation_endpoint = os.getenv('EVALUATION_ENDPOINT_URL')
    if not evaluation_endpoint:
        log_func('error', 'EVALUATION_ENDPOINT_URL not set')
        await set_agent_state_func(AgentState.FINISHED)
        return

    payload = {'session_id': session_id}

    async with httpx.AsyncClient(timeout=10.0) as client:
        headers = {'Content-Type': 'application/json'}
        try:
            log_func('info', f'Calling evaluation endpoint: {evaluation_endpoint}')
            response = await client.post(
                evaluation_endpoint, headers=headers, json=payload
            )
            log_func('info', f'Evaluation endpoint response: {response.status_code}')

            if response.status_code != 200:
                log_func(
                    'warning',
                    f'Non-200 response from evaluation endpoint: {response.text}',
                )
                await set_agent_state_func(AgentState.FINISHED)
                return

            try:
                response_data = response.json()
                log_data = _json_serialize(response_data)
                log_func('info', f'Evaluation response: {log_data}')
            except Exception as e:
                log_func('error', f'Failed to parse JSON response: {str(e)}')
                await set_agent_state_func(AgentState.FINISHED)
                return

            result = response_data.get('result', True)

            if result is True:
                log_func('info', 'Evaluation passed, finishing task')
                await set_agent_state_func(AgentState.FINISHED)
            else:
                log_func('info', 'Evaluation failed, asking user for confirmation')

                message = response_data.get(
                    'reason',
                    'I think there might be some issue with the facts presented in the report. Would you like me to check again?',
                )
                from openhands.events.action import MessageAction

                message_action = MessageAction(content=message, wait_for_response=True)
                add_event_func(message_action, message_source)

                await set_agent_state_func(AgentState.AWAITING_USER_INPUT)

        except httpx.RequestError as e:
            log_func(
                'error', f'HTTP request error calling evaluation endpoint: {str(e)}'
            )
            await set_agent_state_func(AgentState.FINISHED)
        except Exception as e:
            log_func('error', f'Error calling evaluation endpoint: {str(e)}')
            await set_agent_state_func(AgentState.FINISHED)
