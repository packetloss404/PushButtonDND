import network
import socket
from machine import Pin
import time
import config
import json
import mqtt_client
from http_utils import read_request, send_response, parse_query, html_escape, url_encode, HTTPError

# Importing this module never starts hardware or a server. run() owns boot.
cfg = config.get_default_config()
SSID = ""
PASSWORD = ""
AUTH_TOKEN = ""
MQTT_ENABLED = False
MQTT_CONFIG = cfg['mqtt']
led_pin = None
is_on = False
last_change = 0
event_log = []
MAX_LOG_SIZE = 20
mqtt = None
wlan = None
ap = None
wdt = None
wifi_connected = False
last_wifi_check = 0
last_mqtt_check = 0
WIFI_CHECK_INTERVAL = 10000
WIFI_TIMEOUT_MS = 30000


def log_event(event_type, detail):
    """Store the most recent 20 state, WiFi and MQTT events."""
    event_log.append({"ts": time.ticks_ms(), "type": event_type, "detail": detail})
    if len(event_log) > MAX_LOG_SIZE:
        event_log.pop(0)
    print("[LOG] {}: {}".format(event_type, detail))


def mqtt_command_handler(topic, msg):
    payload = msg.decode() if isinstance(msg, bytes) else msg
    if payload == "ON":
        set_output(True, "mqtt")
    elif payload == "OFF":
        set_output(False, "mqtt")


def initialize(configuration=None, connect_wifi=True):
    """Initialize safe relay state and configuration; optionally connect hardware.

    Tests can pass configuration and connect_wifi=False, then exercise the same
    handle_client() used by run() with real accepted TCP sockets.
    """
    global cfg, SSID, PASSWORD, AUTH_TOKEN, MQTT_ENABLED, MQTT_CONFIG
    global led_pin, is_on, last_change, mqtt, wlan, ap, wdt
    global wifi_connected, last_wifi_check, last_mqtt_check, event_log
    if configuration is None:
        cfg, error = config.load_config()
        if error:
            print("[CONFIG]", error)
    else:
        cfg = configuration
    SSID = cfg['wifi']['ssid']
    PASSWORD = cfg['wifi']['password']
    AUTH_TOKEN = cfg['security']['auth_token']
    MQTT_ENABLED = cfg['mqtt']['enabled']
    MQTT_CONFIG = cfg['mqtt']
    led_pin = Pin(2, Pin.OUT, value=0)
    is_on = False
    last_change = time.ticks_ms()
    event_log = []
    mqtt = None
    wlan = None
    ap = None
    wdt = None
    wifi_connected = False
    last_wifi_check = time.ticks_ms()
    last_mqtt_check = time.ticks_ms()
    if not connect_wifi:
        return
    # Watchdog is active and fed during the bounded boot connection wait.
    from machine import WDT
    wdt = WDT(timeout=8000)
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    if SSID:
        try:
            wlan.connect(SSID, PASSWORD)
        except OSError as error:
            log_event("wifi", "Connection failed: {}".format(error))
        started = time.ticks_ms()
        while not wlan.isconnected() and time.ticks_diff(time.ticks_ms(), started) < WIFI_TIMEOUT_MS:
            wdt.feed()
            time.sleep(0.25)
    else:
        # Blank or corrupt initial configuration must remain provisionable.
        ap = network.WLAN(network.AP_IF)
        ap.active(True)
        ap.config(essid="DND-Door-Setup", authmode=0)
        log_event("wifi", "Setup AP: DND-Door-Setup at {}".format(ap.ifconfig()[0]))
    wifi_connected = wlan.isconnected()
    log_event("wifi", "Connected: {}".format(wlan.ifconfig()[0]) if wifi_connected else "Station disconnected")
    if MQTT_ENABLED:
        wdt.feed()
        mqtt = mqtt_client.MQTTClient(MQTT_CONFIG)
        mqtt.message_callback = mqtt_command_handler
        # Preserve failed clients so background retry can recover.
        if wifi_connected:
            wdt.feed()
            connected = mqtt.connect()
            wdt.feed()
            if connected:
                mqtt.publish_state(is_on)
                wdt.feed()
                log_event("mqtt", "Connected to broker")


