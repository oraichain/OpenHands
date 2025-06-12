import json
import os
import time
from collections import deque
from copy import deepcopy
from typing import override

from httpx import request

import openhands.agenthub.codeact_agent.function_calling as codeact_function_calling
from openhands.a2a.A2AManager import A2AManager
from openhands.a2a.tool import ListRemoteAgents, SendTask
from openhands.agenthub.codeact_agent.tools.finish import FinishTool
from openhands.controller.agent import Agent
from openhands.controller.state.state import State
from openhands.core.config import AgentConfig
from openhands.core.logger import openhands_logger as logger
from openhands.core.message import Message, TextContent
from openhands.core.schema import ResearchMode
from openhands.events.action import (
    Action,
    AgentFinishAction,
    StreamingMessageAction,
)
from openhands.events.action.message import MessageAction
from openhands.events.event import Event, EventSource
from openhands.llm.llm import LLM
from openhands.llm.streaming_llm import StreamingLLM
from openhands.memory.condenser import Condenser
from openhands.memory.condenser.condenser import Condensation, View
from openhands.memory.conversation_memory import ConversationMemory
from openhands.runtime.plugins import (
    AgentSkillsRequirement,
    JupyterRequirement,
    PluginRequirement,
)
from openhands.utils.async_utils import call_async_from_sync
from openhands.utils.prompt import PromptManager


