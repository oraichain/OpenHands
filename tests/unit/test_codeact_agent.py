from unittest.mock import Mock

import pytest
from litellm import ChatCompletionMessageToolCall, ModelResponse

from openhands.agenthub.codeact_agent.codeact_agent import CodeActAgent
from openhands.agenthub.codeact_agent.function_calling import (
    BrowserTool,
    IPythonTool,
    LLMBasedFileEditTool,
    WebReadTool,
    create_cmd_run_tool,
    create_str_replace_editor_tool,
    get_tools,
    response_to_actions,
)
from openhands.agenthub.codeact_agent.tools.browser import (
    _BROWSER_DESCRIPTION,
    _BROWSER_TOOL_DESCRIPTION,
)
from openhands.controller.state.state import State
from openhands.core.config import AgentConfig, LLMConfig
from openhands.core.exceptions import FunctionCallNotExistsError
from openhands.core.message import ImageContent, Message, TextContent
from openhands.events.action import (
    CmdRunAction,
    MessageAction,
)
from openhands.events.event import EventSource
from openhands.events.observation.commands import (
    CmdOutputObservation,
)
from openhands.events.tool import ToolCallMetadata
from openhands.llm.llm import LLM


@pytest.fixture
def agent() -> CodeActAgent:
    config = AgentConfig()
    agent = CodeActAgent(llm=LLM(LLMConfig()), config=config)
    agent.llm = Mock()
    agent.llm.config = Mock()
    agent.llm.config.max_message_chars = 1000
    return agent


@pytest.fixture
def mock_state() -> State:
    state = Mock(spec=State)
    state.history = []
    state.extra_data = {}

    return state


def test_reset(agent: CodeActAgent):
    # Add some state
    action = MessageAction(content='test')
    action._source = EventSource.AGENT
    agent.pending_actions.append(action)

    # Reset
    agent.reset()

    # Verify state is cleared
    assert len(agent.pending_actions) == 0


def test_step_with_pending_actions(agent: CodeActAgent):
    # Add a pending action
    pending_action = MessageAction(content='test')
    pending_action._source = EventSource.AGENT
    agent.pending_actions.append(pending_action)

    # Step should return the pending action
    result = agent.step(Mock())
    assert result == pending_action
    assert len(agent.pending_actions) == 0


def test_get_tools_default():
    tools = get_tools(
        codeact_enable_jupyter=True,
        codeact_enable_llm_editor=True,
        codeact_enable_browsing=True,
    )
    assert len(tools) > 0

    # Check required tools are present
    tool_names = [tool['function']['name'] for tool in tools]
    assert 'execute_bash' in tool_names
    assert 'execute_ipython_cell' in tool_names
    assert 'edit_file' in tool_names
    assert 'web_read' in tool_names


def test_get_tools_with_options():
    # Test with all options enabled
    tools = get_tools(
        codeact_enable_browsing=True,
        codeact_enable_jupyter=True,
        codeact_enable_llm_editor=True,
    )
    tool_names = [tool['function']['name'] for tool in tools]
    assert 'browser' in tool_names
    assert 'execute_ipython_cell' in tool_names
    assert 'edit_file' in tool_names

    # Test with all options disabled
    tools = get_tools(
        codeact_enable_browsing=False,
        codeact_enable_jupyter=False,
        codeact_enable_llm_editor=False,
    )
    tool_names = [tool['function']['name'] for tool in tools]
    assert 'browser' not in tool_names
    assert 'execute_ipython_cell' not in tool_names
    assert 'edit_file' not in tool_names


def test_cmd_run_tool():
    CmdRunTool = create_cmd_run_tool()
    assert CmdRunTool['type'] == 'function'
    assert CmdRunTool['function']['name'] == 'execute_bash'
    assert 'command' in CmdRunTool['function']['parameters']['properties']
    assert CmdRunTool['function']['parameters']['required'] == ['command']


def test_ipython_tool():
    assert IPythonTool['type'] == 'function'
    assert IPythonTool['function']['name'] == 'execute_ipython_cell'
    assert 'code' in IPythonTool['function']['parameters']['properties']
    assert IPythonTool['function']['parameters']['required'] == ['code']


def test_llm_based_file_edit_tool():
    assert LLMBasedFileEditTool['type'] == 'function'
    assert LLMBasedFileEditTool['function']['name'] == 'edit_file'

    properties = LLMBasedFileEditTool['function']['parameters']['properties']
    assert 'path' in properties
    assert 'content' in properties
    assert 'start' in properties
    assert 'end' in properties

    assert LLMBasedFileEditTool['function']['parameters']['required'] == [
        'path',
        'content',
    ]