# Helper functions
def set_output(on, source="unknown"):
    global is_on, last_change
    is_on = on
    if led_pin is not None:
        led_pin.value(on)
    last_change = time.ticks_ms()
    state_str = "ON" if on else "OFF"
    print("Light", state_str)
    log_event("state", f"{state_str} via {source}")

    # Cache state while disconnected; publish immediately while connected.
    if mqtt:
        if wdt:
            wdt.feed()
        was_connected = mqtt.connected
        mqtt.publish_state(on)
        if was_connected and not mqtt.connected:
            log_event('mqtt', 'Disconnected from broker')

def html_page():
    status = "ON" if is_on else "OFF"
    color = "#f44336" if is_on else "#4CAF50"


    return f"""<!doctype html>
<html>
<head>
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>PushButtonDND</title>

<style>
  :root {{
    --bg: #1e1e1e;
    --text: #ffffff;
    --card: #2c2c2c;
  }}

  body.light {{
    --bg: #f0f0f0;
    --text: #000000;
    --card: #ffffff;
  }}

  body {{
    background: var(--bg);
    color: var(--text);
    font-family: "Segoe UI", sans-serif;
    margin: 0;
    padding: 40px 20px;
    text-align: center;
    transition: background 0.3s, color 0.3s;
  }}

  #themeToggle {{
    position: fixed;
    top: 20px;
    right: 20px;
    background: var(--card);
    border: 0;
    border-radius: 20px;
    padding: 8px 14px;
    font-size: 14px;
    cursor: pointer;
    color: var(--text);
    box-shadow: 0 0 10px rgba(0,0,0,0.2);
    transition: background 0.3s, color 0.3s, transform 0.2s;
  }}
  #themeToggle:hover {{
    transform: scale(1.07);
  }}

  h1 {{
    margin-top: 50px;
    font-size: 32px;
    text-shadow: 0 0 10px rgba(255,255,255,0.2);
  }}

  .glow-ring {{
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 140px;
    height: 140px;
    border-radius: 50%;
    border: 5px solid {color};
    margin: 40px auto;
    font-size: 32px;
    color: {color};
    font-weight: bold;
    animation: pulseGlow 1.7s infinite ease-in-out;
    box-shadow: 0 0 20px {color}, 0 0 40px {color};
    transition: border 0.3s, color 0.3s, box-shadow 0.3s;
  }}

  @keyframes pulseGlow {{
    0%, 100% {{
      transform: scale(1);
    }}
    50% {{
      transform: scale(1.05);
    }}
  }}

  button.action {{
    font-size: 22px;
    padding: 15px 50px;
    margin: 15px;
    border: 0;
    border-radius: 12px;
    color: #fff;
    cursor: pointer;
    transition: transform 0.2s, box-shadow 0.2s;
  }}
  button.action:hover {{
    transform: scale(1.08);
    box-shadow: 0 0 15px rgba(255,255,255,0.3);
  }}

  .btn-on {{
    background: linear-gradient(135deg, #d32f2f, #ff5252);
  }}

  .btn-off {{
    background: linear-gradient(135deg, #2e7d32, #66bb6a);
  }}

  .btn-settings {{
    position: fixed;
    top: 100px;
    right: 20px;
    background: linear-gradient(135deg, #555, #888);
    border: 0;
    border-radius: 8px;
    padding: 8px 16px;
    font-size: 13px;
    cursor: pointer;
    color: white;
    text-decoration: none;
    box-shadow: 0 0 10px rgba(0,0,0,0.2);
    transition: transform 0.2s, box-shadow 0.2s;
    font-weight: 500;
  }}

  .btn-settings:hover {{
    transform: scale(1.05);
    box-shadow: 0 0 15px rgba(0,0,0,0.3);
  }}

  .status-bar {{
    position: fixed;
    top: 60px;
    right: 20px;
    font-size: 12px;
  }}

  .mqtt-status {{
    padding: 4px 10px;
    border-radius: 12px;
    font-weight: bold;
    display: inline-block;
  }}

  .mqtt-connected {{
    background: #4CAF50;
    color: white;
  }}

  .mqtt-disconnected {{
    background: #f44336;
    color: white;
  }}

  .mqtt-disabled {{
    background: #555;
    color: #ccc;
  }}
</style>
</head>

<body>

<button id="themeToggle" onclick="toggleTheme()">Dark</button>

<div class="status-bar">
  <span id="mqttStatus" class="mqtt-status mqtt-disabled">MQTT: Off</span>
</div>

<h1>DND Status:</h1>

<div id="glow" class="glow-ring">{status}</div>

<p><label for="control_token">API token</label>
<input id="control_token" type="password" autocomplete="off" placeholder="If configured"></p>
<p id="control_error" role="alert"></p>
<button class="action btn-on" onclick="setLight(true)">
  ON
</button>

<button class="action btn-off" onclick="setLight(false)">
  OFF
</button>

<a href="/config" onclick="openSettings(event, this)" class="btn-settings">
  Settings
</a>

<script>
function toggleTheme() {{
  document.body.classList.toggle("light");
  let isLight = document.body.classList.contains("light");
  document.getElementById("themeToggle").textContent =
    isLight ? "Light" : "Dark";
}}

const tokenInput = document.getElementById('control_token');
tokenInput.value = new URLSearchParams(window.location.search).get('token') || '';
function tokenQuery() {{
  return tokenInput.value ? '?token=' + encodeURIComponent(tokenInput.value) : '';
}}
function openSettings(event, link) {{
  link.href = '/config' + tokenQuery();
  if (event.button === 0 && !event.ctrlKey && !event.metaKey && !event.shiftKey && !event.altKey) {{
    stopPolling();
  }}
}}
async function setLight(on) {{
  const error = document.getElementById('control_error');
  error.textContent = '';
  try {{
    const response = await fetch('/api/set?on=' + (on ? '1' : '0') + '&source=web' +
      (tokenInput.value ? '&token=' + encodeURIComponent(tokenInput.value) : ''));
    if (!response.ok) throw new Error(response.status === 403 ? 'Invalid API token' : 'Control failed');
    pollState();
  }} catch (e) {{ error.textContent = e.message; }}
}}

/* ========== LIVE POLLING ========== */
let pollTimer = null;
let pollController = null;
let pollingPaused = false;
function stopPolling() {{
  pollingPaused = true;
  clearInterval(pollTimer);
  pollTimer = null;
  if (pollController) pollController.abort();
  pollController = null;
}}
function startPolling() {{
  pollingPaused = false;
  pollState();
  if (pollTimer === null) pollTimer = setInterval(pollState, 1000);
}}
function pollState() {{
  if (pollingPaused || pollController) return;
  const controller = new AbortController();
  pollController = controller;
  fetch('/api/state', {{signal: controller.signal}})
    .then(r => {{
      if (!r.ok) throw new Error('State request failed');
      return r.json();
    }})
    .then(data => {{
      if (pollingPaused || controller.signal.aborted) return;
      let on = data.on;
      let glow = document.getElementById("glow");

      // Update ring text
      glow.textContent = on ? "ON" : "OFF";

      // Colors
      let c = on ? "#f44336" : "#4CAF50";

      // Apply updates
      glow.style.borderColor = c;
      glow.style.color = c;
      glow.style.boxShadow = "0 0 20px " + c + ", 0 0 40px " + c;

      // Update MQTT status
      let mqttEl = document.getElementById("mqttStatus");
      if (mqttEl && data.mqtt_enabled) {{
        if (data.mqtt_status === "connected") {{
          mqttEl.textContent = "MQTT: Connected";
          mqttEl.className = "mqtt-status mqtt-connected";
        }} else {{
          mqttEl.textContent = "MQTT: Disconnected";
          mqttEl.className = "mqtt-status mqtt-disconnected";
        }}
      }} else if (mqttEl) {{
        mqttEl.textContent = "MQTT: Disabled";
        mqttEl.className = "mqtt-status mqtt-disabled";
      }}
    }})
    .catch(e => {{
      if (e.name !== 'AbortError') console.log("Polling error:", e);
    }})
    .finally(() => {{
      if (pollController === controller) pollController = null;
    }});
}}

// Stop before navigation begins: WebKit can replace its fetch context before
// pagehide. Resume when returning through the browser's back/forward cache.
window.addEventListener('pagehide', stopPolling);
window.addEventListener('pageshow', () => {{ if (pollingPaused) startPolling(); }});
startPolling();
</script>

</body>
</html>
"""

