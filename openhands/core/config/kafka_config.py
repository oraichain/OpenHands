from pydantic import BaseModel, Field, ValidationError


class KafkaConfig(BaseModel):
    """Configuration for Kafka event streaming.

    Attributes:
        enabled: Whether to use Kafka for event streaming
        bootstrap_servers: Kafka bootstrap servers
        topic_prefix: Prefix for Kafka topics
        consumer_group_prefix: Prefix for consumer groups
        producer_config: Additional producer configuration
        consumer_config: Additional consumer configuration
    """

    enabled: bool = Field(default=False)
    bootstrap_servers: str = Field(default='localhost:9092')
    topic_prefix: str = Field(default='openhands')
    consumer_group_prefix: str = Field(default='openhands')
    producer_config: dict = Field(default_factory=dict)
    consumer_config: dict = Field(default_factory=dict)

    model_config = {'extra': 'forbid'}

    @classmethod
    def from_toml_section(cls, data: dict) -> dict[str, 'KafkaConfig']:
        """
        Create a mapping of KafkaConfig instances from a toml dictionary representing the [kafka] section.

        The configuration is built from all keys in data.

        Returns:
            dict[str, KafkaConfig]: A mapping where the key "kafka" corresponds to the [kafka] configuration
        """

        # Initialize the result mapping
        kafka_mapping: dict[str, KafkaConfig] = {}

        # Try to create the configuration instance
        try:
            kafka_mapping['kafka'] = cls.model_validate(data)
        except ValidationError as e:
            raise ValueError(f'Invalid kafka configuration: {e}')

        return kafka_mapping
