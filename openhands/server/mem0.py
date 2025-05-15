import asyncio
import json
import os
import time
import uuid
from enum import Enum
from typing import Any, Dict, List, Optional

from openhands.core.config import AppConfig
from openhands.core.logger import openhands_logger as logger

# Import MemoryClient if not already imported
try:
    from mem0 import MemoryClient
except ImportError:
    # Fallback or raise error if not available
    MemoryClient = None


class Mem0MetadataType(Enum):
    FINISH_CONCLUSION = 'finish_conclusion'
    REPORT_FILE = 'report_file'


# Global variable to store the last sync timestamp per conversation
_last_sync_timestamps: Dict[str, float] = {}


class Mem0Client:
    """
    Singleton wrapper for MemoryClient to ensure a single instance is used across the application.
    Lazily initialized on first use.
    """

    _instance = None
    _client = None
    _initialized = False

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(Mem0Client, cls).__new__(cls)
        return cls._instance

    def __init__(self):
        # Only initialize once
        if not Mem0Client._initialized:
            self._initialize_client()

    def _initialize_client(self):
        # This method is called by __init__ but shouldn't do anything
        # The proper initialization happens through initialize_mem0
        pass

    @property
    def client(self):
        return Mem0Client._client

    @property
    def is_available(self) -> bool:
        return Mem0Client._client is not None

    def add(self, *args, **kwargs):
        if not self.is_available:
            logger.warning('MemoryClient not available. Skipping add operation.')
            return None
        return self.client.add(*args, **kwargs)

    def search(self, *args, **kwargs):
        if not self.is_available:
            logger.warning('MemoryClient not available. Skipping search operation.')
            return []
        return self.client.search(*args, **kwargs)

    def history(self, *args, **kwargs):
        if not self.is_available:
            logger.warning('MemoryClient not available. Skipping history operation.')
            return []
        return self.client.history(*args, **kwargs)


def initialize_mem0(app_config: AppConfig) -> None:
    """Initialize the Mem0 client with API key from config.

    Args:
        app_config: The application configuration containing Mem0 settings
    """
    # Try to get API key from config, fall back to environment variable if not found
    mem0_api_key = getattr(app_config, 'mem0_api_key', None) or os.getenv(
        'MEM0_API_KEY'
    )

    if mem0_api_key and MemoryClient is not None:
        try:
            Mem0Client._client = MemoryClient(api_key=mem0_api_key)
            Mem0Client._initialized = True
            logger.info('Mem0 client initialized successfully')
        except Exception as e:
            logger.error(f'Failed to initialize MemoryClient: {e}')
            Mem0Client._client = None
    else:
        if not mem0_api_key:
            logger.warning('No Mem0 API key found in config or environment variables')
        if MemoryClient is None:
            logger.warning('MemoryClient is not available (mem0 package not installed)')


def _extract_content_from_event(event: dict) -> Optional[str]:
    """Extracts the main content from an event, checking message, args.content, then content."""
    content = event.get('message')
    if not content:
        args = event.get('args')
        if args and isinstance(args, dict):
            content = args.get('content')
    if not content:
        content = event.get('content')
    return content


def _extract_file_text_from_tool_call(tool_calls: list) -> Optional[str]:
    """Extracts file_text from the first tool_call's function.arguments, if present and valid JSON."""
    if tool_calls and 'function' in tool_calls[0]:
        arguments_str = tool_calls[0]['function'].get('arguments')
        if arguments_str:
            try:
                arguments_json = json.loads(arguments_str)
                return arguments_json.get('file_text') or arguments_str
            except Exception as e:
                logger.warning(f'Failed to parse arguments as JSON: {e}')
                return arguments_str
    return None


