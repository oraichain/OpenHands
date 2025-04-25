# mypy: ignore-errors
import pytest
from unittest.mock import MagicMock, patch
import os
from openhands.a2a.common.types import AgentCard, AgentCapabilities, AgentSkill
from openhands.core.logger import openhands_logger as logger
from openhands.controller.agent import Agent
from openhands.controller.state.state import State
from openhands.core.config import AgentConfig, LLMConfig, load_from_toml
from openhands.core.config import AppConfig
from openhands.events.action import (
    AgentFinishAction,
    A2ASendTaskAction,
    NullAction,
    MessageAction,
)
from openhands.events.event import EventSource
from openhands.llm.llm import LLM
from openhands.a2a.A2AManager import A2AManager
from openhands.agenthub.orchestrator_agent.orchestrator_agent import (
    OrchestratorAgent,
    OrchestrationPhase,
)

@pytest.fixture(scope="function")
def setup_orchestrator_agent_integration():
    """Set up the test environment for integration tests with real LLM calls."""
    # Load configuration from config.toml file
    config_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))), "config.toml")
    if not os.path.exists(config_path):
        raise FileNotFoundError(f"Configuration file not found at {config_path}")
    
    config = AppConfig()
    load_from_toml(config, config_path)
    llm_config = config.get_llm_config()
    agent_config = config.get_agent_config()
    
    # Initialize LLM with the configuration from config.toml - no mocking
    llm = LLM(config=llm_config)
    
    # Create a real A2AManager with test agents
    a2a_manager = A2AManager(a2a_server_urls=config.agents['agent'].a2a_server_urls)
    # Register test agent cards
    test_agent1_card = AgentCard(
        name="TestAgent1",
        description="A test agent for data analysis",
        url="http://localhost:8000/agent1",
        version="1.0.0",
        capabilities=AgentCapabilities(
            streaming=True,
            pushNotifications=False,
            stateTransitionHistory=True
        ),
        skills=[
            AgentSkill(
                id="analyze_data",
                name="Data Analysis",
                description="Analyze numerical and textual data",
                tags=["analysis", "data"],
                examples=["Analyze this dataset", "Create a data summary"],
                inputModes=["text"],
                outputModes=["text"]
            ),
            AgentSkill(
                id="create_summary",
                name="Summary Generation",
                description="Generate summary reports from analysis",
                tags=["report", "summary"],
                examples=["Create a summary report", "Generate findings report"],
                inputModes=["text"],
                outputModes=["text"]
            )
        ]
    )
    test_agent2_card = AgentCard(
        name="TestAgent2",
        description="A test agent for task execution",
        url="http://localhost:8000/agent2",
        version="1.0.0",
        capabilities=AgentCapabilities(
            streaming=True,
            pushNotifications=True,
            stateTransitionHistory=True
        ),
        skills=[
            AgentSkill(
                id="execute_task",
                name="Task Execution",
                description="Execute various tasks and processes",
                tags=["execution", "task"],
                examples=["Run this process", "Execute this task"],
                inputModes=["text"],
                outputModes=["text"]
            ),
            AgentSkill(
                id="monitor_progress",
                name="Progress Monitoring",
                description="Monitor and report task progress",
                tags=["monitoring", "progress"],
                examples=["Check task status", "Monitor progress"],
                inputModes=["text"],
                outputModes=["text"]
            )
        ]
    )
    a2a_manager.list_remote_agent_cards = {
        "TestAgent1": test_agent1_card,
        "TestAgent2": test_agent2_card
    }
    # Initialize OrchestratorAgent with real components
    agent = OrchestratorAgent(
        llm=llm,
        config=agent_config,
        a2a_manager=a2a_manager
    )
    agent.team_description = agent._get_team_description()
    # Create a real State with test message
    state = State()
    state.history.append(
        MessageAction(content="Analyze this test data and create a summary report")
    )
    
    return agent, state, config

@pytest.mark.integration
def test_step_executing_plan_phase_pydantic_parsing_integration(setup_orchestrator_agent_integration):
    """Integration test for Pydantic parsing in EXECUTING_PLAN phase with real LLM."""
    logger.info("Starting integration test for Pydantic parsing in EXECUTING_PLAN phase")
    agent, state, _ = setup_orchestrator_agent_integration
    
    # Set up the initial state
    agent.phase = OrchestrationPhase.EXECUTING_PLAN
    agent.task = "Analyze this test data and create a summary report"
    agent.facts = "Test data contains numerical values and text descriptions"
    agent.plan = "1. Analyze test data\n2. Create summary report\n3. Present findings"
    
    logger.info(f"Initial state setup - Phase: {agent.phase}, Task: {agent.task}")
    logger.info(f"Facts: {agent.facts}")
    logger.info(f"Plan: {agent.plan}")
    
    # Add a properly formatted message to state history
    message_action = MessageAction(content="Analyze this test data and create a summary report")
    message_action._source = EventSource.USER  # Set source after creation
    state.history.append(message_action)
    logger.info(f"Added message to state history: {message_action.content}")
    
    # Execute the step with real LLM
    logger.info("Executing agent step...")
    action = agent.step(state)
    logger.info(f"Received action: {action}")
    
    # Verify the response structure and transitions
    assert isinstance(action, (A2ASendTaskAction, NullAction)), "Action should be either A2ASendTaskAction or NullAction"
    
    if isinstance(action, A2ASendTaskAction):
        logger.info(f"Received A2ASendTaskAction - Agent: {action.agent_name}, Task: {action.task_message}")
    else:
        logger.info("Received NullAction")
    
    logger.info(f"Final agent phase: {agent.phase}")