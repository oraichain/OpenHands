import json
import threading
from datetime import datetime
from typing import Any, Callable

from kafka import KafkaProducer

from openhands.core.config import load_app_config
from openhands.core.logger import openhands_logger as logger
from openhands.events.action.message import StreamingMessageAction
from openhands.events.event import Event, EventSource
from openhands.events.event_store import EventStore
from openhands.events.serialization.event import event_from_dict, event_to_dict
from openhands.events.stream import EventStreamSubscriber
from openhands.storage import FileStore

config = load_app_config()


class KafkaEventStream(EventStore):
    """Simplified Kafka-based event stream that only publishes events.

    Each consumer component manages its own Kafka consumer independently.
    This eliminates the complex threading model and subscription callbacks.
    """

    def __init__(
        self,
        sid: str,
        file_store: FileStore,
        user_id: str | None = None,
    ):
        super().__init__(sid, file_store, user_id)
        self.secrets: dict[str, str] = {}
        self._lock = threading.Lock()
        self._write_page_cache: list[dict] = []
        self._producer: KafkaProducer | None = None
        self._init_producer()

    def _init_producer(self):
        """Initialize Kafka producer for publishing events"""
        try:
            producer_config = {
                'bootstrap_servers': config.kafka.bootstrap_servers,
                'value_serializer': lambda v: json.dumps(v).encode('utf-8'),
                'key_serializer': lambda k: k.encode('utf-8') if k else None,
                **config.kafka.producer_config,
            }
            self._producer = KafkaProducer(**producer_config)
            logger.info(f'Initialized Kafka producer for session {self.sid}')
        except Exception as e:
            logger.error(f'Failed to initialize Kafka producer: {e}')
            self._producer = None

    def subscribe(
        self,
        subscriber_id: EventStreamSubscriber,
        callback: Callable[[Event], None],
        callback_id: str,
    ) -> None:
        pass

    def unsubscribe(
        self, subscriber_id: EventStreamSubscriber, callback_id: str
    ) -> None:
        pass

    def add_event(
        self,
        event: Event,
        source: EventSource,
        target_consumers: list[str] | None = None,
    ) -> None:
        """Add event to stream and publish to Kafka topics

        Args:
            event: The event to add
            source: The source of the event
            target_consumers: Optional list of specific consumers to target (e.g., ['server', 'agent_controller'])
                            If None, publishes to all consumers
        """
        if event.id != Event.INVALID_ID:
            raise ValueError(
                f'Event already has an ID:{event.id}. It was probably added back to the EventStream from inside a handler, triggering a loop.'
            )

        event._timestamp = datetime.now().isoformat()
        event._source = source  # type: ignore [attr-defined]

        with self._lock:
            event._id = self.cur_id  # type: ignore [attr-defined]
            self.cur_id += 1

            # Handle file storage and caching
            current_write_page = self._write_page_cache
            data = event_to_dict(event)
            data = self._replace_secrets(data)

            # Add session_id to payload for routing
            data['session_id'] = self.sid

            event = event_from_dict(data)
            current_write_page.append(data)

            if len(current_write_page) == self.cache_size:
                self._write_page_cache = []

        if event.id is not None:
            if not isinstance(event, StreamingMessageAction):
                # Write the event to the store
                self.file_store.write(
                    self._get_filename_for_id(event.id, self.user_id), json.dumps(data)
                )

            # Store the cache page
            self._store_cache_page(current_write_page)

            # Publish to Kafka topics
            self._publish_event(data, target_consumers)

    def _publish_event(
        self, event_data: dict, target_consumers: list[str] | None = None
    ):
        """Publish event to relevant Kafka topics

        Args:
            event_data: The event data to publish
            target_consumers: Optional list of specific consumers to target
        """
        if not self._producer:
            logger.warning('No Kafka producer available, event not published')
            return

        try:
            # Determine which topics to publish to
            # if target_consumers:
            #     topics = [
            #         f'{config.kafka.topic_prefix}.events.{consumer}'
            #         for consumer in target_consumers
            #     ]
            # else:
            #     # Publish to all topic types - consumers will filter what they need
            #     topics = [
            #         f'{config.kafka.topic_prefix}.events.agent_controller',
            #         f'{config.kafka.topic_prefix}.events.server',
            #         f'{config.kafka.topic_prefix}.events.runtime',
            #         f'{config.kafka.topic_prefix}.events.security_analyzer',
            #         f'{config.kafka.topic_prefix}.events.memory',
            #     ]
            topics = [
                f'{config.kafka.topic_prefix}.events.agent_controller',
                f'{config.kafka.topic_prefix}.events.server',
                f'{config.kafka.topic_prefix}.events.runtime',
                # f'{config.kafka.topic_prefix}.events.security_analyzer',
                # f'{config.kafka.topic_prefix}.events.memory',
            ]

            session_id = event_data.get('session_id')
            event_type = event_data.get('action') or event_data.get('observation')
            event_id = event_data.get('id')
            event_source = event_data.get('source')

            logger.info(
                f'📤 KafkaEventStream publishing event {event_type} (id: {event_id}, source: {event_source}) for session {session_id} to {len(topics)} topics'
            )
            logger.debug(f'📤 Publishing to topics: {topics}')

            for topic in topics:
                try:
                    logger.debug(f'📨 Sending event {event_type} to topic {topic}')
                    future = self._producer.send(
                        topic,
                        value=event_data,
                        key=session_id,  # Use session_id as partition key for ordering
                    )
                    # Add both success and error callbacks
                    future.add_callback(
                        lambda metadata, t=topic: logger.debug(
                            f'✅ Successfully published to {t}: partition={metadata.partition}, offset={metadata.offset}'
                        )
                    )
                    future.add_errback(
                        lambda e, t=topic: logger.error(
                            f'❌ Failed to publish to {t}: {e}'
                        )
                    )
                except Exception as e:
                    logger.error(f'❌ Error publishing to topic {topic}: {e}')

            # Flush producer to ensure messages are sent immediately
            try:
                self._producer.flush(timeout=1.0)  # Wait up to 1 second for flush
                logger.info(
                    f'✅ Published and flushed event {event_type} (id: {event_id}) for session {session_id}'
                )
            except Exception as e:
                logger.error(f'❌ Error flushing Kafka producer: {e}')

        except Exception as e:
            logger.error(f'💀 Error publishing event to Kafka: {e}', exc_info=True)

    def _store_cache_page(self, current_write_page: list[dict]):
        """Store a page in the cache"""
        if len(current_write_page) < self.cache_size:
            return
        start = current_write_page[0]['id']
        end = start + self.cache_size
        contents = json.dumps(current_write_page)
        cache_filename = self._get_filename_for_cache(start, end)
        self.file_store.write(cache_filename, contents)

    def set_secrets(self, secrets: dict[str, str]) -> None:
        """Set secrets for redaction"""
        self.secrets = secrets.copy()

    def update_secrets(self, secrets: dict[str, str]) -> None:
        """Update secrets for redaction"""
        self.secrets.update(secrets)

    def _replace_secrets(self, data: dict[str, Any]) -> dict[str, Any]:
        """Replace secrets in data"""
        for key in data:
            if isinstance(data[key], dict):
                data[key] = self._replace_secrets(data[key])
            elif isinstance(data[key], str):
                for secret in self.secrets.values():
                    data[key] = data[key].replace(secret, '<secret_hidden>')
        return data

    def close(self) -> None:
        """Close the event stream"""
        if self._producer:
            try:
                self._producer.close()
                logger.info(f'Closed Kafka producer for session {self.sid}')
            except Exception as e:
                logger.error(f'Error closing Kafka producer: {e}')
