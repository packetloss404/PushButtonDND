"""Real desk-to-door HTTP integration using pinned MicroPython requests.

The firmware sender, debounce/retry state machine, request encoder, door TCP
handler, auth, relay state, and event log all run unchanged. Only board APIs,
MicroPython socket streams and its string/bytes formatting are adapted for
CPython. This does not validate ESP32 networking or physical relay wiring.
"""
from pathlib import Path
import socket
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

import config
import desk
from tests.support import FirmwareServer, HostClock, ROOT, load_module


class MicroString(str):
    """MicroPython permits str values in bytes %s; CPython needs __bytes__."""
    def __bytes__(self):
        return self.encode('utf-8')

    def split(self, *args):
        return [MicroString(value) for value in super().split(*args)]


class MicroSocket:
    """Adapt CPython socket stream methods without replacing HTTP transport."""
    opened = []

    def __init__(self, *args):
        self.raw = socket.socket(*args)
        self.reader = self.raw.makefile('rb', buffering=0)
        self.timeouts = []
        self.closed = False
        self.opened.append(self)

    def settimeout(self, timeout):
        self.timeouts.append(timeout)
        self.raw.settimeout(timeout)

    def connect(self, address):
        return self.raw.connect(address)

    def write(self, data):
        if isinstance(data, str):
            data = data.encode('utf-8')
        self.raw.sendall(data)
        return len(data)

    def readline(self):
        return self.reader.readline()

    def read(self, size=-1):
        return self.reader.read(size)

    def readinto(self, buffer):
        return self.reader.readinto(buffer)

    def close(self):
        self.reader.close()
        self.raw.close()
        self.closed = True


class DeskDoorTests(unittest.TestCase):
    def setUp(self):
        results = ROOT / 'test-results'
        results.mkdir(exist_ok=True)
        directory = tempfile.TemporaryDirectory(dir=results)
        self.addCleanup(directory.cleanup)
        self.server = FirmwareServer(Path(directory.name))
        self.server.__enter__()
        self.addCleanup(self.server.__exit__, None, None, None)
        self.settings = config.get_default_config()
        self.settings['desk']['receiver_url'] = self.server.url + '/api/set?room=office'
        self.settings['desk']['source_tag'] = 'desk & Café=west+'
        self.settings['security']['auth_token'] = self.server.token
        self.requests = load_module('micropython_requests_test', 'tests/vendor/requests.py')
        self.requests.socket = types.SimpleNamespace(socket=MicroSocket,
                                                     getaddrinfo=socket.getaddrinfo,
                                                     SOCK_STREAM=socket.SOCK_STREAM)
        original_request = self.requests.request
        def compatible_request(method, url, *args, **kwargs):
            return original_request(MicroString(method), MicroString(url), *args, **kwargs)
        self.requests.request = compatible_request
        modules = patch.dict(sys.modules, {'requests': self.requests, 'urequests': self.requests})
        modules.start()
        self.addCleanup(modules.stop)
        clock = patch.object(desk, 'time', HostClock)
        clock.start()
        self.addCleanup(clock.stop)
        MicroSocket.opened = []

    def read_json(self, path):
        response = self.requests.get(self.server.url + path, timeout=2)
        try:
            self.assertEqual(response.status_code, 200)
            return response.json()
        finally:
            response.close()

    def test_initial_closed_switch_on_then_debounced_off_reaches_actual_handler(self):
        sync = desk.SwitchSynchronizer(0, 0, lambda on: desk.send_state(self.settings, on))
        sync.step(0, 0, True)
        self.assertEqual(sync.delivered, 0)
        self.assertTrue(self.read_json('/api/state')['on'])
        self.assertTrue(self.server.firmware.led_pin.value())
        events = self.read_json('/api/log')
        self.assertEqual(events[-1]['detail'], 'ON via desk & Café=west+')
        sync.step(1, 100, True)
        sync.step(1, 399, True)
        self.assertTrue(self.read_json('/api/state')['on'])
        sync.step(1, 1000, True)
        self.assertEqual(sync.delivered, 1)
        self.assertFalse(self.read_json('/api/state')['on'])
        self.assertFalse(self.server.firmware.led_pin.value())
        self.assertEqual(self.read_json('/api/log')[-1]['detail'], 'OFF via desk & Café=west+')
        self.assertTrue(all(client.closed for client in MicroSocket.opened))
        self.assertTrue(all(client.timeouts == [2] for client in MicroSocket.opened))

    def test_actual_forbidden_response_is_unacknowledged_until_token_fixed(self):
        self.settings['security']['auth_token'] = 'wrong token'
        sync = desk.SwitchSynchronizer(0, 0, lambda on: desk.send_state(self.settings, on))
        sync.step(0, 0, True)
        self.assertIsNone(sync.delivered)
        self.assertFalse(self.read_json('/api/state')['on'])
        self.assertFalse(self.read_json('/api/log'))
        self.settings['security']['auth_token'] = self.server.token
        sync.step(0, 999, True)
        self.assertIsNone(sync.delivered)
        sync.step(0, 1000, True)
        self.assertEqual(sync.delivered, 0)
        self.assertTrue(self.read_json('/api/state')['on'])
        self.assertTrue(all(client.closed for client in MicroSocket.opened))

    def test_real_connection_refusal_then_recovery_retries_pending_switch(self):
        # Hold an unlistening local socket so no unrelated service can claim it.
        with socket.socket() as unavailable:
            unavailable.bind(('127.0.0.1', 0))
            unavailable_url = 'http://127.0.0.1:' + str(unavailable.getsockname()[1]) + '/api/set'
            actual_url = self.settings['desk']['receiver_url']
            self.settings['desk']['receiver_url'] = unavailable_url
            sync = desk.SwitchSynchronizer(0, 0, lambda on: desk.send_state(self.settings, on))
            sync.step(0, 0, True)
            self.assertIsNone(sync.delivered)
            self.assertFalse(self.read_json('/api/state')['on'])
        self.settings['desk']['receiver_url'] = actual_url
        sync.step(0, 1000, True)
        self.assertEqual(sync.delivered, 0)
        self.assertTrue(self.read_json('/api/state')['on'])
        self.assertTrue(all(client.closed for client in MicroSocket.opened))


if __name__ == '__main__':
    unittest.main()