def config_page():
    """Generate configuration page with tabbed interface"""
    mqtt_enabled_checked = "checked" if cfg['mqtt']['enabled'] else ""
    teams_enabled_checked = ""  # Integration is a disabled placeholder.
    # Attribute values and script literals require different escaping.
    values = {section: {key: html_escape(value) for key, value in fields.items()}
              for section, fields in cfg.items() if isinstance(fields, dict)}
    auth_json = json.dumps(AUTH_TOKEN).replace("<", "\\u003c")

    return f"""<!doctype html>
<html>
<head>
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>PushButtonDND - Configuration</title>

<style>
  :root {{
    --bg: #1e1e1e;
    --text: #ffffff;
    --card: #2c2c2c;
    --border: #444;
    --input-bg: #333;
    --primary: #4CAF50;
    --secondary: #2196F3;
    --warning: #ff9800;
  }}

  body.light {{
    --bg: #f0f0f0;
    --text: #000000;
    --card: #ffffff;
    --border: #ddd;
    --input-bg: #fafafa;
  }}

  body {{
    background: var(--bg);
    color: var(--text);
    font-family: "Segoe UI", sans-serif;
    margin: 0;
    padding: 20px;
    transition: background 0.3s, color 0.3s;
  }}

  .container {{
    max-width: 600px;
    margin: 0 auto;
    background: var(--card);
    padding: 30px;
    border-radius: 12px;
    box-shadow: 0 4px 20px rgba(0,0,0,0.3);
  }}

  h1 {{
    margin-top: 0;
    text-align: center;
    font-size: 28px;
  }}

  .tabs {{
    display: flex;
    gap: 5px;
    margin-bottom: 20px;
    border-bottom: 2px solid var(--border);
  }}

  .tab {{
    flex: 1;
    padding: 12px;
    background: transparent;
    border: none;
    border-bottom: 3px solid transparent;
    color: var(--text);
    cursor: pointer;
    font-size: 14px;
    transition: all 0.3s;
  }}

  .tab:hover {{
    background: var(--input-bg);
  }}

  .tab.active {{
    border-bottom-color: var(--primary);
    font-weight: bold;
  }}

  .tab-content {{
    display: none;
    animation: fadeIn 0.3s;
  }}

  .tab-content.active {{
    display: block;
  }}

  @keyframes fadeIn {{
    from {{ opacity: 0; }}
    to {{ opacity: 1; }}
  }}

  .form-group {{
    margin-bottom: 20px;
  }}

  label {{
    display: block;
    margin-bottom: 6px;
    font-weight: 500;
    font-size: 14px;
  }}

  input[type="text"],
  input[type="password"],
  input[type="number"] {{
    width: 100%;
    padding: 10px;
    background: var(--input-bg);
    border: 1px solid var(--border);
    border-radius: 6px;
    color: var(--text);
    font-size: 14px;
    box-sizing: border-box;
  }}

  input[type="checkbox"] {{
    width: 18px;
    height: 18px;
    margin-right: 8px;
    vertical-align: middle;
  }}

  .checkbox-label {{
    display: inline-flex;
    align-items: center;
    cursor: pointer;
    user-select: none;
  }}

  .password-field {{
    display: flex;
    gap: 10px;
  }}

  .password-field input {{
    flex: 1;
  }}

  .toggle-password {{
    padding: 10px 15px;
    background: var(--secondary);
    border: none;
    border-radius: 6px;
    color: white;
    cursor: pointer;
    font-size: 13px;
    white-space: nowrap;
  }}

  .toggle-password:hover {{
    opacity: 0.9;
  }}

  small {{
    display: block;
    margin-top: 4px;
    color: #888;
    font-size: 12px;
  }}

  .actions {{
    display: flex;
    gap: 10px;
    margin-top: 30px;
    padding-top: 20px;
    border-top: 2px solid var(--border);
  }}

  .btn {{
    flex: 1;
    padding: 14px;
    border: none;
    border-radius: 8px;
    font-size: 16px;
    font-weight: bold;
    cursor: pointer;
    transition: transform 0.2s, box-shadow 0.2s;
  }}

  .btn:hover {{
    transform: scale(1.03);
    box-shadow: 0 4px 12px rgba(0,0,0,0.3);
  }}

  .btn-save {{
    background: linear-gradient(135deg, #2e7d32, #66bb6a);
    color: white;
  }}

  .btn-reset {{
    background: linear-gradient(135deg, #d32f2f, #ff5252);
    color: white;
  }}

  .btn-cancel {{
    background: linear-gradient(135deg, #555, #888);
    color: white;
    text-decoration: none;
    display: flex;
    align-items: center;
    justify-content: center;
  }}

  .coming-soon-badge {{
    display: inline-block;
    background: var(--warning);
    color: white;
    padding: 4px 12px;
    border-radius: 12px;
    font-size: 11px;
    font-weight: bold;
    margin-bottom: 15px;
  }}

  .disabled-section {{
    opacity: 0.5;
    pointer-events: none;
  }}

  .info {{
    background: var(--input-bg);
    padding: 12px;
    border-radius: 6px;
    border-left: 4px solid var(--secondary);
    font-size: 13px;
    line-height: 1.5;
    margin-top: 15px;
  }}

  #themeToggle {{
    position: fixed;
    top: 20px;
    right: 20px;
    background: var(--card);
    border: 0;
    border-radius: 20px;
    padding: 8px 14px;
    font-size: 14px;
    cursor: pointer;
    color: var(--text);
    box-shadow: 0 0 10px rgba(0,0,0,0.2);
    transition: background 0.3s, color 0.3s, transform 0.2s;
  }}

  #themeToggle:hover {{
    transform: scale(1.07);
  }}
</style>
</head>

<body>

<button id="themeToggle" onclick="toggleTheme()">Dark</button>

<div class="container">
  <h1>Configuration</h1>

  <!-- Tab Navigation -->
  <div class="tabs">
    <button class="tab active" onclick="switchTab('wifi', this)">WiFi</button>
    <button class="tab" onclick="switchTab('security', this)">Security</button>
    <button class="tab" onclick="switchTab('mqtt', this)">MQTT</button>
    <button class="tab" onclick="switchTab('teams', this)">Teams</button>
  </div>

  <!-- WiFi Tab -->
  <div id="wifi" class="tab-content active">
    <div class="form-group">
      <label for="ssid">WiFi Network (SSID)</label>
      <input type="text" id="ssid" value="{values['wifi']['ssid']}" placeholder="Your WiFi network name">
      <small>Network name (case-sensitive)</small>
    </div>

    <div class="form-group">
      <label for="wifi_password">WiFi Password</label>
      <div class="password-field">
        <input type="password" id="wifi_password" value="{values['wifi']['password']}" placeholder="WiFi password">
        <button class="toggle-password" onclick="togglePassword('wifi_password', this)">Show</button>
      </div>
      <small>Required for WPA/WPA2 networks</small>
    </div>
  </div>

  <!-- Security Tab -->
  <div id="security" class="tab-content">
    <div class="form-group">
      <label for="auth_token">API Authentication Token</label>
      <input type="text" id="auth_token" value="{values['security']['auth_token']}" placeholder="Leave blank to disable">
      <small>Required for /api/set and /config endpoints. Leave blank to disable authentication.</small>
    </div>
  </div>

  <!-- MQTT Tab -->
  <div id="mqtt" class="tab-content">
    <div class="form-group">
      <label class="checkbox-label">
        <input type="checkbox" id="mqtt_enabled" {mqtt_enabled_checked}>
        <span>Enable MQTT Integration</span>
      </label>
      <small>Connect to MQTT broker for Home Assistant integration</small>
    </div>

    <div class="form-group">
      <label for="mqtt_broker">MQTT Broker Host</label>
      <input type="text" id="mqtt_broker" value="{values['mqtt']['broker']}" placeholder="homeassistant.local or IP">
      <small>Hostname or IP address of your MQTT broker</small>
    </div>

    <div class="form-group">
      <label for="mqtt_port">MQTT Port</label>
      <input type="number" id="mqtt_port" value="{values['mqtt']['port']}" placeholder="1883">
      <small>Default: 1883 (unencrypted). TLS is not supported by this firmware.</small>
    </div>

    <div class="form-group">
      <label for="mqtt_username">MQTT Username</label>
      <input type="text" id="mqtt_username" value="{values['mqtt']['username']}" placeholder="Leave blank if not required">
      <small>Optional: Leave blank for anonymous access</small>
    </div>

    <div class="form-group">
      <label for="mqtt_password">MQTT Password</label>
      <div class="password-field">
        <input type="password" id="mqtt_password" value="{values['mqtt']['password']}" placeholder="Leave blank if not required">
        <button class="toggle-password" onclick="togglePassword('mqtt_password', this)">Show</button>
      </div>
    </div>

    <div class="form-group">
      <label for="mqtt_topic_prefix">Topic Prefix</label>
      <input type="text" id="mqtt_topic_prefix" value="{values['mqtt']['topic_prefix']}" placeholder="pushbuttondnd">
      <small>Prefix for MQTT topics (e.g., pushbuttondnd/state)</small>
    </div>

    <div class="form-group">
      <label for="mqtt_device_name">Device Name</label>
      <input type="text" id="mqtt_device_name" value="{values['mqtt']['device_name']}" placeholder="DND Light">
      <small>Friendly name shown in Home Assistant</small>
    </div>

    <div class="info">
      💡 <strong>Home Assistant:</strong> Enable MQTT integration to auto-discover this device in Home Assistant.
      Make sure your MQTT broker is running and accessible.
    </div>
  </div>

  <!-- Teams Tab -->
  <div id="teams" class="tab-content">
    <div class="coming-soon-badge">Coming Soon</div>

    <div class="disabled-section">
      <div class="form-group">
        <label class="checkbox-label">
          <input type="checkbox" id="teams_enabled" {teams_enabled_checked} disabled>
          <span>Enable Teams Integration</span>
        </label>
        <small>Sync DND light with Microsoft Teams presence</small>
      </div>

      <div class="form-group">
        <label for="teams_client_id">Azure AD Client ID</label>
        <input type="text" id="teams_client_id" value="{values['teams']['client_id']}" disabled placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx">
      </div>

      <div class="form-group">
        <label for="teams_tenant_id">Azure AD Tenant ID</label>
        <input type="text" id="teams_tenant_id" value="{values['teams']['tenant_id']}" disabled placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx">
      </div>

      <div class="form-group">
        <label for="teams_client_secret">Client Secret</label>
        <div class="password-field">
          <input type="password" id="teams_client_secret" value="{values['teams']['client_secret']}" disabled placeholder="Azure AD application secret">
          <button class="toggle-password" disabled>Show</button>
        </div>
      </div>

      <div class="form-group">
        <label for="teams_polling_interval">Polling Interval (seconds)</label>
        <input type="number" id="teams_polling_interval" value="{values['teams']['polling_interval']}" disabled placeholder="300">
        <small>How often to check Teams status (default: 300 = 5 minutes)</small>
      </div>
    </div>

    <div class="info">
      🚧 <strong>Future Feature:</strong> Teams integration will sync your Microsoft Teams status with the DND light.
      When you're in a meeting, the light will turn on automatically. This requires Azure AD app registration.
    </div>
  </div>

  <!-- Action Buttons -->
  <div class="actions">
    <button class="btn btn-save" onclick="saveConfig()">Save & Reboot</button>
    <button class="btn btn-reset" onclick="resetDefaults()">Reset to Defaults</button>
    <a href="/" class="btn btn-cancel">Cancel</a>
  </div>
</div>

<script>
function switchTab(tabName, button) {{
  // Hide all tab contents
  document.querySelectorAll('.tab-content').forEach(el => {{
    el.classList.remove('active');
  }});

  // Deactivate all tabs
  document.querySelectorAll('.tab').forEach(el => {{
    el.classList.remove('active');
  }});

  // Show selected tab content
  document.getElementById(tabName).classList.add('active');

  // Activate selected tab button
  const selected = button || document.querySelectorAll('.tab')[['wifi','security','mqtt','teams'].indexOf(tabName)];
  if (selected) selected.classList.add('active');
}}

function togglePassword(fieldId, btn) {{
  const field = document.getElementById(fieldId);

  if (field.type === 'password') {{
    field.type = 'text';
    btn.textContent = 'Hide';
  }} else {{
    field.type = 'password';
    btn.textContent = 'Show';
  }}
}}

function toggleTheme() {{
  document.body.classList.toggle("light");
  let isLight = document.body.classList.contains("light");
  document.getElementById("themeToggle").textContent = isLight ? "Light" : "Dark";
}}

function saveConfig() {{
  if (!confirm('Save configuration and reboot device?\\n\\nThe device will restart with new settings in 3 seconds.')) {{
    return;
  }}

  // Gather form data
  const newConfig = {{
    version: 1,
    wifi: {{
      ssid: document.getElementById('ssid').value,
      password: document.getElementById('wifi_password').value
    }},
    security: {{
      auth_token: document.getElementById('auth_token').value
    }},
    mqtt: {{
      enabled: document.getElementById('mqtt_enabled').checked,
      broker: document.getElementById('mqtt_broker').value,
      port: parseInt(document.getElementById('mqtt_port').value),
      username: document.getElementById('mqtt_username').value,
      password: document.getElementById('mqtt_password').value,
      topic_prefix: document.getElementById('mqtt_topic_prefix').value,
      device_name: document.getElementById('mqtt_device_name').value,
      qos: 1
    }},
    teams: {{
      enabled: false,
      client_id: document.getElementById('teams_client_id').value,
      tenant_id: document.getElementById('teams_tenant_id').value,
      client_secret: document.getElementById('teams_client_secret').value,
      polling_interval: parseInt(document.getElementById('teams_polling_interval').value)
    }},
    desk: {{
      receiver_url: {json.dumps(cfg['desk']['receiver_url']).replace('<', chr(92) + 'u003c')},
      source_tag: {json.dumps(cfg['desk']['source_tag']).replace('<', chr(92) + 'u003c')}
    }},
    features: {{
      enable_mqtt: document.getElementById('mqtt_enabled').checked,
      enable_teams: false
    }}
  }};

  // Validate
  if (!newConfig.wifi.ssid) {{
    alert('WiFi SSID is required!');
    switchTab('wifi');
    return;
  }}

  if (isNaN(newConfig.mqtt.port) || newConfig.mqtt.port < 1 || newConfig.mqtt.port > 65535) {{
    alert('MQTT port must be between 1 and 65535');
    switchTab('mqtt');
    return;
  }}

  // Save configuration
  const currentToken = {auth_json};
  const tokenParam = currentToken ? '?token=' + encodeURIComponent(currentToken) : '';

  fetch('/api/config' + tokenParam, {{
    method: 'POST',
    headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify(newConfig)
  }})
  .then(r => r.json())
  .then(data => {{
    if (data.success) {{
      alert('Configuration saved!\\n\\nDevice will reboot in 3 seconds...');
      setTimeout(() => {{
        window.location = '/';
      }}, 3000);
    }} else {{
      alert('Error saving configuration:\\n' + data.error);
    }}
  }})
  .catch(e => {{
    alert('Failed to save configuration:\\n' + e);
  }});
}}

function resetDefaults() {{
  if (!confirm('Reset all settings to factory defaults and reboot?\\n\\nThis cannot be undone!')) {{
    return;
  }}

  const currentToken = {auth_json};
  const tokenParam = currentToken ? '?token=' + encodeURIComponent(currentToken) : '';

  fetch('/api/config/reset' + tokenParam, {{
    method: 'POST'
  }})
  .then(r => r.json())
  .then(data => {{
    if (data.success) {{
      alert('Configuration reset to defaults!\\n\\nDevice will reboot in 3 seconds...');
      setTimeout(() => {{
        window.location = '/';
      }}, 3000);
    }} else {{
      alert('Error resetting configuration:\\n' + data.error);
    }}
  }})
  .catch(e => {{
    alert('Failed to reset configuration:\\n' + e);
  }});
}}
</script>

</body>
</html>
"""