class CodeActAgent(Agent):
    VERSION = '2.2'
    """
    The Code Act Agent is a minimalist agent.
    The agent works by passing the model a list of action-observation pairs and prompting the model to take the next step.

    ### Overview

    This agent implements the CodeAct idea ([paper](https://arxiv.org/abs/2402.01030), [tweet](https://twitter.com/xingyaow_/status/1754556835703751087)) that consolidates LLM agents' **act**ions into a unified **code** action space for both *simplicity* and *performance* (see paper for more details).

    The conceptual idea is illustrated below. At each turn, the agent can:

    1. **Converse**: Communicate with humans in natural language to ask for clarification, confirmation, etc.
    2. **CodeAct**: Choose to perform the task by executing code
    - Execute any valid Linux `bash` command
    - Execute any valid `Python` code with [an interactive Python interpreter](https://ipython.org/). This is simulated through `bash` command, see plugin system below for more details.

    ![image](https://github.com/All-Hands-AI/OpenHands/assets/38853559/92b622e3-72ad-4a61-8f41-8c040b6d5fb3)

    """

    sandbox_plugins: list[PluginRequirement] = [
        # NOTE: AgentSkillsRequirement need to go before JupyterRequirement, since
        # AgentSkillsRequirement provides a lot of Python functions,
        # and it needs to be initialized before Jupyter for Jupyter to use those functions.
        AgentSkillsRequirement(),
        JupyterRequirement(),
    ]

    def __init__(
        self,
        llm: LLM,
        config: AgentConfig,
        workspace_mount_path_in_sandbox_store_in_session: bool = True,
        a2a_manager: A2AManager | None = None,
        routing_llms: dict[str, LLM] | None = None,
    ) -> None:
        """Initializes a new instance of the CodeActAgent class.

        Parameters:
        - llm (LLM): The llm to be used by this agent
        - config (AgentConfig): The configuration for this agent
        - workspace_mount_path_in_sandbox_store_in_session (bool, optional): Whether to store the workspace mount path in session. Defaults to True.
        - a2a_manager (A2AManager, optional): The A2A manager to be used by this agent. Defaults to None.
        """
        super().__init__(
            llm,
            config,
            workspace_mount_path_in_sandbox_store_in_session,
            a2a_manager,
        )
        self.pending_actions: deque[Action] = deque()
        self.reset()

        built_in_tools = codeact_function_calling.get_tools(
            codeact_enable_browsing=self.config.codeact_enable_browsing,
            codeact_enable_jupyter=self.config.codeact_enable_jupyter,
            codeact_enable_llm_editor=self.config.codeact_enable_llm_editor,
            llm=self.llm,
            enable_pyodide_bash=self.config.enable_pyodide,
        )

        self.tools = built_in_tools

        self.prompt_manager = PromptManager(
            prompt_dir=os.path.join(os.path.dirname(__file__), 'prompts'),
        )

        # Create a ConversationMemory instance
        self.conversation_memory = ConversationMemory(self.config, self.prompt_manager)
        if 'llm_config' in self.config.condenser:
            logger.info(f'Condenser config: {self.config.condenser.llm_config}')
        self.condenser = Condenser.from_config(self.config.condenser)
        logger.info(f'Using condenser: {type(self.condenser)}')
        self.routing_llms = routing_llms
        self.search_tools: list[dict] = []
        self.session_id: str | None = None
        self.streaming_llm = StreamingLLM(self.llm.config)

    @override
    def set_system_prompt(self, system_prompt: str) -> None:
        self.system_prompt = system_prompt
        if self.prompt_manager:
            self.prompt_manager.set_system_message(system_prompt)
        logger.info(
            f'New system prompt: {self.conversation_memory.process_initial_messages()}'
        )

    @override
    def set_user_prompt(self, user_prompt: str) -> None:
        self.user_prompt = user_prompt
        if self.prompt_manager:
            self.prompt_manager.set_user_message(user_prompt)
        logger.info(
            f'New user prompt: {self.conversation_memory.process_initial_messages()}'
        )

    def reset(self) -> None:
        """Resets the CodeAct Agent."""
        super().reset()
        self.pending_actions.clear()

    def _select_tools_based_on_mode(self, research_mode: str | None) -> list[dict]:
        """Selects the tools based on the mode of the agent."""
        if research_mode == ResearchMode.FOLLOW_UP:
            selected_tools = [FinishTool]
        elif research_mode == ResearchMode.DEEP_RESEARCH:
            # Start with built-in tools
            selected_tools = deepcopy(self.tools)

            if self.config.a2a_server_urls:
                selected_tools.extend([ListRemoteAgents, SendTask])

            # Add search tools, avoiding duplicates
            existing_names = {tool['function']['name'] for tool in selected_tools}
            unique_search_tools = [
                tool
                for tool in self.search_tools
                if tool['function']['name'] not in existing_names
            ]
            selected_tools.extend(unique_search_tools)

            # Add MCP tools, avoiding duplicates
            existing_names = {tool['function']['name'] for tool in selected_tools}
            unique_mcp_tools = [
                tool
                for tool in self.mcp_tools
                if tool['function']['name'] not in existing_names
            ]
            selected_tools.extend(unique_mcp_tools)
        else:
            # For other modes, combine tools and search_tools with deduplication
            selected_tools = deepcopy(self.tools)
            existing_names = {tool['function']['name'] for tool in selected_tools}
            unique_search_tools = [
                tool
                for tool in self.search_tools
                if tool['function']['name'] not in existing_names
            ]
            selected_tools.extend(unique_search_tools)

        logger.debug(f'Selected tools: {selected_tools}')
        return selected_tools

    async def _handle_streaming_response(self, streaming_response):
        """Handle streaming response - both accumulate in pending_actions AND yield chunks immediately"""
        # Accumulate streaming data
        accumulated_tool_calls = {}  # tool_call_id -> partial tool call data
        last_chunk = None
        has_tool_calls = False  # Track if we accumulated any tool calls
        accumulated_content = ''  # Track assistant content

        async for chunk in streaming_response:
            start_time = time.time()
            logger.info(f'Response from LLM: {chunk}')
            end_time = time.time()
            logger.info(f'Streaming response time: {end_time - start_time} seconds')

            last_chunk = chunk
            delta = chunk.choices[0].delta
            # Handle tool call chunks - ACCUMULATE
            if hasattr(delta, 'tool_calls') and delta.tool_calls:
                has_tool_calls = True
                for tool_call_delta in delta.tool_calls:
                    tool_call_id = getattr(tool_call_delta, 'id', None)

                    # Initialize tool call if not exists
                    if tool_call_id and tool_call_id not in accumulated_tool_calls:
                        accumulated_tool_calls[tool_call_id] = {
                            'id': tool_call_id,
                            'type': getattr(tool_call_delta, 'type', 'function'),
                            'function': {'name': '', 'arguments': ''},
                        }

                    # Update existing tool call or use index-based approach
                    if tool_call_id:
                        target_tool_call = accumulated_tool_calls[tool_call_id]
                    else:
                        # Fallback for index-based updates (some providers use index instead of id)
                        tool_call_index = getattr(tool_call_delta, 'index', 0)
                        if tool_call_index < len(accumulated_tool_calls):
                            target_tool_call = list(accumulated_tool_calls.values())[
                                tool_call_index
                            ]
                        else:
                            # Create new tool call with temp id
                            temp_id = f'temp_{tool_call_index}'
                            accumulated_tool_calls[temp_id] = {
                                'id': temp_id,
                                'type': 'function',
                                'function': {'name': '', 'arguments': ''},
                            }
                            target_tool_call = accumulated_tool_calls[temp_id]

                    # Update function name and arguments incrementally
                    if hasattr(tool_call_delta, 'function'):
                        func_delta = tool_call_delta.function
                        if hasattr(func_delta, 'name') and func_delta.name:
                            target_tool_call['function']['name'] += func_delta.name
                        if hasattr(func_delta, 'arguments') and func_delta.arguments:
                            target_tool_call['function']['arguments'] += (
                                func_delta.arguments
                            )
            else:
                if delta.content:
                    accumulated_content += delta.content

                # Only set wait_for_response=True if we don't have tool calls to process
                wait_for_response = not has_tool_calls
                stream_action = StreamingMessageAction(
                    content=delta.content, wait_for_response=wait_for_response
                )
                if self.event_stream is not None:
                    self.event_stream.add_event(stream_action, EventSource.AGENT)

        # AFTER streaming is complete, process accumulated data

        # FIRST: Process tool calls (if any)
        if accumulated_tool_calls:
            # Construct a mock ModelResponse to use with existing response_to_actions logic
            try:
                from litellm import ModelResponse

                # Convert accumulated tool calls to proper format
                formatted_tool_calls = []
                for tool_call_data in accumulated_tool_calls.values():
                    formatted_tool_calls.append(
                        {
                            'id': tool_call_data['id'],
                            'type': tool_call_data['type'],
                            'function': {
                                'name': tool_call_data['function']['name'],
                                'arguments': tool_call_data['function']['arguments'],
                            },
                        }
                    )

                # Create mock response with both content and tool calls if available
                mock_response = ModelResponse(
                    id=last_chunk.id if last_chunk else 'mock-streaming-id',
                    choices=[
                        {
                            'message': {
                                'role': 'assistant',
                                'content': accumulated_content
                                if accumulated_content
                                else None,
                                'tool_calls': formatted_tool_calls,
                            },
                            'index': 0,
                            'finish_reason': 'tool_calls',
                        }
                    ],
                )

                # Use existing response_to_actions logic
                actions = codeact_function_calling.response_to_actions(
                    mock_response,
                    self.session_id,
                    self.workspace_mount_path_in_sandbox_store_in_session,
                )

                for action in actions:
                    self.pending_actions.append(action)

            except Exception as e:
                logger.error(f'Error processing accumulated tool calls: {e}')
                # Fallback to simple message action - use regular MessageAction for pending_actions
                fallback_action = MessageAction(
                    content='Error processing tool calls from streaming response',
                    wait_for_response=True,
                )
                self.pending_actions.append(fallback_action)

    def step(self, state: State) -> Action:
        """Performs one step using the CodeAct Agent.

        This includes gathering info on previous steps and prompting the model to make a command to execute.

        Parameters:
        - state (State): used to get updated info

        Returns:
        - CmdRunAction(command) - bash command to run
        - IPythonRunCellAction(code) - IPython code to run
        - AgentDelegateAction(agent, inputs) - delegate action for (sub)task
        - MessageAction(content) - Message action to run (e.g. ask for clarification)
        - AgentFinishAction() - end the interaction
        """
        if self.session_id is None:
            self.session_id = state.session_id
        # Continue with pending actions if any
        if self.pending_actions:
            return self.pending_actions.popleft()

        # if we're done, go back
        latest_user_message = state.get_last_user_message()

        if latest_user_message and latest_user_message.content.strip() == '/exit':
            return AgentFinishAction()

        # Condense the events from the state. If we get a view we'll pass those
        # to the conversation manager for processing, but if we get a condensation
        # event we'll just return that instead of an action. The controller will
        # immediately ask the agent to step again with the new view.
        condensed_history: list[Event] = []
        match self.condenser.condensed_history(state):
            case View(events=events):
                condensed_history = events

            case Condensation(action=condensation_action):
                return condensation_action

        logger.info(
            f'Processing {len(condensed_history)} events from a total of {len(state.history)} events'
        )
        research_mode = (
            latest_user_message.mode if latest_user_message is not None else None
        )

        messages = self._get_messages(condensed_history, research_mode=research_mode)

        params: dict = {
            'messages': self.llm.format_messages_for_llm(messages),
        }
        # params['extra_body'] = {'metadata': state.to_llm_metadata(agent_name=self.name)}
        # if chat mode, we need to use the search tools
        params['tools'] = self._select_tools_based_on_mode(research_mode)
        logger.debug(f'Messages: {messages}')
        last_message = messages[-1]
        response = None
        if (
            last_message.role == 'user'
            and self.config.enable_llm_router
            and self.config.llm_router_infer_url is not None
            and self.routing_llms is not None
            and self.routing_llms['simple'] is not None
        ):
            content = '\n'.join(
                [
                    msg.text
                    for msg in last_message.content
                    if isinstance(msg, TextContent)
                ]
            )
            text_input = 'Prompt: ' + content
            body = {
                'inputs': [
                    {
                        'name': 'INPUT',
                        'shape': [1, 1],
                        'datatype': 'BYTES',
                        'data': [text_input],
                    }
                ]
            }
            logger.debug(f'Body: {body}')
            headers = {'Content-Type': 'application/json'}
            result = request(
                'POST',
                self.config.llm_router_infer_url,
                data=json.dumps(body),
                headers=headers,
            )
            res = result.json()
            logger.debug(f'Result from classifier: {res}')
            complexity_score = res['outputs'][0]['data'][0]
            logger.debug(f'Complexity score: {complexity_score}')
            if complexity_score > 0.3:
                response = self.llm.completion(**params)
            else:
                response = self.routing_llms['simple'].completion(**params)
        else:
            # Use streaming response
            start_time = time.time()
            response = self.streaming_llm.async_streaming_completion(
                **params, stream=True
            )
            # Process streaming response and populate pending_actions
            call_async_from_sync(self._handle_streaming_response, 15, response)
            end_time = time.time()
            logger.info(f'Streaming response time: {end_time - start_time} seconds')

            # Return first pending action if available
            if self.pending_actions:
                logger.info(
                    f'Returning first of {len(self.pending_actions)} pending actions from streaming'
                )
                return self.pending_actions.popleft()
            # If no pending actions from streaming, return a default message action
            return MessageAction(content='', wait_for_response=True)

        # Fallback if no response or actions generated
        return MessageAction(content='', wait_for_response=True)

    def _get_messages(
        self, events: list[Event], research_mode: str | None = None
    ) -> list[Message]:
        """Constructs the message history for the LLM conversation.

        This method builds a structured conversation history by processing events from the state
        and formatting them into messages that the LLM can understand. It handles both regular
        message flow and function-calling scenarios.

        The method performs the following steps:
        1. Initializes with system prompt and optional initial user message
        2. Processes events (Actions and Observations) into messages
        3. Handles tool calls and their responses in function-calling mode
        4. Manages message role alternation (user/assistant/tool)
        5. Applies caching for specific LLM providers (e.g., Anthropic)
        6. Adds environment reminders for non-function-calling mode

        Args:
            events: The list of events to convert to messages

        Returns:
            list[Message]: A list of formatted messages ready for LLM consumption, including:
                - System message with prompt
                - Initial user message (if configured)
                - Action messages (from both user and assistant)
                - Observation messages (including tool responses)
                - Environment reminders (in non-function-calling mode)

        Note:
            - In function-calling mode, tool calls and their responses are carefully tracked
              to maintain proper conversation flow
            - Messages from the same role are combined to prevent consecutive same-role messages
            - For Anthropic models, specific messages are cached according to their documentation
        """
        if not self.prompt_manager:
            raise Exception('Prompt Manager not instantiated.')
        agent_infos = (
            self.a2a_manager.list_remote_agents() if self.a2a_manager else None
        )
        convert_knowledge_to_list = [
            self.knowledge_base[k] for k in self.knowledge_base
        ]

        # Use ConversationMemory to process initial messages
        # switch mode and initial messages

        messages = self.conversation_memory.process_initial_messages(
            with_caching=self.llm.is_caching_prompt_active(),
            agent_infos=agent_infos,
            knowledge_base=convert_knowledge_to_list,
        )
        if research_mode == ResearchMode.FOLLOW_UP:
            messages = self.conversation_memory.process_initial_followup_message(
                with_caching=self.llm.is_caching_prompt_active(),
                knowledge_base=convert_knowledge_to_list,
            )
        elif research_mode is None or research_mode == ResearchMode.CHAT:
            messages = self.conversation_memory.process_initial_chatmode_message(
                with_caching=self.llm.is_caching_prompt_active(),
                search_tools=[
                    {
                        'name': tool['function']['name'],
                        'description': tool['function']['description'],
                    }
                    for tool in self.search_tools
                ],
                knowledge_base=convert_knowledge_to_list,
            )
        # Use ConversationMemory to process events
        messages = self.conversation_memory.process_events(
            condensed_history=events,
            initial_messages=messages,
            max_message_chars=self.llm.config.max_message_chars,
            vision_is_active=self.llm.vision_is_active(),
        )

        messages = self._enhance_messages(messages)

        if self.llm.is_caching_prompt_active():
            self.conversation_memory.apply_prompt_caching(messages)

        return messages

    def _enhance_messages(self, messages: list[Message]) -> list[Message]:
        """Enhances the user message with additional context based on keywords matched.

        Args:
            messages (list[Message]): The list of messages to enhance

        Returns:
            list[Message]: The enhanced list of messages
        """
        assert self.prompt_manager, 'Prompt Manager not instantiated.'

        results: list[Message] = []
        is_first_message_handled = False
        prev_role = None

        for msg in messages:
            if msg.role == 'user' and not is_first_message_handled:
                is_first_message_handled = True
                # compose the first user message with examples
                self.prompt_manager.add_examples_to_initial_message(
                    msg, self.session_id
                )

            elif msg.role == 'user':
                # Add double newline between consecutive user messages
                if prev_role == 'user' and len(msg.content) > 0:
                    # Find the first TextContent in the message to add newlines
                    for content_item in msg.content:
                        if isinstance(content_item, TextContent):
                            # If the previous message was also from a user, prepend two newlines to ensure separation
                            content_item.text = '\n\n' + content_item.text
                            break

            results.append(msg)
            prev_role = msg.role

        return results
