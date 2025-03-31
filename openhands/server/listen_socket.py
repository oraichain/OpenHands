import asyncio
import os
from datetime import datetime
from urllib.parse import parse_qs

from socketio.exceptions import ConnectionRefusedError

from openhands.core.logger import LOG_DIR
from openhands.core.logger import openhands_logger as logger
from openhands.events.action import (
    NullAction,
)
from openhands.events.action.agent import RecallAction
from openhands.events.observation import (
    NullObservation,
)
from openhands.events.observation.agent import (
    AgentStateChangedObservation,
    RecallObservation,
)
from openhands.events.serialization import event_to_dict
from openhands.events.stream import AsyncEventStreamWrapper
from openhands.server.shared import (
    SettingsStoreImpl,
    config,
    conversation_manager,
    sio,
)
from openhands.storage.conversation.conversation_validator import (
    ConversationValidatorImpl,
)


async def terminal_data_emitter(connection_id: str):
    """Emit OpenHands log data every 3 seconds"""
    logger.info(f'Starting terminal log emitter for connection {connection_id}')

    # Keep track of the last position in the file
    last_position = 0
    current_log_file = None
    try:
        # Get the current date for log file name
        current_date = datetime.now().strftime('%Y-%m-%d')
        log_file = os.path.join(LOG_DIR, 'openhands_2025-03-28.log')

        # Check if we need to switch to a new log file
        if current_log_file != log_file:
            current_log_file = log_file
            # Reset position when switching to new file
            last_position = 0

        # Get the latest logs using tail command with -c +<position> to start from last position
        tail_cmd = f'tail -c +{last_position if last_position > 0 else 1} {log_file}'
        if last_position == 0:
            # If it's the first read, only get last 10 lines
            tail_cmd = f'tail -n 10 {log_file}'

        proc = await asyncio.create_subprocess_shell(
            tail_cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await proc.communicate()

        if stdout:
            log_data = stdout.decode()
            if log_data.strip():  # Only send if there's new data
                # Update last position
                if last_position > 0:
                    last_position += len(stdout)
                else:
                    # Get file size for next iteration
                    proc = await asyncio.create_subprocess_shell(
                        f'wc -c < {log_file}',
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                    )
                    size_stdout, _ = await proc.communicate()
                    last_position = int(size_stdout.decode().strip())

                # Format the data as an event
                terminal_event = {
                    'id': int(datetime.now().timestamp()),
                    'timestamp': datetime.now().isoformat(),
                    'source': 'terminal',
                    'data': log_data,
                    'type': 'terminal_data',
                }

                await sio.emit('oh_event', terminal_event, to=connection_id)

        if stderr:
            logger.error(f'Error getting logs: {stderr.decode()}')

    except Exception as e:
        logger.error(f'Error in terminal data emitter: {e}')


@sio.event
async def connect(connection_id: str, environ):
    logger.info(f'sio:connect: {connection_id}')
    query_params = parse_qs(environ.get('QUERY_STRING', ''))
    latest_event_id = int(query_params.get('latest_event_id', [-1])[0])
    conversation_id = query_params.get('conversation_id', [None])[0]
    if not conversation_id:
        logger.error('No conversation_id in query params')
        raise ConnectionRefusedError('No conversation_id in query params')

    cookies_str = environ.get('HTTP_COOKIE', '')
    conversation_validator = ConversationValidatorImpl()
    user_id, github_user_id = await conversation_validator.validate(
        conversation_id, cookies_str
    )

    settings_store = await SettingsStoreImpl.get_instance(config, user_id)
    settings = await settings_store.load()

    if not settings:
        raise ConnectionRefusedError(
            'Settings not found', {'msg_id': 'CONFIGURATION$SETTINGS_NOT_FOUND'}
        )

    event_stream = await conversation_manager.join_conversation(
        conversation_id, connection_id, settings, user_id, github_user_id
    )
    logger.info(
        f'Connected to conversation {conversation_id} with connection_id {connection_id}. Replaying event stream...'
    )
    agent_state_changed = None
    if event_stream is None:
        raise ConnectionRefusedError('Failed to join conversation')
    async_stream = AsyncEventStreamWrapper(event_stream, latest_event_id + 1)
    async for event in async_stream:
        logger.info(f'oh_event: {event.__class__.__name__}')
        await terminal_data_emitter(connection_id)
        if isinstance(
            event,
            (NullAction, NullObservation, RecallAction, RecallObservation),
        ):
            continue
        elif isinstance(event, AgentStateChangedObservation):
            agent_state_changed = event
        else:
            await sio.emit('oh_event', event_to_dict(event), to=connection_id)
    if agent_state_changed:
        logger.info(f'Agent state changed: {agent_state_changed}')
        await sio.emit('oh_event', event_to_dict(agent_state_changed), to=connection_id)

    logger.info(f'Finished replaying event stream for conversation {conversation_id}')


@sio.event
async def oh_user_action(connection_id: str, data: dict):
    await conversation_manager.send_to_event_stream(connection_id, data)


@sio.event
async def oh_action(connection_id: str, data: dict):
    # TODO: Remove this handler once all clients are updated to use oh_user_action
    # Keeping for backward compatibility with in-progress sessions
    await conversation_manager.send_to_event_stream(connection_id, data)


@sio.event
async def disconnect(connection_id: str):
    logger.info(f'sio:disconnect:{connection_id}')
    await conversation_manager.disconnect_from_session(connection_id)
