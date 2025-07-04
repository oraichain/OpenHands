import asyncio
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Iterable, Type

import socketio

from openhands.core.config.app_config import AppConfig
from openhands.core.exceptions import AgentRuntimeUnavailableError
from openhands.core.logger import openhands_logger as logger
from openhands.core.schema.agent import AgentState
from openhands.events.action import MessageAction
from openhands.events.event_store import EventStore
from openhands.events.stream import EventStreamSubscriber, session_exists
from openhands.server.config.server_config import ServerConfig
from openhands.server.modules.conversation import conversation_module
from openhands.server.monitoring import MonitoringListener
from openhands.server.session.agent_session import WAIT_TIME_BEFORE_CLOSE
from openhands.server.session.conversation import Conversation
from openhands.server.session.session import ROOM_KEY, Session
from openhands.server.settings import Settings
from openhands.storage.conversation.conversation_store import ConversationStore
from openhands.storage.data_models.conversation_metadata import ConversationMetadata
from openhands.storage.files import FileStore
from openhands.utils.async_utils import GENERAL_TIMEOUT, call_async_from_sync, wait_all
from openhands.utils.import_utils import get_impl
from openhands.utils.shutdown_listener import should_continue

from .conversation_manager import ConversationManager

_CLEANUP_INTERVAL = 15
UPDATED_AT_CALLBACK_ID = 'updated_at_callback_id'


