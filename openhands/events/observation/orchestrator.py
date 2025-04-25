from dataclasses import dataclass

from openhands.core.schema import ObservationType
from openhands.events.observation.observation import Observation


@dataclass
class OrchestratorInitializeObservation(Observation):
    """Observation containing the full ledger prompt after orchestrator initialization."""
    task: str
    facts: str
    plan: str
    team: str
    full_ledger: str
    content: str
    observation: str = ObservationType.ORCHESTRATOR_INITIALIZE_OBSERVATION

    @property
    def message(self) -> str:
        return self.content

@dataclass
class OrchestratorFinalObservation(Observation):
    """Observation containing the final answer from the orchestrator."""
    task: str
    content: str
    observation: str = ObservationType.ORCHESTRATOR_FINAL_OBSERVATION

    @property
    def message(self) -> str:
        return self.content