async def process_single_event_for_mem0(
    conversation_id: str, event: dict
) -> List[Dict[str, Any]]:
    """
    Processes a single event dict and returns a list of mem0 events in the format {role, content}.
    Also adds the parsed events to mem0 in the background (non-blocking).
    """
    parsed_events: List[Dict[str, Any]] = []
    metadata: Dict[str, Any] = {'chunk_id': str(uuid.uuid4())}
    source = event.get('source')
    action = event.get('action')
    observation = event.get('observation')
    content = _extract_content_from_event(event)

    if (
        not content
        and not (source == 'agent' and observation == 'edit')
        and action != 'finish'
    ):
        return []

    if source == 'user':
        parsed_events.append({'role': 'user', 'content': content})
    elif source == 'agent':
        if observation == 'mcp':
            return []
        elif observation == 'edit':
            tool_call_metadata = event.get('tool_call_metadata', {})
            model_response = tool_call_metadata.get('model_response', {})
            choices = model_response.get('choices', [])
            if choices and 'message' in choices[0]:
                message_obj = choices[0]['message']
                # First event: content
                edit_content = message_obj.get('content')
                if edit_content:
                    parsed_events.append({'role': 'assistant', 'content': edit_content})
                # Second event: tool_calls[0].function.arguments (extract file_text)
                file_text = _extract_file_text_from_tool_call(
                    message_obj.get('tool_calls', [])
                )
                if file_text:
                    parsed_events.append({'role': 'assistant', 'content': file_text})
                metadata['type'] = Mem0MetadataType.REPORT_FILE.value
        elif action == 'finish':
            tool_call_metadata = event.get('tool_call_metadata', {})
            model_response = tool_call_metadata.get('model_response', {})
            choices = model_response.get('choices', [])
            if choices and 'message' in choices[0]:
                message_obj = choices[0]['message']
                file_text = _extract_file_text_from_tool_call(
                    message_obj.get('tool_calls', [])
                )
                if file_text:
                    parsed_events.append({'role': 'assistant', 'content': file_text})
                metadata['type'] = Mem0MetadataType.FINISH_CONCLUSION.value
        # else:  # If you want to handle other agent cases, add here
        #     parsed_events.append({'role': 'assistant', 'content': content})

    mem0_client = Mem0Client()
    if not mem0_client.is_available:
        logger.warning('Mem0 client is not initialized. Skipping mem0 add.')
        return parsed_events

    logger.info(f'Parsed events: {parsed_events}')
    if parsed_events:
        try:
            add_result = await asyncio.to_thread(
                mem0_client.add,
                agent_id=conversation_id,
                messages=parsed_events,
                metadata=metadata,
                infer=True,
            )
            logger.info(f'Add mem0 result: {add_result}')

            # Store the current timestamp as the last sync timestamp for this conversation
            await update_last_sync_timestamp(conversation_id)

        except Exception as e:
            logger.error(f'Error adding to Mem0: {e}')
    return parsed_events


async def search_knowledge_mem0(
    question: Optional[str] = None,
    space_id: Optional[int] = None,
    raw_followup_conversation_id: Optional[str] = None,
    user_id: Optional[str] = None,
) -> Optional[List[dict]]:
    """
    Search mem0 for knowledge chunks related to the question and conversation.
    Tries both REPORT_FILE and FINISH_CONCLUSION types. Returns a list of knowledge dicts, each with a chunkId, or None if not found.
    """
    mem0_client = Mem0Client()
    if not mem0_client.is_available:
        logger.warning('Mem0 client is not initialized. Skipping mem0 search.')
        return None

    agent_id = raw_followup_conversation_id

    for meta_type in [Mem0MetadataType.REPORT_FILE, Mem0MetadataType.FINISH_CONCLUSION]:
        try:
            memories = mem0_client.search(
                query=question,
                agent_id=agent_id,
                metadata={'type': meta_type.value},
                infer=True,
                top_k=10,
                keyword_search=True,
            )
            if memories:
                memory_id = memories[0]['id']
                histories = mem0_client.history(memory_id)
                if histories:
                    knowledge = histories[0]['input']
                    chunk_id = histories[0]['metadata'].get(
                        'chunk_id', str(uuid.uuid4())
                    )
                    return [{**k, 'chunkId': chunk_id} for k in knowledge]
        except Exception:
            logger.exception(
                f'Unexpected error while searching knowledge for type {meta_type}'
            )
    return None


async def update_last_sync_timestamp(conversation_id: str) -> None:
    """
    Update the last sync timestamp for a conversation.

    Args:
        conversation_id: The ID of the conversation
    """
    current_time = time.time()
    _last_sync_timestamps[conversation_id] = current_time
    logger.debug(
        f'Updated last sync timestamp for conversation {conversation_id}: {current_time}'
    )


async def get_last_sync_timestamp(
    conversation_id: Optional[str] = None,
) -> Optional[float]:
    """
    Get the timestamp of the last successful Mem0 synchronization for a conversation.
    Returns None if no synchronization has been done.

    Args:
        conversation_id: The ID of the conversation. If None, returns the latest timestamp across all conversations.

    Returns:
        The timestamp of the last synchronization or None if no synchronization has been done.
    """
    mem0_client = Mem0Client()
    if not mem0_client.is_available:
        logger.warning(
            'Mem0 client is not initialized. Cannot get last sync timestamp.'
        )
        return None

    if not _last_sync_timestamps:
        logger.info('No sync timestamps available yet.')
        return None

    if conversation_id:
        # Return the timestamp for the specific conversation
        timestamp = _last_sync_timestamps.get(conversation_id)
        logger.debug(
            f'Retrieved last sync timestamp for conversation {conversation_id}: {timestamp}'
        )
        return timestamp
    else:
        # Return the latest timestamp across all conversations
        latest_timestamp = (
            max(_last_sync_timestamps.values()) if _last_sync_timestamps else None
        )
        logger.debug(
            f'Retrieved latest sync timestamp across all conversations: {latest_timestamp}'
        )
        return latest_timestamp