@dataclass
class StandaloneConversationManager(ConversationManager):
    """Manages conversations in standalone mode (single server instance)."""

    sio: socketio.AsyncServer
    config: AppConfig
    file_store: FileStore
    server_config: ServerConfig
    # Defaulting monitoring_listener for temp backward compatibility.
    monitoring_listener: MonitoringListener = MonitoringListener()
    _local_agent_loops_by_sid: dict[str, Session] = field(default_factory=dict)
    _local_connection_id_to_session_id: dict[str, str] = field(default_factory=dict)
    _active_conversations: dict[str, tuple[Conversation, int]] = field(
        default_factory=dict
    )
    _detached_conversations: dict[str, tuple[Conversation, float]] = field(
        default_factory=dict
    )
    _conversations_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    _cleanup_task: asyncio.Task | None = None
    _conversation_store_class: Type | None = None

    async def __aenter__(self):
        self._cleanup_task = asyncio.create_task(self._cleanup_stale())
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        if self._cleanup_task:
            self._cleanup_task.cancel()
            self._cleanup_task = None

    async def attach_to_conversation(
        self, sid: str, user_id: str | None = None
    ) -> Conversation | None:
        start_time = time.time()
        if not await session_exists(sid, self.file_store, user_id=user_id):
            return None

        async with self._conversations_lock:
            # Check if we have an active conversation we can reuse
            if sid in self._active_conversations:
                conversation, count = self._active_conversations[sid]
                self._active_conversations[sid] = (conversation, count + 1)
                logger.info(
                    f'Reusing active conversation {sid}', extra={'session_id': sid}
                )
                return conversation

            # Check if we have a detached conversation we can reuse
            if sid in self._detached_conversations:
                conversation, _ = self._detached_conversations.pop(sid)
                self._active_conversations[sid] = (conversation, 1)
                logger.info(
                    f'Reusing detached conversation {sid}', extra={'session_id': sid}
                )
                return conversation
            conversation_metadata = await conversation_module._get_conversation_by_id(
                sid
            )

            research_mode = (
                conversation_metadata.configs.get('research_mode', None)
                if conversation_metadata
                else None
            )

            # Create new conversation if none exists
            c = Conversation(
                sid,
                file_store=self.file_store,
                config=self.config,
                user_id=user_id,
                research_mode=research_mode,
            )
            try:
                await c.connect()
            except AgentRuntimeUnavailableError as e:
                logger.error(
                    f'Error connecting to conversation {c.sid}: {e}',
                    extra={'session_id': sid},
                )
                await c.disconnect()
                return None
            end_time = time.time()
            logger.info(
                f'Conversation {c.sid} connected in {end_time - start_time} seconds'
            )
            self._active_conversations[sid] = (c, 1)
            return c

    async def join_conversation(
        self,
        sid: str,
        connection_id: str,
        settings: Settings,
        user_id: str | None,
        github_user_id: str | None,
        mnemonic: str | None = None,
        system_prompt: str | None = None,
        user_prompt: str | None = None,
        mcp_disable: dict[str, bool] | None = None,
        knowledge_base: list[dict] | None = None,
        space_id: int | None = None,
        thread_follow_up: int | None = None,
        research_mode: str | None = None,
        raw_followup_conversation_id: str | None = None,
    ) -> EventStore:
        logger.info(
            f'join_conversation:{sid}:{connection_id}',
            extra={'session_id': sid, 'user_id': user_id},
        )

        await self.sio.enter_room(connection_id, ROOM_KEY.format(sid=sid))
        self._local_connection_id_to_session_id[connection_id] = sid

        event_stream = await self.maybe_start_agent_loop(
            sid,
            settings,
            user_id,
            github_user_id=github_user_id,
            mnemonic=mnemonic,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            mcp_disable=mcp_disable,
            knowledge_base=knowledge_base,
            space_id=space_id,
            thread_follow_up=thread_follow_up,
            research_mode=research_mode,
            raw_followup_conversation_id=raw_followup_conversation_id,
        )
        if not event_stream:
            logger.error(
                f'No event stream after joining conversation: {sid}',
                extra={'session_id': sid},
            )
            raise RuntimeError(f'no_event_stream:{sid}')
        return event_stream

    async def detach_from_conversation(self, conversation: Conversation):
        sid = conversation.sid
        async with self._conversations_lock:
            if sid in self._active_conversations:
                conv, count = self._active_conversations[sid]
                if count > 1:
                    self._active_conversations[sid] = (conv, count - 1)
                    return
                else:
                    self._active_conversations.pop(sid)
                    self._detached_conversations[sid] = (conversation, time.time())

    async def _cleanup_stale(self):
        while should_continue():
            try:
                async with self._conversations_lock:
                    # Create a list of items to process to avoid modifying dict during iteration
                    items = list(self._detached_conversations.items())
                    for sid, (conversation, detach_time) in items:
                        await conversation.disconnect()
                        self._detached_conversations.pop(sid, None)

                close_threshold = time.time() - self.config.sandbox.close_delay
                running_loops = list(self._local_agent_loops_by_sid.items())
                running_loops.sort(key=lambda item: item[1].last_active_ts)
                sid_to_close: list[str] = []
                for sid, session in running_loops:
                    state = session.agent_session.get_state()
                    if session.last_active_ts < close_threshold and state not in [
                        AgentState.RUNNING,
                        None,
                    ]:
                        sid_to_close.append(sid)

                connections = await self.get_connections(
                    filter_to_sids=set(sid_to_close)  # get_connections expects a set
                )
                connected_sids = {sid for _, sid in connections.items()}
                sid_to_close = [
                    sid for sid in sid_to_close if sid not in connected_sids
                ]
                await wait_all(
                    (self._close_session(sid) for sid in sid_to_close),
                    timeout=WAIT_TIME_BEFORE_CLOSE,
                )
                await asyncio.sleep(_CLEANUP_INTERVAL)
            except asyncio.CancelledError:
                async with self._conversations_lock:
                    for conversation, _ in self._detached_conversations.values():
                        await conversation.disconnect()
                    self._detached_conversations.clear()
                await wait_all(
                    self._close_session(sid) for sid in self._local_agent_loops_by_sid
                )
                return
            except Exception:
                logger.error('error_cleaning_stale')
                await asyncio.sleep(_CLEANUP_INTERVAL)

    async def _get_conversation_store(
        self, user_id: str | None, github_user_id: str | None
    ) -> ConversationStore:
        conversation_store_class = self._conversation_store_class
        if not conversation_store_class:
            self._conversation_store_class = conversation_store_class = get_impl(
                ConversationStore,  # type: ignore
                self.server_config.conversation_store_class,
            )
        store = await conversation_store_class.get_instance(
            self.config, user_id, github_user_id
        )
        return store

    async def get_running_agent_loops(
        self, user_id: str | None = None, filter_to_sids: set[str] | None = None
    ) -> set[str]:
        """Get the running session ids in chronological order (oldest first).

        If a user is supplied, then the results are limited to session ids for that user.
        If a set of filter_to_sids is supplied, then results are limited to these ids of interest.

        Returns:
            A set of session IDs
        """
        # Get all items and convert to list for sorting
        items: Iterable[tuple[str, Session]] = self._local_agent_loops_by_sid.items()

        # Filter items if needed
        if filter_to_sids is not None:
            items = (item for item in items if item[0] in filter_to_sids)
        if user_id:
            items = (item for item in items if item[1].user_id == user_id)

        sids = {sid for sid, _ in items}
        return sids

    async def get_connections(
        self, user_id: str | None = None, filter_to_sids: set[str] | None = None
    ) -> dict[str, str]:
        connections = dict(**self._local_connection_id_to_session_id)
        if filter_to_sids is not None:
            connections = {
                connection_id: sid
                for connection_id, sid in connections.items()
                if sid in filter_to_sids
            }
        if user_id:
            for connection_id, sid in list(connections.items()):
                session = self._local_agent_loops_by_sid.get(sid)
                if not session or session.user_id != user_id:
                    connections.pop(connection_id)
        return connections

    async def maybe_start_agent_loop(
        self,
        sid: str,
        settings: Settings,
        user_id: str | None,
        initial_user_msg: MessageAction | None = None,
        replay_json: str | None = None,
        github_user_id: str | None = None,
        mnemonic: str | None = None,
        system_prompt: str | None = None,
        user_prompt: str | None = None,
        mcp_disable: dict[str, bool] | None = None,
        knowledge_base: list[dict] | None = None,
        space_id: int | None = None,
        thread_follow_up: int | None = None,
        research_mode: str | None = None,
        raw_followup_conversation_id: str | None = None,
    ) -> EventStore:
        logger.info(f'maybe_start_agent_loop:{sid}', extra={'session_id': sid})
        session: Session | None = None
        if not await self.is_agent_loop_running(sid):
            logger.info(f'start_agent_loop:{sid}', extra={'session_id': sid})

            response_ids = await self.get_running_agent_loops(user_id)
            if len(response_ids) >= self.config.max_concurrent_conversations:
                logger.info(
                    f'too_many_sessions_for:{user_id}',
                    extra={'session_id': sid, 'user_id': user_id},
                )
                # # Get the conversations sorted (oldest first)
                # conversation_store = await self._get_conversation_store(
                #     user_id, github_user_id
                # )
                # conversations = await conversation_store.get_all_metadata(response_ids)
                # conversations.sort(key=_last_updated_at_key, reverse=True)

                # while len(conversations) >= self.config.max_concurrent_conversations:
                #     oldest_conversation_id = conversations.pop().conversation_id
                #     await self.close_session(oldest_conversation_id)
                # Instead of closing the oldest conversation, raise an error
                event_store = await self._get_event_store(sid, user_id, True)
                if not event_store:
                    logger.error(
                        f'No event stream after starting agent loop: {sid}',
                        extra={'session_id': sid},
                    )
                    raise RuntimeError(f'no_event_stream:{sid}')
                return event_store

            session = Session(
                sid=sid,
                file_store=self.file_store,
                config=self.config,
                sio=self.sio,
                user_id=user_id,
                space_id=space_id,
                thread_follow_up=thread_follow_up,
                raw_followup_conversation_id=raw_followup_conversation_id,
            )
            self._local_agent_loops_by_sid[sid] = session
            asyncio.create_task(
                session.initialize_agent(
                    settings,
                    initial_user_msg,
                    replay_json,
                    mnemonic=mnemonic,
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    mcp_disable=mcp_disable,
                    knowledge_base=knowledge_base,
                    research_mode=research_mode,
                )
            )
            # This does not get added when resuming an existing conversation
            try:
                session.agent_session.event_stream.subscribe(
                    EventStreamSubscriber.SERVER,
                    self._create_conversation_update_callback(
                        user_id, github_user_id, sid
                    ),
                    UPDATED_AT_CALLBACK_ID,
                )
            except ValueError:
                pass  # Already subscribed - take no action

        event_store = await self._get_event_store(sid, user_id)
        if not event_store:
            logger.error(
                f'No event stream after starting agent loop: {sid}',
                extra={'session_id': sid},
            )
            raise RuntimeError(f'no_event_stream:{sid}')
        return event_store

    async def _get_event_store(
        self, sid: str, user_id: str | None, is_reached_limit: bool = False
    ) -> EventStore | None:
        logger.info(f'_get_event_store:{sid}', extra={'session_id': sid})
        # If the limit is reached, return an EventStore with the sid, file_store, user_id, and cur_id to return old events.
        if is_reached_limit:
            return EventStore(
                sid,
                self.file_store,
                user_id,
            )

        session = self._local_agent_loops_by_sid.get(sid)
        if session:
            logger.info(f'found_local_agent_loop:{sid}', extra={'session_id': sid})
            event_stream = session.agent_session.event_stream
            return EventStore(
                event_stream.sid,
                event_stream.file_store,
                event_stream.user_id,
                event_stream.cur_id,
            )
        return None

    async def send_to_event_stream(self, connection_id: str, data: dict):
        # If there is a local session running, send to that
        sid = self._local_connection_id_to_session_id.get(connection_id)
        if not sid:
            raise RuntimeError(f'no_connected_session:{connection_id}')

        session = self._local_agent_loops_by_sid.get(sid)
        if session:
            await session.dispatch(data)
            return

        raise RuntimeError(f'no_connected_session:{connection_id}:{sid}')

    async def disconnect_from_session(self, connection_id: str):
        sid = self._local_connection_id_to_session_id.pop(connection_id, None)
        logger.info(
            f'disconnect_from_session:{connection_id}:{sid}', extra={'session_id': sid}
        )
        if not sid:
            # This can occur if the init action was never run.
            logger.warning(
                f'disconnect_from_uninitialized_session:{connection_id}',
                extra={'session_id': sid},
            )
            return

        # P0 Fix: Clean up finished sessions when last connection disconnects
        session = self._local_agent_loops_by_sid.get(sid)
        if session:
            agent_state = session.agent_session.get_state()
            if agent_state in [
                AgentState.FINISHED,
                AgentState.REJECTED,
                AgentState.ERROR,
                AgentState.AWAITING_USER_INPUT,
                AgentState.AWAITING_USER_CONFIRMATION,
            ]:
                # Check if there are no other active connections to this session
                # Count remaining connections for this session
                remaining_connections = [
                    conn_id
                    for conn_id, sess_id in self._local_connection_id_to_session_id.items()
                    if sess_id == sid
                ]
                if not remaining_connections:
                    logger.info(f'Cleaning up finished session on disconnect: {sid}')
                    await self._close_session(sid)

    async def close_session(self, sid: str):
        session = self._local_agent_loops_by_sid.get(sid)
        if session:
            await self._close_session(sid)

    async def _close_session(self, sid: str):
        logger.info(f'_close_session:{sid}', extra={'session_id': sid})

        # Clear up local variables
        connection_ids_to_remove = list(
            connection_id
            for connection_id, conn_sid in self._local_connection_id_to_session_id.items()
            if sid == conn_sid
        )
        logger.info(
            f'removing connections: {connection_ids_to_remove}',
            extra={'session_id': sid},
        )
        for connnnection_id in connection_ids_to_remove:
            self._local_connection_id_to_session_id.pop(connnnection_id, None)

        session = self._local_agent_loops_by_sid.pop(sid, None)
        if not session:
            logger.warning(f'no_session_to_close:{sid}', extra={'session_id': sid})
            return

        logger.info(f'closing_session:{session.sid}', extra={'session_id': sid})
        await session.close()
        logger.info(f'closed_session:{session.sid}', extra={'session_id': sid})

    @classmethod
    def get_instance(
        cls,
        sio: socketio.AsyncServer,
        config: AppConfig,
        file_store: FileStore,
        server_config: ServerConfig,
        monitoring_listener: MonitoringListener | None,
    ) -> ConversationManager:
        return StandaloneConversationManager(
            sio,
            config,
            file_store,
            server_config,
            monitoring_listener or MonitoringListener(),
        )

    def _create_conversation_update_callback(
        self, user_id: str | None, github_user_id: str | None, conversation_id: str
    ) -> Callable:
        def callback(event, *args, **kwargs):
            call_async_from_sync(
                self._update_conversation_for_event,
                GENERAL_TIMEOUT,
                user_id,
                github_user_id,
                conversation_id,
                event,
            )

        return callback

    async def _update_conversation_for_event(
        self, user_id: str, github_user_id: str, conversation_id: str, event=None
    ):
        conversation_store = await self._get_conversation_store(user_id, github_user_id)
        conversation = await conversation_store.get_metadata(conversation_id)
        conversation.last_updated_at = datetime.now(timezone.utc)

        # Update cost/token metrics if event has llm_metrics
        if event and hasattr(event, 'llm_metrics') and event.llm_metrics:
            metrics = event.llm_metrics

            # Update accumulated cost
            if hasattr(metrics, 'accumulated_cost'):
                conversation.accumulated_cost = metrics.accumulated_cost

            # Update token usage
            if hasattr(metrics, 'accumulated_token_usage'):
                token_usage = metrics.accumulated_token_usage
                conversation.prompt_tokens = token_usage.prompt_tokens
                conversation.completion_tokens = token_usage.completion_tokens
                conversation.total_tokens = (
                    token_usage.prompt_tokens + token_usage.completion_tokens
                )

        await conversation_store.save_metadata(conversation)


def _last_updated_at_key(conversation: ConversationMetadata) -> float:
    last_updated_at = conversation.last_updated_at
    if last_updated_at is None:
        return 0.0
    return last_updated_at.timestamp()
