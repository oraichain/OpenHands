from __future__ import annotations

from multiprocessing.pool import RUN
from typing import List, Tuple

from overrides import override

from evaluation.benchmarks.the_agent_company.browsing import BrowserAction
from openhands.core.config.condenser_config import CondenseByTokenLengthConfig
from openhands.core.logger import openhands_logger as logger
from openhands.core.schema import ObservationType
from openhands.core.schema.action import ActionType
from openhands.events.action.a2a_action import A2ASendTaskAction
from openhands.events.action.action import Action
from openhands.events.action.browse import BrowseInteractiveAction
from openhands.events.action.mcp import McpAction
from openhands.events.action.message import MessageAction
from openhands.events.action.files import FileEditAction, FileReadAction, FileWriteAction
from openhands.events.action.commands import CmdRunAction, IPythonRunCellAction
from openhands.events.action.agent import AgentThinkAction
from openhands.events.event import Event, EventSource
from openhands.events.observation.observation import Observation
from openhands.llm.llm import LLM
from openhands.memory.condenser.condenser import Condenser, View, RollingCondenser
from openhands.events.observation.files import FileWriteObservation, FileEditObservation, FileReadObservation
from openhands.events.observation.commands import CmdOutputObservation, IPythonRunCellObservation
from openhands.events.observation.browse import BrowserOutputObservation
from openhands.events.observation.a2a import (
    A2AListRemoteAgentsObservation,
    A2ASendTaskUpdateObservation,
    A2ASendTaskArtifactObservation,
    A2ASendTaskResponseObservation,
)
from openhands.events.observation.mcp import MCPObservation
from openhands.events.observation.planner_mcp import PlanObservation
from openhands.events.observation.playwright_mcp import BrowserMCPObservation
from openhands.events.observation.evaluation import ReportVerificationObservation
from openhands.events.observation.credit import CreditErrorObservation
from openhands.events.observation.delegate import AgentDelegateObservation


