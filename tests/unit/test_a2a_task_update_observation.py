import pytest
from typing import Any, Dict
from unittest.mock import MagicMock

from openhands.a2a.common.types import (
    TaskState,
)
from openhands.controller.agent import Agent
from openhands.controller.agent_controller import AgentController
from openhands.controller.state.state import State
from openhands.core.config import LLMConfig
from openhands.core.schema import AgentState
from openhands.events import EventSource, EventStream
from openhands.events.observation.a2a import A2ASendTaskUpdateObservation
from openhands.llm.metrics import Metrics
from openhands.storage.memory import InMemoryFileStore


@pytest.fixture
def mock_agent():
    agent = MagicMock(spec=Agent)
    agent.name = "TestAgent"
    agent.reset = MagicMock()
    agent.llm = MagicMock()
    agent.llm.metrics = Metrics()
    agent.llm.config = LLMConfig()
    agent.llm.config.max_message_chars = 1000
    return agent


@pytest.fixture
def mock_event_stream():
    stream = EventStream(sid="test-session", file_store=InMemoryFileStore())
    return stream


@pytest.fixture
def agent_controller(mock_agent, mock_event_stream):
    controller = AgentController(
        agent=mock_agent,
        event_stream=mock_event_stream,
        max_iterations=10,
        sid="test-session",
    )
    return controller


def create_task_update_event(
    task_id: str = "task123", 
    state: TaskState = TaskState.WORKING, 
    final: bool = False, 
    message_text: str = "Task update message"
) -> Dict[str, Any]:
    """Helper to create a task_update_event dictionary for testing"""
    # Create a dictionary representation of the task update event
    # This is what would come from the A2A API
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
            "timestamp": "2024-03-20T10:00:00"
        },
        "final": final,
        "metadata": {
            "priority": 1,
            "tags": ["test", "update"],
        }
    }
    
    return task_update_dict


@pytest.mark.asyncio
async def test_handle_observation_input_required(agent_controller):
    """Test handling of A2ASendTaskUpdateObservation with INPUT_REQUIRED state"""
    task_update_event = create_task_update_event(state=TaskState.INPUT_REQUIRED)
    
    observation = A2ASendTaskUpdateObservation(
        content="Input required",
        task_update_event=task_update_event,
        agent_name="test_agent",
    )
    
    # Set initial state to RUNNING
    await agent_controller.set_agent_state_to(AgentState.RUNNING)
    
    # Handle the observation
    await agent_controller._handle_observation(observation)
    
    # Verify the agent state changed to AWAITING_USER_INPUT
    assert agent_controller.get_agent_state() == AgentState.AWAITING_USER_INPUT


@pytest.mark.asyncio
async def test_handle_observation_other_states(agent_controller):
    """Test handling of A2ASendTaskUpdateObservation with other states"""
    # Test with WORKING state
    task_update_event = create_task_update_event(state=TaskState.WORKING)
    
    observation = A2ASendTaskUpdateObservation(
        content="Agent is working",
        task_update_event=task_update_event,
        agent_name="test_agent",
    )
    
    # Set initial state to RUNNING
    await agent_controller.set_agent_state_to(AgentState.RUNNING)
    
    # Handle the observation
    await agent_controller._handle_observation(observation)
    
    # Verify the agent state remains RUNNING (unchanged)
    assert agent_controller.get_agent_state() == AgentState.RUNNING


def test_should_step_failed_state(agent_controller):
    """Test should_step returns True for FAILED state"""
    task_update_event = create_task_update_event(state=TaskState.FAILED, final=False)
    
    observation = A2ASendTaskUpdateObservation(
        content="Task failed",
        task_update_event=task_update_event,
        agent_name="test_agent",
    )
    
    # should_step should return True for FAILED state
    assert agent_controller.should_step(observation) is True


def test_should_step_working_state(agent_controller):
    """Test should_step returns False for WORKING state"""
    task_update_event = create_task_update_event(state=TaskState.WORKING, final=False)
    
    observation = A2ASendTaskUpdateObservation(
        content="Agent is working",
        task_update_event=task_update_event,
        agent_name="test_agent",
    )
    
    # should_step should return False for WORKING state
    assert agent_controller.should_step(observation) is False


def test_should_step_input_required(agent_controller):
    """Test should_step returns False for INPUT_REQUIRED state"""
    task_update_event = create_task_update_event(state=TaskState.INPUT_REQUIRED, final=False)
    
    observation = A2ASendTaskUpdateObservation(
        content="Input required",
        task_update_event=task_update_event,
        agent_name="test_agent",
    )
    
    # should_step should return False for INPUT_REQUIRED state
    assert agent_controller.should_step(observation) is False


def test_should_step_final_true(agent_controller):
    """Test should_step returns TaskEventHandler.should_step_on_task_update(event) when final=True"""
    # Create event with final=True
    task_update_event = create_task_update_event(state=TaskState.COMPLETED, final=True)
    
    observation = A2ASendTaskUpdateObservation(
        content="Task completed",
        task_update_event=task_update_event,
        agent_name="test_agent",
    )
    
    # We expect should_step to return True for final=True
    assert agent_controller.should_step(observation) is True


def test_should_step_delegate_controller(agent_controller, mock_agent, mock_event_stream):
    """Test should_step returns False when there's a delegate controller"""
    # Create a delegate controller
    delegate = AgentController(
        agent=mock_agent,
        event_stream=mock_event_stream,
        max_iterations=10,
        sid="delegate-session",
        is_delegate=True,
    )
    
    # Set the delegate
    agent_controller.delegate = delegate
    
    task_update_event = create_task_update_event(state=TaskState.FAILED, final=False)
    
    observation = A2ASendTaskUpdateObservation(
        content="Task failed",
        task_update_event=task_update_event,
        agent_name="test_agent",
    )
    
    # should_step should return False when there's a delegate
    assert agent_controller.should_step(observation) is False


@pytest.mark.asyncio
async def test_observation_event_interaction(agent_controller, mock_event_stream):
    """Test the full interaction between observation events and agent controller"""
    # Mock the event stream's add_event method to track events
    original_add_event = mock_event_stream.add_event
    added_events = []
    
    def mock_add_event(event, source):
        added_events.append((event, source))
        original_add_event(event, source)
    
    mock_event_stream.add_event = mock_add_event
    
    # Create an observation with INPUT_REQUIRED
    task_update_event = create_task_update_event(state=TaskState.INPUT_REQUIRED)
    
    observation = A2ASendTaskUpdateObservation(
        content="Input required",
        task_update_event=task_update_event,
        agent_name="test_agent",
    )
    
    # Set initial state to RUNNING
    await agent_controller.set_agent_state_to(AgentState.RUNNING)
    
    # Process the event
    await agent_controller._on_event(observation)
    
    # Verify state changed to AWAITING_USER_INPUT
    assert agent_controller.get_agent_state() == AgentState.AWAITING_USER_INPUT
    
    # Verify the event was added to the history
    assert observation in agent_controller.state.history
    
    # Verify state change events were added (two state changes occur)
    # First change: LOADING → RUNNING
    # Second change: RUNNING → AWAITING_USER_INPUT
    assert len(added_events) == 2
    
    # Reset mock
    mock_event_stream.add_event = original_add_event 