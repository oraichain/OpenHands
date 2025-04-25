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
    action: str = ActionType.ORCHESTRATOR_INITIALIZATION

    @property
    def message(self) -> str:
        return f'Initialized orchestrator for task: {self.task}'


@dataclass
class GatheringFactsAction(Action):
    """Action indicating the orchestrator agent is gathering facts about the task."""
    task: str
    action: str = ActionType.GATHERING_FACTS

    @property
    def message(self) -> str:
        return f'Gathering facts about task: {self.task}'


@dataclass
class CreatingPlanAction(Action):
    """Action indicating the orchestrator agent is creating a plan for the task."""
    task: str
    facts: str
    action: str = ActionType.CREATING_PLAN

    @property
    def message(self) -> str:
        return f'Creating plan for task: {self.task}'


@dataclass
class UpdatingKnowledgeAction(Action):
    """Action indicating the orchestrator agent is updating its knowledge (facts and plan)."""
    task: str
    current_facts: str
    current_plan: str
    action: str = ActionType.UPDATING_KNOWLEDGE

    @property
    def message(self) -> str:
        return f'Updating knowledge for task: {self.task}'


@dataclass
class FinalAnswerAction(Action):
    """Action indicating the orchestrator agent is generating the final answer."""
    task: str
    action: str = ActionType.FINAL_ANSWER

    @property
    def message(self) -> str:
        return f'Generating final answer for task: {self.task}'


@dataclass
class OrchestratorInitializeObservation(Action):
    """Observation containing the full ledger prompt after orchestrator initialization."""
    task: str
    facts: str
    plan: str
    team: str
    full_ledger: str
    action: str = ActionType.ORCHESTRATOR_INITIALIZE_OBSERVATION

    @property
    def message(self) -> str:
        return f'Full ledger for task: {self.task}' 