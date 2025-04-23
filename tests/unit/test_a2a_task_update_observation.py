import asyncio
import shutil
from typing import Any, Dict
from unittest.mock import MagicMock

import pytest

from openhands.a2a.common.types import (
    TaskState,
)
from openhands.controller.agent import Agent
from openhands.controller.agent_controller import AgentController
from openhands.core.config import LLMConfig
from openhands.core.config.agent_config import AgentConfig
from openhands.core.schema import AgentState
from openhands.events import EventSource, EventStream
from openhands.events.action import MessageAction
from openhands.events.observation.a2a import A2ASendTaskUpdateObservation
from openhands.llm.metrics import Metrics
from openhands.memory.conversation_memory import ConversationMemory
from openhands.storage.memory import InMemoryFileStore
from openhands.utils.prompt import PromptManager


@pytest.fixture
def mock_agent():
    agent = MagicMock(spec=Agent)
    agent.name = 'TestAgent'
    agent.reset = MagicMock()
    agent.llm = MagicMock()
    agent.llm.metrics = Metrics()
    agent.llm.config = LLMConfig()
    agent.llm.config.max_message_chars = 1000
    agent.config = AgentConfig()
    return agent


@pytest.fixture
def mock_event_stream():
    stream = EventStream(sid='test-session', file_store=InMemoryFileStore())
    yield stream
    # Properly close the event stream to avoid thread issues during shutdown
    stream.close()


@pytest.fixture
def prompt_dir(tmp_path):
    # Copy contents from "openhands/agenthub/codeact_agent" to the temp directory
    shutil.copytree(
        'openhands/agenthub/codeact_agent/prompts', tmp_path, dirs_exist_ok=True
    )

    # Return the temporary directory path
    return tmp_path


@pytest.fixture
def agent_controller(mock_agent, mock_event_stream):
    controller = AgentController(
        agent=mock_agent,
        event_stream=mock_event_stream,
        max_iterations=10,
        sid='test-session',
    )
    yield controller
    # Properly close the controller to avoid thread issues during shutdown
    asyncio.get_event_loop().run_until_complete(controller.close(set_stop_state=False))


@pytest.fixture
def conversation_memory(mock_agent, prompt_dir):
    # Create a conversation memory with the agent config
    prompt_manager = PromptManager(prompt_dir=prompt_dir)
    return ConversationMemory(config=mock_agent.config, prompt_manager=prompt_manager)


def create_task_update_event(
    task_id: str = 'task123',
    state: TaskState = TaskState.WORKING,
    final: bool = False,
    message_text: str = 'Task update message',
) -> Dict[str, Any]:
    """Helper to create a task_update_event dictionary for testing"""
    # Create a dictionary representation of the task update event
    # This is what would come from the A2A API
    task_update_dict = {
        'id': task_id,
        'status': {
            'state': state.value,
            'message': {
                'role': 'agent',
                'parts': [
                    {
                        'type': 'text',
                        'text': message_text,
                        'metadata': {'timestamp': '2024-03-20T10:00:00'},
                    }
                ],
                'metadata': {'confidence': 0.9},
            },
            'timestamp': '2024-03-20T10:00:00',
        },
        'final': final,
        'metadata': {
            'priority': 1,
            'tags': ['test', 'update'],
        },
    }

    return task_update_dict


@pytest.mark.asyncio
async def test_handle_observation_input_required(agent_controller):
    """Test handling of A2ASendTaskUpdateObservation with INPUT_REQUIRED state"""
    task_update_event = create_task_update_event(state=TaskState.INPUT_REQUIRED)

    observation = A2ASendTaskUpdateObservation(
        content='Input required',
        task_update_event=task_update_event,
        agent_name='test_agent',
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
        content='Agent is working',
        task_update_event=task_update_event,
        agent_name='test_agent',
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
        content='Task failed',
        task_update_event=task_update_event,
        agent_name='test_agent',
    )

    # should_step should return True for FAILED state
    assert agent_controller.should_step(observation) is True


def test_should_step_working_state(agent_controller):
    """Test should_step returns False for WORKING state"""
    task_update_event = create_task_update_event(state=TaskState.WORKING, final=False)

    observation = A2ASendTaskUpdateObservation(
        content='Agent is working',
        task_update_event=task_update_event,
        agent_name='test_agent',
    )

    # should_step should return False for WORKING state
    assert agent_controller.should_step(observation) is False


def test_should_step_input_required(agent_controller):
    """Test should_step returns False for INPUT_REQUIRED state"""
    task_update_event = create_task_update_event(
        state=TaskState.INPUT_REQUIRED, final=False
    )

    observation = A2ASendTaskUpdateObservation(
        content='Input required',
        task_update_event=task_update_event,
        agent_name='test_agent',
    )

    # should_step should return False for INPUT_REQUIRED state
    assert agent_controller.should_step(observation) is False


def test_should_step_final_true(agent_controller):
    """Test should_step returns TaskEventHandler.should_step_on_task_update(event) when final=True"""
    # Create event with final=True
    task_update_event = create_task_update_event(state=TaskState.COMPLETED, final=True)

    observation = A2ASendTaskUpdateObservation(
        content='Task completed',
        task_update_event=task_update_event,
        agent_name='test_agent',
    )

    # We expect should_step to return True for final=True
    assert agent_controller.should_step(observation) is True