class TokenLengthCondenser(RollingCondenser):
    """A condenser that keeps only essential events for completed tasks.

    This condenser:
    1. Keeps the initial user message (task description)
    2. Keeps report markdown files (from edit observations with file text)
    3. Keeps final conclusions (from finish actions with file text)
    4. Condenses all other events
    """

    def __init__(
        self,
        llm: LLM,
        maximum_tokens_before_condensing: int = 150000,
    ):
        """Initialize the TaskCompletionCondenser.

        Args:
            maximum_tokens_before_condensing: Maximum number of tokens before condensing
        """
        logger.info('[TaskCompletionCondenser]: Initialize successfully')
        self.maximum_tokens_before_condensing = maximum_tokens_before_condensing
        self.llm = llm
        super().__init__()

    def _is_removable_event(self, event: Event) -> bool:
        """Check if an event should be removed from the history.

        Args:
            event: The event to check

        Returns:
            bool: True if the event should be kept, False otherwise
        """
        if (
            isinstance(event, Action)
            and (
                isinstance(event, McpAction)
                or isinstance(event, A2ASendTaskAction)
                or isinstance(event, BrowserAction)
                or isinstance(event, BrowseInteractiveAction)
                or isinstance(event, FileEditAction)
                or isinstance(event, FileReadAction)
                or isinstance(event, FileWriteAction)
                or isinstance(event, IPythonRunCellAction)
                or isinstance(event, CmdRunAction)
                or isinstance(event, AgentThinkAction)
            )
        ):
            return True

        if (
            isinstance(event, Observation)
            and (
                isinstance(event, FileWriteObservation)
                or isinstance(event, FileEditObservation)
                or isinstance(event, FileReadObservation)
                or isinstance(event, CmdOutputObservation)
                or isinstance(event, IPythonRunCellObservation)
                or isinstance(event, BrowserOutputObservation)
                or isinstance(event, A2AListRemoteAgentsObservation)
                or isinstance(event, A2ASendTaskUpdateObservation)
                or isinstance(event, A2ASendTaskArtifactObservation)
                or isinstance(event, A2ASendTaskResponseObservation)
                or isinstance(event, MCPObservation)
                or isinstance(event, BrowserMCPObservation)
                or isinstance(event, PlanObservation)
                or isinstance(event, ReportVerificationObservation)
                or isinstance(event, CreditErrorObservation)
                or isinstance(event, AgentDelegateObservation)
            )
        ):
            return True

        if (
            event.source == EventSource.AGENT
            and hasattr(event, 'action')
            and event.action == ActionType.MESSAGE
        ):
            return True

        return False

    def condense(self, view: View, previous_num_tokens_context_window: int) -> View:
        """Create an optimized view that keeps only essential events.

        Args:
            view: The view to condense

        Returns:
            An optimized View containing only essential events
        """
        # Check if we should condense
        if not self.should_condense(view, previous_num_tokens_context_window):
            return view

        # 1st phase: forget unimportant events
        kept_events = self._forget_unimportant_events(view)

        # 2nd phase: condense the important ones
        condensed_events = self._condense_important_events(kept_events)

        # Record metadata about this condensation
        forgotten_count = len(view) - len(kept_events)
        self.add_metadata('forgotten_events_count', forgotten_count)
        self.add_metadata('kept_events_count', len(kept_events))
        self.add_metadata('condensed_events_count', len(condensed_events))

        logger.info(
            f'[TaskCompletionCondenser]: Condensed view from {len(view)} to {len(condensed_events)} events'
        )

        logger.info(f'[TaskCompletionCondenser]: condensed_events={condensed_events}')
        return View(events=condensed_events)

    @classmethod
    def from_config(
        cls, config: CondenseByTokenLengthConfig
    ) -> TokenLengthCondenser:
        """Create a TokenLengthCondenser from a configuration."""
        return TokenLengthCondenser(**config.model_dump(exclude=['type']))
    
    def _forget_unimportant_events(self, view: View) -> list[Event]:
        """Forget unimportant events from the view. Return kept events."""
        kept_events = []

        # Keep track of event IDs to include (using event.id, not array indices)
        event_ids_to_keep = set()

        # find the last user prompt, and keep all events after it so that the result is less affected by the condenser
        # Find first user message - we'll need to ensure it's included
        last_user_message = next(
            (
                e
                for e in reversed(view.events)
                if isinstance(e, MessageAction) and e.source == EventSource.USER
            ),
            None,
        )
        # Process each task chunk - only keep important events from completed tasks
        for event in view.events:
            # Skip events with negative IDs (likely condensation events)
            if event.id < 0:
                continue

            # if we've reached the last user message, stop
            if last_user_message is not None and event.id == last_user_message.id:
                break

            # Skip removable events
            if self._is_removable_event(event):
                continue

            event_ids_to_keep.add(event.id)

            logger.info(
                f'[TaskCompletionCondenser]: Keeping event ID {event.id}'
            )

        # Build the optimized events list using event IDs
        kept_events = [event for event in view if event.id in event_ids_to_keep]

        return kept_events
    
    def _condense_important_events(self, events: list[Event]) -> list[Event]:
        """Condense the important events."""
        concated_user_event_content: str = ''
        concated_agent_event_content: str = ''
        # store the first user and agent event index so that we can condense all the events into them
        first_user_message: MessageAction = None
        first_agent_message: MessageAction = None

        for i, event in enumerate(events):
            if event.source == EventSource.USER and isinstance(event, MessageAction):
                concated_user_event_content += f'{event.content}\n<user_prompt>\n'
                if first_user_message is None:
                    first_user_message = event
            if event.source == EventSource.AGENT and isinstance(event, MessageAction):
                concated_agent_event_content += f'{event.content}\n<agent_analysis_report>\n'
                if first_agent_message is None:
                    first_agent_message = event

        # Construct prompt for summarization
        user_summary_prompt = """You are an AI assistant tasked with summarizing all user prompts into a single, concise list of bullet points representing all requirements, goals, and clarifications, with each distinct user prompt separated by the <user_prompt> tag. The summary must:
Merge all user prompts into one cohesive set of bullet points per prompt, capturing all requirements, goals, and clarifications.

Maintain the tone and any inferred intents of the original user prompts.

Be clear, concise, and minimal while preserving the full essence of the user's intent.

Output only the bullet point list with no additional commentary or explanation.

Example Output Format:
Requirement from prompt 1, reflecting original tone and intent

Requirement from prompt 1, reflecting original tone and intent
<user_prompt>

Requirement from prompt 2, reflecting original tone and intent

Requirement from prompt 2, reflecting original tone and intent

"""
        response = self.llm.completion(
            messages=[
                {'content': user_summary_prompt, 'role': 'system'},
                {'content': concated_user_event_content, 'role': 'user'},
            ],
        )
        user_summary = response.choices[0].message.content

        agent_summary_prompt = """
You are an AI assistant tasked with summarizing AI Agent reports, messages, and analysis into a concise format, with each distinct report or analysis separated by the <agent_analysis_report> tag. The summary must adhere to the following guidelines:
Ignore assistant thinking messages.

For reports and analysis related to the conversation's topic:
Identify and merge relevant reports and analysis into a single summarized section with a new, descriptive title.

Organize the section with appropriate headers to structure the summarized content.

Capture essential data, knowledge, goals, clarifications, and analysis in a clear and concise manner.

For unrelated reports or analysis:
Create separate sections for each, with new, descriptive titles.

Condense and summarize the content, capturing essential data and insights concisely.

Ensure the summarized report is clear, concise, and suitable as a reference for the next iteration.

Output only the summarized report sections with no additional commentary or explanation.

Example Output Format:
Summarized Report: [New Title for Related Reports]
Header 1: Summarized content from related reports

Header 2: Summarized content from related reports
<agent_analysis_report>
**Summarized Report: [New Title for Unrelated Report 1]**

Summarized content from unrelated report 1
<agent_analysis_report>
**Summarized Report: [New Title for Unrelated Report 2]**

Summarized content from unrelated report 2

"""
        response = self.llm.completion(
            messages=[
                {'content': agent_summary_prompt, 'role': 'system'},
                {'content': concated_agent_event_content, 'role': 'user'},
            ],
        )
        agent_summary = response.choices[0].message.content

        # update the first user and agent event content with the summary
        first_user_message.content = user_summary
        first_agent_message.content = agent_summary

        return events

    @override
    def should_condense(self, view: View, previous_num_tokens_context_window: int) -> bool:
        """Determine if the view should be condensed.

        The view should be condensed if there are completed task chunks.

        Args:
            view: The view to check

        Returns:
            True if the view should be condensed, False otherwise
        """

        logger.info(f'[TaskCompletionCondenser]: received view={view}')
        if previous_num_tokens_context_window > self.maximum_tokens_before_condensing:
            logger.info(f'[TaskCompletionCondenser]: previous_num_tokens_context_window={previous_num_tokens_context_window} > maximum_tokens_before_condensing={self.maximum_tokens_before_condensing}')
            return True

        return False

# Register the configuration type
TokenLengthCondenser.register_config(CondenseByTokenLengthConfig)
