"""Door firmware tests: real request parser/handler, simulated hardware only."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

import config


class Clock:
    now = 100

    def ticks_ms(self):
        return self.now

    def ticks_diff(self, later, earlier):
        return later - earlier

    def sleep(self, seconds):
        self.now += int(seconds * 1000)


class Pin:
    OUT = 1

    def __init__(self, pin, mode, value=0):
        self.state = value

    def value(self, value=None):
        if value is not None:
            self.state = value
        return self.state


class Socket:
    """Short reads/writes simulate segmented TCP without mocking routing."""
    def __init__(self, request, chunk=83):
        self.remaining = request
        self.output = bytearray()
        self.chunk = chunk
        self.closed = False

    def settimeout(self, timeout):
        self.timeout = timeout

    def recv(self, size):
        value = self.remaining[:min(size, self.chunk)]
        self.remaining = self.remaining[len(value):]
        return value

    def send(self, data):
        self.output.extend(data)
        return len(data)

    def sendall(self, data):
        self.output.extend(data)

    def close(self):
        self.closed = True


class DoorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.network = types.SimpleNamespace(STA_IF=0, AP_IF=1)
        cls.machine = types.SimpleNamespace(Pin=Pin, WDT=Mock(), reset=Mock())
        spec = importlib.util.spec_from_file_location('door_under_test', Path(__file__).resolve().parents[1] / 'door.py')
        cls.door = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, network=cls.network, machine=cls.machine):
            spec.loader.exec_module(cls.door)

    def setUp(self):
        self.clock = Clock()
        self.door.time = self.clock
        self.cfg = config.get_default_config()
        self.cfg['wifi']['ssid'] = 'Test WiFi'
        self.cfg['security']['auth_token'] = 'a&b=\'"<secret>'
        self.door.initialize(self.cfg, connect_wifi=False)
        runtime = Path(__file__).resolve().parents[1] / 'test-results'
        runtime.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=runtime)
        self.addCleanup(self.temp.cleanup)
        self.paths = patch.multiple(config,
            CONFIG_PATH=str(Path(self.temp.name) / 'config.json'),
            BACKUP_PATH=str(Path(self.temp.name) / 'config.json.backup'),
            TEMP_PATH=str(Path(self.temp.name) / 'config.json.tmp'))
        self.paths.start()
        self.addCleanup(self.paths.stop)

    def request(self, method, path, body='', headers=None):
        headers = dict(headers or {})
        if body or method == 'POST':
            headers['Content-Length'] = str(len(body.encode()))
        request = method + ' ' + path + ' HTTP/1.1\r\nHost: localhost\r\n'
        request += ''.join(k + ': ' + v + '\r\n' for k, v in headers.items()) + '\r\n' + body
        sock = Socket(request.encode())
        reboot = self.door.handle_client(sock)
        self.assertTrue(sock.closed)
        head, payload = bytes(sock.output).split(b'\r\n\r\n', 1)
        return int(head.split()[1]), payload.decode(), reboot

    def auth(self):
        return {'Authorization': 'Bearer ' + self.cfg['security']['auth_token']}

    def test_disconnected_client_during_error_response_does_not_stop_server(self):
        client = Mock()
        client.recv.side_effect = OSError('Connection reset')
        client.send.side_effect = OSError('Broken pipe')
        self.assertFalse(self.door.handle_client(client))
        client.close.assert_called_once()
        self.assertEqual(self.request('GET', '/api/state')[0], 200)

    def test_socket_close_error_does_not_stop_server(self):
        client = Socket(b'GET /api/state HTTP/1.1\r\nHost: localhost\r\n\r\n')
        client.close = Mock(side_effect=OSError('Already closed'))
        self.assertFalse(self.door.handle_client(client))

    def test_mqtt_boot_feeds_watchdog_and_retains_failed_client(self):
        station = Mock()
        station.isconnected.return_value = True
        station.ifconfig.return_value = ('192.0.2.1',)
        self.network.WLAN = Mock(return_value=station)
        client = Mock(connected=False)
        client.connect.return_value = False
        self.machine.WDT.reset_mock()
        self.cfg['mqtt']['enabled'] = True
        with patch.dict(sys.modules, machine=self.machine), patch.object(self.door.mqtt_client, 'MQTTClient', return_value=client):
            self.door.initialize(self.cfg)
        self.assertIs(self.door.mqtt, client)
        client.connect.assert_called_once()
        self.assertGreaterEqual(self.machine.WDT.return_value.feed.call_count, 3)

    def test_safe_boot_pin_and_state(self):
        self.assertEqual(self.door.led_pin.value(), 0)
        status, body, reboot = self.request('GET', '/api/state')
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)['on'], False)
        self.assertFalse(reboot)

    def test_auth_is_exact_not_substring_or_body(self):
        for path in ('/api/set?on=1&not_token=' + self.door.url_encode(self.cfg['security']['auth_token']),
                     '/api/set?on=1&token=wrong'):
            self.assertEqual(self.request('GET', path)[0], 403)
        status = self.request('GET', '/api/set?on=1', headers=self.auth())[0]
        self.assertEqual(status, 200)
        self.assertTrue(self.door.is_on)

    def test_encoded_token_and_source(self):
        token = self.door.url_encode(self.cfg['security']['auth_token'])
        self.assertEqual(self.request('GET', '/api/set?on=1&token=' + token + '&source=desk')[0], 200)
        self.assertEqual(self.door.event_log[-1]['detail'], 'ON via desk')
        self.assertEqual(self.request('GET', '/api/set?on=0&token=' + token)[0], 200)
        self.assertFalse(self.door.is_on)

    def test_methods_paths_and_invalid_on_are_rejected(self):
        self.assertEqual(self.request('GET', '/api/set', headers=self.auth())[0], 400)
        self.assertEqual(self.request('POST', '/api/set?on=1', headers=self.auth())[0], 405)
        self.assertEqual(self.request('GET', '/api/set/extra?on=1', headers=self.auth())[0], 404)
        self.assertFalse(self.door.is_on)

    def test_event_ring_and_elapsed_time(self):
        for index in range(25):
            self.door.set_output(bool(index % 2), 'test')
        self.assertEqual(len(self.door.event_log), 20)
        self.clock.now += 45
        self.assertEqual(json.loads(self.request('GET', '/api/state')[1])['last_ms'], 45)
        self.assertEqual(len(json.loads(self.request('GET', '/api/log')[1])), 20)

    def test_large_segmented_config_save_and_restore(self):
        self.cfg['mqtt']['password'] = 'x' * 1400
        status, body, reboot = self.request('POST', '/api/config', json.dumps(self.cfg), self.auth())
        self.assertEqual(status, 200, body)
        self.assertTrue(reboot)
        loaded, error = config.load_config()
        self.assertIsNone(error)
        self.assertEqual(loaded['mqtt']['password'], 'x' * 1400)
        self.assertEqual(loaded['desk'], self.cfg['desk'])

    def test_save_rejects_bad_json_and_schema(self):
        for body in ('{', '[]', '{"wifi": null}'):
            status, response, reboot = self.request('POST', '/api/config', body, self.auth())
            self.assertEqual(status, 400, response)
            self.assertFalse(reboot)
        self.assertFalse(Path(config.CONFIG_PATH).exists())

    def test_reset_returns_to_provisionable_defaults(self):
        self.assertTrue(config.save_config(self.cfg)[0])
        status, body, reboot = self.request('POST', '/api/config/reset', headers=self.auth())
        self.assertEqual(status, 200, body)
        self.assertTrue(reboot)
        self.assertFalse(Path(config.CONFIG_PATH).exists())
        self.assertEqual(config.load_config()[0]['wifi']['ssid'], '')

    def test_public_html_never_discloses_token_and_config_escapes_values(self):
        self.cfg['wifi']['ssid'] = '\"><script>bad()</script>'
        page = self.request('GET', '/')[1]
        self.assertNotIn(self.cfg['security']['auth_token'], page)
        self.assertIn('setLight(true)', page)
        self.assertEqual(self.request('GET', '/config')[0], 403)
        status, page, reboot = self.request('GET', '/config', headers=self.auth())
        self.assertEqual(status, 200)
        self.assertNotIn('<script>bad()', page)
        self.assertIn('&lt;script&gt;bad()', page)
        self.assertNotIn('event.target', page)

    def test_background_runs_after_traffic_and_keeps_failed_mqtt_client(self):
        self.door.wlan = Mock()
        self.door.wlan.isconnected.return_value = True
        self.door.wlan.ifconfig.return_value = ('192.0.2.1',)
        self.door.wifi_connected = True
        self.door.mqtt = Mock(connected=True)
        self.clock.now += 1000
        self.request('GET', '/api/state')
        self.door.service_background()
        self.door.mqtt.check_messages.assert_called_once()
        self.door.mqtt.connected = False
        self.door.set_output(True, 'desk')
        self.door.mqtt.publish_state.assert_called_with(True)

    def test_retry_exhaustion_logs_once_instead_of_flooding_ring(self):
        self.door.wifi_connected = True
        client = Mock(connected=False)
        client._gave_up = False
        def give_up():
            client._gave_up = True
            return 'gave_up'
        client.reconnect_nonblocking.side_effect = give_up
        self.door.mqtt = client
        for unused in range(30):
            self.clock.now += 100
            self.door.service_background()
        self.assertEqual(len(self.door.event_log), 1)
        self.assertIn('Gave up', self.door.event_log[0]['detail'])

    def test_blank_wifi_starts_door_setup_access_point(self):
        station = Mock()
        station.isconnected.return_value = False
        access_point = Mock()
        access_point.ifconfig.return_value = ('192.168.4.1',)
        self.network.WLAN = Mock(side_effect=[station, access_point])
        self.machine.WDT.reset_mock()
        with patch.dict(sys.modules, machine=self.machine):
            self.door.initialize(config.get_default_config())
        access_point.config.assert_called_once_with(essid='DND-Door-Setup', authmode=0)
        station.connect.assert_not_called()


if __name__ == '__main__':
    unittest.main()