def check_auth(path, headers=None):
    """Compare one decoded query token or Authorization header exactly."""
    if not AUTH_TOKEN:
        return True
    params = parse_query(path)
    if params.get('token') == AUTH_TOKEN:
        return True
    headers = headers or {}
    authorization = headers.get('authorization', headers.get('Authorization', ''))
    return authorization == AUTH_TOKEN or authorization == 'Bearer ' + AUTH_TOKEN


def _respond(client, status, body, content_type='text/plain'):
    if wdt:
        wdt.feed()
    send_response(client, status, body, content_type)


def _json_response(client, status, value):
    _respond(client, status, json.dumps(value), 'application/json')


def handle_client(client):
    """Serve one bounded HTTP request; return True only after saved/reset config.

    The caller schedules reboot after the response has been sent and closed.
    It is intentionally outside this handler so tests can inspect persistence.
    """
    try:
        if wdt:
            wdt.feed()
        method, target, headers, body = read_request(client)
        if wdt:
            wdt.feed()
        route = target.split('?', 1)[0]
        methods = {
            '/': 'GET', '/config': 'GET', '/api/state': 'GET',
            '/api/log': 'GET', '/api/set': 'GET',
            '/api/config': 'POST', '/api/config/reset': 'POST'
        }
        if route not in methods:
            _json_response(client, 404, {'error': 'Not found'})
            return False
        if method != methods[route]:
            _json_response(client, 405, {'error': 'Method not allowed'})
            return False
        if route in ('/config', '/api/set', '/api/config', '/api/config/reset') and not check_auth(target, headers):
            _json_response(client, 403, {'error': 'Forbidden'})
            return False
        if route == '/':
            _respond(client, 200, html_page(), 'text/html')
        elif route == '/config':
            _respond(client, 200, config_page(), 'text/html')
        elif route == '/api/state':
            _json_response(client, 200, {
                'on': is_on, 'last_ms': max(0, time.ticks_diff(time.ticks_ms(), last_change)),
                'mqtt_status': 'connected' if mqtt and mqtt.connected else 'disconnected',
                'mqtt_enabled': MQTT_ENABLED
            })
        elif route == '/api/log':
            _json_response(client, 200, event_log)
        elif route == '/api/set':
            params = parse_query(target)
            if params.get('on') not in ('1', '0', 'true', 'false'):
                _json_response(client, 400, {'error': 'on must be 1, 0, true or false'})
                return False
            source = params.get('source', 'api')[:40]
            set_output(params['on'] in ('1', 'true'), source)
            _respond(client, 200, 'OK')
        elif route == '/api/config/reset':
            success, error = config.reset_config()
            _json_response(client, 200 if success else 500,
                           {'success': success, 'error': error})
            return success
        elif route == '/api/config':
            try:
                new_config = json.loads(body)
            except ValueError:
                _json_response(client, 400, {'success': False, 'error': 'Invalid JSON'})
                return False
            if not isinstance(new_config, dict):
                _json_response(client, 400, {'success': False, 'error': 'Configuration must be an object'})
                return False
            # Door settings must not erase desk values maintained through REPL/API.
            if 'desk' not in new_config:
                new_config['desk'] = cfg['desk'].copy()
            valid, error = config.validate_config(new_config)
            if not valid:
                _json_response(client, 400, {'success': False, 'error': error})
                return False
            success, error = config.save_config(new_config)
            _json_response(client, 200 if success else 500,
                           {'success': success, 'error': error})
            return success
        return False
    except HTTPError as error:
        try:
            _json_response(client, error.status, {'success': False, 'error': str(error)})
        except OSError:
            pass  # Peer may already have disconnected during request reception.
        return False
    except (OSError, ValueError, UnicodeError) as error:
        # A disconnected/malformed client must not terminate the firmware loop.
        try:
            _json_response(client, 400, {'success': False, 'error': 'Invalid request'})
        except OSError:
            pass
        return False
    finally:
        try:
            client.close()
        except OSError:
            pass


