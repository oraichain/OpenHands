import json
import threading
from typing import Callable

from kafka import KafkaConsumer

from openhands.core.config import load_app_config
from openhands.core.logger import openhands_logger as logger
from openhands.events.event import Event
from openhands.events.serialization.event import event_from_dict
from openhands.utils.shutdown_listener import should_continue

config = load_app_config()


class KafkaEventConsumer:
    """Generic Kafka event consumer that components can inherit from or use as a mixin."""

    def __init__(self, consumer_group: str, topic_suffix: str, session_id: str):
        self.consumer_group = consumer_group
        self.topic_suffix = topic_suffix
        self.session_id = session_id
        self._consumer: KafkaConsumer | None = None
        self._consumer_thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._event_handlers: list[Callable[[Event], None]] = []

    def add_event_handler(self, handler: Callable[[Event], None]):
        """Add an event handler function"""
        self._event_handlers.append(handler)

    def start_consumer(self):
        """Start the Kafka consumer in a background thread"""
        if self._consumer_thread and self._consumer_thread.is_alive():
            logger.warning(f'Consumer already running for {self.consumer_group}')
            return

        try:
            topic_name = f'{config.kafka.topic_prefix}.events.{self.topic_suffix}'

            consumer_config = {
                'bootstrap_servers': config.kafka.bootstrap_servers,
                'group_id': f'{config.kafka.consumer_group_prefix}.{self.consumer_group}',
                'value_deserializer': lambda m: json.loads(m.decode('utf-8')),
                'enable_auto_commit': False,  # We handle commits manually to prevent message loops
                'auto_offset_reset': 'latest',  # Start from latest messages for new consumers
                'session_timeout_ms': 30000,  # 30 seconds
                'heartbeat_interval_ms': 10000,  # 10 seconds
                'max_poll_records': 100,  # Process in smaller batches
                **config.kafka.consumer_config,  # Allow overrides from config
            }

            logger.debug(
                f'Starting Kafka consumer for session {self.session_id} with group {consumer_config["group_id"]} on topic {topic_name}'
            )

            self._consumer = KafkaConsumer(topic_name, **consumer_config)

            self._consumer_thread = threading.Thread(
                target=self._consume_events,
                daemon=True,
            )
            self._consumer_thread.start()

            logger.info(
                f'🔄 Started Kafka consumer for {self.consumer_group} on topic {topic_name} (session: {self.session_id})'
            )

        except Exception as e:
            logger.error(
                f'Failed to start Kafka consumer for {self.consumer_group}: {e}'
            )

    def stop_consumer(self):
        """Stop the Kafka consumer"""
        self._stop_event.set()

        if self._consumer_thread and self._consumer_thread.is_alive():
            self._consumer_thread.join(timeout=5.0)

        if self._consumer:
            try:
                self._consumer.close()
                logger.info(f'Stopped Kafka consumer for {self.consumer_group}')
            except Exception as e:
                logger.error(f'Error stopping Kafka consumer: {e}')

    def _consume_events(self):
        if not self._consumer:
            return

        logger.info(
            f'🔄 Starting Kafka consumer loop for {self.consumer_group} (session: {self.session_id})'
        )

        try:
            while should_continue() and not self._stop_event.is_set():
                try:
                    message_pack = self._consumer.poll(timeout_ms=1000)

                    if message_pack:
                        logger.debug(
                            f'📨 Consumer {self.consumer_group} received {len(message_pack)} message packs'
                        )

                    for topic_partition, messages in message_pack.items():
                        logger.debug(
                            f'📨 Consumer {self.consumer_group} processing {len(messages)} messages from {topic_partition}'
                        )
                        for message in messages:
                            try:
                                event_data = message.value

                                # Filter by session_id
                                message_session_id = event_data.get('session_id')
                                event_type = event_data.get('action') or event_data.get(
                                    'observation'
                                )
                                event_id = event_data.get('id')

                                logger.debug(
                                    f'📥 Consumer {self.consumer_group} received event {event_type} (id: {event_id}) for session {message_session_id} (expecting {self.session_id})'
                                )

                                if message_session_id != self.session_id:
                                    logger.debug(
                                        f'⏭️ Skipping event {event_type} - session mismatch ({message_session_id} != {self.session_id})'
                                    )
                                    # Still need to "process" this message by continuing, so it gets committed
                                    continue

                                logger.info(
                                    f'🎯 Processing event {event_type} (id: {event_id}) for session {message_session_id} in consumer {self.consumer_group}'
                                )

                                # Convert to event object
                                event = event_from_dict(event_data)

                                # Process with all handlers
                                for handler in self._event_handlers:
                                    try:
                                        logger.debug(
                                            f'🔧 Calling event handler for {event_type} in {self.consumer_group}'
                                        )
                                        handler(event)
                                        logger.debug(
                                            f'✅ Event handler completed for {event_type} in {self.consumer_group}'
                                        )
                                    except Exception as e:
                                        logger.error(
                                            f'❌ Error in event handler for {self.consumer_group}: {e}',
                                            exc_info=True,
                                        )
                                        # Continue processing other handlers and don't fail the message

                            except Exception as e:
                                logger.error(
                                    f'❌ Error processing Kafka message in {self.consumer_group}: {e}',
                                    exc_info=True,
                                )
                    self._consumer.commit()
                except Exception as e:
                    if not self._stop_event.is_set():
                        logger.error(
                            f'❌ Error in Kafka consumer loop for {self.consumer_group}: {e}',
                            exc_info=True,
                        )

        except Exception as e:
            logger.error(
                f'💀 Fatal error in Kafka consumer {self.consumer_group}: {e}',
                exc_info=True,
            )
        finally:
            logger.info(f'🛑 Kafka consumer loop stopped for {self.consumer_group}')
            if self._consumer:
                try:
                    self._consumer.close()
                except Exception:
                    pass
