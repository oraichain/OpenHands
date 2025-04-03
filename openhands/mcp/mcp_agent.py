from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field

from openhands.core.logger import openhands_logger as logger
from openhands.mcp.mcp import MCPClients
from openhands.mcp.mcp_base import ToolResult


class MCPAgent(BaseModel):
    """Agent for interacting with MCP (Model Context Protocol) servers.

    This agent connects to an MCP server using either SSE or stdio transport
    and makes the server's tools available through the agent's tool interface.
    """

    name: str = 'mcp_agent'
    description: str = 'An agent that connects to an MCP server and uses its tools.'

    # Initialize MCP tool collection
    mcp_clients: MCPClients = Field(default_factory=MCPClients)
    model_config = {'arbitrary_types_allowed': True}

    connection_type: str = 'sse'  # "stdio" or "sse"

    # Track tool schemas to detect changes
    tool_schemas: Dict[str, Dict[str, Any]] = Field(default_factory=dict)

    async def initialize(
        self,
        connection_type: Optional[str] = None,
        server_url: Optional[str] = None,
        command: Optional[List[List[str]]] = None,
    ) -> None:
        """Initialize the MCP connection.

        Args:
            connection_type: Type of connection to use ("stdio" or "sse")
            server_url: URL of the MCP server (for SSE connection)
            command: Command to run (for stdio connection)
            args: Arguments for the command (for stdio connection)
        """
        if connection_type:
            self.connection_type = connection_type

        # Connect to the MCP server based on connection type
        if self.connection_type == 'sse':
            if not server_url:
                raise ValueError('Server URL is required for SSE connection')
            await self.mcp_clients.connect_sse(server_url=server_url)
        elif self.connection_type == 'stdio':
            if not command:
                raise ValueError('Command is required for stdio connection')
            if command and len(command) > 1:
                await self.mcp_clients.connect_stdio(command=command[0], args=command[1])
            else:
                await self.mcp_clients.connect_stdio(command=command[0], args=[])
        else:
            raise ValueError(f'Unsupported connection type: {self.connection_type}')

        # Store initial tool schemas
        await self._refresh_tools()

        # Add system message about available tools
        tool_names = list(self.mcp_clients.tool_map.keys())
        tools_info = ', '.join(tool_names)

        # Add system prompt and available tools information
        logger.info(f'Available MCP tools: {tools_info}')

    async def _refresh_tools(self) -> Tuple[List[str], List[str]]:
        """Refresh the list of available tools from the MCP server.

        Returns:
            A tuple of (added_tools, removed_tools)
        """
        if not self.mcp_clients.session:
            return [], []

        # Get current tool schemas directly from the server
        response = await self.mcp_clients.session.list_tools()
        current_tools = {tool.name: tool.inputSchema for tool in response.tools}

        # Determine added, removed, and changed tools
        current_names = set(current_tools.keys())
        previous_names = set(self.tool_schemas.keys())

        added_tools = list(current_names - previous_names)
        removed_tools = list(previous_names - current_names)

        # Check for schema changes in existing tools
        changed_tools = []
        for name in current_names.intersection(previous_names):
            if current_tools[name] != self.tool_schemas.get(name):
                changed_tools.append(name)

        # Update stored schemas
        self.tool_schemas = current_tools

        # Log and notify about changes
        if added_tools:
            logger.info(f'Added MCP tools: {added_tools}')
        if removed_tools:
            logger.info(f'Removed MCP tools: {removed_tools}')
        if changed_tools:
            logger.info(f'Changed MCP tools: {changed_tools}')

        return added_tools, removed_tools

    async def run_tool(
        self, tool_name: str, args: Dict[str, Any] | None = None
    ) -> ToolResult:
        """Run a tool with the given name and input.

        Args:
            tool_name: Name of the tool to run
            args: Input for the tool
        """
        if not self.mcp_clients.session:
            raise ValueError('MCP connection not initialized')

        return await self.mcp_clients.execute(name=tool_name, tool_input=args)

    async def cleanup(self) -> None:
        """Clean up MCP connection when done."""
        if self.mcp_clients.session:
            await self.mcp_clients.disconnect()
            logger.info('MCP connection closed')


def convert_mcp_agents_to_tools(mcp_agents: list[MCPAgent] | None) -> list[dict]:
    """
    Converts a list of MCPAgent instances to ChatCompletionToolParam format
    that can be used by CodeActAgent.

    Args:
        mcp_agents: List of MCPAgent instances or None

    Returns:
        List of ChatCompletionToolParam tools ready to be used by CodeActAgent
    """
    if mcp_agents is None:
        logger.warning('mcp_agents is None, returning empty list')
        return []

    all_mcp_tools = []
    try:
        for agent in mcp_agents:
            # Each MCPAgent has an mcp_clients property that is a ToolCollection
            # The ToolCollection has a to_params method that converts tools to ChatCompletionToolParam format
            mcp_tools = agent.mcp_clients.to_params()
            all_mcp_tools.extend(mcp_tools)
    except Exception as e:
        logger.error(f'Error in convert_mcp_agents_to_tools: {e}')
        return []
    return all_mcp_tools

async def create_mcp_agents(
    mcp_servers: List[str], commands: List[List[List[str]]]
) -> List[MCPAgent]:
    mcp_agents: List[MCPAgent] = []
    # Initialize SSE connections
    if mcp_servers:
        for server_url in mcp_servers:
            logger.info(
                f'Initializing MCP agent for {server_url} with SSE connection...'
            )

            agent = MCPAgent()
            try:
                await agent.initialize(connection_type='sse', server_url=server_url)
                mcp_agents.append(agent)
                logger.info(f'Connected to MCP server {server_url} via SSE')
            except Exception as e:
                logger.error(f'Failed to connect to {server_url}: {str(e)}')
                raise

    # Initialize stdio connections
    if commands:
        for command in commands:
            logger.info(
                f'Initializing MCP agent for {command} with stdio connection...'
            )

            agent = MCPAgent()
            try:
                await agent.initialize(
                    connection_type='stdio', command=command
                )
                mcp_agents.append(agent)
                logger.info(f'Connected to MCP server via stdio with command {command}')
            except Exception as e:
                logger.error(f'Failed to connect with command {command}: {str(e)}')
                raise

    return mcp_agents