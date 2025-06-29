import base64
import datetime
import json
import pickle
import sys
import time
from pathlib import Path

from openhands.controller.state.state import State
from openhands.core.config import load_app_config
from openhands.core.database import db_pool
from openhands.core.logger import openhands_logger as logger

migrated_conversations_ids = set()

# get migrated conversations ids from database


def get_migrated_conversations_ids(start_date: datetime.datetime):
    with db_pool.get_connection_context() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                'SELECT conversation_id FROM conversations WHERE created_at >= %s',
                (start_date,),
            )
            ids = [row[0] for row in cursor.fetchall()]
            migrated_conversations_ids.update(ids)


def migrate_conversation_data(
    cursor, user_id: str, conversation_id: str, conversation_dir: Path
) -> int:
    """Migrate all data for a single conversation. Returns number of events migrated."""
    events_migrated = 0

    # Migrate metadata
    metadata_file = conversation_dir / 'metadata.json'
    if metadata_file.exists():
        with open(metadata_file, 'r') as f:
            metadata = json.load(f)

        cursor.execute(
            'SELECT id FROM conversations WHERE conversation_id = %s AND user_id = %s',
            (conversation_id, user_id),
        )

        if cursor.fetchone():
            cursor.execute(
                'UPDATE conversations SET metadata = %s, title = %s WHERE conversation_id = %s AND user_id = %s',
                (
                    json.dumps(metadata),
                    metadata.get('title', ''),
                    conversation_id,
                    user_id,
                ),
            )
        else:
            cursor.execute(
                'INSERT INTO conversations (user_id, conversation_id, metadata, published, title, created_at) VALUES (%s, %s, %s, %s, %s, %s)',
                (
                    user_id,
                    conversation_id,
                    json.dumps(metadata),
                    False,
                    metadata.get('title', ''),
                    metadata.get('created_at'),
                ),
            )

    # Migrate events in bulk
    events_dir = conversation_dir / 'events'
    if events_dir.exists():
        event_files = sorted(
            [f for f in events_dir.glob('*.json') if f.stem.isdigit()],
            key=lambda x: int(x.stem),
        )

        # Collect and filter events
        events_to_insert = []
        events_to_update = []

        for event_file in event_files:
            event_id = int(event_file.stem)
            with open(event_file, 'r') as f:
                event_data = json.load(f)

            # Filter out streaming_action events
            if (
                event_data.get('action') == 'streaming_action'
                or event_data.get('observation') == 'streaming_action'
            ):
                continue

            # Check if event already exists
            cursor.execute(
                'SELECT id FROM conversation_events WHERE conversation_id = %s AND event_id = %s',
                (conversation_id, event_id),
            )

            if cursor.fetchone():
                events_to_update.append(
                    (json.dumps(event_data), conversation_id, event_id)
                )
            else:
                events_to_insert.append(
                    (conversation_id, event_id, json.dumps(event_data))
                )

        # Bulk insert new events
        if events_to_insert:
            cursor.executemany(
                'INSERT INTO conversation_events (conversation_id, event_id, metadata, created_at) VALUES (%s, %s, %s, CURRENT_TIMESTAMP)',
                events_to_insert,
            )
            events_migrated += len(events_to_insert)

        # Bulk update existing events
        if events_to_update:
            cursor.executemany(
                'UPDATE conversation_events SET metadata = %s WHERE conversation_id = %s AND event_id = %s',
                events_to_update,
            )
            events_migrated += len(events_to_update)

    # Migrate agent state
    agent_state_file = conversation_dir / 'agent_state.pkl'
    if agent_state_file.exists():
        state: State
        try:
            with open(agent_state_file, 'rb') as f:
                data = f.read()
                pickled = base64.b64decode(data)
                state = pickle.loads(pickled)
            state_json = state.to_json()

        except Exception:
            state_json = json.dumps({'error': 'Could not serialize agent state'})

        cursor.execute(
            'SELECT id FROM agent_states WHERE conversation_id = %s', (conversation_id,)
        )

        if cursor.fetchone():
            cursor.execute(
                'UPDATE agent_states SET metadata = %s, updated_at = CURRENT_TIMESTAMP WHERE conversation_id = %s',
                (state_json, conversation_id),
            )
        else:
            cursor.execute(
                'INSERT INTO agent_states (conversation_id, metadata, created_at, updated_at) VALUES (%s, %s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)',
                (conversation_id, state_json),
            )

    return events_migrated


def migrate_user_settings(cursor, user_id: str, settings_file: Path) -> None:
    """Migrate user settings."""
    if not settings_file.exists():
        return

    with open(settings_file, 'r') as f:
        settings_data = json.load(f)

    cursor.execute('SELECT id FROM user_settings WHERE user_id = %s', (user_id,))

    if cursor.fetchone():
        cursor.execute(
            'UPDATE user_settings SET settings = %s WHERE user_id = %s',
            (json.dumps(settings_data), user_id),
        )
    else:
        cursor.execute(
            'INSERT INTO user_settings (user_id, settings) VALUES (%s, %s)',
            (user_id, json.dumps(settings_data)),
        )


def migration_from_local_to_database():
    """Main migration function."""
    config_app = load_app_config()

    if not isinstance(config_app.file_store_path, str):
        logger.error('file_store_path must be configured')
        return

    file_store_path = Path(config_app.file_store_path)
    users_dir = file_store_path / 'users'

    if not users_dir.exists():
        logger.info('No users directory found in file store')
        return

    logger.info(f'Starting migration from {file_store_path}')
    db_pool.init_pool()

    total_conversations = 0
    total_events = 0
    total_users = 0

    with db_pool.get_connection_context() as conn:
        with conn.cursor() as cursor:
            for user_dir in users_dir.iterdir():
                if not user_dir.is_dir():
                    continue

                user_id = user_dir.name
                total_users += 1

                # Migrate user settings
                settings_file = user_dir / 'settings.json'
                migrate_user_settings(cursor, user_id, settings_file)

                # Migrate conversations
                conversations_dir = user_dir / 'conversations'
                if not conversations_dir.exists():
                    continue

                for conversation_dir in conversations_dir.iterdir():
                    if not conversation_dir.is_dir():
                        continue

                    conversation_id = conversation_dir.name
                    if conversation_id in migrated_conversations_ids:
                        continue

                    total_conversations += 1

                    # Time the conversation processing
                    start_time = time.time()

                    try:
                        events_count = migrate_conversation_data(
                            cursor, user_id, conversation_id, conversation_dir
                        )
                        conn.commit()

                        end_time = time.time()
                        processing_time = end_time - start_time
                        total_events += events_count

                        logger.info(
                            f'✓ Conversation {conversation_id} completed - {events_count} events, {processing_time:.4f}s'
                        )

                    except Exception as e:
                        end_time = time.time()
                        processing_time = end_time - start_time
                        logger.error(
                            f'✗ Error migrating conversation {conversation_id} after {processing_time:.4f}s: {e}'
                        )
                        conn.rollback()

    logger.info(
        f'🎉 All migration completed! Users: {total_users}, Conversations: {total_conversations}, Events: {total_events}, on {datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")}'
    )


if __name__ == '__main__':
    if len(sys.argv) > 1:
        start_date = datetime.datetime.strptime(sys.argv[1], '%Y-%m-%d')
        get_migrated_conversations_ids(start_date)

    migration_from_local_to_database()
