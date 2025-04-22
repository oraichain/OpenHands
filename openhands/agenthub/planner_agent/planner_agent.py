from collections import deque

from openhands.core.config.agent_config import AgentConfig
from openhands.core.logger import openhands_logger as logger
from openhands.controller.agent import Agent
from openhands.controller.state.state import State
from openhands.events.action import Action, AgentFinishAction
from openhands.llm.llm import LLM
from openhands.runtime.plugins.agent_skills import AgentSkillsRequirement
from openhands.runtime.plugins.jupyter import JupyterRequirement
from openhands.runtime.plugins.requirement import PluginRequirement
from openhands.agenthub.task_solving_agent.function_calling import get_tools as TaskSolvingTools, response_to_actions as TaskSolvingParser

from .prompt import get_prompt


class PlannerAgent(Agent):
    VERSION = '1.0'
    """
    The planner agent utilizes a special prompting strategy to create long term plans for solving problems.
    The agent is given its previous action-observation pairs, current task, and hint based on last action taken at every step.
    """
    VERSION = '2.2'

    sandbox_plugins: list[PluginRequirement] = [
        # NOTE: AgentSkillsRequirement need to go before JupyterRequirement, since
        # AgentSkillsRequirement provides a lot of Python functions,
        # and it needs to be initialized before Jupyter for Jupyter to use those functions.
        AgentSkillsRequirement(),
        JupyterRequirement(),
    ]

    def __init__(self, llm: LLM, config: AgentConfig, workspace_mount_path_in_sandbox_store_in_session: bool = True,):
        """
        Initialize the Planner Agent with an LLM

        Parameters:
        - llm (LLM): The llm to be used by this agent
        """
        super().__init__(llm, config, workspace_mount_path_in_sandbox_store_in_session)
        self.pending_actions: deque[Action] = deque()
        self.reset()

        built_in_tools = TaskSolvingTools(
            codeact_enable_browsing=self.config.codeact_enable_browsing,
            codeact_enable_jupyter=self.config.codeact_enable_jupyter,
            codeact_enable_llm_editor=self.config.codeact_enable_llm_editor,
            llm=self.llm,
        )

        self.tools = built_in_tools

    def step(self, state: State) -> Action:
        """
        Checks to see if current step is completed, returns AgentFinishAction if True.
        Otherwise, creates a plan prompt and sends to model for inference, returning the result as the next action.

        Parameters:
        - state (State): The current state given the previous actions and observations

        Returns:
        - AgentFinishAction: If the last state was 'completed', 'verified', or 'abandoned'
        - Action: The next action to take based on llm response
        """

        if state.root_task.state in [
            'completed',
            'verified',
            'abandoned',
        ]:
            return AgentFinishAction()
        prompt = get_prompt(state)
        messages = [{'content': prompt, 'role': 'user'}]
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
        response = self.llm.completion(messages=messages)
        actions = TaskSolvingParser.response_to_actions(
            response,
            state.session_id,
            self.workspace_mount_path_in_sandbox_store_in_session,
        )
        logger.debug(f'Actions after response_to_actions: {actions}')
        for action in actions:
            self.pending_actions.append(action)
        return self.pending_actions.popleft()

    def search_memory(self, query: str) -> list[str]:
        return []
