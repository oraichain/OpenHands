from collections import deque
from openhands.agenthub.planner_agent.prompt import get_prompt_and_images
from openhands.agenthub.planner_agent.response_parser import PlannerResponseParser
from openhands.controller.agent import Agent
from openhands.controller.state.state import State
from openhands.core.config import AgentConfig
from openhands.core.message import ImageContent, Message, TextContent
from openhands.events.action import Action, AgentFinishAction
from openhands.llm.llm import LLM
from openhands.agenthub.codeact_agent import function_calling


class PlannerAgent(Agent):
    VERSION = '1.0'
    """
    The planner agent utilizes a special prompting strategy to create long term plans for solving problems.
    The agent is given its previous action-observation pairs, current task, and hint based on last action taken at every step.
    """
    response_parser = PlannerResponseParser()

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

    def reset(self) -> None:
        """Resets the CodeAct Agent."""
        super().reset()
        self.pending_actions.clear()

    def step(self, state: State) -> Action:
        """Checks to see if current step is completed, returns AgentFinishAction if True.
        Otherwise, creates a plan prompt and sends to model for inference, returning the result as the next action.

        Parameters:
        - state (State): The current state given the previous actions and observations

        Returns:
        - AgentFinishAction: If the last state was 'completed', 'verified', or 'abandoned'
        - Action: The next action to take based on llm response
        """

        # Continue with pending actions if any
        if self.pending_actions:
            return self.pending_actions.popleft()

        # if we're done, go back
        latest_user_message = state.get_last_user_message()
        if latest_user_message and latest_user_message.content.strip() == '/exit':
            return AgentFinishAction()

        if state.root_task.state in [
            'completed',
            'verified',
            'abandoned',
        ]:
            return AgentFinishAction()

        prompt, image_urls = get_prompt_and_images(
            state, self.llm.config.max_message_chars
        )
        content = [TextContent(text=prompt)]
        if self.llm.vision_is_active() and image_urls:
            content.append(ImageContent(image_urls=image_urls))
        message = Message(role='user', content=content)

        params: dict = {
            'messages': self.llm.format_messages_for_llm(message),
            'tools': [],
        }

        if self.mcp_tools:
            # Only add tools with unique names
            existing_names = {tool['function']['name'] for tool in params['tools']}
            unique_mcp_tools = [
                tool
                for tool in self.mcp_tools
                if tool['function']['name'] not in existing_names
            ]
            params['tools'] = unique_mcp_tools

        response = self.llm.completion(**params)

        actions = self.response_parser.parse(response)
        print(f'Actions after response_to_actions: {actions}')
        for action in actions:
            self.pending_actions.append(action)
        return self.pending_actions.popleft()
