from __future__ import annotations

import json
from dataclasses import dataclass

from openhands.core.config.app_config import AppConfig
from openhands.server.settings import Settings
from openhands.storage import get_file_store
from openhands.storage.files import FileStore
from openhands.storage.settings.settings_store import SettingsStore
from openhands.utils.async_utils import call_sync_from_async


@dataclass
class FileSettingsStore(SettingsStore):
    file_store: FileStore
    path: str = 'settings.json'
    user_id: str | None = None

    async def load(self, _user_id: str | None = None) -> Settings | None:
        final_user_id = _user_id or self.user_id
        try:
            effective_path = (
                f'users/{final_user_id}/settings.json' if final_user_id else self.path
            )
            json_str = await call_sync_from_async(self.file_store.read, effective_path)
            kwargs = json.loads(json_str)
            settings = Settings(**kwargs)
            return settings
        except FileNotFoundError:
            return None

    async def store(self, settings: Settings, _user_id: str | None = None) -> None:
        final_user_id = _user_id or self.user_id
        effective_path = (
            f'users/{final_user_id}/settings.json' if final_user_id else self.path
        )
        json_str = settings.model_dump_json(context={'expose_secrets': True})
        await call_sync_from_async(self.file_store.write, effective_path, json_str)

    @classmethod
    async def get_instance(
        cls, config: AppConfig, user_id: str | None
    ) -> FileSettingsStore:
        file_store = get_file_store(config.file_store, config.file_store_path)
        return FileSettingsStore(file_store, 'settings.json', user_id)
