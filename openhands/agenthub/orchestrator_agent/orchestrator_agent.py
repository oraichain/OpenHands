import json
import os
from enum import Enum
from typing import List, Type

from openhands.a2a.A2AManager import A2AManager
from openhands.agenthub.orchestrator_agent import _prompt as prompts
from openhands.agenthub.orchestrator_agent.utils import get_json_string_from_string
from openhands.controller.agent import Agent
from openhands.controller.state.state import State
from openhands.core.config import AgentConfig
from openhands.core.exceptions import AgentError
from openhands.core.logger import openhands_logger as logger
from openhands.core.message import Message, TextContent
from openhands.events.action import (
    Action,
    AgentFinishAction,
    A2ASendTaskAction,
    MessageAction,
    NullAction,
)
from openhands.events.action.orchestrator import OrchestratorInitializationAction
from openhands.events.event import Event
from openhands.llm.llm import LLM
from openhands.utils.prompt import PromptManager
from openhands.memory.conversation_memory import ConversationMemory
from openhands.memory.condenser import Condenser
from openhands.memory.condenser.condenser import Condensation, View

# Add Pydantic for structured responses
from pydantic import BaseModel

# Define the states of the orchestration process
class OrchestrationPhase(Enum):
    START = 0
    EXECUTING_PLAN = 3
    UPDATING_KNOWLEDGE = 4  # Combined phase for updating both facts and plan, used only for recovery
    FINAL_ANSWER = 5
    ERROR = -1

# Define Pydantic models for structured responses in EXECUTING_PLAN phase
class BooleanAnswer(BaseModel):
    answer: bool
    reason: str | None = None

class NextSpeaker(BaseModel):
    answer: str | None = None
    reason: str | None = None

class InstructionOrQuestion(BaseModel):
    answer: str | None = None
    reason: str | None = None

class ProgressUpdate(BaseModel):
    is_request_satisfied: BooleanAnswer
    is_in_loop: BooleanAnswer
    is_progress_being_made: BooleanAnswer
    next_speaker: NextSpeaker
    instruction_or_question: InstructionOrQuestion