def test_should_step_delegate_controller(
    agent_controller, mock_agent, mock_event_stream
):
    """Test should_step returns False when there's a delegate controller"""
    # Create a delegate controller
    delegate = AgentController(
        agent=mock_agent,
        event_stream=mock_event_stream,
        max_iterations=10,
        sid='delegate-session',
        is_delegate=True,
    )

    # Set the delegate
    agent_controller.delegate = delegate

    task_update_event = create_task_update_event(state=TaskState.FAILED, final=False)

    observation = A2ASendTaskUpdateObservation(
        content='Task failed',
        task_update_event=task_update_event,
        agent_name='test_agent',
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
        content='Input required',
        task_update_event=task_update_event,
        agent_name='test_agent',
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


@pytest.mark.asyncio
async def test_input_required_followed_by_user_response(
    agent_controller, mock_event_stream, conversation_memory
):
    """Test the conversation flow of task requiring input followed by user's response"""
    # Step 1: Set up initial agent state to RUNNING
    await agent_controller.set_agent_state_to(AgentState.RUNNING)

    # Step 2: Send an INPUT_REQUIRED task update
    task_update_event = create_task_update_event(
        state=TaskState.INPUT_REQUIRED,
        message_text='Please provide additional information for this task',
    )

    input_required_observation = A2ASendTaskUpdateObservation(
        content='Please provide additional information for this task',
        task_update_event=task_update_event,
        agent_name='test_agent',
    )

    # Process the input required observation
    await agent_controller._on_event(input_required_observation)

    # Verify state changed to AWAITING_USER_INPUT
    assert agent_controller.get_agent_state() == AgentState.AWAITING_USER_INPUT

    # Step 3: User responds with a message
    user_message = MessageAction(
        content="Here's the additional information you requested"
    )

    # Add the user message to the event stream with the source USER and process it via _on_event
    mock_event_stream.add_event(user_message, EventSource.USER)

    # Process the user message using on_event which will add it to history
    await agent_controller._on_event(user_message)

    # Verify the agent state was set back to RUNNING
    assert agent_controller.get_agent_state() == AgentState.RUNNING

    # Step 4: Verify that both messages are in the history in the correct order
    history_events = agent_controller.state.history

    # Find the input required message and user response in history
    input_required_in_history = False
    user_response_in_history = False
    input_required_index = -1
    user_response_index = -1

    for i, event in enumerate(history_events):
        if (
            isinstance(event, A2ASendTaskUpdateObservation)
            and event.content == input_required_observation.content
        ):
            input_required_in_history = True
            input_required_index = i
        elif isinstance(event, MessageAction) and event.content == user_message.content:
            user_response_in_history = True
            user_response_index = i

    # Verify both messages are in history
    assert input_required_in_history, 'Input required message not found in history'
    assert user_response_in_history, 'User response not found in history'

    # Verify the order is correct (input required followed by user response)
    assert (
        input_required_index < user_response_index
    ), 'Messages are not in the correct order'

    # Verify there's no duplicate entries of these messages
    input_required_count = sum(
        1
        for e in history_events
        if isinstance(e, A2ASendTaskUpdateObservation)
        and e.content == input_required_observation.content
    )
    user_response_count = sum(
        1
        for e in history_events
        if isinstance(e, MessageAction) and e.content == user_message.content
    )

    assert (
        input_required_count == 1
    ), 'Input required message appears multiple times in history'
    assert (
        user_response_count == 1
    ), 'User response should appear exactly once in history'

    # Step 5: Verify ConversationMemory processes the events correctly
    # Process the observation through ConversationMemory
    tool_call_id_to_message = {}
    observation_messages = conversation_memory._process_observation(
        obs=input_required_observation,
        tool_call_id_to_message=tool_call_id_to_message,
        max_message_chars=None,
    )

    # Verify the input required observation was properly processed into a message
    assert len(observation_messages) == 1
    assert observation_messages[0].role == 'assistant'
    assert any(
        content.text == input_required_observation.content
        for content in observation_messages[0].content
    )

    # Process the user message action through ConversationMemory
    action_messages = conversation_memory._process_action(
        action=user_message, pending_tool_call_action_messages={}
    )

    # Verify the user message was properly processed
    assert len(action_messages) == 1
    assert action_messages[0].role == 'user'
    assert any(
        content.text == user_message.content for content in action_messages[0].content
    )

    # Verify the conversation flow by processing the history events in order
    messages = []

    # First, process the observation
    for msg in observation_messages:
        messages.append(msg)

    # Then, process the user's response
    for msg in action_messages:
        messages.append(msg)

    # Verify the correct conversation flow
    assert len(messages) == 2
    assert any(
        content.text == input_required_observation.content
        for content in messages[0].content
    )
    assert any(content.text == user_message.content for content in messages[1].content)
    assert messages[0].role == 'assistant'
    assert messages[1].role == 'user'
