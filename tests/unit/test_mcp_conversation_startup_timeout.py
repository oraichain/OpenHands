"""Test suite for reproducing MCP connection timeout issues during conversation startup.

This test simulates the scenario where MCP server connections timeout during
conversation initialization, which prevents the conversation from starting.
"""

import asyncio
import logging
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from openhands.core.config.app_config import AppConfig
from openhands.core.config.mcp_config import MCPConfig
from openhands.core.schema import AgentState
from openhands.events.action import MessageAction
from openhands.events.observation import AgentStateChangedObservation
from openhands.mcp import fetch_mcp_tools_from_config
from openhands.mcp.client import MCPClient
from openhands.server.session.session import Session
from openhands.server.settings import Settings
from openhands.storage.files import FileStore

# Configure logging for better test debugging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)


class TestMCPConversationStartupTimeout:
    """Test class for MCP timeout issues during conversation startup."""

    @pytest.fixture
    def mock_file_store(self):
        """Create a mock FileStore."""
        return MagicMock(spec=FileStore)

    @pytest.fixture
    def settings(self):
        """Create basic Settings."""
        return Settings()

    @pytest.fixture
    def app_config_with_mcp(self):
        """Create an AppConfig with MCP configuration."""
        config = AppConfig()
        config.dict_mcp_config = {
            "server1": MCPConfig(name="server1", url="http://localhost:8080/sse"),
            "server2": MCPConfig(name="server2", url="http://unreachable:9999/sse"),
            "server3": MCPConfig(name="server3", url="http://timeout:8888/sse"),
        }
        return config

    @pytest.mark.asyncio
    async def test_mcp_connection_timeout_blocks_conversation_startup(
        self, app_config_with_mcp, mock_file_store, settings
    ):
        """Test that MCP connection timeout during initialization blocks conversation startup.

        This simulates the real-world scenario where:
        1. User starts a conversation
        2. Session initialization tries to connect to MCP servers
        3. Some MCP servers are unreachable/timeout
        4. Connection failure propagates and prevents conversation from starting
        """
        logger.info("=== Starting MCP timeout test ===")
        
        # Create a session
        session = Session(
            sid="test-session-123",
            config=app_config_with_mcp,
            file_store=mock_file_store,
            sio=None,  # No socket server for this test
        )
        logger.info(f"Created session with MCP config: {app_config_with_mcp.dict_mcp_config}")

        # Mock the MCPClient to simulate timeout behavior
        def create_timeout_client(name: str, config: MCPConfig):
            logger.info(f"Creating mock client for {name}: {config.url}")
            client = MagicMock(spec=MCPClient)

            async def mock_connect_sse(*args, **kwargs):
                logger.info(f"Mock connect_sse called for {name} ({config.url})")
                if "timeout" in config.url:
                    # Simulate timeout after 6 seconds (longer than default 5s timeout)
                    logger.info(f"Simulating timeout for {config.url}")
                    await asyncio.sleep(6)
                    raise asyncio.TimeoutError(f"Connection to {config.url} timed out")
                elif "unreachable" in config.url:
                    # Simulate connection refused
                    logger.info(f"Simulating connection refused for {config.url}")
                    raise ConnectionError(f"Connection to {config.url} refused")
                else:
                    # Successful connection
                    logger.info(f"Simulating successful connection for {config.url}")
                    return client

            client.connect_sse = mock_connect_sse
            client.disconnect = AsyncMock()
            return client

        # Mock the MCPClient constructor
        with patch("openhands.mcp.utils.MCPClient") as mock_mcp_client:
            mock_mcp_client.side_effect = lambda name: create_timeout_client(
                name, app_config_with_mcp.dict_mcp_config[name]
            )

            # Mock agent creation to avoid complex dependencies
            mock_agent = MagicMock()
            mock_agent.set_mcp_tools = MagicMock()
            mock_agent.set_search_tools = MagicMock()
            mock_agent.update_agent_knowledge_base = MagicMock()
            mock_agent.set_system_prompt = MagicMock()
            mock_agent.set_user_prompt = MagicMock()
            
            def mock_get_cls(agent_name):
                mock_agent_class = MagicMock()
                mock_agent_class.return_value = mock_agent
                return mock_agent_class
            
            with patch('openhands.controller.agent.Agent.get_cls', side_effect=mock_get_cls):
                with patch.object(session.agent_session, 'start', new_callable=AsyncMock) as mock_start:
                    # Attempt to initialize the agent (this should handle MCP timeouts gracefully)
                    initial_message = MessageAction(content="Hello, let's start coding!")
                    logger.info("Starting agent initialization...")

                    start_time = asyncio.get_event_loop().time()
                    try:
                        await session.initialize_agent(
                            settings=settings,
                            initial_message=initial_message,
                            replay_json=None,
                        )
                        end_time = asyncio.get_event_loop().time()
                        elapsed = end_time - start_time
                        
                        logger.info(f"Agent initialization completed in {elapsed:.2f}s")
                        
                        # Verify that agent was created and MCP tools were set
                        assert mock_agent.set_mcp_tools.called, "Agent should receive MCP tools"
                        
                        # Verify session start was called
                        assert mock_start.called, "Agent session should be started"
                        
                        # Session initialization should complete even with MCP timeouts
                        logger.info("✅ Session initialized successfully despite MCP timeouts")
                        
                    except Exception as e:
                        end_time = asyncio.get_event_loop().time()
                        elapsed = end_time - start_time
                        logger.error(f"❌ Session initialization failed after {elapsed:.2f}s: {str(e)}")
                        logger.error(f"Exception type: {type(e)}")
                        # This should not happen - MCP timeouts should not prevent conversation startup
                        pytest.fail(
                            f"Session initialization failed due to MCP timeout: {str(e)}"
                        )

    @pytest.mark.asyncio
    async def test_direct_mcp_fetch_with_timeout(self, app_config_with_mcp):
        """Test direct MCP tools fetching with timeout simulation."""
        logger.info("=== Testing direct MCP fetch with timeouts ===")
        
        # Test the core MCP fetching function directly
        start_time = asyncio.get_event_loop().time()
        
        try:
            mcp_tools = await fetch_mcp_tools_from_config(
                app_config_with_mcp.dict_mcp_config
            )
            end_time = asyncio.get_event_loop().time()
            elapsed = end_time - start_time
            
            logger.info(f"MCP tools fetch completed in {elapsed:.2f}s")
            logger.info(f"Returned {len(mcp_tools)} tools")
            
            # Should complete reasonably quickly and return empty list
            assert elapsed < 10, f"MCP fetch took too long: {elapsed:.2f}s"
            assert isinstance(mcp_tools, list), "Should return a list"
            
        except Exception as e:
            end_time = asyncio.get_event_loop().time()
            elapsed = end_time - start_time
            logger.error(f"MCP fetch failed after {elapsed:.2f}s: {str(e)}")
            pytest.fail(f"MCP fetch should not fail: {str(e)}")

    @pytest.mark.asyncio
    async def test_conversation_state_changes_during_mcp_timeout(
        self, app_config_with_mcp, mock_file_store, settings
    ):
        """Test that conversation state changes correctly during MCP timeout scenarios.
        
        This test monitors agent state transitions to verify:
        1. State starts as LOADING during initialization
        2. If MCP timeout causes failure, state should change to ERROR 
        3. If MCP timeout is handled gracefully, state should eventually reach INIT
        """
        logger.info("=== Testing conversation state changes during MCP timeout ===")
        
        # Track all state changes
        state_changes = []
        
        def track_state_changes(event):
            if isinstance(event, AgentStateChangedObservation):
                state_changes.append(event.agent_state)
                logger.info(f"🔄 Agent state changed to: {event.agent_state}")
        
        # Create a session
        session = Session(
            sid="test-session-state-tracking",
            config=app_config_with_mcp,
            file_store=mock_file_store,
            sio=None,
        )
        
        # Subscribe to state changes
        session.agent_session.event_stream.subscribe(
            "TEST_SUBSCRIBER", track_state_changes, "test-session-state-tracking"
        )
        
        # Mock the MCPClient with extreme timeout to force failure
        def create_extreme_timeout_client(name: str, config: MCPConfig):
            logger.info(f"Creating extreme timeout client for {name}: {config.url}")
            client = MagicMock(spec=MCPClient)

            async def mock_connect_sse(*args, **kwargs):
                logger.info(f"Mock extreme timeout connect_sse called for {name}")
                # Simulate very long timeout that should cause issues
                await asyncio.sleep(15)  # Much longer than reasonable
                raise asyncio.TimeoutError(f"Extreme timeout for {config.url}")

            client.connect_sse = mock_connect_sse
            client.disconnect = AsyncMock()
            return client

        # Test with extreme timeout scenario
        with patch("openhands.mcp.utils.MCPClient") as mock_mcp_client:
            mock_mcp_client.side_effect = lambda name: create_extreme_timeout_client(
                name, app_config_with_mcp.dict_mcp_config[name]
            )

            # Mock agent creation to avoid complex dependencies
            mock_agent = MagicMock()
            mock_agent.set_mcp_tools = MagicMock()
            mock_agent.set_search_tools = MagicMock()
            mock_agent.update_agent_knowledge_base = MagicMock()
            mock_agent.set_system_prompt = MagicMock()
            mock_agent.set_user_prompt = MagicMock()
            
            def mock_get_cls(agent_name):
                mock_agent_class = MagicMock()
                mock_agent_class.return_value = mock_agent
                return mock_agent_class
            
            with patch('openhands.controller.agent.Agent.get_cls', side_effect=mock_get_cls):
                with patch.object(session.agent_session, 'start', new_callable=AsyncMock) as mock_start:
                    
                    initial_message = MessageAction(content="Test state tracking")
                    logger.info("Starting agent initialization with extreme MCP timeouts...")

                    start_time = asyncio.get_event_loop().time()
                    
                    try:
                        await session.initialize_agent(
                            settings=settings,
                            initial_message=initial_message,
                            replay_json=None,
                        )
                        
                        end_time = asyncio.get_event_loop().time()
                        elapsed = end_time - start_time
                        
                        logger.info(f"Agent initialization completed in {elapsed:.2f}s")
                        logger.info(f"State changes observed: {state_changes}")
                        
                        # Verify state progression
                        assert len(state_changes) > 0, "Should have observed at least one state change"
                        
                        # First state should be LOADING
                        assert state_changes[0] == AgentState.LOADING, f"Expected LOADING as first state, got {state_changes[0]}"
                        
                        # If initialization succeeds despite timeouts, final state should be RUNNING or AWAITING_USER_INPUT
                        if mock_start.called:
                            logger.info("✅ Session initialized successfully despite extreme MCP timeouts")
                            # State should not be ERROR if initialization succeeded
                            assert AgentState.ERROR not in state_changes, "Should not have ERROR state if initialization succeeded"
                        
                    except Exception as e:
                        end_time = asyncio.get_event_loop().time()
                        elapsed = end_time - start_time
                        logger.error(f"❌ Agent initialization failed after {elapsed:.2f}s: {str(e)}")
                        logger.info(f"State changes during failure: {state_changes}")
                        
                        # If initialization fails, we should see appropriate state changes
                        assert len(state_changes) > 0, "Should have observed state changes even during failure"
                        assert state_changes[0] == AgentState.LOADING, f"Expected LOADING as first state, got {state_changes[0]}"
                        
                        # Should end in ERROR state if initialization failed
                        if len(state_changes) > 1:
                            assert state_changes[-1] == AgentState.ERROR, f"Expected ERROR as final state, got {state_changes[-1]}"

    @pytest.mark.asyncio 
    async def test_mcp_timeout_causes_conversation_failure(
        self, app_config_with_mcp, mock_file_store, settings
    ):
        """Test scenario where MCP timeout actually causes conversation startup to fail.
        
        This simulates a critical MCP dependency that prevents conversation from starting.
        """
        logger.info("=== Testing MCP timeout causing conversation failure ===")
        
        state_changes = []
        error_messages = []
        
        def track_events(event):
            if isinstance(event, AgentStateChangedObservation):
                state_changes.append(event.agent_state)
                logger.info(f"🔄 State: {event.agent_state}")
        
        session = Session(
            sid="test-session-failure",
            config=app_config_with_mcp,
            file_store=mock_file_store,
            sio=None,
        )
        
        session.agent_session.event_stream.subscribe(
            "FAILURE_TEST", track_events, "test-session-failure"
        )
        
        # Mock fetch_mcp_tools_from_config to always fail with timeout
        async def failing_mcp_fetch(*args, **kwargs):
            logger.info("Simulating critical MCP dependency failure")
            await asyncio.sleep(1)  # Short delay to simulate timeout
            raise asyncio.TimeoutError("Critical MCP service unavailable")
        
        with patch('openhands.server.session.session.fetch_mcp_tools_from_config', side_effect=failing_mcp_fetch):
            initial_message = MessageAction(content="Test critical failure")
            
            start_time = asyncio.get_event_loop().time()
            
            with pytest.raises(Exception) as exc_info:
                await session.initialize_agent(
                    settings=settings,
                    initial_message=initial_message,
                    replay_json=None,
                )
            
            end_time = asyncio.get_event_loop().time()
            elapsed = end_time - start_time
            
            logger.info(f"Initialization failed as expected after {elapsed:.2f}s")
            logger.info(f"Exception: {exc_info.value}")
            logger.info(f"State changes: {state_changes}")
            
            # Verify the failure scenario
            exception_str = str(exc_info.value).lower()
            assert "timeout" in exception_str or "mcp" in exception_str, \
                f"Exception should be related to MCP timeout: {exc_info.value}"
            
            # Should have started with LOADING state
            assert len(state_changes) > 0, "Should observe state changes"
            assert state_changes[0] == AgentState.LOADING, f"Expected LOADING first, got {state_changes[0]}"
            
            # Conversation should fail to start (not reach RUNNING or AWAITING_USER_INPUT state)
            assert AgentState.RUNNING not in state_changes and AgentState.AWAITING_USER_INPUT not in state_changes, \
                "Conversation should not reach RUNNING or AWAITING_USER_INPUT state when MCP fails critically"
            
            logger.info("✅ Confirmed: Critical MCP timeout prevents conversation startup")

    @pytest.mark.asyncio
    async def test_graceful_mcp_timeout_handling_with_state_tracking(
        self, app_config_with_mcp, mock_file_store, settings  
    ):
        """Test that MCP timeouts are handled gracefully with proper state transitions.
        
        This represents the ideal behavior: MCP timeouts don't prevent conversation startup.
        """
        logger.info("=== Testing graceful MCP timeout handling ===")
        
        state_changes = []
        
        def track_states(event):
            if isinstance(event, AgentStateChangedObservation):
                state_changes.append(event.agent_state)
                logger.info(f"🟢 State: {event.agent_state}")
        
        session = Session(
            sid="test-graceful-handling",
            config=app_config_with_mcp,
            file_store=mock_file_store,
            sio=None,
        )
        
        session.agent_session.event_stream.subscribe(
            "GRACEFUL_TEST", track_states, "test-graceful-handling"
        )
        
        # Mock fetch_mcp_tools_from_config to timeout but return empty list (graceful)
        async def graceful_mcp_fetch(*args, **kwargs):
            logger.info("Simulating MCP timeout with graceful handling")
            await asyncio.sleep(2)  # Simulate some delay
            logger.warning("MCP servers timed out, but returning empty tools list")
            return []  # Return empty list instead of raising exception
        
        with patch('openhands.server.session.session.fetch_mcp_tools_from_config', side_effect=graceful_mcp_fetch):
            # Mock agent creation
            mock_agent = MagicMock()
            mock_agent.set_mcp_tools = MagicMock()
            mock_agent.set_search_tools = MagicMock()
            mock_agent.update_agent_knowledge_base = MagicMock()
            mock_agent.set_system_prompt = MagicMock()
            mock_agent.set_user_prompt = MagicMock()
            
            def mock_get_cls(agent_name):
                mock_agent_class = MagicMock()
                mock_agent_class.return_value = mock_agent
                return mock_agent_class
            
            with patch('openhands.controller.agent.Agent.get_cls', side_effect=mock_get_cls):
                with patch.object(session.agent_session, 'start', new_callable=AsyncMock) as mock_start:
                    
                    initial_message = MessageAction(content="Test graceful handling")
                    
                    start_time = asyncio.get_event_loop().time()
                    
                    # This should succeed despite MCP timeouts
                    await session.initialize_agent(
                        settings=settings,
                        initial_message=initial_message,
                        replay_json=None,
                    )
                    
                    end_time = asyncio.get_event_loop().time()
                    elapsed = end_time - start_time
                    
                    logger.info(f"Graceful initialization completed in {elapsed:.2f}s")
                    logger.info(f"State progression: {state_changes}")
                    
                    # Verify successful graceful handling
                    assert len(state_changes) > 0, "Should observe state changes"
                    assert state_changes[0] == AgentState.LOADING, f"Should start with LOADING, got {state_changes[0]}"
                    
                    # Should NOT have ERROR state in graceful handling
                    assert AgentState.ERROR not in state_changes, f"Should not have ERROR state in graceful handling: {state_changes}"
                    
                    # Agent should be created and session started
                    assert mock_agent.set_mcp_tools.called, "Agent should receive MCP tools (empty list)"
                    assert mock_start.called, "Session should start successfully"
                    
                    # Verify empty MCP tools were passed (graceful degradation)
                    mcp_tools_call = mock_agent.set_mcp_tools.call_args[0][0]
                    assert mcp_tools_call == [], "Should pass empty MCP tools list when servers timeout"
                    
                    logger.info("✅ Confirmed: MCP timeouts handled gracefully, conversation starts normally")
