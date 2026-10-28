"""Firmware MQTT behavior at the umqtt transport boundary (no real broker)."""
import json
import sys
import types
import unittest
from unittest.mock import patch

import config
import mqtt_client


class FakeSocket:
    def __init__(self):
        self.timeout = None
        self.closed = False

    def settimeout(self, value):
        self.timeout = value

    def setblocking(self, blocking):
        self.timeout = None if blocking else 0

    def close(self):
        self.closed = True


class FakeMQTT:
    instances = []
    failure = None

    def __init__(self, **kwargs):
        self.options = kwargs
        self.sock = FakeSocket()
        self.publications = []
        self.subscriptions = []
        self.pings = 0
        self.disconnected = False
        self.__class__.instances.append(self)

    def set_last_will(self, *args, **kwargs):
        self.will = (args, kwargs)

    def set_callback(self, callback):
        self.callback = callback

    def connect(self, timeout=None):
        self.connect_timeout = timeout
        if self.failure == 'connect':
            raise OSError('unreachable')

    def subscribe(self, topic, qos):
        if self.failure == 'subscribe':
            raise OSError('subscribe refused')
        self.subscriptions.append((topic, qos))
        self.sock.setblocking(True)

    def publish(self, topic, message, retain, qos):
        assert isinstance(topic, bytes)
        assert isinstance(message, bytes)
        if self.failure == 'publish':
            raise OSError('missing PUBACK')
        self.publications.append((topic, message, retain, qos))
        self.sock.setblocking(True)

    def check_msg(self):
        if self.failure == 'check':
            raise OSError('connection closed')
        self.sock.setblocking(False)
        self.sock.setblocking(True)

    def ping(self):
        if self.failure == 'ping':
            raise OSError('ping failed')
        self.pings += 1

    def disconnect(self):
        self.disconnected = True
        self.sock.close()


