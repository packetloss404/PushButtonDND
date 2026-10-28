"""Deterministic real umqtt packet parsing regressions, without a broker."""
import importlib.util
from pathlib import Path
import time

import pytest

import config
import mqtt_client
from tests.support import FirmwareServer


class PacketStream:
    def __init__(self, packets):
        self.packets = bytearray(packets)
        self.writes = []
        self.closed = False

    def read(self, size):
        if len(self.packets) < size:
            raise OSError('No further packet: simulated socket timeout')
        result = bytes(self.packets[:size])
        del self.packets[:size]
        return result

    def write(self, data, size=None):
        result = bytes(data[:size])
        self.writes.append(result)
        return len(result)

    def settimeout(self, value):
        pass

    def setblocking(self, blocking):
        pass

    def close(self):
        self.closed = True


@pytest.mark.parametrize('outer_ack', [True, False])
def test_incoming_command_during_publish_cannot_steal_outer_puback(monkeypatch, tmp_path, outer_ack):
    # The unmodified client's wait_msg can invoke a callback while publishing.
    # Previously the callback synchronously published pid2, consumed pid1 ACK,
    # and left the outer publication waiting despite both ACKs having arrived.
    path = Path(__file__).parent / 'vendor' / 'umqtt_simple.py'
    spec = importlib.util.spec_from_file_location('packet_umqtt', path)
    upstream = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(upstream)
    monkeypatch.setattr(time, 'ticks_ms', lambda: int(time.monotonic() * 1000), raising=False)
    monkeypatch.setattr(time, 'ticks_add', lambda a, b: a + b, raising=False)
    monkeypatch.setattr(time, 'ticks_diff', lambda a, b: a - b, raising=False)
    wrapper = mqtt_client.MQTTClient(config.get_default_config()['mqtt'])
    wire = upstream.MQTTClient(b'protocol_test', 'unused')
    topic = b'pushbuttondnd/set'
    publish_command = (b'\x30' + bytes([2 + len(topic) + 2]) +
                       len(topic).to_bytes(2, 'big') + topic + b'ON')
    acknowledgements = b'\x40\x02\x00\x01\x40\x02\x00\x02' if outer_ack else b''
    stream = PacketStream(publish_command + acknowledgements)
    wire.sock = mqtt_client._BoundedSocket(stream, 1)
    wire.set_callback(wrapper._on_message_internal)
    wrapper.client = wire
    wrapper.connected = True
    with FirmwareServer(tmp_path) as door:
        door.firmware.mqtt = wrapper
        wrapper.message_callback = door.firmware.mqtt_command_handler
        assert wrapper.publish('discovery', 'config', qos=1) is outer_ack
        assert door.firmware.is_on is True
        assert door.firmware.led_pin.value() == 1
        assert door.firmware.event_log[-1]['detail'] == 'ON via mqtt'
        assert wrapper._state is True
        assert wrapper.connected is outer_ack
        assert wrapper._transport_depth == 0
        assert wrapper._pending_commands == []
        if outer_ack:
            assert wire.pid == 2
            assert not stream.packets
        else:
            assert stream.closed
