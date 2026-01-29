"""
MQTT client wrapper for PushButtonDND
Handles connection, publishing, subscribing, and Home Assistant auto-discovery
"""

import time
import json


def unique_id():
    """Generate unique ID from MAC address"""
    try:
        import network
        import ubinascii
        wlan = network.WLAN(network.STA_IF)
        mac = ubinascii.hexlify(wlan.config('mac')).decode()
        return mac
    except Exception as e:
        print(f"[MQTT] Error getting MAC address: {e}")
        return "unknown"


class MQTTClient:
    """MQTT client with Home Assistant auto-discovery support"""

    def __init__(self, mqtt_config):
        """
        Initialize MQTT client with configuration
        mqtt_config: dict with broker, port, username, password, topic_prefix, device_name, qos
        """
        self.config = mqtt_config
        self.client = None
        self.connected = False
        self.retry_count = 0
        self.max_retries = 10
        self.retry_delays = [5, 10, 30, 60, 60, 60, 60, 60, 60, 60]  # Exponential backoff
        self.message_callback = None
        self.client_id = f"pushbuttondnd_{unique_id()}"
        # Non-blocking reconnect state
        self._reconnect_pending = False
        self._reconnect_after = 0  # ticks_ms when next attempt is allowed
        self._gave_up = False

    def connect(self):
        """
        Connect to MQTT broker with Last Will and Testament
        Returns: True if successful, False otherwise
        """
        try:
            from umqtt.simple import MQTTClient as MQTT

            print(f"[MQTT] Connecting to {self.config['broker']}:{self.config['port']}...")

            # Create MQTT client
            self.client = MQTT(
                client_id=self.client_id,
                server=self.config['broker'],
                port=self.config['port'],
                user=self.config['username'] if self.config['username'] else None,
                password=self.config['password'] if self.config['password'] else None,
                keepalive=60
            )

            # Set Last Will and Testament (LWT) before connecting
            lwt_topic = f"{self.config['topic_prefix']}/availability"
            self.client.set_last_will(lwt_topic, b"offline", retain=True, qos=1)

            # Connect to broker
            self.client.connect()
            self.connected = True
            self.retry_count = 0

            print(f"[MQTT] Connected to {self.config['broker']}")

            # Publish online status
            self.publish(lwt_topic, "online", retain=True, qos=1)

            # Subscribe to command topic
            cmd_topic = f"{self.config['topic_prefix']}/set"
            self.client.set_callback(self._on_message_internal)
            self.client.subscribe(cmd_topic, qos=self.config['qos'])
            print(f"[MQTT] Subscribed to {cmd_topic}")

            # Publish Home Assistant discovery message
            self.publish_discovery()

            return True

        except ImportError:
            print("[ERROR] MQTT library (umqtt.simple) not available")
            self.connected = False
            return False
        except Exception as e:
            print(f"[ERROR] MQTT connect failed: {e}")
            self.connected = False
            return False

    def publish(self, topic, payload, retain=False, qos=1):
        """
        Publish message to MQTT topic
        Returns: True if successful, False otherwise
        """
        if not self.connected or not self.client:
            return False

        try:
            # Ensure payload is bytes
            if isinstance(payload, str):
                payload = payload.encode()

            self.client.publish(topic, payload, retain=retain, qos=qos)
            return True

        except Exception as e:
            print(f"[ERROR] MQTT publish failed: {e}")
            self.connected = False
            return False

    def publish_state(self, is_on):
        """
        Publish current state to state topic
        is_on: Boolean indicating if light is on
        """
        topic = f"{self.config['topic_prefix']}/state"
        payload = "ON" if is_on else "OFF"
        success = self.publish(topic, payload, retain=True, qos=self.config['qos'])

        if success:
            print(f"[MQTT] Published state: {payload}")
        return success

    def publish_discovery(self):
        """
        Publish Home Assistant MQTT discovery message
        This enables auto-discovery of the device in Home Assistant
        """
        topic = f"homeassistant/light/{self.config['topic_prefix']}/config"

        # Build discovery payload
        payload = {
            "name": self.config.get('device_name', 'DND Light'),
            "unique_id": f"pushbuttondnd_{unique_id()}",
            "state_topic": f"{self.config['topic_prefix']}/state",
            "command_topic": f"{self.config['topic_prefix']}/set",
            "availability_topic": f"{self.config['topic_prefix']}/availability",
            "payload_on": "ON",
            "payload_off": "OFF",
            "optimistic": False,
            "qos": self.config['qos'],
            "retain": True,
            "device": {
                "identifiers": [f"pushbuttondnd_{unique_id()}"],
                "name": "PushButtonDND",
                "manufacturer": "DIY",
                "model": "ESP32 DND Light",
                "sw_version": "1.0"
            }
        }

        # Publish discovery message
        payload_json = json.dumps(payload)
        success = self.publish(topic, payload_json, retain=True, qos=1)

        if success:
            print(f"[MQTT] Published Home Assistant discovery")
        return success

    def _on_message_internal(self, topic, msg):
        """Internal callback handler for incoming MQTT messages"""
        try:
            # Call user-provided callback if set
            if self.message_callback:
                self.message_callback(topic, msg)
        except Exception as e:
            print(f"[ERROR] MQTT message callback error: {e}")

    def check_messages(self):
        """
        Non-blocking check for new MQTT messages
        Call this regularly in your main loop
        """
        if not self.connected or not self.client:
            return

        try:
            self.client.check_msg()  # Non-blocking
        except Exception as e:
            print(f"[ERROR] MQTT check_msg failed: {e}")
            self.connected = False

    def reconnect(self):
        """
        Blocking reconnect with exponential backoff (legacy).
        Returns: True if reconnected, False otherwise
        """
        if self.retry_count >= self.max_retries:
            print(f"[MQTT] Max retries ({self.max_retries}) reached, giving up")
            return False

        delay = self.retry_delays[min(self.retry_count, len(self.retry_delays) - 1)]
        print(f"[MQTT] Reconnecting in {delay}s (attempt {self.retry_count + 1}/{self.max_retries})")

        time.sleep(delay)
        self.retry_count += 1

        return self.connect()

    def reconnect_nonblocking(self):
        """
        Non-blocking reconnect attempt. Call every main loop iteration.
        Returns: "waiting" | "connected" | "gave_up"
        """
        if self.connected:
            return "connected"

        if self._gave_up:
            return "gave_up"

        now = time.ticks_ms()

        if not self._reconnect_pending:
            # Schedule next reconnection attempt
            delay = self.retry_delays[min(self.retry_count, len(self.retry_delays) - 1)]
            self._reconnect_after = time.ticks_add(now, delay * 1000)
            self._reconnect_pending = True
            print(f"[MQTT] Will reconnect in {delay}s (attempt {self.retry_count + 1}/{self.max_retries})")
            return "waiting"

        # Check if it's time to attempt
        if time.ticks_diff(now, self._reconnect_after) < 0:
            return "waiting"

        # Time to attempt connection
        self._reconnect_pending = False
        self.retry_count += 1

        if self.retry_count > self.max_retries:
            print(f"[MQTT] Max retries ({self.max_retries}) reached, giving up")
            self._gave_up = True
            return "gave_up"

        print("[MQTT] Attempting reconnection...")
        if self.connect():
            return "connected"
        return "waiting"

    def reset_retries(self):
        """Reset retry state to allow reconnection after giving up"""
        self.retry_count = 0
        self._reconnect_pending = False
        self._gave_up = False
        print("[MQTT] Retry counter reset")

    def disconnect(self):
        """
        Clean disconnect from MQTT broker
        Publishes offline status before disconnecting
        """
        if self.connected and self.client:
            try:
                # Publish offline status
                lwt_topic = f"{self.config['topic_prefix']}/availability"
                self.publish(lwt_topic, "offline", retain=True, qos=1)

                # Disconnect
                self.client.disconnect()
                print("[MQTT] Disconnected")
            except Exception as e:
                print(f"[MQTT] Disconnect error: {e}")

            self.connected = False
            self.client = None