class MQTTTests(unittest.TestCase):
    def setUp(self):
        FakeMQTT.instances = []
        FakeMQTT.failure = None
        self.now = 0
        simple = types.ModuleType('umqtt.simple')
        simple.MQTTClient = FakeMQTT
        self.patches = [
            patch.dict(sys.modules, {'umqtt': types.ModuleType('umqtt'), 'umqtt.simple': simple}),
            patch.object(mqtt_client.time, 'ticks_ms', lambda: self.now, create=True),
            patch.object(mqtt_client.time, 'ticks_add', lambda a, b: (a + b) % (1 << 30), create=True),
            patch.object(mqtt_client.time, 'ticks_diff', lambda a, b: ((a - b + (1 << 29)) % (1 << 30)) - (1 << 29), create=True),
            patch.object(mqtt_client, 'unique_id', lambda: 'abc123'),
        ]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)
        self.cfg = config.get_default_config()['mqtt']
        self.client = mqtt_client.MQTTClient(self.cfg)

    def test_connect_publishes_discovery_initial_state_and_availability(self):
        self.assertTrue(self.client.connect())
        wire = FakeMQTT.instances[-1]
        self.assertEqual(wire.connect_timeout, 1)
        self.assertEqual(wire.options['client_id'], b'pushbuttondnd_abc123')
        self.assertEqual(wire.will, ((b'pushbuttondnd/availability', b'offline'), {'retain': True, 'qos': 1}))
        self.assertEqual(wire.subscriptions, [(b'pushbuttondnd/set', 1)])
        payload = json.loads(wire.publications[0][1])
        self.assertEqual(payload['command_topic'], 'pushbuttondnd/set')
        self.assertEqual(payload['unique_id'], 'pushbuttondnd_abc123')
        self.assertFalse(payload['retain'])
        self.assertEqual(wire.publications[1], (b'pushbuttondnd/state', b'OFF', True, 1))
        self.assertEqual(wire.publications[-1], (b'pushbuttondnd/availability', b'online', True, 1))
        self.assertEqual(wire.sock._sock.timeout, 1)

    def test_empty_password_is_bytes_with_username(self):
        self.cfg['username'] = 'user'
        self.assertTrue(self.client.connect())
        self.assertEqual(FakeMQTT.instances[-1].options['password'], b'')

    def test_partial_connect_failure_closes_socket_and_does_not_report_connected(self):
        for failure in ('connect', 'subscribe', 'publish'):
            FakeMQTT.failure = failure
            self.assertFalse(self.client.connect())
            self.assertFalse(self.client.connected)
            self.assertIsNone(self.client.client)
            sock = FakeMQTT.instances[-1].sock
            if isinstance(sock, mqtt_client._BoundedSocket):
                sock = sock._sock
            self.assertTrue(sock.closed)

    def test_offline_state_is_published_after_reconnect(self):
        self.assertFalse(self.client.publish_state(True))
        self.assertTrue(self.client.connect())
        self.assertIn((b'pushbuttondnd/state', b'ON', True, 1), FakeMQTT.instances[-1].publications)

    def test_command_topic_filter_and_callback(self):
        received = []
        self.client.message_callback = lambda topic, message: received.append((topic, message))
        self.assertTrue(self.client.connect())
        wire = FakeMQTT.instances[-1]
        wire.callback(b'unrelated/set', b'ON')
        wire.callback(b'pushbuttondnd/set', b'ON')
        self.assertEqual(received, [])
        self.client.check_messages()
        self.assertEqual(received, [(b'pushbuttondnd/set', b'ON')])

    def test_connect_defers_commands_until_setup_finishes_and_reports_drain_failure(self):
        original_subscribe = FakeMQTT.subscribe
        original_publish = FakeMQTT.publish
        callback_publications = []
        def subscribe(wire, topic, qos):
            original_subscribe(wire, topic, qos)
            wire.callback(topic, b'ON')
        def publish(wire, topic, message, retain, qos):
            if topic == b'pushbuttondnd/state' and message == b'ON':
                callback_publications.extend(wire.publications)
                raise OSError('Command state publication failed')
            original_publish(wire, topic, message, retain, qos)
        self.client.message_callback = lambda topic, message: self.client.publish_state(True)
        with patch.object(FakeMQTT, 'subscribe', subscribe), patch.object(FakeMQTT, 'publish', publish):
            self.assertFalse(self.client.connect())
        self.assertEqual(callback_publications[-1], (b'pushbuttondnd/availability', b'online', True, 1))
        self.assertFalse(self.client.connected)
        self.assertTrue(self.client._state)
        self.assertEqual(self.client._transport_depth, 0)

    def test_command_burst_queue_is_bounded_and_keeps_latest_in_order(self):
        received = []
        self.client.message_callback = lambda topic, message: received.append(message)
        self.assertTrue(self.client.connect())
        wire = FakeMQTT.instances[-1]
        for number in range(20):
            wire.callback(b'pushbuttondnd/set', str(number).encode())
        self.assertEqual(len(self.client._pending_commands), 16)
        self.client.check_messages()
        self.assertEqual(received, [b'4'])
        self.assertEqual(len(self.client._pending_commands), 15)
        # Offline polling also drains queued desired states between retries.
        self.client._drop_connection()
        for unused in range(15):
            self.client.reconnect_nonblocking()
        self.assertEqual(received, [str(number).encode() for number in range(4, 20)])
        self.assertEqual(self.client._pending_commands, [])

    def test_keepalive_ping_and_pending_packet_timeout(self):
        self.assertTrue(self.client.connect())
        wire = FakeMQTT.instances[-1]
        self.now = 29999
        self.client.check_messages()
        self.assertEqual(wire.pings, 0)
        self.now = 30000
        self.client.check_messages()
        self.assertEqual(wire.pings, 1)
        self.assertEqual(wire.sock._sock.timeout, 1)
        self.client.check_messages()
        self.assertEqual(wire.pings, 1)

    def test_socket_error_drops_connection_for_retry(self):
        self.assertTrue(self.client.connect())
        FakeMQTT.failure = 'check'
        self.client.check_messages()
        self.assertFalse(self.client.connected)
        self.assertIsNone(self.client.client)

    def test_operation_deadline_expires_even_when_socket_keeps_returning_data(self):
        raw = FakeSocket()
        def read(size):
            self.now += 600
            return b'x'
        raw.read = read
        bounded = mqtt_client._BoundedSocket(raw, 1)
        bounded.set_deadline(1500)
        self.assertEqual(bounded.read(1), b'x')
        self.assertEqual(bounded.read(1), b'x')
        self.assertEqual(bounded.read(1), b'x')
        with self.assertRaises(OSError):
            bounded.read(1)
        self.assertLessEqual(raw.timeout, 0.3)

    def test_ping_failure_marks_disconnected(self):
        self.assertTrue(self.client.connect())
        FakeMQTT.failure = 'ping'
        self.now = 30000
        self.client.check_messages()
        self.assertFalse(self.client.connected)

    def test_publish_error_preserves_state_for_next_connection(self):
        self.assertTrue(self.client.connect())
        FakeMQTT.failure = 'publish'
        self.assertFalse(self.client.publish_state(True))
        self.assertFalse(self.client.connected)
        FakeMQTT.failure = None
        self.assertTrue(self.client.connect())
        self.assertIn((b'pushbuttondnd/state', b'ON', True, 1), FakeMQTT.instances[-1].publications)

    def test_backoff_does_not_sleep_and_stops_after_exactly_ten_attempts(self):
        FakeMQTT.failure = 'connect'
        with patch.object(mqtt_client.time, 'sleep', side_effect=AssertionError('must not sleep')):
            for attempt in range(10):
                self.assertEqual(self.client.reconnect_nonblocking(), 'waiting')
                self.now = self.client._reconnect_after - 1
                self.assertEqual(self.client.reconnect_nonblocking(), 'waiting')
                self.now += 1
                result = self.client.reconnect_nonblocking()
                self.assertEqual(result, 'gave_up' if attempt == 9 else 'waiting')
            self.assertEqual(self.client.reconnect_nonblocking(), 'gave_up')
            self.assertEqual(len(FakeMQTT.instances), 10)
            self.client.reset_retries()
            FakeMQTT.failure = None
            self.assertEqual(self.client.reconnect_nonblocking(), 'waiting')
            self.now = self.client._reconnect_after
            self.assertEqual(self.client.reconnect_nonblocking(), 'connected')

    def test_reconnect_delay_survives_ticks_wrap(self):
        self.now = (1 << 30) - 100
        self.assertEqual(self.client.reconnect_nonblocking(), 'waiting')
        self.now = 4900
        self.assertEqual(self.client.reconnect_nonblocking(), 'connected')

    def test_clean_disconnect_publishes_offline_and_cleans_up(self):
        self.assertTrue(self.client.connect())
        wire = FakeMQTT.instances[-1]
        self.client.disconnect()
        self.assertEqual(wire.publications[-1], (b'pushbuttondnd/availability', b'offline', True, 1))
        self.assertTrue(wire.disconnected)
        self.assertFalse(self.client.connected)
        self.assertIsNone(self.client.client)


if __name__ == '__main__':
    unittest.main()
