from dataclasses import dataclass
from typing import Optional

from openhands.core.schema import ActionType
from openhands.events.action.action import Action, ActionSecurityRisk


@dataclass
class HumanFeedbackAction(Action):
    """Action to request additional information from user about their initial prompt."""

    human_feedback_questions: str
    original_prompt: str
    wait_for_response: bool = False
    action: str = ActionType.HUMAN_FEEDBACK
    security_risk: Optional[ActionSecurityRisk] = None
    mode: Optional[str] = None
    enable_think: bool = False

    @property
    def message(self) -> str:
        return self.human_feedback_questions

    def __str__(self) -> str:
        ret = f'**HumanFeedbackAction** (source={self.source})\n'
        ret += f'CONTENT: {self.human_feedback_questions}'
        return ret
