"""Real TCP/MQTT integration against Mosquitto and pinned upstream umqtt.simple.

Only the MicroPython socket stream API and tick clock are adapted to CPython.
No MQTT messages, broker responses, or firmware wrapper methods are mocked.
"""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import time
import types
import uuid
from urllib.parse import urlencode
from urllib.request import urlopen

import pytest

import config
import mqtt_client
from tests.support import FirmwareServer


pytestmark = pytest.mark.broker


class MicroSocket:
    """Adapt CPython sockets to the MicroPython read/write stream interface."""
    def __init__(self):
        self.raw = socket.socket()

    def settimeout(self, timeout):
        self.raw.settimeout(timeout)

    def setblocking(self, blocking):
        self.raw.setblocking(blocking)

    def connect(self, address):
        return self.raw.connect(address)

    def read(self, size):
        try:
            data = self.raw.recv(size)
        except BlockingIOError:
            return None
        while data and len(data) < size:
            more = self.raw.recv(size - len(data))
            if not more:
                break
            data += more
        return data

    def write(self, data, size=None):
        data = memoryview(data)[:size]
        self.raw.sendall(data)
        return len(data)

    def close(self):
        self.raw.close()


@pytest.fixture
def broker(tmp_path):
    external_port = os.environ.get('MQTT_TEST_PORT')
    if external_port:
        yield types.SimpleNamespace(host=os.environ.get('MQTT_TEST_HOST', '127.0.0.1'),
                                    port=int(external_port))
        return
    executable = os.environ.get('MOSQUITTO_PATH') or shutil.which('mosquitto')
    if not executable:
        if os.environ.get('REQUIRE_MQTT_BROKER') == '1':
            pytest.fail('Mosquitto is required by REQUIRE_MQTT_BROKER=1')
        pytest.skip('Install mosquitto or set MOSQUITTO_PATH for real-broker integration')
    with socket.socket() as reservation:
        reservation.bind(('127.0.0.1', 0))
        port = reservation.getsockname()[1]
    settings = tmp_path / 'mosquitto.conf'
    settings.write_text('listener {} 127.0.0.1\nallow_anonymous true\npersistence false\n'.format(port))
    processes = []

    def start():
        process = subprocess.Popen([executable, '-c', str(settings)],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        processes.append(process)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if process.poll() is not None:
                pytest.fail('Mosquitto exited with {}'.format(process.returncode))
            try:
                with socket.create_connection(('127.0.0.1', port), timeout=0.1):
                    return process
            except OSError:
                time.sleep(0.02)
        pytest.fail('Mosquitto did not accept TCP connections')

    process = start()
    yield types.SimpleNamespace(host='127.0.0.1', port=port)
    for process in processes:
        if process.poll() is None:
            process.terminate()
        process.wait(timeout=5)


@pytest.fixture
def wire(monkeypatch, broker):
    path = Path(__file__).parent / 'vendor' / 'umqtt_simple.py'
    spec = importlib.util.spec_from_file_location('upstream_umqtt_simple', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.socket = types.SimpleNamespace(socket=MicroSocket, getaddrinfo=socket.getaddrinfo)
    package = types.ModuleType('umqtt')
    monkeypatch.setitem(sys.modules, 'umqtt', package)
    monkeypatch.setitem(sys.modules, 'umqtt.simple', module)
    monkeypatch.setattr(time, 'ticks_ms', lambda: int(time.monotonic() * 1000) % (1 << 30), raising=False)
    monkeypatch.setattr(time, 'ticks_add', lambda a, b: (a + b) % (1 << 30), raising=False)
    monkeypatch.setattr(time, 'ticks_diff', lambda a, b: ((a - b + (1 << 29)) % (1 << 30)) - (1 << 29), raising=False)
    identity = uuid.uuid4().hex
    monkeypatch.setattr(mqtt_client, 'unique_id', lambda: identity)
    clients = []

    def observer():
        client = module.MQTTClient(('observer_' + identity + '_' + str(len(clients))).encode(), broker.host, port=broker.port)
        client.connect(timeout=1)
        client.sock = mqtt_client._BoundedSocket(client.sock, 1)
        messages = []
        client.set_callback(lambda topic, data: messages.append((topic.decode(), data)))
        clients.append(client)
        return client, messages

    cfg = config.get_default_config()['mqtt']
    prefix = 'pushbuttondnd_test_' + identity
    cfg.update(broker=broker.host, port=broker.port, topic_prefix=prefix)
    firmware = mqtt_client.MQTTClient(cfg)
    yield types.SimpleNamespace(firmware=firmware, observer=observer, prefix=prefix)
    firmware.disconnect()
    for client in clients:
        try:
            client.disconnect()
        except OSError:
            client.sock.close()


def eventually(poll, condition):
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        poll()
        if condition():
            return
        time.sleep(0.01)
    assert condition(), 'Expected MQTT message did not arrive'


def test_real_broker_discovery_retained_state_and_bidirectional_commands(wire, tmp_path):
    with FirmwareServer(tmp_path) as door:
        firmware = wire.firmware
        door.firmware.mqtt = firmware
        door.firmware.MQTT_ENABLED = True
        firmware.message_callback = door.firmware.mqtt_command_handler
        assert firmware.connect()
        observer, messages = wire.observer()
        observer.subscribe(('homeassistant/light/' + wire.prefix + '/config').encode(), qos=1)
        observer.subscribe((wire.prefix + '/state').encode(), qos=1)
        observer.subscribe((wire.prefix + '/availability').encode(), qos=1)
        eventually(observer.check_msg, lambda: len(messages) >= 3)
        discovery = next(json.loads(data) for topic, data in messages if topic.startswith('homeassistant/'))
        assert discovery['unique_id'] == firmware.client_id
        assert discovery['command_topic'] == wire.prefix + '/set'
        assert discovery['retain'] is False
        assert (wire.prefix + '/state', b'OFF') in messages
        assert (wire.prefix + '/availability', b'online') in messages

        # Real broker command executes the shipping door callback and relay logic.
        observer.publish((wire.prefix + '/set').encode(), b'ON', qos=1)
        eventually(firmware.check_messages, lambda: door.firmware.is_on)
        assert door.firmware.led_pin.value() == 1
        assert door.firmware.event_log[-1]['detail'] == 'ON via mqtt'
        eventually(observer.check_msg, lambda: (wire.prefix + '/state', b'ON') in messages)

        # Actual authenticated HTTP control runs set_output and publishes back.
        query = urlencode({'on': '0', 'token': door.token, 'source': 'api'})
        with urlopen(door.url + '/api/set?' + query, timeout=3) as response:
            assert response.status == 200
            assert response.read() == b'OK'
        assert door.firmware.led_pin.value() == 0
        assert door.firmware.event_log[-1]['detail'] == 'OFF via api'
        eventually(observer.check_msg,
                   lambda: messages.count((wire.prefix + '/state', b'OFF')) == 2)
        newcomer, retained = wire.observer()
        newcomer.subscribe((wire.prefix + '/state').encode(), qos=1)
        eventually(newcomer.check_msg, lambda: retained == [(wire.prefix + '/state', b'OFF')])


def test_real_broker_last_will_and_clean_offline_status(wire):
    assert wire.firmware.connect()
    observer, messages = wire.observer()
    observer.subscribe((wire.prefix + '/availability').encode(), qos=1)
    eventually(observer.check_msg, lambda: (wire.prefix + '/availability', b'online') in messages)
    wire.firmware._drop_connection()  # Abrupt TCP loss: broker must publish LWT.
    eventually(observer.check_msg, lambda: messages[-1] == (wire.prefix + '/availability', b'offline'))
    assert wire.firmware.connect()
    eventually(observer.check_msg, lambda: messages[-1] == (wire.prefix + '/availability', b'online'))
    wire.firmware.disconnect()
    eventually(observer.check_msg, lambda: messages[-1] == (wire.prefix + '/availability', b'offline'))


def test_real_broker_transport_recovery_restores_latest_offline_state(wire):
    firmware = wire.firmware
    assert firmware.connect()
    firmware.client.sock._sock.raw.shutdown(socket.SHUT_RDWR)
    eventually(firmware.check_messages, lambda: not firmware.connected)
    assert not firmware.publish_state(True)
    assert firmware.reconnect_nonblocking() == 'waiting'
    firmware._reconnect_after = time.ticks_ms()  # Advance the scheduler, not network I/O.
    assert firmware.reconnect_nonblocking() == 'connected'
    observer, messages = wire.observer()
    observer.subscribe((wire.prefix + '/state').encode(), qos=1)
    eventually(observer.check_msg, lambda: messages == [(wire.prefix + '/state', b'ON')])
    firmware._last_ping = time.ticks_add(time.ticks_ms(), -30000)
    firmware.check_messages()
    firmware.check_messages()  # Consume real PINGRESP without dropping connection.
    assert firmware.connected


@pytest.mark.parametrize('suffix', ['/office/door', '.office', ' Office', '_café'])
def test_real_broker_prefix_has_valid_discovery_topic(wire, suffix):
    firmware = wire.firmware
    firmware.config['topic_prefix'] = wire.prefix + suffix
    assert firmware.connect()
    observer, messages = wire.observer()
    discovery_topic = 'homeassistant/light/' + firmware.client_id + '/config'
    observer.subscribe(discovery_topic.encode(), qos=1)
    eventually(observer.check_msg, lambda: bool(messages))
    assert messages[0][0] == discovery_topic
    payload = json.loads(messages[0][1])
    assert payload['state_topic'] == wire.prefix + suffix + '/state'
    assert payload['command_topic'] == wire.prefix + suffix + '/set'
    assert payload['retain'] is False
