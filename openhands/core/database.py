import os

from psycopg_pool import ConnectionPool

from openhands.core.logger import openhands_logger as logger


class DBConnectionPool:
    """
    Singleton class for managing database connections.
    Uses connection pooling to efficiently handle database operations.
    """

    _instance = None
    _pool = None
    _initializing = False

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(DBConnectionPool, cls).__new__(cls)
        return cls._instance

    def init_pool(self):
        """Initialize the connection pool if not already initialized."""
        if self._pool is None and not self._initializing:
            try:
                self._initializing = True

                # Get database connection info from environment
                user = os.getenv('POSTGRES_USER')
                password = os.getenv('POSTGRES_PASSWORD')
                database = os.getenv('POSTGRES_DB')
                host = os.getenv('POSTGRES_HOST', 'localhost')
                port = os.getenv('POSTGRES_PORT', '5432')

                # Build connection string for psycopg3
                conninfo = f'host={host} port={port} dbname={database} user={user} password={password}'

                # Create a connection pool
                self._pool = ConnectionPool(
                    conninfo=conninfo,
                    min_size=2,
                    max_size=10,
                )
                logger.info('Database connection pool initialized successfully')
            except Exception as e:
                logger.error(f'Failed to initialize connection pool: {str(e)}')
                self._pool = None
            finally:
                self._initializing = False

        return self._pool

    def get_connection(self):
        """Get a connection from the pool."""
        pool = self.init_pool()
        if pool:
            return pool.getconn()
        return None

    def release_connection(self, conn):
        """Return a connection to the pool."""
        if self._pool and conn:
            self._pool.putconn(conn)

    def close_pool(self):
        """Close the connection pool."""
        if self._pool:
            self._pool.close()
            self._pool = None


db_pool = DBConnectionPool()
