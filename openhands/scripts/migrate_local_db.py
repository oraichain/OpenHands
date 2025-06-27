from openhands.core.config import load_app_config
from openhands.storage import get_file_store

config_app = load_app_config()

file_store = get_file_store('local', config_app.file_store_path)


# def migration_from_local_to_database():
# migrate all the conversation from local to database
# get
# we should read the local file from "workspace/file_store"

# we should read the local file from "workspace/file_store"
