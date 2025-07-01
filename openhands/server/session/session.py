import asyncio
import time
from copy import deepcopy
from logging import LoggerAdapter
from typing import Callable

import socketio

from openhands.a2a.A2AManager import A2AManager
from openhands.controller.agent import Agent
from openhands.core.config import AppConfig
from openhands.core.config.condenser_config import LLMSummarizingCondenserConfig
from openhands.core.logger import OpenHandsLoggerAdapter
from openhands.core.schema import AgentState
from openhands.core.schema.research import ResearchMode
from openhands.events.action import MessageAction, NullAction
from openhands.events.event import Event, EventSource
from openhands.events.kafka_consumer import KafkaEventConsumer
from openhands.events.observation import (
    AgentStateChangedObservation,
    CmdOutputObservation,
    NullObservation,
)
from openhands.events.observation.error import ErrorObservation
from openhands.events.serialization import event_from_dict, event_to_dict
from openhands.llm.llm import LLM
from openhands.server.mcp_cache import mcp_tools_cache
from openhands.server.session.agent_session import AgentSession
from openhands.server.settings import Settings
from openhands.storage.files import FileStore

# from openhands.server.mcp_cache import mcp_tools_cache

ROOM_KEY = 'room:{sid}'


class Session:
    sid: str
    sio: socketio.AsyncServer | None
    last_active_ts: int = 0
    is_alive: bool = True
    agent_session: AgentSession
    loop: asyncio.AbstractEventLoop
    config: AppConfig
    file_store: FileStore
    user_id: str | None
    logger: LoggerAdapter
    space_id: int | None
    thread_follow_up: int | None
    _kafka_consumer: KafkaEventConsumer | None = None
    _conversation_update_callback: Callable | None = None

    def __init__(
        self,
        sid: str,
        config: AppConfig,
        file_store: FileStore,
        sio: socketio.AsyncServer | None,
        user_id: str | None = None,
        space_id: int | None = None,
        thread_follow_up: int | None = None,
        raw_followup_conversation_id: str | None = None,
    ):
        self.sid = sid
        self.sio = sio
        self.last_active_ts = int(time.time())
        self.file_store = file_store
        self.logger = OpenHandsLoggerAdapter(extra={'session_id': sid})
        self.agent_session = AgentSession(
            sid,
            file_store,
            status_callback=self.queue_status_message,
            user_id=user_id,
            space_id=space_id,
            thread_follow_up=thread_follow_up,
            raw_followup_conversation_id=raw_followup_conversation_id,
        )

        # Use Kafka consumer for event processing if using KafkaEventStream
        from openhands.events.kafka_stream import KafkaEventStream

        if isinstance(self.agent_session.event_stream, KafkaEventStream):
            self._kafka_consumer = KafkaEventConsumer(
                consumer_group=f'server_session_{sid}',
                topic_suffix='server',
                session_id=sid,
            )
            self._kafka_consumer.add_event_handler(self._process_kafka_event)
            self._kafka_consumer.start_consumer()
        else:
            # Fallback to old subscription method for non-Kafka streams
            from openhands.events.stream import EventStreamSubscriber

            self.agent_session.event_stream.subscribe(
                EventStreamSubscriber.SERVER, self.on_event, self.sid
            )

        # Copying this means that when we update variables they are not applied to the shared global configuration!
        self.config = deepcopy(config)
        self.loop = asyncio.get_event_loop()
        self.user_id = user_id
        self.space_id = space_id
        self.thread_follow_up = thread_follow_up
        self.raw_followup_conversation_id = raw_followup_conversation_id

    async def close(self):
        if self.sio:
            await self.sio.emit(
                'oh_event',
                event_to_dict(
                    AgentStateChangedObservation('', AgentState.STOPPED.value)
                ),
                to=ROOM_KEY.format(sid=self.sid),
            )
        self.is_alive = False

        # Stop Kafka consumer
        if self._kafka_consumer:
            self._kafka_consumer.stop_consumer()

        await self.agent_session.close()

    async def initialize_agent(
        self,
        settings: Settings,
        initial_message: MessageAction | None,
        replay_json: str | None,
        mnemonic: str | None = None,
        system_prompt: str | None = None,
        user_prompt: str | None = None,
        mcp_disable: dict[str, bool] | None = None,
        knowledge_base: list[dict] | None = None,
        research_mode: str | None = None,
    ):
        # Lazy import to avoid circular import

        start_time = time.time()
        self.agent_session.event_stream.add_event(
            AgentStateChangedObservation('', AgentState.LOADING),
            EventSource.ENVIRONMENT,
        )
        agent_cls = settings.agent or self.config.default_agent
        self.config.security.confirmation_mode = (
            self.config.security.confirmation_mode
            if settings.confirmation_mode is None
            else settings.confirmation_mode
        )
        self.config.security.security_analyzer = (
            settings.security_analyzer or self.config.security.security_analyzer
        )
        self.config.sandbox.base_container_image = (
            settings.sandbox_base_container_image
            or self.config.sandbox.base_container_image
        )
        self.config.sandbox.runtime_container_image = (
            settings.sandbox_runtime_container_image
            if settings.sandbox_base_container_image
            or settings.sandbox_runtime_container_image
            else self.config.sandbox.runtime_container_image
        )
        max_iterations = settings.max_iterations or self.config.max_iterations

        # This is a shallow copy of the default LLM config, so changes here will
        # persist if we retrieve the default LLM config again when constructing
        # the agent
        default_llm_config = self.config.get_llm_config()
        default_llm_config.model = settings.llm_model or ''
        default_llm_config.api_key = settings.llm_api_key
        default_llm_config.base_url = settings.llm_base_url

        # TODO: override other LLM config & agent config groups (#2075)

        llm = self._create_llm(agent_cls)

        routing_llms = {}
        for config_name, routing_llm_config in self.config.llms.items():
            routing_llms[config_name] = LLM(
                config=routing_llm_config,
            )

        agent_config = self.config.get_agent_config(agent_cls)
        self.logger.info(f'Enabling default condenser: {agent_config.condenser}')
        if settings.enable_default_condenser and agent_config.condenser.type == 'noop':
            default_condenser_config = LLMSummarizingCondenserConfig(
                llm_config=llm.config, keep_first=3, max_size=20
            )

            self.logger.info(f'Enabling default condenser: {default_condenser_config}')
            agent_config.condenser = default_condenser_config
        mcp_disable_set = (
            set(key for key, disabled in mcp_disable.items() if disabled)
            if mcp_disable
            else None
        )

        workspace_mount_path_in_sandbox_store_in_session = (
            self.config.workspace_mount_path_in_sandbox_store_in_session
        )
        if self.config.runtime == 'local':
            workspace_mount_path_in_sandbox_store_in_session = False
        self.logger.info(f'Initializing tools cache: {mcp_tools_cache.is_loaded}')
        # Initialize tools cache if not loaded
        if not mcp_tools_cache.is_loaded:
            await mcp_tools_cache.initialize_tools(
                self.config.dict_mcp_config,
                self.config.dict_search_engine_config,
                sid=self.sid,
                mnemonic=mnemonic,
            )  # Get tools, filter disabled MCPs and research mode
        mcp_tools = (
            []
            if research_mode == ResearchMode.FOLLOW_UP
            else mcp_tools_cache.get_flat_mcp_tools(mcp_disable_set)
        )

        # Search tools already included in mcp_tools
        search_tools = (
            []
            if research_mode == ResearchMode.FOLLOW_UP
            else mcp_tools_cache.get_search_tools()
        )
        self.logger.info(f'MCP tools: {len(mcp_tools)} tools loaded')

        a2a_manager: A2AManager = A2AManager(agent_config.a2a_server_urls)
        try:
            await a2a_manager.initialize_agent_cards()
        except Exception as e:
            self.logger.warning(f'Error initializing A2A manager: {e}')

        if self.config.runtime == 'pyodide':
            agent_config.enable_pyodide = True

        agent = Agent.get_cls(agent_cls)(
            llm,
            agent_config,
            workspace_mount_path_in_sandbox_store_in_session,
            a2a_manager,
            routing_llms=routing_llms,
            enable_streaming=self.config.conversation.enable_streaming,
            session_id=self.sid,
        )
        agent.set_mcp_tools(mcp_tools)
        agent.set_search_tools(search_tools)
        agent.set_event_stream(self.agent_session.event_stream)

        # update some metadata of the agent
        if knowledge_base:
            agent.update_agent_knowledge_base(knowledge_base)

        if system_prompt:
            agent.set_system_prompt(system_prompt)

        if user_prompt:
            agent.set_user_prompt(user_prompt)

        git_provider_tokens = None
        selected_repository = None
        selected_branch = None
        # TODO FIXME: We don't use git or repositories in the agent session
        # if isinstance(settings, ConversationInitData):
        #     git_provider_tokens = settings.git_provider_tokens
        #     selected_repository = settings.selected_repository
        #     selected_branch = settings.selected_branch

        try:
            await self.agent_session.start(
                runtime_name=self.config.runtime,
                config=self.config,
                agent=agent,
                max_iterations=max_iterations,
                max_budget_per_task=self.config.max_budget_per_task,
                agent_to_llm_config=self.config.get_agent_to_llm_config_map(),
                agent_configs=self.config.get_agent_configs(),
                git_provider_tokens=git_provider_tokens,
                selected_repository=selected_repository,
                selected_branch=selected_branch,
                initial_message=initial_message,
                replay_json=replay_json,
                mnemonic=mnemonic,
                research_mode=research_mode,
            )
            end_time = time.time()
            total_time = end_time - start_time
            self.logger.info(f'Total initialize_agent time: {total_time:.2f} seconds')
            return
        except Exception as e:
            self.logger.exception(f'Error creating agent_session: {e}')
            err_class = e.__class__.__name__
            await self.send_error(f'Failed to create agent session: {err_class}')
            return

    def _create_llm(self, agent_cls: str | None) -> LLM:
        """
        Initialize LLM, extracted for testing.
        """
        agent_name = agent_cls if agent_cls is not None else 'agent'
        return LLM(
            config=self.config.get_llm_config_from_agent(agent_name),
            retry_listener=self._notify_on_llm_retry,
            session_id=self.sid,
            user_id=self.user_id,
        )

    def _notify_on_llm_retry(self, retries: int, max: int) -> None:
        msg_id = 'STATUS$LLM_RETRY'
        self.queue_status_message(
            'info', msg_id, f'Retrying LLM request, {retries} / {max}'
        )

    def on_event(self, event: Event):
        asyncio.get_event_loop().run_until_complete(self._on_event(event))

    async def _on_event(self, event: Event):
        """Callback function for events that mainly come from the agent.
        Event is the base class for any agent action and observation.

        Args:
            event: The agent event (Observation or Action).
        """
        event_type = (
            event.action
            if hasattr(event, 'action')
            else event.observation
            if hasattr(event, 'observation')
            else type(event).__name__
        )
        event_source = getattr(event, 'source', 'unknown')

        self.logger.info(
            f'📝 Session {self.sid} _on_event processing: {event_type} (source={event_source})'
        )

        if isinstance(event, NullAction):
            self.logger.debug(f'⏭️ Session {self.sid} skipping NullAction')
            return
        if isinstance(event, NullObservation):
            self.logger.debug(f'⏭️ Session {self.sid} skipping NullObservation')
            return
        if event.source == EventSource.AGENT:
            self.logger.info(
                f'🤖 Session {self.sid} sending AGENT event to websocket: {event_type}'
            )
            await self.send(event_to_dict(event))
            self.logger.info(
                f'✅ Session {self.sid} sent AGENT event to websocket: {event_type}'
            )
        elif event.source == EventSource.USER:
            self.logger.info(
                f'👤 Session {self.sid} sending USER event to websocket: {event_type}'
            )
            await self.send(event_to_dict(event))
        # NOTE: ipython observations are not sent here currently
        elif event.source == EventSource.ENVIRONMENT and isinstance(
            event, (CmdOutputObservation, AgentStateChangedObservation)
        ):
            # feedback from the environment to agent actions is understood as agent events by the UI
            event_dict = event_to_dict(event)
            event_dict['source'] = EventSource.AGENT
            self.logger.info(
                f'🌍 Session {self.sid} sending ENVIRONMENT event as AGENT to websocket: {event_type}'
            )
            await self.send(event_dict)
            if (
                isinstance(event, AgentStateChangedObservation)
                and event.agent_state == AgentState.ERROR
            ):
                self.logger.info(
                    'Agent status error',
                    extra={'signal': 'agent_status_error'},
                )
        elif isinstance(event, ErrorObservation):
            # send error events as agent events to the UI
            event_dict = event_to_dict(event)
            event_dict['source'] = EventSource.AGENT
            self.logger.info(
                f'❌ Session {self.sid} sending ERROR event as AGENT to websocket: {event_type}'
            )
            await self.send(event_dict)
        else:
            self.logger.debug(
                f'⏭️ Session {self.sid} skipping event: {event_type} (source={event_source})'
            )

    async def dispatch(self, data: dict):
        self.logger.info(
            f'📨 Session.dispatch received data: {data.get("action", "unknown")}'
        )

        event = event_from_dict(data.copy())
        self.logger.info(
            f'📝 Created event: {type(event).__name__} (id: {getattr(event, "id", "unset")})'
        )

        # This checks if the model supports images
        if isinstance(event, MessageAction) and event.image_urls:
            controller = self.agent_session.controller
            if controller:
                if controller.agent.llm.config.disable_vision:
                    await self.send_error(
                        'Support for images is disabled for this model, try without an image.'
                    )
                    return
                if not controller.agent.llm.vision_is_active():
                    await self.send_error(
                        'Model does not support image upload, change to a different model or try without an image.'
                    )
                    return

        self.logger.info(
            f'🚀 Adding event {type(event).__name__} to event stream (session: {self.sid})'
        )
        self.agent_session.event_stream.add_event(event, EventSource.USER)
        self.logger.info(f'✅ Event {type(event).__name__} added to event stream')

    async def send(self, data: dict[str, object]):
        if asyncio.get_running_loop() != self.loop:
            self.loop.create_task(self._send(data))
            return
        await self._send(data)

    async def _send(self, data: dict[str, object]) -> bool:
        try:
            if not self.is_alive:
                self.logger.warning(
                    f'🚫 Session {self.sid} not alive, cannot send data'
                )
                return False
            if self.sio:
                self.logger.debug(
                    f'📡 Session {self.sid} emitting to websocket: {data.get("action", data.get("observation", "unknown"))}'
                )
                await self.sio.emit('oh_event', data, to=ROOM_KEY.format(sid=self.sid))
                self.logger.debug(
                    f'✅ Session {self.sid} emitted to websocket successfully'
                )
            else:
                self.logger.warning(
                    f'🚫 Session {self.sid} no socket.io connection available'
                )
            await asyncio.sleep(0.001)  # This flushes the data to the client
            self.last_active_ts = int(time.time())
            return True
        except RuntimeError as e:
            self.logger.error(
                f'❌ Session {self.sid} error sending data to websocket: {str(e)}'
            )
            self.is_alive = False
            return False

    async def send_error(self, message: str):
        """Sends an error message to the client."""
        await self.send({'error': True, 'message': message})

    async def _send_status_message(self, msg_type: str, id: str, message: str):
        """Sends a status message to the client."""
        if msg_type == 'error':
            agent_session = self.agent_session
            controller = self.agent_session.controller
            if controller is not None and not agent_session.is_closed():
                await controller.set_agent_state_to(AgentState.ERROR)
            self.logger.info(
                f'Agent status error: {message}',
                extra={'signal': 'agent_status_error'},
            )
        await self.send(
            {'status_update': True, 'type': msg_type, 'id': id, 'message': message}
        )

    def queue_status_message(self, msg_type: str, id: str, message: str):
        """Queues a status message to be sent asynchronously."""
        asyncio.run_coroutine_threadsafe(
            self._send_status_message(msg_type, id, message), self.loop
        )

    def _process_kafka_event(self, event: Event) -> None:
        """Process events received from Kafka consumer"""
        try:
            event_type = (
                event.action
                if hasattr(event, 'action')
                else event.observation
                if hasattr(event, 'observation')
                else type(event).__name__
            )
            event_source = getattr(event, 'source', 'unknown')

            self.logger.info(
                f'🎯 Session {self.sid} received Kafka event: {event_type} (id={event.id}, source={event_source})'
            )

            # Schedule the async operation to run in the main event loop
            asyncio.run_coroutine_threadsafe(self._on_event(event), self.loop)

            # Also call conversation update callback if set
            if self._conversation_update_callback:
                self._conversation_update_callback(event)

            self.logger.info(
                f'✅ Session {self.sid} processed Kafka event: {event_type}'
            )
        except Exception as e:
            self.logger.error(
                f'❌ Session {self.sid} error processing Kafka event: {e}',
                exc_info=True,
            )

    def set_conversation_update_callback(self, callback: Callable) -> None:
        """Set the conversation update callback for this session"""
        self._conversation_update_callback = callback
