import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlencode, urlsplit

import config
import desk


class Client:
    def __init__(self, request, chunk=37):
        self.request = request
        self.chunk = chunk
        self.output = b''
        self.closed = False

    def settimeout(self, timeout):
        self.timeout = timeout

    def recv(self, size):
        size = min(size, self.chunk)
        result = self.request[:size]
        self.request = self.request[size:]
        return result

    def send(self, data):
        count = min(len(data), 23)
        self.output += data[:count]
        return count

    def close(self):
        self.closed = True


def form_request(values, method='POST', path='/save'):
    body = urlencode(values).encode()
    return (method + ' ' + path + ' HTTP/1.1\r\nHost: desk\r\nContent-Type: application/x-www-form-urlencoded\r\nContent-Length: ' + str(len(body)) + '\r\n\r\n').encode() + body


class DeskTests(unittest.TestCase):
    def setUp(self):
        results = Path(__file__).resolve().parents[1] / 'test-results'
        results.mkdir(exist_ok=True)
        directory = tempfile.TemporaryDirectory(dir=results)
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / 'config.json'
        constants = patch.multiple(config, CONFIG_PATH=str(self.path), BACKUP_PATH=str(self.path) + '.backup', TEMP_PATH=str(self.path) + '.tmp')
        constants.start()
        self.addCleanup(constants.stop)
        ticks = patch.object(desk.time, 'ticks_diff', lambda now, before: now - before, create=True)
        ticks.start()
        self.addCleanup(ticks.stop)

    def values(self):
        return {'ssid': 'Café & Office', 'password': 'p&=+é', 'url': 'http://door/api/set?room=1', 'token': 't &=+é'}

    def test_fragmented_setup_form_persists_unicode_and_reboot_signal(self):
        self.assertTrue(desk.should_enter_setup())
        client = Client(form_request(self.values()))
        self.assertTrue(desk.handle_setup_client(client))
        self.assertTrue(client.closed)
        self.assertIn(b'200 OK', client.output)
        settings, error = config.load_config()
        self.assertIsNone(error)
        self.assertEqual(settings['wifi'], {'ssid': 'Café & Office', 'password': 'p&=+é'})
        self.assertEqual(settings['security']['auth_token'], 't &=+é')
        self.assertEqual(settings['desk']['receiver_url'], 'http://door/api/set?room=1')
        self.assertFalse(desk.should_enter_setup())

    def test_invalid_setup_never_saves_or_reboots(self):
        for changes in ({'ssid': ''}, {'url': 'javascript:alert(1)'}, {'url': ''}):
            values = self.values()
            values.update(changes)
            client = Client(form_request(values))
            self.assertFalse(desk.handle_setup_client(client))
            self.assertIn(b'400 Bad Request', client.output)
            self.assertFalse(self.path.exists())
            self.assertTrue(client.closed)

    def test_bad_paths_methods_and_incomplete_requests_do_not_crash(self):
        for request, status in ((b'GET / HTTP/1.1\r\n\r\n', b'200 OK'), (b'GET /save HTTP/1.1\r\n\r\n', b'405 Method Not Allowed'), (b'GET /unknown HTTP/1.1\r\n\r\n', b'404 Not Found'), (b'POST /save HTTP/1.1\r\nContent-Length: 100\r\n\r\nshort', b'400 Bad Request')):
            with self.subTest(request=request):
                client = Client(request)
                self.assertFalse(desk.handle_setup_client(client))
                self.assertIn(status, client.output)
                self.assertTrue(client.closed)

    def test_corrupt_or_blank_ssid_config_reenters_provisioning(self):
        for text in ('invalid', '{"wifi":null}', '{"wifi":{"ssid":""}}'):
            self.path.write_text(text)
            self.assertTrue(desk.should_enter_setup())

    def test_delivery_encodes_token_and_existing_query_and_bounds_timeout(self):
        settings = config.get_default_config()
        settings['desk']['receiver_url'] = self.values()['url']
        settings['desk']['source_tag'] = 'desk & office'
        settings['security']['auth_token'] = self.values()['token']
        response = types.SimpleNamespace(status_code=200, close=Mock())
        get = Mock(return_value=response)
        with patch.dict('sys.modules', dict.fromkeys(('requests', 'urequests'), types.SimpleNamespace(get=get))):
            self.assertTrue(desk.send_state(settings, True))
        args, kwargs = get.call_args
        self.assertEqual(kwargs['timeout'], 2)
        query = parse_qs(urlsplit(args[0]).query)
        self.assertEqual(query, {'room': ['1'], 'on': ['1'], 'source': ['desk & office'], 'token': ['t &=+é']})
        response.close.assert_called_once()

    def test_http_failure_or_exception_is_not_acknowledged_and_responses_close(self):
        settings = config.get_default_config()
        response = types.SimpleNamespace(status_code=403, close=Mock())
        with patch.dict('sys.modules', dict.fromkeys(('requests', 'urequests'), types.SimpleNamespace(get=Mock(return_value=response)))):
            self.assertFalse(desk.send_state(settings, True))
        response.close.assert_called_once()
        with patch.dict('sys.modules', dict.fromkeys(('requests', 'urequests'), types.SimpleNamespace(get=Mock(side_effect=OSError('timeout'))))):
            self.assertFalse(desk.send_state(settings, True))
        response.close.side_effect = OSError('socket already closed')
        response.status_code = 200
        with patch.dict('sys.modules', dict.fromkeys(('requests', 'urequests'), types.SimpleNamespace(get=Mock(return_value=response)))):
            self.assertTrue(desk.send_state(settings, True))

    def test_setup_feeds_watchdog_between_read_and_write(self):
        feed = Mock()
        client = Client(form_request(self.values()))
        self.assertTrue(desk.handle_setup_client(client, feed))
        self.assertGreaterEqual(feed.call_count, 2)

    def test_disconnect_during_setup_error_response_is_isolated(self):
        client = Client(b'POST /save HTTP/1.1\r\nContent-Length: 50\r\n\r\nshort')
        client.send = Mock(side_effect=OSError('peer disconnected'))
        self.assertFalse(desk.handle_setup_client(client))
        self.assertTrue(client.closed)
        client = Client(b'')
        client.recv = Mock(side_effect=OSError('connection reset'))
        client.send = Mock(side_effect=OSError('peer disconnected'))
        self.assertFalse(desk.handle_setup_client(client))
        self.assertTrue(client.closed)

    def test_ap_setup_serves_real_handler_and_reboots_after_save(self):
        class Reset(Exception):
            pass
        client = Client(form_request(self.values()))
        server = Mock()
        server.accept.return_value = (client, ('127.0.0.1', 1234))
        ap = Mock()
        network = types.SimpleNamespace(AP_IF=1, WLAN=Mock(return_value=ap))
        socket_module = types.SimpleNamespace(socket=Mock(return_value=server), SOL_SOCKET=1, SO_REUSEADDR=2)
        wdt = types.SimpleNamespace(feed=Mock())
        machine = types.SimpleNamespace(WDT=Mock(return_value=wdt), reset=Mock(side_effect=Reset()))
        with patch.dict('sys.modules', {'network': network, 'socket': socket_module, 'machine': machine}):
            with patch.object(desk.time, 'sleep'):
                with self.assertRaises(Reset):
                    desk.run_ap_setup()
        ap.config.assert_called_once_with(essid='DND-Desk-Setup', authmode=0)
        machine.reset.assert_called_once()
        self.assertTrue(client.closed)
        self.assertTrue(self.path.exists())
        server.close.assert_called_once()
        self.assertGreaterEqual(wdt.feed.call_count, 4)

    def test_initial_switch_state_and_debounce_and_failed_delivery_retry(self):
        sender = Mock(side_effect=[True, False, True])
        sync = desk.SwitchSynchronizer(1, 0, sender)
        sync.step(1, 0, True)
        sender.assert_called_once_with(False)
        sync.step(0, 100, True)
        sync.step(1, 200, True)
        sync.step(0, 250, True)
        sync.step(0, 549, True)
        self.assertEqual(sender.call_count, 1)
        sync.step(0, 1000, True)
        self.assertEqual(sender.call_count, 2)
        self.assertEqual(sync.delivered, 1)
        sync.step(0, 1999, True)
        self.assertEqual(sender.call_count, 2)
        sync.step(0, 2000, True)
        self.assertEqual(sender.call_count, 3)
        self.assertEqual(sync.delivered, 0)
        sender.assert_called_with(True)

    def test_offline_changes_sync_after_recovery_and_wraparound(self):
        sender = Mock(return_value=True)
        sync = desk.SwitchSynchronizer(1, 0, sender)
        sync.step(1, 0, True)
        sync.step(0, 100, False)
        sync.step(0, 500, False)
        self.assertEqual(sender.call_count, 1)
        sync.step(0, 600, True)
        self.assertEqual(sender.call_count, 2)
        sender.assert_called_with(True)
        with patch.object(desk.time, 'ticks_diff', lambda now, before: ((now - before + 512) % 1024) - 512):
            sync = desk.SwitchSynchronizer(1, 900, sender)
            sync.step(0, 950, False)
            sync.step(0, 300, True)
            self.assertEqual(sync.stable, 0)

    def test_normal_loop_survives_initial_wifi_failure_and_feeds_watchdog(self):
        settings = config.get_default_config()
        settings['wifi']['ssid'] = 'office'
        config.save_config(settings)
        class Stop(Exception):
            pass
        clock = types.SimpleNamespace(now=0)
        feeds = []
        def sleep(seconds):
            clock.now += round(seconds * 1000)
            if clock.now > 40500:
                raise Stop()
        wifi = Mock()
        wifi.isconnected.side_effect = lambda: wifi.connect.call_count >= 2
        wifi.connect.side_effect = [OSError('connection busy'), None]
        pin = Mock()
        pin.value.return_value = 0
        pin_class = Mock(return_value=pin)
        pin_class.IN, pin_class.PULL_UP = 0, 1
        machine = types.SimpleNamespace(Pin=pin_class, WDT=Mock(return_value=types.SimpleNamespace(feed=lambda: feeds.append(clock.now))))
        network = types.SimpleNamespace(STA_IF=0, WLAN=Mock(return_value=wifi))
        with patch.dict('sys.modules', {'machine': machine, 'network': network}):
            with patch.object(desk.time, 'ticks_ms', lambda: clock.now, create=True), patch.object(desk.time, 'sleep', sleep), patch.object(desk, 'send_state', return_value=True) as send:
                with self.assertRaises(Stop):
                    desk.run_normal()
        self.assertEqual(wifi.connect.call_count, 2)
        send.assert_called_once_with(settings, True)
        self.assertGreater(len(feeds), 300)
        self.assertLessEqual(max(b - a for a, b in zip(feeds, feeds[1:])), 100)
        machine.WDT.assert_called_once_with(timeout=8000)


if __name__ == '__main__':
    unittest.main()
