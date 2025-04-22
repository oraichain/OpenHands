from openhands.a2a.common.types import TaskState, TaskStatusUpdateEvent
from openhands.events.observation.a2a import A2ASendTaskUpdateObservation


class TaskEventHandler:
    @staticmethod
    def should_step_on_task_update(event: A2ASendTaskUpdateObservation) -> bool:
        task_update_event = TaskStatusUpdateEvent(**event.task_update_event)
        if task_update_event.final:
            return True
        state = task_update_event.status.state
        match state:
            case TaskState.SUBMITTED:
                return False
            case TaskState.WORKING:
                return False
            case TaskState.COMPLETED:
                return False
            case TaskState.UNKNOWN:
                return False
            case TaskState.INPUT_REQUIRED:
                return False
            case TaskState.CANCELED:
                return False
            case TaskState.FAILED:
                return True

    @staticmethod
    def handle_observation(event: A2ASendTaskUpdateObservation) -> str | None:
        task_update_event = TaskStatusUpdateEvent(**event.task_update_event)
        if task_update_event.final:
            return None
        state = task_update_event.status.state
        match state:
            case TaskState.SUBMITTED:
                return None
            case TaskState.WORKING:
                return None
            case TaskState.COMPLETED:
                return None
            case TaskState.UNKNOWN:
                return None
            case TaskState.CANCELED:
                return None
            case TaskState.FAILED:
                return None
            case TaskState.INPUT_REQUIRED:
                if task_update_event.status.message is not None:
                    return f'{event.agent_name}: {task_update_event.status.message.parts[0].text}'
                return None
