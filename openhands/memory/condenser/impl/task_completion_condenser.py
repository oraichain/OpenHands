from __future__ import annotations

from typing import List, Tuple

from openhands.core.config.condenser_config import TaskCompletionCondenserConfig
from openhands.core.logger import openhands_logger as logger
from openhands.core.schema import ObservationType
from openhands.core.schema.action import ActionType
from openhands.events.event import Event, EventSource
from openhands.memory.condenser.condenser import Condenser, View


class TaskCompletionCondenser(Condenser):
    """A condenser that keeps only essential events for completed tasks.

    This condenser:
    1. Keeps the initial user message (task description)
    2. Keeps report markdown files (from edit observations with file text)
    3. Keeps final conclusions (from finish actions with file text)
    4. Condenses all other events
    """

    def __init__(self, keep_first: int = 1):
        """Initialize the TaskCompletionCondenser.

        Args:
            keep_first: Number of initial events to always keep (typically the user's task)
        """
        logger.info('[TaskCompletionCondenser]: Initialize successfully')
        super().__init__()

    def _is_important_event(self, event: Event) -> bool:
        """Check if an event should be kept in the history.

        Args:
            event: The event to check

        Returns:
            bool: True if the event should be kept, False otherwise
        """
        if (
            event.source == EventSource.USER
            and hasattr(event, 'action')
            and event.action == ActionType.MESSAGE
        ):
            return True

        if (
            event.source == EventSource.AGENT
            and hasattr(event, 'observation')
            and event.observation == ObservationType.EDIT  # file edit observation
        ):
            return True

        if (
            event.source == EventSource.AGENT
            and hasattr(event, 'action')
            and event.action == ActionType.FINISH
        ):
            return True

        if (
            event.source == EventSource.AGENT
            and hasattr(event, 'action')
            and event.action == ActionType.MESSAGE
        ):
            return True

        return False

    def _find_task_chunks(self, view: View) -> List[Tuple[int, int]]:
        """Find chunks of completed tasks in the view.

        Each task starts with a user message and ends with an agent message.
        A valid chunk is from a user message to the next agent message (inclusive).

        Args:
            view: The view to analyze

        Returns:
            List of tuples (start_index, end_index) for each task chunk
        """
        task_chunks = []

        # Process each event to find user messages and their corresponding agent responses
        i = 0
        while i < len(view):
            event = view[i]

            # flag that this may start a new task
            if (
                event.source == EventSource.USER
                and hasattr(event, 'action')
                and event.action == ActionType.MESSAGE
            ):
                start_idx = i
                logger.info(
                    f'[TaskCompletionCondenser]: Potential chunk start found at index {i}, ID: {event.id}'
                )

                # Found the end of the task, may action finish of agent or agent message -> mean conclusion
                found_agent_message = False
                for j in range(i + 1, len(view)):
                    next_event = view[j]

                    if (
                        next_event.source == EventSource.AGENT
                        and hasattr(next_event, 'action')
                        and next_event.action == ActionType.MESSAGE
                    ) or (
                        next_event.source == EventSource.AGENT
                        and hasattr(next_event, 'action')
                        and next_event.action == ActionType.FINISH
                    ):
                        # Found an agent message, create a chunk
                        end_idx = j  # Include the agent message in the chunk
                        task_chunks.append((start_idx, end_idx))
                        logger.info(
                            f'[TaskCompletionCondenser]: Created chunk from index {start_idx} to {end_idx}'
                        )
                        found_agent_message = True
                        break

                if not found_agent_message:
                    logger.info(
                        f'[TaskCompletionCondenser]: No agent message found after user message at index {i}'
                    )

            i += 1

        logger.info(f'[TaskCompletionCondenser]: Found {len(task_chunks)} task chunks')
        logger.info(f'[TaskCompletionCondenser]: task_chunks={task_chunks}')

        return task_chunks

    def condense(self, view: View) -> View:
        """Create an optimized view that keeps only essential events.

        Args:
            view: The view to condense

        Returns:
            An optimized View containing only essential events
        """
        # Check if we should condense
        if not self.should_condense(view):
            return view

        task_chunks = self._find_task_chunks(view)

        kept_events = []

        # Keep track of event IDs to include (using event.id, not array indices)
        event_ids_to_keep = set()

        # Create a set of indices that are covered by task chunks
        covered_indices: set[int] = set()
        for start_idx, end_idx in task_chunks:
            covered_indices.update(range(start_idx, end_idx + 1))

        # Process each task chunk - only keep important events from completed tasks
        for start_idx, end_idx in task_chunks:
            chunk_events = view[start_idx : end_idx + 1]

            logger.info(
                f'[TaskCompletionCondenser]: Processing completed task chunk {start_idx}-{end_idx} with {len(chunk_events)} events'
            )

            # For completed task chunks, only keep important events
            for event in chunk_events:
                # Skip events with negative IDs (likely condensation events)
                if event.id < 0:
                    continue

                if self._is_important_event(event):
                    event_ids_to_keep.add(event.id)
                    logger.info(
                        f'[TaskCompletionCondenser]: Keeping important event ID {event.id} from completed task'
                    )

        # Process events outside task chunks - keep all of them (they might be pending tasks)
        for i, event in enumerate(view):
            if i not in covered_indices:
                # Skip events with negative IDs (likely condensation events)
                if event.id < 0:
                    continue

                event_ids_to_keep.add(event.id)
                logger.info(
                    f'[TaskCompletionCondenser]: Keeping event ID {event.id} outside task chunks (potential pending task)'
                )

        # Build the optimized events list using event IDs
        for event in view:
            if event.id in event_ids_to_keep:
                kept_events.append(event)

        # Record metadata about this condensation
        forgotten_count = len(view) - len(kept_events)
        self.add_metadata('forgotten_events_count', forgotten_count)
        self.add_metadata('kept_events_count', len(kept_events))
        self.add_metadata('task_chunks', len(task_chunks))

        logger.info(
            f'[TaskCompletionCondenser]: Condensed view from {len(view)} to {len(kept_events)} events'
        )

        logger.info(f'[TaskCompletionCondenser]: kept_events={kept_events}')

        return View(events=kept_events)

    @classmethod
    def from_config(
        cls, config: TaskCompletionCondenserConfig
    ) -> TaskCompletionCondenser:
        """Create a TaskCompletionCondenser from a configuration."""
        return TaskCompletionCondenser(**config.model_dump(exclude=['type']))

    def should_condense(self, view: View) -> bool:
        """Determine if the view should be condensed.

        The view should be condensed if there are completed task chunks.

        Args:
            view: The view to check

        Returns:
            True if the view should be condensed, False otherwise
        """

        logger.info(f'[TaskCompletionCondenser]: received view={view}')
        task_chunks = self._find_task_chunks(view)

        result = len(task_chunks) > 0
        logger.info(
            f'[TaskCompletionCondenser]: should_condense result={result} with {len(task_chunks)} chunks'
        )
        return result


# Register the configuration type
TaskCompletionCondenser.register_config(TaskCompletionCondenserConfig)
