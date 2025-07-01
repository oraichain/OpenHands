from openhands.core.logger import openhands_logger as logger
from openhands.events.kafka_stream import KafkaEventStream
from openhands.events.stream import EventStream
from openhands.storage import FileStore


def create_event_stream(
    sid: str,
    file_store: FileStore,
    user_id: str | None = None,
    max_delay_time: float = 0.5,
) -> EventStream | KafkaEventStream:
    """Create an event stream based on configuration.

    Args:
        sid: Session ID
        file_store: File store instance
        config: Application configuration
        user_id: Optional user ID
        max_delay_time: Maximum delay time for threading-based stream

    Returns:
        EventStream or KafkaEventStream based on configuration
    """
    from openhands.core.config import load_app_config

    config = load_app_config()

    if config.kafka.enabled:
        logger.info(f'Creating Kafka event stream for session {sid}')
        return KafkaEventStream(
            sid=sid,
            file_store=file_store,
            user_id=user_id,
        )
    else:
        logger.info(f'Creating standard event stream for session {sid}')
        return EventStream(
            sid=sid,
            file_store=file_store,
            user_id=user_id,
            max_delay_time=max_delay_time,
        )
