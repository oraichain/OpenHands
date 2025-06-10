import asyncio
from functools import lru_cache
from typing import Optional, Union

from openhands.core.config.mcp_config import MCPConfig
from openhands.core.config.search_engine import SearchEngineConfig
from openhands.core.logger import openhands_logger as logger
from openhands.mcp.utils import (
    fetch_mcp_tools_from_config,
    fetch_search_tools_from_config,
)


class MCPToolsCache:
    """Singleton class to cache MCP tools and search tools during server startup."""

    _instance: Optional['MCPToolsCache'] = None
    _initialized: bool = False

    def __init__(self):
        self._mcp_tools: list[dict] = []
        self._search_tools: list[dict] = []
        self._initialization_lock = asyncio.Lock()

    @classmethod
    def get_instance(cls) -> 'MCPToolsCache':
        """Get the singleton instance of MCPToolsCache."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    async def initialize(
        self,
        dict_mcp_config: dict[str, MCPConfig],
        dict_search_engine_config: dict[str, SearchEngineConfig],
        sid: Optional[str] = None,
        mnemonic: Optional[str] = None,
    ) -> None:
        """Initialize MCP tools and search tools. This should be called once during server startup."""
        async with self._initialization_lock:
            if self._initialized:
                logger.info('MCP tools cache already initialized, skipping')
                return

            logger.info('Initializing MCP tools cache...')

            try:

                async def get_mcp_tools() -> list[dict]:
                    if dict_mcp_config:
                        return await fetch_mcp_tools_from_config(
                            dict_mcp_config, sid=sid, mnemonic=mnemonic
                        )
                    return []

                async def get_search_tools() -> list[dict]:
                    if dict_search_engine_config:
                        return await fetch_search_tools_from_config(
                            dict_search_engine_config, sid=sid, mnemonic=mnemonic
                        )
                    return []

                # Fetch both MCP and search tools in parallel
                results = await asyncio.gather(
                    get_mcp_tools(),
                    get_search_tools(),
                    return_exceptions=True,
                )

                mcp_result: Union[list[dict], BaseException] = results[0]
                search_result: Union[list[dict], BaseException] = results[1]

                # Handle results
                self._mcp_tools = (
                    mcp_result if not isinstance(mcp_result, BaseException) else []
                )
                self._search_tools = (
                    search_result
                    if not isinstance(search_result, BaseException)
                    else []
                )

                if isinstance(mcp_result, BaseException):
                    logger.error(f'Error fetching MCP tools: {mcp_result}')
                else:
                    logger.info(f'Cached {len(self._mcp_tools)} MCP tools')

                if isinstance(search_result, BaseException):
                    logger.error(f'Error fetching search tools: {search_result}')
                else:
                    logger.info(f'Cached {len(self._search_tools)} search tools')

                self._initialized = True
                logger.info('MCP tools cache initialization completed successfully')

            except Exception as e:
                logger.error(f'Error initializing MCP tools cache: {e}')
                raise

    def get_mcp_tools(self) -> list[dict]:
        """Get cached MCP tools."""
        if not self._initialized:
            logger.warning('MCP tools cache not initialized, returning empty list')
            return []
        return self._mcp_tools.copy()

    def get_search_tools(self) -> list[dict]:
        """Get cached search tools."""
        if not self._initialized:
            logger.warning('Search tools cache not initialized, returning empty list')
            return []
        return self._search_tools.copy()

    def is_initialized(self) -> bool:
        """Check if the cache has been initialized."""
        return self._initialized

    async def refresh(
        self,
        dict_mcp_config: dict[str, MCPConfig],
        dict_search_engine_config: dict[str, SearchEngineConfig],
        sid: Optional[str] = None,
        mnemonic: Optional[str] = None,
    ) -> None:
        """Refresh the cached tools. Useful for updating tools without server restart."""
        async with self._initialization_lock:
            logger.info('Refreshing MCP tools cache...')
            self._initialized = False
            await self.initialize(
                dict_mcp_config, dict_search_engine_config, sid, mnemonic
            )


@lru_cache(maxsize=1)
def get_mcp_tools_cache() -> MCPToolsCache:
    """Get the singleton MCPToolsCache instance."""
    return MCPToolsCache.get_instance()
