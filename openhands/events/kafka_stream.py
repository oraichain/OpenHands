import json
import threading
from datetime import datetime
from typing import Any, Callable, Dict

from openhands.core.logger import openhands_logger as logger
from openhands.events.action.message import StreamingMessageAction
from openhands.events.event import Event, EventSource
from openhands.events.event_store import EventStore
from openhands.events.serialization.event import event_from_dict, event_to_dict
from openhands.events.stream import EventStreamSubscriber
from openhands.storage import FileStore

try:
    from kafka import KafkaConsumer, KafkaProducer

    KAFKA_AVAILABLE = True
except ImportError:
    logger.warning(
        'Kafka library not available. Install kafka-python for Kafka support.'
    )
    KAFKA_AVAILABLE = False


class SharedKafkaConsumerManager:
    """Manages shared Kafka consumers for multiple sessions.

    Uses warm-up consumers that handle multiple sessions instead of
    creating one consumer per session per subscriber.
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if hasattr(self, '_initialized'):
            return
        self._initialized = True

        # Shared consumers per subscriber type (not per session)
        self._consumers: Dict[str, KafkaConsumer] = {}
        self._consumer_threads: Dict[str, threading.Thread] = {}

        # Session callbacks: subscriber_id -> session_id -> callback_id -> callback
        self._session_callbacks: Dict[str, Dict[str, Dict[str, Callable]]] = {}
        self._stop_event = threading.Event()
        self._kafka_config = {}
        self._producer = None

    def initialize(self, kafka_config: dict):
        """Initialize the shared consumer manager with Kafka config"""
        self._kafka_config = kafka_config

        # Initialize shared producer
        if KAFKA_AVAILABLE:
            self._init_producer()

            # Pre-initialize consumers for known subscriber types
            self._prewarm_consumers()

    def _init_producer(self):
        """Initialize shared Kafka producer"""
        try:
            producer_config = {
                'bootstrap_servers': self._kafka_config.get(
                    'bootstrap_servers', 'localhost:9092'
                ),
                'value_serializer': lambda v: json.dumps(v).encode('utf-8'),
                'key_serializer': lambda k: k.encode('utf-8') if k else None,
                **self._kafka_config.get('producer_config', {}),
            }
            self._producer = KafkaProducer(**producer_config)
            logger.info('Initialized shared Kafka producer')
        except Exception as e:
            logger.error(f'Failed to initialize shared Kafka producer: {e}')
            self._producer = None

    def _prewarm_consumers(self):
        """Pre-warm consumers for all known subscriber types"""
        known_subscribers = [
            EventStreamSubscriber.AGENT_CONTROLLER,
            EventStreamSubscriber.SERVER,
            EventStreamSubscriber.RUNTIME,
            EventStreamSubscriber.SECURITY_ANALYZER,
            EventStreamSubscriber.RESOLVER,
            EventStreamSubscriber.MEMORY,
            EventStreamSubscriber.MAIN,
            EventStreamSubscriber.TEST,
        ]

        for subscriber_id in known_subscribers:
            self._initialize_shared_consumer(subscriber_id)

        logger.info(f'Pre-warmed {len(known_subscribers)} Kafka consumers')

    def _initialize_shared_consumer(self, subscriber_id: str):
        """Initialize a shared consumer for a subscriber type if not exists"""
        if subscriber_id in self._consumers:
            return

        try:
            # Use subscriber-based topics instead of session-based
            topic_name = f"{self._kafka_config.get('topic_prefix', 'openhands')}.events.{subscriber_id}"

            consumer_config = {
                'bootstrap_servers': self._kafka_config.get(
                    'bootstrap_servers', 'localhost:9092'
                ),
                'group_id': f"{self._kafka_config.get('consumer_group_prefix', 'openhands')}.{subscriber_id}",
                'value_deserializer': lambda m: json.loads(m.decode('utf-8')),
                'auto_offset_reset': 'latest',
                'enable_auto_commit': True,
                **self._kafka_config.get('consumer_config', {}),
            }

            consumer = KafkaConsumer(topic_name, **consumer_config)
            self._consumers[subscriber_id] = consumer

            # Initialize callback structure
            self._session_callbacks[subscriber_id] = {}

            # Start shared consumer thread
            thread = threading.Thread(
                target=self._consume_events_shared,
                args=(subscriber_id, consumer),
                daemon=True,
            )
            thread.start()
            self._consumer_threads[subscriber_id] = thread

            logger.info(f'Started shared consumer for subscriber: {subscriber_id}')

        except Exception as e:
            logger.error(f'Failed to start shared consumer for {subscriber_id}: {e}')

    def subscribe_session(
        self, subscriber_id: str, session_id: str, callback_id: str, callback: Callable
    ):
        """Subscribe a session callback to a shared consumer"""
        with self._lock:
            # Ensure consumer exists for this subscriber type
            if subscriber_id not in self._consumers:
                self._initialize_shared_consumer(subscriber_id)

            if subscriber_id not in self._session_callbacks:
                self._session_callbacks[subscriber_id] = {}

            if session_id not in self._session_callbacks[subscriber_id]:
                self._session_callbacks[subscriber_id][session_id] = {}

            self._session_callbacks[subscriber_id][session_id][callback_id] = callback
            logger.debug(f'Subscribed session {session_id} to {subscriber_id}')

    def unsubscribe_session(
        self, subscriber_id: str, session_id: str, callback_id: str
    ):
        """Unsubscribe a session callback from shared consumer"""
        with self._lock:
            if (
                subscriber_id in self._session_callbacks
                and session_id in self._session_callbacks[subscriber_id]
                and callback_id in self._session_callbacks[subscriber_id][session_id]
            ):
                del self._session_callbacks[subscriber_id][session_id][callback_id]

                # Clean up empty session
                if not self._session_callbacks[subscriber_id][session_id]:
                    del self._session_callbacks[subscriber_id][session_id]
                    logger.debug(
                        f'Cleaned up session {session_id} from {subscriber_id}'
                    )

    def remove_session(self, session_id: str):
        """Remove all callbacks for a session"""
        with self._lock:
            for subscriber_id in list(self._session_callbacks.keys()):
                if session_id in self._session_callbacks[subscriber_id]:
                    del self._session_callbacks[subscriber_id][session_id]
                    logger.debug(f'Removed session {session_id} from {subscriber_id}')

    def publish_event(self, event_data: dict, active_subscribers: list[str]):
        """Publish event to topics for active subscribers"""
        if not self._producer:
            return False

        try:
            topic_prefix = self._kafka_config.get('topic_prefix', 'openhands')
            session_id = event_data.get('session_id')

            # Publish to all active subscriber topics
            for subscriber_id in active_subscribers:
                topic_name = f'{topic_prefix}.events.{subscriber_id}'

                future = self._producer.send(
                    topic_name,
                    value=event_data,
                    key=session_id,  # Use session_id as partition key for ordering
                )
                # Don't block - fire and forget with error handling
                future.add_errback(
                    lambda e, topic=topic_name: logger.error(
                        f'Failed to publish to {topic}: {e}'
                    )
                )

            return True

        except Exception as e:
            logger.error(f'Error publishing to Kafka: {e}')
            return False

    def _consume_events_shared(self, subscriber_id: str, consumer: KafkaConsumer):
        """Shared consumer thread that routes messages to appropriate sessions"""
        try:
            while not self._stop_event.is_set():
                try:
                    message_pack = consumer.poll(timeout_ms=1000)

                    for topic_partition, messages in message_pack.items():
                        for message in messages:
                            try:
                                event_data = message.value

                                # Extract session_id from payload
                                target_session_id = event_data.get('session_id')
                                if not target_session_id:
                                    logger.warning(
                                        f'Message missing session_id in topic {topic_partition.topic}'
                                    )
                                    continue

                                # Route to appropriate session callbacks
                                if (
                                    subscriber_id in self._session_callbacks
                                    and target_session_id
                                    in self._session_callbacks[subscriber_id]
                                ):
                                    event = event_from_dict(event_data)
                                    session_callbacks = self._session_callbacks[
                                        subscriber_id
                                    ][target_session_id]

                                    for (
                                        callback_id,
                                        callback,
                                    ) in session_callbacks.items():
                                        try:
                                            callback(event)
                                        except Exception as e:
                                            logger.error(
                                                f'Error in callback {callback_id} for session {target_session_id}: {e}'
                                            )

                            except Exception as e:
                                logger.error(
                                    f'Error processing message for {subscriber_id}: {e}'
                                )

                except Exception as e:
                    if not self._stop_event.is_set():
                        logger.error(
                            f'Error in shared consumer for {subscriber_id}: {e}'
                        )

        except Exception as e:
            logger.error(
                f'Fatal error in shared consumer thread for {subscriber_id}: {e}'
            )
        finally:
            try:
                consumer.close()
            except Exception:
                pass

    def close(self):
        """Close all shared consumers and producer"""
        logger.info('Shutting down shared Kafka consumer manager')
        self._stop_event.set()

        # Close producer
        if self._producer:
            try:
                self._producer.close()
                logger.info('Closed shared Kafka producer')
            except Exception as e:
                logger.error(f'Error closing shared producer: {e}')

        # Close consumers
        for subscriber_id, consumer in self._consumers.items():
            try:
                consumer.close()
                logger.debug(f'Closed shared consumer {subscriber_id}')
            except Exception as e:
                logger.error(f'Error closing shared consumer {subscriber_id}: {e}')

        # Wait for threads to finish
        for subscriber_id, thread in self._consumer_threads.items():
            try:
                thread.join(timeout=5.0)
                logger.debug(f'Joined consumer thread {subscriber_id}')
            except Exception as e:
                logger.error(f'Error joining thread {subscriber_id}: {e}')

        self._consumers.clear()
        self._consumer_threads.clear()
        self._session_callbacks.clear()


class KafkaEventStream(EventStore):
    """Kafka-based event stream using shared warm-up consumers.

    This implementation uses shared consumers per subscriber type
    and routes messages based on session_id in the payload.
    """

    def __init__(
        self,
        sid: str,
        file_store: FileStore,
        user_id: str | None = None,
    ):
        super().__init__(sid, file_store, user_id)
        self.secrets: dict[str, str] = {}
        self._subscribers: dict[str, dict[str, Callable]] = {}
        self._lock = threading.Lock()
        self._write_page_cache: list[dict] = []

        # Use shared consumer manager
        self._consumer_manager = SharedKafkaConsumerManager()

        if not KAFKA_AVAILABLE:
            logger.warning('Kafka not available, falling back to local processing')

    def subscribe(
        self,
        subscriber_id: EventStreamSubscriber,
        callback: Callable[[Event], None],
        callback_id: str,
    ) -> None:
        """Subscribe to events using shared Kafka consumer"""
        with self._lock:
            if subscriber_id not in self._subscribers:
                self._subscribers[subscriber_id] = {}

            if callback_id in self._subscribers[subscriber_id]:
                raise ValueError(
                    f'Callback ID on subscriber {subscriber_id} already exists: {callback_id}'
                )

            self._subscribers[subscriber_id][callback_id] = callback

            # Subscribe this session to the shared consumer
            if KAFKA_AVAILABLE:
                self._consumer_manager.subscribe_session(
                    subscriber_id, self.sid, callback_id, callback
                )

    def unsubscribe(
        self, subscriber_id: EventStreamSubscriber, callback_id: str
    ) -> None:
        """Unsubscribe from events"""
        with self._lock:
            if subscriber_id not in self._subscribers:
                logger.warning(
                    f'Subscriber not found during unsubscribe: {subscriber_id}'
                )
                return

            if callback_id not in self._subscribers[subscriber_id]:
                logger.warning(f'Callback not found during unsubscribe: {callback_id}')
                return

            del self._subscribers[subscriber_id][callback_id]

            # Unsubscribe from shared consumer
            if KAFKA_AVAILABLE:
                self._consumer_manager.unsubscribe_session(
                    subscriber_id, self.sid, callback_id
                )

    def add_event(self, event: Event, source: EventSource) -> None:
        """Add event to stream - publishes to relevant subscriber topics"""
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

            # Publish to Kafka or process locally
            if KAFKA_AVAILABLE:
                active_subscribers = list(self._subscribers.keys())
                success = self._consumer_manager.publish_event(data, active_subscribers)
                if not success:
                    self._process_locally(event)
            else:
                self._process_locally(event)

    def _process_locally(self, event: Event):
        """Process event locally (fallback when Kafka is not available)"""
        # Call all subscribers directly (like original EventStream)
        for subscriber_id in sorted(self._subscribers.keys()):
            callbacks = self._subscribers[subscriber_id]
            for callback_id, callback in callbacks.items():
                try:
                    callback(event)
                except Exception as e:
                    logger.error(
                        f'Error in callback {callback_id} for subscriber {subscriber_id}: {e}'
                    )

    def _store_cache_page(self, current_write_page: list[dict]):
        """Store a page in the cache (same as original)"""
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
        """Replace secrets in data (same as original)"""
        for key in data:
            if isinstance(data[key], dict):
                data[key] = self._replace_secrets(data[key])
            elif isinstance(data[key], str):
                for secret in self.secrets.values():
                    data[key] = data[key].replace(secret, '<secret_hidden>')
        return data

    def close(self) -> None:
        """Close the event stream"""
        # Remove this session from shared consumers
        if KAFKA_AVAILABLE:
            self._consumer_manager.remove_session(self.sid)
