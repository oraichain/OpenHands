import json
from typing import List, Optional

import psycopg

from openhands.core.database import db_pool
from openhands.core.logger import openhands_logger as logger
from openhands.storage.files import FileStore
from openhands.storage.locations import parse_conversation_path


class DatabaseFileStore(FileStore):
    def write(self, path: str, contents: str | bytes) -> None:
        """Write contents to database based on path type."""
        try:
            parsed_path = parse_conversation_path(path)
            logger.info(f'Parsed path: {parsed_path}')
            if parsed_path is None:
                logger.error(f'Failed to parse conversation path: {path}')
                return

            user_id = parsed_path['user_id']
            session_id = parsed_path['session_id']
            event_id = parsed_path['event_id']
            path_type = parsed_path['type']

            conn: psycopg.Connection | None = None
            try:
                conn = db_pool.get_connection()
                if not conn:
                    logger.error('Failed to get database connection from pool')
                    return

                with conn.cursor() as cursor:
                    if path_type == 'events':
                        self._write_event(cursor, session_id, event_id, contents)
                    elif path_type == 'metadata':
                        self._write_metadata(cursor, session_id, contents, user_id)
                    else:
                        logger.warning(f'Unsupported path type for write: {path_type}')
                        return

                    conn.commit()
                    logger.debug(
                        f'Successfully wrote {path_type} for session {session_id}'
                    )

            except Exception as e:
                if conn:
                    conn.rollback()
                logger.error(f'Database error while writing {path}: {str(e)}')
                raise
            finally:
                if conn:
                    db_pool.release_connection(conn)

        except Exception as e:
            logger.error(f'Error writing to database for path {path}: {str(e)}')
            raise

    def _write_event(
        self,
        cursor: psycopg.Cursor,
        conversation_id: str,
        event_id: int,
        contents: str | bytes,
    ) -> None:
        """Write event data to conversation_events table."""
        if isinstance(contents, bytes):
            contents = contents.decode('utf-8')

        try:
            metadata = json.loads(contents)
        except json.JSONDecodeError as e:
            logger.error(
                f'Failed to parse event JSON for conversation {conversation_id}, event {event_id}: {e}'
            )
            raise

        # First try to update existing event
        cursor.execute(
            """
            UPDATE conversation_events
            SET metadata = %s, created_at = CURRENT_TIMESTAMP
            WHERE conversation_id = %s AND event_id = %s
            """,
            (json.dumps(metadata), conversation_id, event_id),
        )

        # If no rows were updated, insert new event
        if cursor.rowcount == 0:
            cursor.execute(
                """
                INSERT INTO conversation_events (conversation_id, event_id, metadata, created_at)
                VALUES (%s, %s, %s, CURRENT_TIMESTAMP)
                """,
                (conversation_id, event_id, json.dumps(metadata)),
            )

    def _write_metadata(
        self,
        cursor: psycopg.Cursor,
        conversation_id: str,
        contents: str | bytes,
        user_id: Optional[str],
    ) -> None:
        """Write metadata to conversations table."""
        if isinstance(contents, bytes):
            contents = contents.decode('utf-8')

        try:
            metadata = json.loads(contents)
        except json.JSONDecodeError as e:
            logger.error(
                f'Failed to parse metadata JSON for conversation {conversation_id}: {e}'
            )
            raise

        # First check if conversation exists
        cursor.execute(
            'SELECT id FROM conversations WHERE conversation_id = %s AND user_id = %s',
            (conversation_id, user_id or ''),
        )

        if cursor.fetchone():
            # Update existing conversation
            cursor.execute(
                """
                UPDATE conversations
                SET metadata = %s
                WHERE conversation_id = %s AND user_id = %s
                """,
                (json.dumps(metadata), conversation_id, user_id or ''),
            )
        else:
            # Insert new conversation
            cursor.execute(
                """
                INSERT INTO conversations (user_id, conversation_id, metadata, published, created_at)
                VALUES (%s, %s, %s, false, CURRENT_TIMESTAMP)
                """,
                (user_id or '', conversation_id, json.dumps(metadata)),
            )

    def read(self, path: str) -> str:
        """Read contents from database based on path type."""
        try:
            parsed_path = parse_conversation_path(path)
            if parsed_path is None:
                logger.error(f'Failed to parse conversation path: {path}')
                raise FileNotFoundError(f'Invalid path format: {path}')

            session_id = parsed_path['session_id']
            event_id = parsed_path['event_id']
            path_type = parsed_path['type']

            conn: psycopg.Connection | None = None
            try:
                conn = db_pool.get_connection()
                if not conn:
                    logger.error('Failed to get database connection from pool')
                    raise ConnectionError('Could not connect to database')

                with conn.cursor() as cursor:
                    if path_type == 'events':
                        result = self._read_event(cursor, session_id, event_id)
                    elif path_type == 'metadata':
                        user_id = parsed_path['user_id']
                        result = self._read_metadata(cursor, session_id, user_id)
                    else:
                        logger.warning(f'Unsupported path type for read: {path_type}')
                        raise FileNotFoundError(f'Unsupported path type: {path_type}')

                return result

            except Exception as e:
                logger.error(f'Database error while reading {path}: {str(e)}')
                raise
            finally:
                if conn:
                    db_pool.release_connection(conn)

        except Exception as e:
            logger.error(f'Error reading from database for path {path}: {str(e)}')
            raise

    def _read_event(
        self, cursor: psycopg.Cursor, conversation_id: str, event_id: int
    ) -> str:
        """Read event data from conversation_events table."""
        cursor.execute(
            'SELECT metadata FROM conversation_events WHERE conversation_id = %s AND event_id = %s',
            (conversation_id, event_id),
        )

        result = cursor.fetchone()
        if result is None:
            raise FileNotFoundError(
                f'Event {event_id} not found for conversation {conversation_id}'
            )

        return json.dumps(result[0]) if isinstance(result[0], dict) else result[0]

    def _read_metadata(
        self, cursor, conversation_id: str, user_id: Optional[str]
    ) -> str:
        """Read metadata from conversations table."""
        cursor.execute(
            'SELECT metadata FROM conversations WHERE conversation_id = %s AND user_id = %s',
            (conversation_id, user_id or ''),
        )

        result = cursor.fetchone()
        if result is None:
            raise FileNotFoundError(
                f'Metadata not found for conversation {conversation_id}'
            )

        return json.dumps(result[0]) if isinstance(result[0], dict) else result[0]

    def list(self, path: str) -> List[str]:
        """List files/events based on path pattern."""
        try:
            parsed_path = parse_conversation_path(path)
            if parsed_path is None:
                logger.error(f'Failed to parse conversation path for listing: {path}')
                return []

            session_id = parsed_path['session_id']
            path_type = parsed_path['type']

            conn: psycopg.Connection | None = None
            try:
                conn = db_pool.get_connection()
                if not conn:
                    logger.error('Failed to get database connection from pool')
                    return []

                with conn.cursor() as cursor:
                    if path_type == 'events':
                        result = self._list_events_for_conversation(cursor, session_id)
                    else:
                        logger.warning(
                            f'Listing not supported for path type: {path_type}'
                        )
                        result = []

                return result

            except Exception as e:
                logger.error(f'Database error while listing {path}: {str(e)}')
                return []
            finally:
                if conn:
                    db_pool.release_connection(conn)

        except Exception as e:
            logger.error(f'Error listing database for path {path}: {str(e)}')
            return []

    def _list_events_for_conversation(
        self, cursor: psycopg.Cursor, conversation_id: str
    ) -> List[str]:
        """List all metadata entries for a conversation from conversation_events table."""
        cursor.execute(
            'SELECT metadata FROM conversation_events WHERE conversation_id = %s ORDER BY created_at',
            (conversation_id,),
        )

        results = cursor.fetchall()
        metadata_list = []
        for metadata in results:
            metadata_list.append(json.dumps(metadata[0]))

        return metadata_list

    def delete(self, path: str) -> None:
        """Delete data from database based on path type."""
        try:
            parsed_path = parse_conversation_path(path)
            if parsed_path is None:
                logger.error(f'Failed to parse conversation path: {path}')
                return

            session_id = parsed_path['session_id']
            event_id = parsed_path['event_id']
            path_type = parsed_path['type']

            conn: psycopg.Connection | None = None
            try:
                conn = db_pool.get_connection()
                if not conn:
                    logger.error('Failed to get database connection from pool')
                    return

                with conn.cursor() as cursor:
                    if path_type == 'events':
                        self._delete_event(cursor, session_id, event_id)
                    elif path_type == 'metadata':
                        user_id = parsed_path['user_id']
                        self._delete_metadata(cursor, session_id, user_id)
                    else:
                        logger.warning(f'Unsupported path type for delete: {path_type}')
                        return

                    conn.commit()
                    logger.debug(
                        f'Successfully deleted {path_type} for session {session_id}'
                    )

            except Exception as e:
                if conn:
                    conn.rollback()
                logger.error(f'Database error while deleting {path}: {str(e)}')
                raise
            finally:
                if conn:
                    db_pool.release_connection(conn)

        except Exception as e:
            logger.error(f'Error deleting from database for path {path}: {str(e)}')
            raise

    def _delete_event(
        self, cursor: psycopg.Cursor, conversation_id: str, event_id: int
    ) -> None:
        """Delete event from conversation_events table."""
        cursor.execute(
            'DELETE FROM conversation_events WHERE conversation_id = %s AND event_id = %s',
            (conversation_id, event_id),
        )

    def _delete_metadata(
        self, cursor: psycopg.Cursor, conversation_id: str, user_id: Optional[str]
    ) -> None:
        """Delete conversation metadata (set metadata to empty)."""
        cursor.execute(
            """
            UPDATE conversations
            SET metadata = '{}'::jsonb
            WHERE conversation_id = %s AND user_id = %s
            """,
            (conversation_id, user_id or ''),
        )
