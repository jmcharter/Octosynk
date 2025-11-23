from datetime import datetime
import json
import structlog
import paho.mqtt.client as mqtt
from octosynk.config import Config

logger = structlog.stdlib.get_logger(__name__)


class MQTTClient:
    def __init__(self, config: Config):
        self.config = config
        self.client = None
        self.enabled_state = None  # Will be set from retained message or default to ON

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

            # Publish Home Assistant discovery configs
            self._publish_discovery_configs()

            # Subscribe to both state and command topics
            # Any retained message will arrive immediately in _on_message
            state_topic = f"{self.config.mqtt_topic_prefix}/enabled"
            command_topic = f"{self.config.mqtt_topic_prefix}/enabled/set"
            client.subscribe(state_topic)
            client.subscribe(command_topic)
            logger.debug("Subscribed to topics", state_topic=state_topic, command_topic=command_topic)
        else:
            logger.error("MQTT connection failed", return_code=rc)

    def _on_message(self, client, userdata, msg):
        """Callback when message received"""
        topic = msg.topic
        payload = msg.payload.decode()

        # Ignore empty messages (used to clear retained messages)
        if not payload:
            return

        if topic == f"{self.config.mqtt_topic_prefix}/enabled/set":
            # Command received from Home Assistant - update state and publish back
            self.enabled_state = payload
            self.publish_state("enabled", payload)
            logger.info("Enabled state changed via command", state=payload)
        elif topic == f"{self.config.mqtt_topic_prefix}/enabled":
            # State update (retained message on reconnect)
            self.enabled_state = payload
            logger.info("Enabled state updated", state=payload)

    def _publish_discovery_configs(self):
        """Publish Home Assistant MQTT Discovery configurations"""
        if not self.client:
            return

        base_topic = f"homeassistant"
        device_config = {
            "identifiers": ["octosynk"],
            "name": "Octosynk",
            "model": "Octopus Intelligent Sync",
            "manufacturer": "Octosynk",
        }

        # Switch for enabling/disabling sync
        switch_config = {
            "name": "Auto-Sync",
            "unique_id": "octosynk_auto_sync",
            "command_topic": f"{self.config.mqtt_topic_prefix}/enabled/set",
            "state_topic": f"{self.config.mqtt_topic_prefix}/enabled",
            "payload_on": "ON",
            "payload_off": "OFF",
            "optimistic": True,  # Update UI immediately without waiting for state confirmation
            "icon": "mdi:solar-power",
            "device": device_config,
        }
        self.client.publish(
            f"{base_topic}/switch/{self.config.mqtt_topic_prefix}/auto_sync/config",
            json.dumps(switch_config),
            retain=True,
        )

        # Sensor for last sync time
        last_sync_config = {
            "name": "Last Sync",
            "unique_id": "octosynk_last_sync",
            "state_topic": f"{self.config.mqtt_topic_prefix}/last_sync",
            "device_class": "timestamp",
            "icon": "mdi:clock-check",
            "device": device_config,
        }
        self.client.publish(
            f"{base_topic}/sensor/{self.config.mqtt_topic_prefix}/last_sync/config",
            json.dumps(last_sync_config),
            retain=True,
        )

        # Sensor for active slots
        active_slots_config = {
            "name": "Active Slots",
            "unique_id": "octosynk_active_slots",
            "state_topic": f"{self.config.mqtt_topic_prefix}/active_slots",
            "unit_of_measurement": "slots",
            "icon": "mdi:calendar-clock",
            "device": device_config,
        }
        self.client.publish(
            f"{base_topic}/sensor/{self.config.mqtt_topic_prefix}/active_slots/config",
            json.dumps(active_slots_config),
            retain=True,
        )

        # Sensor for next dispatch
        next_dispatch_config = {
            "name": "Next Dispatch",
            "unique_id": "octosynk_next_dispatch",
            "state_topic": f"{self.config.mqtt_topic_prefix}/next_dispatch",
            "device_class": "timestamp",
            "icon": "mdi:clock-start",
            "device": device_config,
        }
        self.client.publish(
            f"{base_topic}/sensor/{self.config.mqtt_topic_prefix}/next_dispatch/config",
            json.dumps(next_dispatch_config),
            retain=True,
        )

        logger.info("Published Home Assistant discovery configurations")

    def is_enabled(self) -> bool:
        """Check if syncing is enabled via MQTT

        Returns True if enabled. On first run (no retained state),
        defaults to ON and publishes it as retained.
        """
        if not self.client:
            # MQTT not configured, always enabled
            return True

        # If no state received from MQTT (first run), default to ON
        if self.enabled_state is None:
            logger.info("No existing state found, defaulting to enabled")
            self.publish_state("enabled", "ON")
            self.enabled_state = "ON"
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
