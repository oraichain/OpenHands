from dataclasses import dataclass
from typing import Any

from openhands.core.schema import ObservationType
from openhands.events.observation.observation import Observation


@dataclass
class PlanStatusObservation(Observation):
    """This data class represents the status of the plan"""

    status: dict[str, Any]
    observation: str = ObservationType.PLAN_STATUS

    @property
    def message(self) -> str:
        return self.content
