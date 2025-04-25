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
    observation: str = ObservationType.ORCHESTRATOR_INITIALIZE_OBSERVATION

    @property
    def content(self) -> str:
        return self.full_ledger 