def service_background():
    """Run on every loop, including iterations serving busy browser traffic."""
    global wifi_connected, last_wifi_check, last_mqtt_check
    now = time.ticks_ms()
    if wdt:
        wdt.feed()
    if wlan and time.ticks_diff(now, last_wifi_check) >= WIFI_CHECK_INTERVAL:
        last_wifi_check = now
        was_connected = wifi_connected
        wifi_connected = wlan.isconnected()
        if was_connected and not wifi_connected:
            log_event('wifi', 'Disconnected')
            if mqtt:
                mqtt.connected = False
        if not wifi_connected and SSID:
            try:
                wlan.connect(SSID, PASSWORD)
            except OSError as error:
                log_event('wifi', 'Reconnection failed: {}'.format(error))
        if not was_connected and wifi_connected:
            log_event('wifi', 'Reconnected: {}'.format(wlan.ifconfig()[0]))
            if mqtt:
                mqtt.reset_retries()
    if wifi_connected and mqtt and time.ticks_diff(now, last_mqtt_check) >= 100:
        last_mqtt_check = now
        if mqtt.connected:
            mqtt.check_messages()
            if not mqtt.connected:
                log_event('mqtt', 'Disconnected from broker')
        else:
            already_gave_up = getattr(mqtt, '_gave_up', False)
            result = mqtt.reconnect_nonblocking()
            if wdt:
                wdt.feed()
            if result == 'connected':
                mqtt.publish_state(is_on)
                log_event('mqtt', 'Reconnected to broker')
            elif result == 'gave_up' and not already_gave_up:
                log_event('mqtt', 'Gave up reconnecting (max retries)')


def run():
    """ESP32 entry point: initialize hardware and run HTTP/background services."""
    initialize()
    server = socket.socket()
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(socket.getaddrinfo('0.0.0.0', 80)[0][-1])
    server.listen(2)
    server.settimeout(0.1)
    try:
        while True:
            service_background()
            try:
                client, address = server.accept()
            except OSError:
                continue
            if handle_client(client):
                # Response is complete before reboot, feeding throughout the delay.
                for unused in range(12):
                    if wdt:
                        wdt.feed()
                    time.sleep(0.25)
                import machine
                machine.reset()
    finally:
        server.close()


if __name__ == '__main__':
    run()
