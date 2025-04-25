from dataclasses import dataclass

from openhands.core.schema import ActionType
from openhands.events.action.action import Action


@dataclass
class OrchestratorInitializationAction(Action):
    """Action indicating the orchestrator agent has completed initialization with facts and plan."""
    task: str
    facts: str
    plan: str
    team: str
    full_ledger: str
    action: str = ActionType.ORCHESTRATOR_INITIALIZATION

    @property
    def message(self) -> str:
        return f'Initialized orchestrator for task: {self.task}'

@dataclass
class OrchestratorFinalAnswerAction(Action):
    """Action indicating the orchestrator agent has completed the task and is providing the final answer."""
    task: str
    reason: str
    action: str = ActionType.ORCHESTRATOR_FINAL_ANSWER

    @property
    def message(self) -> str:
        return f'Final answer for task: {self.task}'
