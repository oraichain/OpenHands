from typing import Any, ClassVar

from pydantic import BaseModel, Field, SecretStr

from openhands.core import logger
from openhands.core.config.agent_config import AgentConfig
from openhands.core.config.condenser_config import CondenserConfig, NoOpCondenserConfig
from openhands.core.config.config_utils import (
    OH_DEFAULT_AGENT,
    OH_MAX_ITERATIONS,
    model_defaults_to_dict,
)
from openhands.core.config.conversation_config import ConversationConfig
from openhands.core.config.extended_config import ExtendedConfig
from openhands.core.config.llm_config import LLMConfig
from openhands.core.config.mcp_config import MCPConfig
from openhands.core.config.sandbox_config import SandboxConfig
from openhands.core.config.search_engine import SearchEngineConfig
from openhands.core.config.security_config import SecurityConfig


class AppConfig(BaseModel):
    """Configuration for the app.

    Attributes:
        llms: Dictionary mapping LLM names to their configurations.
            The default configuration is stored under the 'llm' key.
        agents: Dictionary mapping agent names to their configurations.
            The default configuration is stored under the 'agent' key.
        default_agent: Name of the default agent to use.
        sandbox: Sandbox configuration settings.
        runtime: Runtime environment identifier.
        file_store: Type of file store to use.
        file_store_path: Path to the file store.
        save_trajectory_path: Either a folder path to store trajectories with auto-generated filenames, or a designated trajectory file path.
        save_screenshots_in_trajectory: Whether to save screenshots in trajectory (in encoded image format).
        replay_trajectory_path: Path to load trajectory and replay. If provided, trajectory would be replayed first before user's instruction.
        workspace_base: Base path for the workspace. Defaults to `./workspace` as absolute path.
        workspace_mount_path: Path to mount the workspace. Defaults to `workspace_base`.
        workspace_mount_path_in_sandbox: Path to mount the workspace in sandbox. Defaults to `/workspace`.
        workspace_mount_path_in_sandbox_store_in_session: Whether to store the workspace mount path in session. Defaults to `True`.
        workspace_mount_rewrite: Path to rewrite the workspace mount path.
        cache_dir: Path to cache directory. Defaults to `/tmp/cache`.
        run_as_openhands: Whether to run as openhands.
        max_iterations: Maximum number of iterations allowed.
        max_budget_per_task: Maximum budget per task, agent stops if exceeded.
        e2b_api_key: E2B API key.
        disable_color: Whether to disable terminal colors. For terminals that don't support color.
        debug: Whether to enable debugging mode.
        file_uploads_max_file_size_mb: Maximum file upload size in MB. `0` means unlimited.
        file_uploads_restrict_file_types: Whether to restrict upload file types.
        file_uploads_allowed_extensions: Allowed file extensions. `['.*']` allows all.
        cli_multiline_input: Whether to enable multiline input in CLI. When disabled,
            input is read line by line. When enabled, input continues until /exit command.
        dict_mcp_config: dictionary of MCP configurations.
        condenser: Condenser configuration settings.
        evaluation_endpoint_url: URL of the evaluation endpoint.
        evaluation_timeout: Timeout for the evaluation endpoint.
        enable_evaluation: Whether to enable the evaluation endpoint.
    """

    llms: dict[str, LLMConfig] = Field(default_factory=dict)
    agents: dict[str, AgentConfig] = Field(default_factory=dict)
    default_agent: str = Field(default=OH_DEFAULT_AGENT)
    sandbox: SandboxConfig = Field(default_factory=SandboxConfig)
    security: SecurityConfig = Field(default_factory=SecurityConfig)
    extended: ExtendedConfig = Field(default_factory=lambda: ExtendedConfig({}))
    runtime: str = Field(default='docker')
    file_store: str = Field(default='local')
    file_store_path: str = Field(default='/tmp/openhands_file_store')
    save_trajectory_path: str | None = Field(default=None)
    save_screenshots_in_trajectory: bool = Field(default=False)
    replay_trajectory_path: str | None = Field(default=None)
    workspace_base: str | None = Field(default=None)
    workspace_mount_path: str | None = Field(default=None)
    workspace_mount_path_in_sandbox: str = Field(default='/workspace')
    workspace_mount_path_in_sandbox_store_in_session: bool = Field(default=True)
    workspace_mount_rewrite: str | None = Field(default=None)
    cache_dir: str = Field(default='/tmp/cache')
    run_as_openhands: bool = Field(default=True)
    max_iterations: int = Field(default=OH_MAX_ITERATIONS)
    max_budget_per_task: float | None = Field(default=None)
    e2b_api_key: SecretStr | None = Field(default=None)
    modal_api_token_id: SecretStr | None = Field(default=None)
    modal_api_token_secret: SecretStr | None = Field(default=None)
    disable_color: bool = Field(default=False)
    jwt_secret: SecretStr | None = Field(default=None)
    debug: bool = Field(default=False)
    file_uploads_max_file_size_mb: int = Field(default=0)
    file_uploads_restrict_file_types: bool = Field(default=False)
    file_uploads_allowed_extensions: list[str] = Field(default_factory=lambda: ['.*'])
    runloop_api_key: SecretStr | None = Field(default=None)
    daytona_api_key: SecretStr | None = Field(default=None)
    daytona_api_url: str = Field(default='https://app.daytona.io/api')
    daytona_target: str = Field(default='eu')
    cli_multiline_input: bool = Field(default=False)
    conversation_max_age_seconds: int = Field(default=864000)  # 10 days in seconds
    enable_default_condenser: bool = Field(default=True)
    max_concurrent_conversations: int = Field(
        default=5
    )  # Maximum number of concurrent agent loops allowed per user
    # mcp: MCPConfig = Field(default_factory=MCPConfig)
    dict_mcp_config: dict[str, MCPConfig] = Field(default_factory=dict)
    dict_search_engine_config: dict[str, SearchEngineConfig] = Field(
        default_factory=dict
    )
    condenser: CondenserConfig = Field(default_factory=NoOpCondenserConfig)
    enable_microagents: bool = Field(default=True)

    defaults_dict: ClassVar[dict] = {}

    model_config = {'extra': 'forbid'}

    evaluation_endpoint_url: str | None = Field(default=None)
    evaluation_timeout: int = Field(default=60)
    enable_evaluation: bool = Field(default=False)
    conversation: ConversationConfig = Field(default_factory=ConversationConfig)

    def get_llm_config(self, name: str = 'llm') -> LLMConfig:
        """'llm' is the name for default config (for backward compatibility prior to 0.8)."""
        if name in self.llms:
            return self.llms[name]
        if name is not None and name != 'llm':
            logger.openhands_logger.warning(
                f'llm config group {name} not found, using default config'
            )
        if 'llm' not in self.llms:
            self.llms['llm'] = LLMConfig()
        return self.llms['llm']

    def set_llm_config(self, value: LLMConfig, name: str = 'llm') -> None:
        self.llms[name] = value

    def get_agent_config(self, name: str = 'agent') -> AgentConfig:
        """'agent' is the name for default config (for backward compatibility prior to 0.8)."""
        if name in self.agents:
            return self.agents[name]
        if 'agent' not in self.agents:
            self.agents['agent'] = AgentConfig()
        return self.agents['agent']

    def set_agent_config(self, value: AgentConfig, name: str = 'agent') -> None:
        self.agents[name] = value

    def get_agent_to_llm_config_map(self) -> dict[str, LLMConfig]:
        """Get a map of agent names to llm configs."""
        return {name: self.get_llm_config_from_agent(name) for name in self.agents}

    def get_llm_config_from_agent(self, name: str = 'agent') -> LLMConfig:
        agent_config: AgentConfig = self.get_agent_config(name)
        llm_config_name = (
            agent_config.llm_config if agent_config.llm_config is not None else 'llm'
        )
        return self.get_llm_config(llm_config_name)

    def get_agent_configs(self) -> dict[str, AgentConfig]:
        return self.agents

    def model_post_init(self, __context: Any) -> None:
        """Post-initialization hook, called when the instance is created with only default values."""
        super().model_post_init(__context)
        if not AppConfig.defaults_dict:  # Only set defaults_dict if it's empty
            AppConfig.defaults_dict = model_defaults_to_dict(self)
