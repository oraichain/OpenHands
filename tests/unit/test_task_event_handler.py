import pytest
import copy
from typing import Dict

from openhands.a2a.common.types import (
    Message,
    TaskState,
    TaskStatus,
    TaskStatusUpdateEvent,
    TextPart,
)
from openhands.a2a.task_event_handler import TaskEventHandler
from openhands.events.observation.a2a import A2ASendTaskUpdateObservation


def create_task_update_observation(
    task_id: str = "task123",
    state: TaskState = TaskState.WORKING,
    final: bool = False,
    message_text: str = "Task update message",
) -> A2ASendTaskUpdateObservation:
    """Helper to create an A2ASendTaskUpdateObservation for testing"""
    text_part = TextPart(
        text=message_text,
        metadata={"timestamp": "2024-03-20T10:00:00"}
    )
    
    message = Message(
        role="agent",
        parts=[text_part],
        metadata={"confidence": 0.9}
    )
    
    task_status = TaskStatus(
        state=state,
        message=message,
    )
    
    task_update_event = TaskStatusUpdateEvent(
        id=task_id,
        status=task_status,
        final=final,
        metadata={
            "priority": 1,
            "tags": ["test", "update"],
        },
    )
    
    # Convert to dictionary to match how it's used in the actual code
    task_update_dict = {
        "id": task_id,
        "status": {
            "state": state.value,
            "message": {
                "role": "agent",
                "parts": [
                    {
                        "type": "text",
                        "text": message_text,
                        "metadata": {"timestamp": "2024-03-20T10:00:00"}
                    }
                ],
                "metadata": {"confidence": 0.9}
            },
            "timestamp": task_status.timestamp.isoformat()
        },
        "final": final,
        "metadata": {
            "priority": 1,
            "tags": ["test", "update"],
        }
    }
    
    return A2ASendTaskUpdateObservation(
        content="Task update",
        task_update_event=task_update_dict,
        agent_name="test_agent",
    )


def test_should_step_on_task_update_final_true():
    """Test that should_step_on_task_update returns True when final is True"""
    observation = create_task_update_observation(
        state=TaskState.COMPLETED, 
        final=True
    )
    
    result = TaskEventHandler.should_step_on_task_update(observation)
    
    assert result is True


def test_should_step_on_task_update_failed_state():
    """Test that should_step_on_task_update returns True for FAILED state"""
    observation = create_task_update_observation(
        state=TaskState.FAILED, 
        final=False
    )
    
    result = TaskEventHandler.should_step_on_task_update(observation)
    
    assert result is True


def test_should_step_on_task_update_non_action_states():
    """Test that should_step_on_task_update returns False for states that don't require action"""
    # Test all states that should return False
    non_action_states = [
        TaskState.SUBMITTED,
        TaskState.WORKING,
        TaskState.COMPLETED,
        TaskState.UNKNOWN,
        TaskState.INPUT_REQUIRED,
        TaskState.CANCELED,
    ]
    
    for state in non_action_states:
        observation = create_task_update_observation(
            state=state, 
            final=False
        )
        
        result = TaskEventHandler.should_step_on_task_update(observation)
        
        assert result is False, f"Expected False for state {state}, but got {result}"


def test_handle_observation_input_required_with_message():
    """Test handle_observation returns message text for INPUT_REQUIRED state with a message"""
    observation = create_task_update_observation(
        state=TaskState.INPUT_REQUIRED,
        message_text="Please provide more information"
    )
    
    result = TaskEventHandler.handle_observation(observation)
    
    assert result == "Please provide more information"


def test_handle_observation_input_required_without_message():
    """Test handle_observation returns None for INPUT_REQUIRED state without a message"""
    # Create a dictionary representation of TaskStatusUpdateEvent with null message
    task_update_dict = {
        "id": "task123",
        "status": {
            "state": TaskState.INPUT_REQUIRED.value,
            "message": None,
            "timestamp": "2024-03-20T10:00:00"
        },
        "final": False,
        "metadata": {}
    }
    
    observation = A2ASendTaskUpdateObservation(
        content="Task update",
        task_update_event=task_update_dict,
        agent_name="test_agent",
    )
    
    result = TaskEventHandler.handle_observation(observation)
    
    assert result is None


def test_handle_observation_non_input_required_states():
    """Test handle_observation returns None for states other than INPUT_REQUIRED"""
    non_input_states = [
        TaskState.SUBMITTED,
        TaskState.WORKING,
        TaskState.COMPLETED,
        TaskState.UNKNOWN,
        TaskState.FAILED,
        TaskState.CANCELED,
    ]
    
    for state in non_input_states:
        observation = create_task_update_observation(
            state=state,
            final=False
        )
        
        result = TaskEventHandler.handle_observation(observation)
        
        assert result is None, f"Expected None for state {state}, but got {result}"


def test_handle_observation_final_true():
    """Test handle_observation returns None when final is True"""
    observation = create_task_update_observation(
        state=TaskState.COMPLETED,
        final=True
    )
    
    result = TaskEventHandler.handle_observation(observation)
    
    assert result is None 