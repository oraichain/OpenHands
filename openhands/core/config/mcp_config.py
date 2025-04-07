from typing import List
from urllib.parse import urlparse

from pydantic import BaseModel, Field, ValidationError


class MCPSSEConfig(BaseModel):
    """Configuration for MCP SSE (Server-Sent Events) settings.

    Attributes:
        mcp_servers: List of MCP server URLs.
    """

    url: str = Field()

    mcp_agent_name: str = Field(default='mcp-agent')

    description: str = Field(default='MCP agent')

    model_config = {'extra': 'forbid'}

    def validate_servers(self) -> None:
        """Validate that server URLs are valid and unique."""
        # Check for duplicate server URLs
        # if len(set(self.mcp_servers)) != len(self.mcp_servers):
        #     raise ValueError('Duplicate MCP server URLs are not allowed')

        # Validate URLs
        try:
            result = urlparse(self.url)
            if not all([result.scheme, result.netloc]):
                raise ValueError(f'Invalid URL format: {self.url}')
        except Exception as e:
            raise ValueError(f'Invalid URL {self.url}: {str(e)}')


class MCPStdioConfig(BaseModel):
    """Configuration for MCP stdio settings.

    Attributes:
        commands: List of commands to run.
        args: List of arguments for each command.
    """

    command: str = Field()
    args: list[str] = Field(default_factory=list)

    mcp_agent_name: str = Field(default='mcp-agent')
    description: str = Field(default='MCP agent')

    model_config = {'extra': 'forbid'}


class MCPConfig(BaseModel):
    """Configuration for MCP (Message Control Protocol) settings.

    Attributes:
        sse: SSE-specific configuration.
        stdio: stdio-specific configuration.
    """

    sse: List[MCPSSEConfig] = Field(default_factory=list)
    stdio: List[MCPStdioConfig] = Field(default_factory=list)

    model_config = {'extra': 'forbid'}

    @classmethod
    def from_toml_section(cls, data: dict) -> dict[str, 'MCPConfig']:
        """
        Create a mapping of MCPConfig instances from a toml dictionary representing the [mcp] section.

        The configuration is built from all keys in data.

        Returns:
            dict[str, MCPConfig]: A mapping where the key "mcp" corresponds to the [mcp] configuration
        """
        # Initialize the result mapping
        mcp_mapping: dict[str, MCPConfig] = {}

        try:
            # Create SSE config if present
            mcp_servers = data.get('mcp-sse', {}).get('mcp_servers', [])
            sse_configs = []
            for server in mcp_servers:
                sse_config = MCPSSEConfig(**server)
                sse_config.validate_servers()
                sse_configs.append(sse_config)

            # Create stdio config if present
            mcp_stdios = data.get('mcp-stdio', {}).get('mcp_stdios', [])
            stdio_configs = [MCPStdioConfig(**stdio) for stdio in mcp_stdios]

            # Create the main MCP config
            mcp_mapping['mcp'] = cls(sse=sse_configs, stdio=stdio_configs)
        except ValidationError as e:
            raise ValueError(f'Invalid MCP configuration: {e}')

        return mcp_mapping