def test_str_replace_editor_tool():
    StrReplaceEditorTool = create_str_replace_editor_tool()
    assert StrReplaceEditorTool['type'] == 'function'
    assert StrReplaceEditorTool['function']['name'] == 'str_replace_editor'

    properties = StrReplaceEditorTool['function']['parameters']['properties']
    assert 'command' in properties
    assert 'path' in properties
    assert 'file_text' in properties
    assert 'old_str' in properties
    assert 'new_str' in properties
    assert 'insert_line' in properties
    assert 'view_range' in properties

    assert StrReplaceEditorTool['function']['parameters']['required'] == [
        'command',
        'path',
    ]


def test_web_read_tool():
    assert WebReadTool['type'] == 'function'
    assert WebReadTool['function']['name'] == 'web_read'
    assert 'url' in WebReadTool['function']['parameters']['properties']
    assert WebReadTool['function']['parameters']['required'] == ['url']


def test_browser_tool():
    assert BrowserTool['type'] == 'function'
    assert BrowserTool['function']['name'] == 'browser'
    assert 'code' in BrowserTool['function']['parameters']['properties']
    assert BrowserTool['function']['parameters']['required'] == ['code']
    # Check that the description includes all the functions
    description = _BROWSER_TOOL_DESCRIPTION
    assert 'goto(' in description
    assert 'go_back()' in description
    assert 'go_forward()' in description
    assert 'noop(' in description
    assert 'scroll(' in description
    assert 'fill(' in description
    assert 'select_option(' in description
    assert 'click(' in description
    assert 'dblclick(' in description
    assert 'hover(' in description
    assert 'press(' in description
    assert 'focus(' in description
    assert 'clear(' in description
    assert 'drag_and_drop(' in description
    assert 'upload_file(' in description

    # Test BrowserTool definition
    assert BrowserTool['type'] == 'function'
    assert BrowserTool['function']['name'] == 'browser'
    assert BrowserTool['function']['description'] == _BROWSER_DESCRIPTION
    assert BrowserTool['function']['parameters']['type'] == 'object'
    assert 'code' in BrowserTool['function']['parameters']['properties']
    assert BrowserTool['function']['parameters']['required'] == ['code']
    assert (
        BrowserTool['function']['parameters']['properties']['code']['type'] == 'string'
    )
    assert 'description' in BrowserTool['function']['parameters']['properties']['code']


def test_response_to_actions_invalid_tool():
    # Test response with invalid tool call
    mock_response = ModelResponse(
        id='mock-id',
        choices=[
            {
                'message': {
                    'content': 'Invalid tool',
                    'tool_calls': [
                        {
                            'id': 'tool_call_10',
                            'function': {'name': 'invalid_tool', 'arguments': '{}'},
                        }
                    ],
                }
            }
        ],
    )

    with pytest.raises(FunctionCallNotExistsError):
        response_to_actions(mock_response)


def test_step_with_no_pending_actions(mock_state: State):
    # Mock the LLM response
    mock_response = Mock()
    mock_response.id = 'mock_id'
    mock_response.total_calls_in_response = 1
    mock_response.choices = [Mock()]
    mock_response.choices[0].message = Mock()
    mock_response.choices[0].message.content = 'Task completed'
    mock_response.choices[0].message.tool_calls = []

    mock_config = Mock()
    mock_config.model = 'mock_model'

    llm = Mock()
    llm.config = mock_config
    llm.completion = Mock(return_value=mock_response)
    llm.is_function_calling_active = Mock(return_value=True)  # Enable function calling
    llm.is_caching_prompt_active = Mock(return_value=False)

    # Create agent with mocked LLM
    config = AgentConfig()
    config.enable_prompt_extensions = False
    agent = CodeActAgent(llm=llm, config=config)

    # Test step with no pending actions
    mock_state.latest_user_message = None
    mock_state.latest_user_message_id = None
    mock_state.latest_user_message_timestamp = None
    mock_state.latest_user_message_cause = None
    mock_state.latest_user_message_timeout = None
    mock_state.latest_user_message_llm_metrics = None
    mock_state.latest_user_message_tool_call_metadata = None

    action = agent.step(mock_state)
    assert isinstance(action, MessageAction)
    assert action.content == 'Task completed'


