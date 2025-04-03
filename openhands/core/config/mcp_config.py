from typing import List, Tuple
from urllib.parse import urlparse

from pydantic import BaseModel, Field, ValidationError
from openhands.core.logger import openhands_logger as logger


class MCPConfig(BaseModel):
    """Configuration for MCP (Model Context Protocol) settings.

    Attributes:
        mcp_servers: List of MCP server URLs.
        commands: List of command configurations, where each command is a tuple of (command, args).
    """

    mcp_servers: List[str] = Field(default_factory=list)
    commands: List[List[List[str]]] = Field(default_factory=list)

    model_config = {'extra': 'forbid'}

    def validate_config(self) -> None:
        """Validate the MCP configuration."""
        # Validate server URLs
        if len(set(self.mcp_servers)) != len(self.mcp_servers):
            raise ValueError('Duplicate MCP server URLs are not allowed')

        for url in self.mcp_servers:
            try:
                result = urlparse(url)
                if not all([result.scheme, result.netloc]):
                    raise ValueError(f'Invalid URL format: {url}')
            except Exception as e:
                raise ValueError(f'Invalid URL {url}: {str(e)}')

        # Validate commands
        for cmd in self.commands:
            if not isinstance(cmd, list) or len(cmd) < 1:
                raise ValueError(f'Invalid command format: {cmd}. Expected [command, [args...]]')
            if not isinstance(cmd[0], str):
                raise ValueError(f'Command must be a string: {cmd[0]}')
            if len(cmd) > 1 and not isinstance(cmd[1], list):
                raise ValueError(f'Arguments must be a list: {cmd[1]}')

    @classmethod
    def from_toml_section(cls, data: dict) -> dict[str, 'MCPConfig']:
        """
        Create a mapping of MCPConfig instances from a toml dictionary representing the [mcp] section.

        The default configuration is built from all non-dict keys in data.
        Then, each key with a dict value is treated as a custom MCP configuration, and its values override
        the default configuration.

        Example:
        Apply generic MCP config with custom MCP overrides, e.g.
            [mcp]
            mcp_servers = ["http://localhost:4000/sse"]
            commands = [["python", ["-c"]], ["bash", ["-c"]]]
            [mcp.delegation]
            mcp_servers = ["http://localhost:4001/sse"]
            commands = [["node", ["-e"]], ["npm", ["run"]]]

        Returns:
            dict[str, MCPConfig]: A mapping where the key "mcp" corresponds to the default configuration
            and additional keys represent custom configurations.
        """
        # Initialize the result mapping
        mcp_mapping: dict[str, MCPConfig] = {}

        # Extract base config data and custom sections
        base_data = {}
        custom_sections: dict[str, dict] = {}
        
        # Process the mcp section
        for key, value in data.items():
            if isinstance(value, dict):
                custom_sections[key] = value
            else:
                base_data[key] = value

        # Try to create the base config
        try:
            base_config = cls(**base_data)
            base_config.validate_config()
            mcp_mapping['mcp'] = base_config
        except ValidationError as e:
            logger.warning(f'Invalid base MCP configuration: {e}. Using defaults.')
            # If base config fails, create a default one
            base_config = cls()
            mcp_mapping['mcp'] = base_config

        # Process custom sections
        for name, overrides in custom_sections.items():
            try:
                # Merge base config with overrides
                merged = {**base_config.model_dump(), **overrides}
                custom_config = cls(**merged)
                custom_config.validate_config()
                mcp_mapping[f'mcp.{name}'] = custom_config
            except ValidationError as e:
                logger.warning(
                    f'Invalid MCP configuration for [{name}]: {e}. This section will be skipped.'
                )
                continue

        return mcp_mapping