class OrchestratorAgent(Agent):
    VERSION = '1.0'
    AGENT_NAME = 'Orchestrator'

    def __init__(
        self,
        llm: LLM,
        config: AgentConfig,
        workspace_mount_path_in_sandbox_store_in_session: bool = True,
        a2a_manager: A2AManager | None = None,
        max_stall: int = 3,
    ) -> None:
        """Initializes a new instance of the OrchestratorAgent class.

        Parameters:
        - llm (LLM): The llm to be used by this agent
        - config (AgentConfig): The configuration for this agent
        - workspace_mount_path_in_sandbox_store_in_session (bool, optional): Whether to store the workspace mount path in session. Defaults to True.
        - a2a_manager (A2AManager, optional): The A2A manager to be used by this agent. Defaults to None.
        - max_stall (int, optional): Maximum number of times to attempt plan/fact updates when progress is stalled. Defaults to 3.
        """
        super().__init__(
            llm,
            config,
            workspace_mount_path_in_sandbox_store_in_session,
            a2a_manager,
        )
        if not self.a2a_manager:
            # Orchestrator requires A2AManager
            # TODO: Or should it function without it, just answering directly?
            # For now, let's assume it's required.
            raise AgentError('A2AManager is required for OrchestratorAgent')

        self.prompt_manager = PromptManager(
            prompt_dir=os.path.join(os.path.dirname(__file__), 'prompts'), # Use prompts specific to this agent if needed
        )

        # Initialize ConversationMemory and Condenser
        self.conversation_memory = ConversationMemory(self.config, self.prompt_manager)
        if 'llm_config' in self.config.condenser:
            logger.info(f'Condenser config: {self.config.condenser.llm_config}')
        self.condenser = Condenser.from_config(self.config.condenser)
        logger.info(f'Using condenser: {type(self.condenser)}')

        self.max_stall = max_stall
        # Initialize state
        self.reset()

    def _initialize_facts_and_plan(self, state: State) -> None:
        """Initialize facts and plan during agent setup.
        
        This method is called during reset to gather facts and create the initial plan
        before entering the main execution loop.
        """
        if not self.task:
            return

        # Gather facts
        prompt = prompts.ORCHESTRATOR_TASK_LEDGER_FACTS_PROMPT.format(task=self.task)
        messages = self._get_messages(state.history, prompt)
        self.facts = self._call_llm(messages)
        logger.info(f"Generated Initial Facts:\n{self.facts}")

        # Create plan
        if self.facts:
            prompt = prompts.ORCHESTRATOR_TASK_LEDGER_PLAN_PROMPT.format(
                team=self.team_description,
                task=self.task,
            )
            messages = self._get_messages(state.history, prompt)
            self.plan = self._call_llm(messages)
            logger.info(f"Generated Initial Plan:\n{self.plan}")

    def reset(self) -> None:
        """Resets the agent state."""
        super().reset()
        self.phase = OrchestrationPhase.START
        self.task: str | None = None
        self.team_description: str = 'No team description available.' # Should be provided externally or discovered
        self.facts: str | None = None
        self.plan: str | None = None
        self.last_error: str | None = None
        self.stall_count: int = 0

    def _initialize_agent(self, state: State) -> OrchestratorInitializationAction:
        """Initialize the agent with task, team description, facts, and plan.
        
        Returns:
            OrchestratorInitializationAction: The initialization action containing task, facts, plan and team info
        """
        self.task = self._get_initial_task(state)
        self.team_description = self._get_team_description()
        logger.info(f"Initialized task: {self.task}")
        logger.info(f"Team description: {self.team_description}")
        self._initialize_facts_and_plan(state)
        # Skip the fact gathering and plan creation phases
        self.phase = OrchestrationPhase.EXECUTING_PLAN

        return OrchestratorInitializationAction(
            task=self.task,
            facts=self.facts,
            plan=self.plan,
            team=self.team_description
        )

    def _get_initial_task(self, state: State) -> str:
        """Extracts the initial task from the state history."""
        # Find the first user message
        for event in state.history:
            if event.source == 'user' and isinstance(event, MessageAction):
                return event.content
        # Fallback or raise error if no task found
        # This could also be passed explicitly during agent initialization or first step
        # For now, try getting user prompt if set
        if self.user_prompt:
            return self.user_prompt
        raise AgentError("Could not determine the initial task.")

    def _get_team_description(self) -> str:
        """Gets the description of the available team members from A2AManager."""
        if not self.a2a_manager:
             return 'No A2A Manager available.'
        try:
            agents = self.a2a_manager.list_remote_agents() # Assuming A2AManager has such a method
            if not agents:
                return 'No agents available in the team.'
            # Format the agent list into a string description
            # TODO: Enhance this to potentially include agent capabilities if available
            return "Available agents:\n" + "\n".join([f"- {agent['name']}: {agent['description']}" for agent in agents])
        except Exception as e:
            logger.error(f"Failed to list agents via A2AManager: {e}")
            return 'Could not retrieve team description.'

    def step(self, state: State) -> Action:
        """Performs one step of the orchestration process."""
        logger.info(f"Orchestrator Agent step, current phase: {self.phase}")
        self.last_error = None # Clear last error at the start of a step

        if self.phase == OrchestrationPhase.START:
            return self._initialize_agent(state)
        try:
            if self.phase == OrchestrationPhase.EXECUTING_PLAN:
                return self._execute_or_monitor_plan(state)
            elif self.phase == OrchestrationPhase.UPDATING_KNOWLEDGE:
                return self._update_knowledge(state)
            elif self.phase == OrchestrationPhase.FINAL_ANSWER:
                return self._generate_final_answer(state)
            elif self.phase == OrchestrationPhase.ERROR:
                # Handle error state, maybe retry or finish with error
                error_msg = self.last_error or "Unknown error"
                logger.error(f"Orchestrator entered ERROR state: {error_msg}")
                # Reset state when entering error phase
                self.reset()
                # Set phase back to ERROR after reset
                self.phase = OrchestrationPhase.ERROR
                raise AgentError(f"Orchestrator entered ERROR state: {error_msg}")
            else:
                raise AgentError(f"Unknown orchestration phase: {self.phase}")
        except Exception as e:
            logger.error(f"Error during orchestration step (phase {self.phase}): {e}")
            # Store error message before reset
            error_msg = str(e)
            # Reset state when encountering an error
            self.reset()
            # Set phase to ERROR and store error message after reset
            self.phase = OrchestrationPhase.ERROR
            self.last_error = error_msg
            raise e

    def _get_messages(self, events: list[Event], current_prompt: str) -> list[Message]:
        """Constructs the message history for the LLM conversation, including the current prompt.

        Args:
            events: The list of events (history) to include.
            current_prompt: The specific prompt for the current phase/task.

        Returns:
            list[Message]: A list of formatted messages ready for LLM consumption.
        """
        # Process historical events using ConversationMemory
        # This condenses actions/observations into suitable message formats
        messages = self.conversation_memory.process_events(
            condensed_history=events,
            initial_messages=[],
            max_message_chars=self.llm.config.max_message_chars,
            vision_is_active=self.llm.vision_is_active(),
        )
        logger.info(f"messages: {messages}")
        # Add the current prompt as the latest user message
        messages.append(Message(role='user', content=[TextContent(text=current_prompt)]))
        logger.info(f"messages: {messages}")
        
        # Enhance messages with additional context
        messages = self._enhance_messages(messages)
      
        return messages

    def _enhance_messages(self, messages: list[Message]) -> list[Message]:
        """Enhances messages with additional context and formatting.

        This method:
        1. Handles the first message specially by adding examples if needed
        2. Ensures proper spacing between consecutive user messages
        3. Maintains conversation flow and readability

        Args:
            messages (list[Message]): The list of messages to enhance

        Returns:
            list[Message]: The enhanced list of messages with added context and formatting
        """
        assert self.prompt_manager, 'Prompt Manager not instantiated.'

        results: list[Message] = []
        is_first_message_handled = False
        prev_role = None

        for msg in messages:
            if msg.role == 'user' and not is_first_message_handled:
                is_first_message_handled = True
                # Add examples to the first user message if needed
                self.prompt_manager.add_examples_to_initial_message(msg)

            elif msg.role == 'user':
                # Add spacing between consecutive user messages for better readability
                if prev_role == 'user' and len(msg.content) > 0:
                    # Find the first TextContent to add spacing
                    for content_item in msg.content:
                        if isinstance(content_item, TextContent):
                            # Add double newline for clear separation
                            content_item.text = '\n\n' + content_item.text
                            break

            results.append(msg)
            prev_role = msg.role

        return results

    def _call_llm(self, messages: List[Message], response_model: Type[BaseModel] | None = None) -> str | BaseModel:
        """Helper method to call the LLM with a given list of messages, optionally with a response model."""
        logger.debug(f"Sending {len(messages)} messages to LLM for phase {self.phase}")
        # The last message is typically the current instruction/prompt
        if messages:
            logger.debug(f"Last message content: {messages[-1].content}")

        # Call the LLM completion method
        response = self.llm.completion(
            messages=self.llm.format_messages_for_llm(messages),
            thinking={"type": "disabled"},
            # reasoning_effort="low",
            # ,response_format=response_model
        )
       
        if not response.choices:
            raise AgentError("LLM response was empty or invalid.")

        response_content = response.choices[0].message.content or ''
        if not isinstance(response_content, str):
            # Handle cases where content might not be simple string if LLM returns complex types
            logger.warning(f"Received non-string LLM content: {type(response_content)}. Attempting conversion.")
            try:
                response_content = str(response_content)
            except Exception as e:
                raise AgentError(f"Failed to convert LLM response content to string: {e}")

        logger.debug(f"LLM Raw Response ({self.phase}): {response_content}")

        # If a response_model is provided, attempt to parse the content into the Pydantic model
        if response_model:
            try:
                json_string = get_json_string_from_string(response_content)
                response_dict = json.loads(json_string)
                parsed_response = response_model(**response_dict)
                logger.debug(f"Parsed Structured Response ({self.phase}): {parsed_response}")
                return parsed_response
            except Exception as e:
                logger.error(f"Failed to parse LLM response into {response_model.__name__}: {e}")
                raise AgentError(f"Structured response parsing failed: {e}")
        
        return response_content

    def _execute_or_monitor_plan(self, state: State) -> Action:
        """Executes the plan by delegating or monitors progress."""
        if not self.task or not self.plan or not self.facts:
            self.phase = OrchestrationPhase.ERROR
            self.last_error = "Task, plan, or facts not defined for execution."
            return NullAction()

        # Format the progress prompt
        available_names = []
        if self.a2a_manager:
            available_names = [agent['name'] for agent in self.a2a_manager.list_remote_agents()] # Placeholder
        prompt = prompts.ORCHESTRATOR_PROGRESS_LEDGER_PROMPT.format(
            task=self.task,
            team=self.team_description,
            names=available_names,
        )
        logger.debug(f"prompt: {prompt}")
        messages = self._get_messages(state.history, prompt)
        logger.debug(f"messages: {messages}")
        progress_update = self._call_llm(messages, response_model=ProgressUpdate)
        if not isinstance(progress_update, ProgressUpdate):
            logger.error(f"Expected ProgressUpdate object, got {type(progress_update)}")
            self.phase = OrchestrationPhase.ERROR
            self.last_error = f"Failed to get structured ProgressUpdate, got {type(progress_update)}"
            return NullAction("Error in getting structured progress update.")

        logger.info(f"Parsed Progress Update: {progress_update}")

        # Check conditions based on the parsed response
        if progress_update.is_request_satisfied.answer:
            # Store the completed task before reset
            completed_task = self.task
            # Reset agent state
            self.reset()
            # Set phase to FINAL_ANSWER and restore task for final answer generation
            self.phase = OrchestrationPhase.FINAL_ANSWER
            self.task = completed_task
            return NullAction("Task marked as satisfied, proceeding to final answer.")

        # If we're making progress, continue with execution
        if not progress_update.is_in_loop.answer and progress_update.is_progress_being_made.answer:
            self.stall_count = 0  # Reset stall count when making progress
            # Delegate the task
            next_speaker = progress_update.next_speaker.answer
            instruction = progress_update.instruction_or_question.answer

            if not next_speaker or not instruction:
                raise AgentError("LLM progress update did not specify next speaker or instruction.")

            if not self.a2a_manager:
                raise AgentError("Cannot delegate task: A2AManager is not available.")

            logger.info(f"Delegating to '{next_speaker}': {instruction}")
            return A2ASendTaskAction(agent_name=next_speaker, task_message=instruction)

        # Only update plan if we're actually stalled
        self.stall_count += 1
        logger.warning(f"Loop/stall detected (count: {self.stall_count}/{self.max_stall}): {progress_update.is_in_loop.reason or 'No reason provided'} / {progress_update.is_progress_being_made.reason or 'No reason provided'}")
        
        if self.stall_count >= self.max_stall:
            # When max_stall is reached, try a more aggressive recovery by updating both facts and plan
            logger.warning(f"Max stall count ({self.max_stall}) reached. Attempting aggressive recovery by updating both facts and plan.")
            self.phase = OrchestrationPhase.UPDATING_KNOWLEDGE
            self.stall_count = 0  # Reset stall count for the recovery attempt
            return NullAction("Max stalls reached, attempting recovery by updating both facts and plan.")
        
        return NullAction("Stuck or no progress detected, attempting to update plan.")

    def _update_plan(self, state: State) -> Action:
        """Updates the plan based on recent failures or lack of progress."""
        if not self.task or not self.plan or not self.team_description:
            self.phase = OrchestrationPhase.ERROR
            self.last_error = "Task, plan, or team description not defined for plan update."
            return NullAction()

        prompt = prompts.ORCHESTRATOR_TASK_LEDGER_PLAN_UPDATE_PROMPT.format(
            team=self.team_description,
            task=self.task,
        )
        messages = self._get_messages(state.history, prompt)
        response_content = self._call_llm(messages)
        self.plan = response_content # Update the plan
        logger.info(f"Updated Plan:\n{self.plan}")

        # After updating the plan, go back to execution
        self.phase = OrchestrationPhase.EXECUTING_PLAN
        return NullAction("Updated plan, proceeding to execution.")

    def _update_knowledge(self, state: State) -> Action:
        """Updates both facts and plan in a single phase to reduce state transitions."""
        if not self.task or not self.facts or not self.plan or not self.team_description:
            self.phase = OrchestrationPhase.ERROR
            self.last_error = "Task, facts, plan, or team description not defined for knowledge update."
            return NullAction()

        # First update facts
        facts_prompt = prompts.ORCHESTRATOR_TASK_LEDGER_FACTS_UPDATE_PROMPT.format(
            task=self.task,
            facts=self.facts,
            # The reason for update should now be available in the history context
        )
        messages = self._get_messages(state.history, facts_prompt)
        facts_response = self._call_llm(messages)
        self.facts = facts_response
        logger.info(f"Updated Facts:\n{self.facts}")

        # Then immediately update plan with new facts
        plan_prompt = prompts.ORCHESTRATOR_TASK_LEDGER_PLAN_UPDATE_PROMPT.format(
            team=self.team_description,
            task=self.task,
            # 'what went wrong' is now available in the history context
        )
        messages = self._get_messages(state.history, plan_prompt)
        plan_response = self._call_llm(messages)
        self.plan = plan_response
        logger.info(f"Updated Plan:\n{self.plan}")

        # After updating both facts and plan, go back to execution with new initialization
        self.phase = OrchestrationPhase.EXECUTING_PLAN
        return OrchestratorInitializationAction(
            task=self.task,
            facts=self.facts,
            plan=self.plan,
            team=self.team_description
        )

    def _generate_final_answer(self, state: State) -> Action:
        """Generates the final answer based on the completed task execution."""
        if not self.task:
             self.phase = OrchestrationPhase.ERROR
             self.last_error = "Task is not defined for final answer generation."
             return NullAction()

        prompt = prompts.ORCHESTRATOR_FINAL_ANSWER_PROMPT.format(
            task=self.task,
        )

        messages = self._get_messages(state.history, prompt)
        
        response_content = self._call_llm(messages)

        logger.info(f"Generated Final Answer:\n{response_content}")

        # Mark agent as complete and return the final answer
        self._complete = True
        return AgentFinishAction(outputs={
            'output': response_content,
            'status': 'success'
        })