def test_correct_tool_description_loaded_based_on_model_name(mock_state: State):
    """Tests that the simplified tool descriptions are loaded for specific models."""
    o3_mock_config = Mock()
    o3_mock_config.model = 'mock_o3_model'

    llm = Mock()
    llm.config = o3_mock_config

    agent = CodeActAgent(llm=llm, config=AgentConfig())
    for tool in agent.tools:
        # Assert all descriptions have less than 1024 characters
        assert len(tool['function']['description']) < 1024

    sonnet_mock_config = Mock()
    sonnet_mock_config.model = 'mock_sonnet_model'

    llm.config = sonnet_mock_config
    agent = CodeActAgent(llm=llm, config=AgentConfig())
    # Assert existence of the detailed tool descriptions that are longer than 1024 characters
    assert any(len(tool['function']['description']) > 1024 for tool in agent.tools)


def test_mismatched_tool_call_events(mock_state: State):
    """Tests that the agent can convert mismatched tool call events (i.e., an observation with no corresponding action) into messages."""
    agent = CodeActAgent(llm=LLM(LLMConfig()), config=AgentConfig())

    tool_call_metadata = Mock(
        spec=ToolCallMetadata,
        model_response=Mock(
            id='model_response_0',
            choices=[
                Mock(
                    message=Mock(
                        role='assistant',
                        content='',
                        tool_calls=[
                            Mock(spec=ChatCompletionMessageToolCall, id='tool_call_0')
                        ],
                    )
                )
            ],
        ),
        tool_call_id='tool_call_0',
        function_name='foo',
    )

    action = CmdRunAction('foo')
    action._source = 'agent'
    action.tool_call_metadata = tool_call_metadata

    observation = CmdOutputObservation(content='', command_id=0, command='foo')
    observation.tool_call_metadata = tool_call_metadata

    # When both events are provided, the agent should get three messages:
    # 1. The system message,
    # 2. The action message, and
    # 3. The observation message
    mock_state.history = [action, observation]
    messages = agent._get_messages(mock_state.history)
    assert len(messages) == 3

    # The same should hold if the events are presented out-of-order
    mock_state.history = [observation, action]
    messages = agent._get_messages(mock_state.history)
    assert len(messages) == 3

    # If only one of the two events is present, then we should just get the system message
    mock_state.history = [action]
    messages = agent._get_messages(mock_state.history)
    assert len(messages) == 1

    mock_state.history = [observation]
    messages = agent._get_messages(mock_state.history)
    assert len(messages) == 1


def test_enhance_messages_adds_newlines_between_consecutive_user_messages(
    agent: CodeActAgent,
):
    """Test that _enhance_messages adds newlines between consecutive user messages."""
    # Set up the prompt manager
    agent.prompt_manager = Mock()
    agent.prompt_manager.add_examples_to_initial_message = Mock()
    agent.prompt_manager.add_info_to_initial_message = Mock()
    agent.prompt_manager.enhance_message = Mock()

    # Create consecutive user messages with various content types
    messages = [
        # First user message with TextContent only
        Message(role='user', content=[TextContent(text='First user message')]),
        # Second user message with TextContent only - should get newlines added
        Message(role='user', content=[TextContent(text='Second user message')]),
        # Assistant message
        Message(role='assistant', content=[TextContent(text='Assistant response')]),
        # Third user message with TextContent only - shouldn't get newlines
        Message(role='user', content=[TextContent(text='Third user message')]),
        # Fourth user message with ImageContent first, TextContent second - should get newlines
        Message(
            role='user',
            content=[
                ImageContent(image_urls=['https://example.com/image.jpg']),
                TextContent(text='Fourth user message with image'),
            ],
        ),
        # Fifth user message with only ImageContent - no TextContent to modify
        Message(
            role='user',
            content=[
                ImageContent(image_urls=['https://example.com/another-image.jpg'])
            ],
        ),
    ]

    # Call _enhance_messages
    enhanced_messages = agent._enhance_messages(messages)

    # Verify newlines were added correctly
    assert enhanced_messages[1].content[0].text.startswith('\n\n')
    assert enhanced_messages[1].content[0].text == '\n\nSecond user message'

    # Third message follows assistant, so shouldn't have newlines
    assert not enhanced_messages[3].content[0].text.startswith('\n\n')
    assert enhanced_messages[3].content[0].text == 'Third user message'

    # Fourth message follows user, so should have newlines in its TextContent
    assert enhanced_messages[4].content[1].text.startswith('\n\n')
    assert enhanced_messages[4].content[1].text == '\n\nFourth user message with image'

    # Fifth message only has ImageContent, no TextContent to modify
    assert len(enhanced_messages[5].content) == 1
    assert isinstance(enhanced_messages[5].content[0], ImageContent)
