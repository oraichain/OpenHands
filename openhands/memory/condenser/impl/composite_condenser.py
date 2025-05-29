from __future__ import annotations

from openhands.core.config.condenser_config import (
    TaskCompletionBrowserCondenserConfig,
)
from openhands.core.logger import openhands_logger as logger
from openhands.memory.condenser.condenser import Condensation, Condenser, View
from openhands.memory.condenser.impl.browser_output_condenser import (
    BrowserOutputCondenser,
)
from openhands.memory.condenser.impl.task_completion_condenser import (
    TaskCompletionCondenser,
)


class TaskCompletionBrowserCondenser(Condenser):
    """A composite condenser that applies both TaskCompletion and BrowserOutput condensation.

    This condenser:
    1. First applies TaskCompletionCondenser logic to keep only essential events for completed tasks
    2. Then applies BrowserOutputCondenser logic to mask older browser observations

    This combination is useful when you want to:
    - Keep only important events from completed tasks (reports, conclusions, etc.)
    - Reduce token usage from large browser observations (screenshots, accessibility trees)
    """

    def __init__(self, keep_first: int = 1, browser_attention_window: int = 1):
        """Initialize the composite condenser.

        Args:
            keep_first: Number of initial events to always keep (typically the user's task)
            browser_attention_window: Number of recent browser observations to keep in full detail
        """
        self.task_condenser = TaskCompletionCondenser(keep_first=keep_first)
        self.browser_condenser = BrowserOutputCondenser(
            attention_window=browser_attention_window
        )

        logger.info('[TaskCompletionBrowserCondenser]: Initialize successfully')
        super().__init__()

    def condense(self, view: View) -> View | Condensation:
        """Apply both condensation strategies sequentially.

        Args:
            view: The view to condense

        Returns:
            A condensed view with both task completion and browser output condensation applied
        """
        logger.info(
            f'[TaskCompletionBrowserCondenser]: Starting condensation with {len(view)} events'
        )

        # Step 1: Apply task completion condensation
        task_result = self.task_condenser.condense(view)

        # Handle case where task condenser returns a Condensation instead of View
        if isinstance(task_result, Condensation):
            logger.info(
                '[TaskCompletionBrowserCondenser]: Task condenser returned Condensation, returning as-is'
            )
            return task_result

        logger.info(
            f'[TaskCompletionBrowserCondenser]: After task condensation: {len(task_result)} events'
        )

        # Step 2: Apply browser output condensation to the task-condensed view
        browser_result = self.browser_condenser.condense(task_result)

        # Handle case where browser condenser returns a Condensation instead of View
        if isinstance(browser_result, Condensation):
            logger.info(
                '[TaskCompletionBrowserCondenser]: Browser condenser returned Condensation, returning as-is'
            )
            return browser_result

        logger.info(
            f'[TaskCompletionBrowserCondenser]: After browser condensation: {len(browser_result)} events'
        )

        # Record metadata about this condensation
        original_count = len(view)
        final_count = len(browser_result)
        forgotten_count = original_count - final_count

        self.add_metadata('original_events_count', original_count)
        self.add_metadata('final_events_count', final_count)
        self.add_metadata('forgotten_events_count', forgotten_count)
        self.add_metadata('task_condenser_applied', True)
        self.add_metadata('browser_condenser_applied', True)

        logger.info(
            f'[TaskCompletionBrowserCondenser]: Condensed view from {original_count} to {final_count} events'
        )

        return browser_result

    @classmethod
    def from_config(
        cls, config: TaskCompletionBrowserCondenserConfig
    ) -> TaskCompletionBrowserCondenser:
        """Create a TaskCompletionBrowserCondenser from a configuration."""
        return TaskCompletionBrowserCondenser(
            keep_first=config.keep_first,
            browser_attention_window=config.browser_attention_window,
        )


# Register the configuration type
TaskCompletionBrowserCondenser.register_config(TaskCompletionBrowserCondenserConfig)
