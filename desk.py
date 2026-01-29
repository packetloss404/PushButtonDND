import network
import time
import json
import socket
from machine import Pin

# Check for existing configuration
has_config = False
try:
    import config
    try:
        import os
        os.stat('/config.json')
        has_config = True
    except OSError:
        has_config = False
except ImportError:
    config = None


def url_decode(s):
    """Decode URL-encoded string"""
    s = s.replace('+', ' ')
    parts = s.split('%')
    result = parts[0]
    for part in parts[1:]:
        try:
            result += chr(int(part[:2], 16)) + part[2:]
        except (ValueError, IndexError):
            result += '%' + part
    return result


def setup_page():
    """Minimal config page for AP mode setup"""
    return """<!doctype html>
<html><head>
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>DND Desk Setup</title>
<style>
body{font-family:sans-serif;margin:20px;background:#1e1e1e;color:#fff}
input{width:100%;padding:8px;margin:4px 0 12px;box-sizing:border-box;border-radius:4px;border:1px solid #555;background:#333;color:#fff}
label{font-weight:bold;font-size:14px}
button{width:100%;padding:12px;background:#4CAF50;color:#fff;border:none;border-radius:6px;font-size:16px;cursor:pointer}
h1{text-align:center}
.info{color:#aaa;font-size:12px;margin-bottom:16px}
</style></head><body>
<h1>DND Desk Setup</h1>
<p class="info">Connect this desk unit to your WiFi and configure the door unit address.</p>
<form method="POST" action="/save">
<label>WiFi SSID</label>
<input name="ssid" required>
<label>WiFi Password</label>
<input name="password" type="password">
<label>Door Unit URL</label>
<input name="url" value="http://esp-doorlight.local/api/set">
<label>Auth Token</label>
<input name="token" value="SECRET123">
<button type="submit">Save &amp; Reboot</button>
</form></body></html>"""


def run_ap_setup():
    """Run AP mode setup server. Reboots after config is saved."""
    ap = network.WLAN(network.AP_IF)
    ap.active(True)
    ap.config(essid='DND-Desk-Setup', authmode=0)

    # Wait for AP to be active
    while not ap.active():
        time.sleep(0.1)

    print(f"[AP] Setup AP active: {ap.ifconfig()}")
    print("[AP] Connect to WiFi 'DND-Desk-Setup' and go to http://192.168.4.1")

    s = socket.socket()
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(('0.0.0.0', 80))
    s.listen(1)

    while True:
        cl, addr = s.accept()
        try:
            req = cl.recv(1024).decode()
            if not req:
                cl.close()
                continue

            if req.startswith("POST /save"):
                # Extract POST body
                body = req.split('\r\n\r\n', 1)[1] if '\r\n\r\n' in req else ""

                # Parse URL-encoded form data
                params = {}
                for pair in body.split('&'):
                    if '=' in pair:
                        k, v = pair.split('=', 1)
                        params[k] = url_decode(v)

                # Build config from defaults + form values
                new_config = config.get_default_config()
                new_config['wifi']['ssid'] = params.get('ssid', '')
                new_config['wifi']['password'] = params.get('password', '')
                new_config['security']['auth_token'] = params.get('token', 'SECRET123')
                new_config['desk'] = {
                    'receiver_url': params.get('url', 'http://esp-doorlight.local/api/set'),
                    'source_tag': 'desk'
                }

                success, error = config.save_config(new_config)
                if success:
                    cl.send("HTTP/1.1 200 OK\r\nContent-Type: text/html\r\n\r\n"
                            "<html><body style='background:#1e1e1e;color:#fff;font-family:sans-serif;text-align:center;padding:40px'>"
                            "<h2>Saved!</h2><p>Rebooting... Connect to your WiFi network.</p></body></html>")
                    cl.close()
                    time.sleep(2)
                    import machine
                    machine.reset()
                else:
                    cl.send(f"HTTP/1.1 500 Error\r\nContent-Type: text/plain\r\n\r\nSave failed: {error}")
                    cl.close()
            else:
                # Serve setup form
                cl.send("HTTP/1.1 200 OK\r\nContent-Type: text/html\r\n\r\n" + setup_page())
                cl.close()
        except Exception as e:
            print(f"[AP] Error: {e}")
            try:
                cl.close()
            except:
                pass


def run_normal():
    """Normal operation: monitor switch and send state to door unit."""
    cfg, err = config.load_config()
    if err:
        print(f"Config error: {err}")

    RECEIVER_URL = cfg.get('desk', {}).get('receiver_url', 'http://esp-doorlight.local/api/set')
    TOKEN = cfg['security']['auth_token']
    SOURCE = cfg.get('desk', {}).get('source_tag', 'desk')

    switch_pin = Pin(15, Pin.IN, Pin.PULL_UP)
    last_state = switch_pin.value()

    # Wi-Fi connect with 30-second timeout
    WIFI_TIMEOUT_MS = 30000
    wifi = network.WLAN(network.STA_IF)
    wifi.active(True)
    wifi.connect(cfg['wifi']['ssid'], cfg['wifi']['password'])
    print("Connecting to Wi-Fi...")
    wifi_start = time.ticks_ms()
    while not wifi.isconnected():
        if time.ticks_diff(time.ticks_ms(), wifi_start) > WIFI_TIMEOUT_MS:
            print("[WIFI] Connection timeout after 30s, will retry in main loop")
            break
        time.sleep(0.5)
    if wifi.isconnected():
        print("Connected:", wifi.ifconfig())
    else:
        print("[WIFI] Not connected, will retry in main loop")

    # Initialize hardware watchdog timer (8 second timeout)
    from machine import WDT
    wdt = WDT(timeout=8000)
    print("[WDT] Watchdog timer initialized (8s timeout)")

    def send_state(state):
        try:
            url = f"{RECEIVER_URL}?on={1 if state else 0}&source={SOURCE}"
            if TOKEN:
                url += f"&token={TOKEN}"
            print("Sending", url)
            import urequests
            resp = urequests.get(url)
            print(resp.text)
            resp.close()
        except Exception as e:
            print("Error sending:", e)

    last_wifi_check = time.ticks_ms()
    WIFI_CHECK_INTERVAL = 10000

    print("Monitoring switch...")
    while True:
        wdt.feed()
        now = time.ticks_ms()

        # Check switch state
        state = switch_pin.value()
        if state != last_state:
            last_state = state
            send_state(not state)  # LOW = ON (pull-up, switch to GND)
            time.sleep(0.3)  # Debounce

        # Check WiFi every 10 seconds
        if time.ticks_diff(now, last_wifi_check) > WIFI_CHECK_INTERVAL:
            last_wifi_check = now
            if not wifi.isconnected():
                print("[WIFI] Disconnected, reconnecting...")
                wifi.connect(cfg['wifi']['ssid'], cfg['wifi']['password'])

        time.sleep(0.05)


# Entry point
if has_config:
    run_normal()
else:
    if config:
        print("[DESK] No config found, entering AP setup mode")
        run_ap_setup()
    else:
        print("[ERROR] config.py module not found, cannot start")
        print("[ERROR] Upload config.py to this device")
