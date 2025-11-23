from datetime import datetime
import structlog
import paho.mqtt.client as mqtt
from octosynk.config import Config

logger = structlog.stdlib.get_logger(__name__)


class MQTTClient:
    def __init__(self, config: Config):
        self.config = config
        self.client = None
        self.enabled_state = "ON"  # Default to enabled if MQTT not configured

        if not config.mqtt_broker:
            logger.debug("MQTT not configured, running in standalone mode")
            return

        self.client = mqtt.Client()

        # Set up callbacks
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message

        # Set credentials if provided
        if config.mqtt_username and config.mqtt_password:
            self.client.username_pw_set(config.mqtt_username, config.mqtt_password)

        try:
            self.client.connect(config.mqtt_broker, config.mqtt_port, 60)
            self.client.loop_start()
            logger.info("Connected to MQTT broker", broker=config.mqtt_broker, port=config.mqtt_port)
        except Exception as e:
            logger.warning("Failed to connect to MQTT broker", error=str(e))
            self.client = None

    def _on_connect(self, client, userdata, flags, rc):
        """Callback when connected to MQTT broker"""
        if rc == 0:
            logger.info("MQTT connection established")
            # Subscribe to the enabled state topic
            enabled_topic = f"{self.config.mqtt_topic_prefix}/enabled"
            client.subscribe(enabled_topic)
            logger.debug("Subscribed to topic", topic=enabled_topic)

            # Publish initial state
            self.publish_state("enabled", self.enabled_state)
        else:
            logger.error("MQTT connection failed", return_code=rc)

    def _on_message(self, client, userdata, msg):
        """Callback when message received"""
        topic = msg.topic
        payload = msg.payload.decode()

        if topic == f"{self.config.mqtt_topic_prefix}/enabled":
            self.enabled_state = payload
            logger.info("Enabled state updated", state=payload)

    def is_enabled(self) -> bool:
        """Check if syncing is enabled via MQTT"""
        if not self.client:
            # MQTT not configured, always enabled
            return True

        return self.enabled_state == "ON"

    def publish_state(self, key: str, value: str):
        """Publish state to MQTT topic"""
        if not self.client:
            return

        topic = f"{self.config.mqtt_topic_prefix}/{key}"
        try:
            self.client.publish(topic, value, retain=True)
            logger.debug("Published MQTT state", topic=topic, value=value)
        except Exception as e:
            logger.warning("Failed to publish MQTT state", error=str(e), topic=topic)

    def publish_last_sync(self):
        """Publish last sync timestamp"""
        timestamp = datetime.now().isoformat()
        self.publish_state("last_sync", timestamp)

    def publish_active_slots(self, count: int):
        """Publish number of active charging slots"""
        self.publish_state("active_slots", str(count))

    def publish_next_dispatch(self, dispatch_time: str):
        """Publish next dispatch time"""
        self.publish_state("next_dispatch", dispatch_time)

    def disconnect(self):
        """Disconnect from MQTT broker"""
        if self.client:
            self.client.loop_stop()
            self.client.disconnect()
            logger.debug("Disconnected from MQTT broker")
