"""Desk ESP32 firmware. Importing this module never starts hardware or servers."""
import time
import config
from http_utils import HTTPError, read_request, send_response, parse_query, url_encode

DEBOUNCE_MS = 300
RETRY_MS = 1000
HTTP_TIMEOUT = 2


def setup_page():
    return """<!doctype html>
<html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>DND Desk Setup</title>
<style>
body{font-family:sans-serif;margin:20px;background:#1e1e1e;color:#fff;max-width:600px}
input{width:100%;padding:8px;margin:4px 0 12px;box-sizing:border-box;border-radius:4px;border:1px solid #555;background:#333;color:#fff}
label{font-weight:bold;font-size:14px}
button{width:100%;padding:12px;background:#4CAF50;color:#fff;border:none;border-radius:6px;font-size:16px;cursor:pointer}
h1{text-align:center}.info{color:#aaa;font-size:12px;margin-bottom:16px}
</style></head><body>
<h1>DND Desk Setup</h1>
<p class="info">Connect this desk unit to your WiFi and configure the door unit address.</p>
<form method="POST" action="/save">
<label for="ssid">WiFi SSID</label><input id="ssid" name="ssid" required>
<label for="password">WiFi Password</label><input id="password" name="password" type="password">
<label for="url">Door Unit URL</label><input id="url" name="url" type="url" required value="http://esp-doorlight.local/api/set">
<label for="token">Auth Token</label><input id="token" name="token" value="">
<p class="info">Use the token configured on the door unit; leave blank if authentication is disabled.</p>
<button type="submit">Save &amp; Reboot</button>
</form></body></html>"""


def handle_setup_client(client, feed=None):
    """Serve the actual setup protocol; return True when caller should reboot."""
    def reply(status, body, content_type='text/plain'):
        if feed:
            feed()
        send_response(client, status, body, content_type)

    try:
        method, target, headers, body = read_request(client)
        if feed:
            feed()
        path = target.split('?', 1)[0]
        if path == '/' and method == 'GET':
            reply(200, setup_page(), 'text/html; charset=utf-8')
        elif path == '/save':
            if method != 'POST':
                reply(405, 'Use POST to save settings')
                return False
            if headers.get('content-type', '').split(';', 1)[0].strip().lower() != 'application/x-www-form-urlencoded':
                reply(415, 'Expected an HTML form')
                return False
            values = parse_query('/?' + body)
            new_config = config.get_default_config()
            new_config['wifi'] = {'ssid': values.get('ssid', ''), 'password': values.get('password', '')}
            new_config['security']['auth_token'] = values.get('token', '')
            new_config['desk'] = {'receiver_url': values.get('url', ''), 'source_tag': 'desk'}
            if not new_config['wifi']['ssid'].strip():
                reply(400, 'WiFi SSID is required')
                return False
            valid, error = config.validate_config(new_config)
            if not valid:
                reply(400, error)
                return False
            success, error = config.save_config(new_config)
            if not success:
                reply(500, 'Save failed: ' + str(error))
                return False
            reply(200, '<!doctype html><html><body><h2>Saved!</h2><p>Rebooting... Connect to your WiFi network.</p></body></html>', 'text/html; charset=utf-8')
            return True
        else:
            reply(404, 'Not found')
    except HTTPError as error:
        try:
            reply(error.status, error.message)
        except OSError:
            pass
    except (ValueError, OSError) as error:
        try:
            reply(400, 'Invalid or incomplete request')
        except OSError:
            pass
        print('[AP] Request error:', error)
    finally:
        try:
            client.close()
        except OSError:
            pass
    return False


def should_enter_setup():
    settings, error = config.load_config()
    return bool(error or not settings['wifi']['ssid'].strip())


def run_ap_setup():
    import network
    import socket
    import machine
    wdt = machine.WDT(timeout=8000)
    ap = network.WLAN(network.AP_IF)
    ap.active(True)
    ap.config(essid='DND-Desk-Setup', authmode=0)
    print('[AP] Connect to DND-Desk-Setup and open http://192.168.4.1')
    server = socket.socket()
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(('0.0.0.0', 80))
    server.listen(1)
    server.settimeout(1)
    try:
        while True:
            wdt.feed()
            try:
                client, _ = server.accept()
            except OSError:
                continue
            if handle_setup_client(client, wdt.feed):
                wdt.feed()
                time.sleep(2)
                machine.reset()
                return
    finally:
        server.close()


def send_state(settings, state):
    """Send with encoded arguments and a bounded socket timeout; report success."""
    response = None
    receiver = settings['desk']['receiver_url']
    separator = '&' if '?' in receiver else '?'
    url = receiver + separator + 'on=' + ('1' if state else '0')
    url += '&source=' + url_encode(settings['desk']['source_tag'])
    token = settings['security']['auth_token']
    if token:
        url += '&token=' + url_encode(token)
    try:
        try:
            import requests as urequests
        except ImportError:
            import urequests
        response = urequests.get(url, timeout=HTTP_TIMEOUT)
        return 200 <= response.status_code < 300
    except Exception as error:
        print('[HTTP] State delivery failed:', error)
        return False
    finally:
        if response is not None:
            try:
                response.close()
            except OSError:
                pass


class SwitchSynchronizer:
    """Debounce to a stable level and retry unacknowledged delivery after outages."""
    def __init__(self, raw_state, now, sender):
        self.candidate = raw_state
        self.stable = raw_state
        self.candidate_since = now
        self.delivered = None
        self.last_attempt = None
        self.was_connected = False
        self.sender = sender

    def step(self, raw_state, now, connected):
        if raw_state != self.candidate:
            self.candidate = raw_state
            self.candidate_since = now
        if time.ticks_diff(now, self.candidate_since) >= DEBOUNCE_MS:
            self.stable = self.candidate
        if connected and not self.was_connected:
            self.delivered = None
            self.last_attempt = None
        self.was_connected = connected
        if connected and self.delivered != self.stable:
            if self.last_attempt is None or time.ticks_diff(now, self.last_attempt) >= RETRY_MS:
                self.last_attempt = now
                if self.sender(not self.stable):
                    self.delivered = self.stable


def run_normal():
    import network
    from machine import Pin, WDT
    settings, error = config.load_config()
    if error or not settings['wifi']['ssid'].strip():
        run_ap_setup()
        return
    wdt = WDT(timeout=8000)
    switch = Pin(15, Pin.IN, Pin.PULL_UP)
    wifi = network.WLAN(network.STA_IF)
    wifi.active(True)
    try:
        wifi.connect(settings['wifi']['ssid'], settings['wifi']['password'])
    except OSError as error:
        print('[WIFI] Initial connection failed:', error)
    started = time.ticks_ms()
    while not wifi.isconnected() and time.ticks_diff(time.ticks_ms(), started) < 30000:
        wdt.feed()
        time.sleep(0.1)
    sync = SwitchSynchronizer(switch.value(), time.ticks_ms(), lambda state: send_state(settings, state))
    last_wifi_check = time.ticks_ms()
    while True:
        wdt.feed()
        now = time.ticks_ms()
        connected = wifi.isconnected()
        sync.step(switch.value(), now, connected)
        if not connected and time.ticks_diff(now, last_wifi_check) >= 10000:
            last_wifi_check = now
            try:
                wifi.connect(settings['wifi']['ssid'], settings['wifi']['password'])
            except OSError as error:
                print('[WIFI] Reconnect failed:', error)
        time.sleep(0.05)


def run():
    if should_enter_setup():
        run_ap_setup()
    else:
        run_normal()


if __name__ == '__main__':
    run()
