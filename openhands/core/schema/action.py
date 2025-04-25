from enum import Enum


class ActionType(str, Enum):
    MESSAGE = 'message'
    ORCHESTRATOR_INITIALIZATION = 'orchestrator_initialization'  # Indicates the orchestrator agent has completed initialization
    ORCHESTRATOR_INITIALIZE_OBSERVATION = 'orchestrator_initialize_observation'  # Contains the full ledger after initialization
    """Represents a message.
    """

    START = 'start'
    """Starts a new development task OR send chat from the user. Only sent by the client.
    """

    READ = 'read'
    """Reads the content of a file.
    """

    WRITE = 'write'
    """Writes the content to a file.
    """

    EDIT = 'edit'
    """Edits a file by providing a draft.
    """

    RUN = 'run'
    """Runs a command.
    """

    RUN_IPYTHON = 'run_ipython'
    """Runs a IPython cell.
    """

    BROWSE = 'browse'
    """Opens a web page.
    """

    BROWSE_INTERACTIVE = 'browse_interactive'
    """Interact with the browser instance.
    """

    MCP = 'call_tool_mcp'
    """Interact with the MCP server.
    """

    DELEGATE = 'delegate'
    """Delegates a task to another agent.
    """

    THINK = 'think'
    """Logs a thought.
    """

    FINISH = 'finish'
    """If you're absolutely certain that you've completed your task and have tested your work,
    use the finish action to stop working.
    """

    REJECT = 'reject'
    """If you're absolutely certain that you cannot complete the task with given requirements,
    use the reject action to stop working.
    """

    NULL = 'null'

    PAUSE = 'pause'
    """Pauses the task.
    """

    RESUME = 'resume'
    """Resumes the task.
    """

    STOP = 'stop'
    """Stops the task. Must send a start action to restart a new task.
    """

    CHANGE_AGENT_STATE = 'change_agent_state'

    PUSH = 'push'
    """Push a branch to github."""

    SEND_PR = 'send_pr'
    """Send a PR to github."""

    RECALL = 'recall'
    """Retrieves content from a user workspace, microagent, or other source."""

    CONDENSATION = 'condensation'
    """Condenses a list of events into a summary."""

    A2A_LIST_REMOTE_AGENTS = 'a2a_list_remote_agents'
    """List the available remote agents you can use to delegate the task."""

    A2A_SEND_TASK = 'a2a_send_task'
    """Send a task to a remote agent."""

    GATHERING_FACTS = 'gathering_facts'
    """Indicates the orchestrator agent is gathering facts about the task."""

    CREATING_PLAN = 'creating_plan'
    """Indicates the orchestrator agent is creating a plan for the task."""

    UPDATING_KNOWLEDGE = 'updating_knowledge'
    """Indicates the orchestrator agent is updating its knowledge (facts and plan)."""

    FINAL_ANSWER = 'final_answer'
    """Indicates the orchestrator agent is generating the final answer."""
