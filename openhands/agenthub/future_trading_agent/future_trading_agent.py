import os
from collections import deque

import openhands.agenthub.future_trading_agent.function_calling as task_solving_function_calling
from openhands.controller.agent import Agent
from openhands.controller.state.state import State
from openhands.core.config import AgentConfig
from openhands.core.logger import openhands_logger as logger
from openhands.core.message import Message, TextContent
from openhands.events.action import (
    Action,
    AgentFinishAction,
)
from openhands.llm.llm import LLM
from openhands.memory.condenser import Condenser
from openhands.memory.conversation_memory import ConversationMemory
from openhands.runtime.plugins import (
    AgentSkillsRequirement,
    JupyterRequirement,
    PluginRequirement,
)
from openhands.utils.prompt import PromptManager


class FutureTradingAgent(Agent):
    VERSION = '2.2'

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
    ) -> None:
        """Initializes a new instance of the TaskSolvingAgent class.

        Parameters:
        - llm (LLM): The llm to be used by this agent
        - config (AgentConfig): The configuration for this agent
        - workspace_mount_path_in_sandbox_store_in_session (bool, optional): Whether to store the workspace mount path in session. Defaults to True.
        """
        super().__init__(llm, config, workspace_mount_path_in_sandbox_store_in_session)
        self.pending_actions: deque[Action] = deque()
        self.reset()

        built_in_tools = task_solving_function_calling.get_tools(
            codeact_enable_browsing=self.config.codeact_enable_browsing,
            codeact_enable_jupyter=self.config.codeact_enable_jupyter,
            codeact_enable_llm_editor=self.config.codeact_enable_llm_editor,
            llm=self.llm,
        )

        self.tools = built_in_tools

        # Retrieve the enabled tools
        logger.info(
            f"TOOLS loaded for TaskSolvingAgent: {', '.join([tool.get('function').get('name') for tool in self.tools])}"
        )
        self.prompt_manager = PromptManager(
            prompt_dir=os.path.join(os.path.dirname(__file__), 'prompts'),
        )

        # Create a ConversationMemory instance
        self.conversation_memory = ConversationMemory(self.config, self.prompt_manager)

        self.condenser = Condenser.from_config(self.config.condenser)
        logger.debug(f'Using condenser: {type(self.condenser)}')

    def reset(self) -> None:
        """Resets the Task Solving Agent."""
        super().reset()
        self.pending_actions.clear()

    def step(self, state: State) -> Action:
        """Performs one step using the TaskSolving Agent.
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
        # Continue with pending actions if any
        if self.pending_actions:
            return self.pending_actions.popleft()

        # if we're done, go back
        latest_user_message = state.get_last_user_message()
        if latest_user_message and latest_user_message.content.strip() == '/exit':
            return AgentFinishAction()

        # prepare what we want to send to the LLM
        messages = self._get_messages(state)
        params: dict = {
            'messages': self.llm.format_messages_for_llm(messages),
        }
        params['tools'] = self.tools
        if self.mcp_tools:
            # Only add tools with unique names
            existing_names = {tool['function']['name'] for tool in params['tools']}
            unique_mcp_tools = [
                tool
                for tool in self.mcp_tools
                if tool['function']['name'] not in existing_names
            ]
            params['tools'] += unique_mcp_tools

        # log to litellm proxy if possible
        params['extra_body'] = {'metadata': state.to_llm_metadata(agent_name=self.name)}
        response = self.llm.completion(**params)
        logger.debug(f'Response from LLM: {response}')
        actions = task_solving_function_calling.response_to_actions(
            response,
            state.session_id,
            self.workspace_mount_path_in_sandbox_store_in_session,
        )
        logger.debug(f'Actions after response_to_actions: {actions}')
        for action in actions:
            self.pending_actions.append(action)
        return self.pending_actions.popleft()

    def _get_messages(self, state: State) -> list[Message]:
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
            state (State): The current state object containing conversation history and other metadata

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

        # Use ConversationMemory to process initial messages
        messages = self.conversation_memory.process_initial_messages(
            with_caching=self.llm.is_caching_prompt_active()
        )

        # Condense the events from the state.
        events = self.condenser.condensed_history(state)

        logger.debug(
            f'Processing {len(events)} events from a total of {len(state.history)} events'
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
                self.prompt_manager.add_examples_to_initial_message(msg)

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
