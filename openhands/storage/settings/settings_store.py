from __future__ import annotations

from abc import ABC, abstractmethod

from openhands.core.config.app_config import AppConfig
from openhands.server.settings import Settings


class SettingsStore(ABC):
    """Storage for ConversationInitData. May or may not support multiple users depending on the environment."""

    @abstractmethod
    async def load(self, user_id: str | None = None) -> Settings | None:
        """Load session init data."""

    @abstractmethod
    async def store(self, settings: Settings, user_id: str | None = None) -> None:
        """Store session init data."""

    @classmethod
    @abstractmethod
    async def get_instance(
        cls, config: AppConfig, user_id: str | None
    ) -> SettingsStore:
        """Get a store for the user represented by the token given."""
