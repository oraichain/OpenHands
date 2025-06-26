from dataclasses import dataclass

from openhands.core.schema import ActionType
from openhands.events.action.action import Action, ActionSecurityRisk


@dataclass
class PlanningAction(Action):
    content: str
    wait_for_response: bool = False
    action: str = ActionType.PLANNING
    security_risk: ActionSecurityRisk | None = None
    mode: str | None = None

    @property
    def message(self) -> str:
        return self.content

    def __str__(self) -> str:
        ret = f'**PlanningAction** (source={self.source})\n'
        ret += f'CONTENT: {self.content}'
        return ret
