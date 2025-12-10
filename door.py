import network
import socket
from machine import Pin
import time
import config
import json
import mqtt_client

# Load configuration
cfg, err = config.load_config()
if err:
    print(f"Config error: {err}, using defaults")

SSID = cfg['wifi']['ssid']
PASSWORD = cfg['wifi']['password']
AUTH_TOKEN = cfg['security']['auth_token']
MQTT_ENABLED = cfg['mqtt']['enabled']
MQTT_CONFIG = cfg['mqtt']

led_pin = Pin(2, Pin.OUT)
is_on = False
last_change = time.ticks_ms()

# Wi-Fi setup
wlan = network.WLAN(network.STA_IF)
wlan.active(True)
wlan.connect(SSID, PASSWORD)
print("Connecting to Wi-Fi...")
while not wlan.isconnected():
    time.sleep(0.5)
print("Connected:", wlan.ifconfig())

# Initialize MQTT if enabled
mqtt = None
if cfg['mqtt']['enabled']:
    print("[MQTT] Initializing...")
    mqtt = mqtt_client.MQTTClient(cfg['mqtt'])

    # Set callback for incoming MQTT commands
    def mqtt_command_handler(topic, msg):
        try:
            payload = msg.decode()
            print(f"[MQTT] Received command: {payload}")
            if payload == "ON":
                set_output(True)
            elif payload == "OFF":
                set_output(False)
        except Exception as e:
            print(f"[ERROR] MQTT command error: {e}")

    mqtt.message_callback = mqtt_command_handler

    # Connect to broker
    if not mqtt.connect():
        print("[MQTT] Connection failed, continuing without MQTT")
        mqtt = None

# Helper functions
def set_output(on):
    global is_on, last_change
    is_on = on
    led_pin.value(on)
    last_change = time.ticks_ms()
    print("Light", "ON" if on else "OFF")

    # Publish to MQTT if enabled and connected
    if mqtt and mqtt.connected:
        mqtt.publish_state(on)

def html_page():
    status = "ON" if is_on else "OFF"
    color = "#f44336" if is_on else "#4CAF50"
    token_query = f"&token={AUTH_TOKEN}" if AUTH_TOKEN else ""

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

<button class="action btn-on"
 onclick="location='/api/set?on=1{token_query}'">
  ON
</button>

<button class="action btn-off"
 onclick="location='/api/set?on=0{token_query}'">
  OFF
</button>

<a href="/config{token_query}" class="btn-settings">
  Settings
</a>

<script>
function toggleTheme() {{
  document.body.classList.toggle("light");
  let isLight = document.body.classList.contains("light");
  document.getElementById("themeToggle").textContent =
    isLight ? "Light" : "Dark";
}}

/* ========== LIVE POLLING ========== */
function pollState() {{
  fetch('/api/state')
    .then(r => r.json())
    .then(data => {{
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
    .catch(e => console.log("Polling error:", e));
}}

// Poll every second
setInterval(pollState, 1000);
</script>

</body>
</html>
"""

def config_page():
    """Generate configuration page with tabbed interface"""
    mqtt_enabled_checked = "checked" if cfg['mqtt']['enabled'] else ""
    teams_enabled_checked = "checked" if cfg['teams']['enabled'] else ""

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
    <button class="tab active" onclick="switchTab('wifi')">WiFi</button>
    <button class="tab" onclick="switchTab('security')">Security</button>
    <button class="tab" onclick="switchTab('mqtt')">MQTT</button>
    <button class="tab" onclick="switchTab('teams')">Teams</button>
  </div>

  <!-- WiFi Tab -->
  <div id="wifi" class="tab-content active">
    <div class="form-group">
      <label for="ssid">WiFi Network (SSID)</label>
      <input type="text" id="ssid" value="{cfg['wifi']['ssid']}" placeholder="Your WiFi network name">
      <small>Network name (case-sensitive)</small>
    </div>

    <div class="form-group">
      <label for="wifi_password">WiFi Password</label>
      <div class="password-field">
        <input type="password" id="wifi_password" value="{cfg['wifi']['password']}" placeholder="WiFi password">
        <button class="toggle-password" onclick="togglePassword('wifi_password')">Show</button>
      </div>
      <small>Required for WPA/WPA2 networks</small>
    </div>
  </div>

  <!-- Security Tab -->
  <div id="security" class="tab-content">
    <div class="form-group">
      <label for="auth_token">API Authentication Token</label>
      <input type="text" id="auth_token" value="{cfg['security']['auth_token']}" placeholder="Leave blank to disable">
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
      <input type="text" id="mqtt_broker" value="{cfg['mqtt']['broker']}" placeholder="homeassistant.local or IP">
      <small>Hostname or IP address of your MQTT broker</small>
    </div>

    <div class="form-group">
      <label for="mqtt_port">MQTT Port</label>
      <input type="number" id="mqtt_port" value="{cfg['mqtt']['port']}" placeholder="1883">
      <small>Default: 1883 (unencrypted), 8883 (TLS)</small>
    </div>

    <div class="form-group">
      <label for="mqtt_username">MQTT Username</label>
      <input type="text" id="mqtt_username" value="{cfg['mqtt']['username']}" placeholder="Leave blank if not required">
      <small>Optional: Leave blank for anonymous access</small>
    </div>

    <div class="form-group">
      <label for="mqtt_password">MQTT Password</label>
      <div class="password-field">
        <input type="password" id="mqtt_password" value="{cfg['mqtt']['password']}" placeholder="Leave blank if not required">
        <button class="toggle-password" onclick="togglePassword('mqtt_password')">Show</button>
      </div>
    </div>

    <div class="form-group">
      <label for="mqtt_topic_prefix">Topic Prefix</label>
      <input type="text" id="mqtt_topic_prefix" value="{cfg['mqtt']['topic_prefix']}" placeholder="pushbuttondnd">
      <small>Prefix for MQTT topics (e.g., pushbuttondnd/state)</small>
    </div>

    <div class="form-group">
      <label for="mqtt_device_name">Device Name</label>
      <input type="text" id="mqtt_device_name" value="{cfg['mqtt']['device_name']}" placeholder="DND Light">
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
        <input type="text" id="teams_client_id" value="{cfg['teams']['client_id']}" disabled placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx">
      </div>

      <div class="form-group">
        <label for="teams_tenant_id">Azure AD Tenant ID</label>
        <input type="text" id="teams_tenant_id" value="{cfg['teams']['tenant_id']}" disabled placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx">
      </div>

      <div class="form-group">
        <label for="teams_client_secret">Client Secret</label>
        <div class="password-field">
          <input type="password" id="teams_client_secret" value="{cfg['teams']['client_secret']}" disabled placeholder="Azure AD application secret">
          <button class="toggle-password" disabled>Show</button>
        </div>
      </div>

      <div class="form-group">
        <label for="teams_polling_interval">Polling Interval (seconds)</label>
        <input type="number" id="teams_polling_interval" value="{cfg['teams']['polling_interval']}" disabled placeholder="300">
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
function switchTab(tabName) {{
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
  event.target.classList.add('active');
}}

function togglePassword(fieldId) {{
  const field = document.getElementById(fieldId);
  const btn = event.target;

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
  const tokenParam = '{AUTH_TOKEN}' ? '?token={AUTH_TOKEN}' : '';

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

  const tokenParam = '{AUTH_TOKEN}' ? '?token={AUTH_TOKEN}' : '';

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

def check_auth(request_str):
    """Check if request contains valid auth token"""
    if not AUTH_TOKEN:
        return True  # Auth disabled

    # Check query parameter: ?token=SECRET123
    if f"token={AUTH_TOKEN}" in request_str:
        return True

    # Check Authorization header (optional)
    lines = request_str.split('\r\n')
    for line in lines:
        if line.startswith('Authorization:'):
            token = line.split(':', 1)[1].strip()
            if token == f"Bearer {AUTH_TOKEN}" or token == AUTH_TOKEN:
                return True

    return False

def extract_post_body(request_str):
    """Extract POST body from HTTP request"""
    # Find the empty line separating headers from body
    parts = request_str.split('\r\n\r\n', 1)
    if len(parts) > 1:
        return parts[1]
    return ""

def forbidden(s):
    s.send("HTTP/1.1 403 Forbidden\r\n\r\nForbidden")

# Start web server
addr = socket.getaddrinfo("0.0.0.0", 80)[0][-1]
s = socket.socket()
s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)  # Allow address reuse
s.bind(addr)
s.listen(1)
s.settimeout(1.0)  # 1 second timeout for non-blocking operation
print("Web server running on:", wlan.ifconfig()[0])

# MQTT tracking variables
last_mqtt_check = time.ticks_ms()
last_mqtt_reconnect = time.ticks_ms()

while True:
    try:
        cl, addr = s.accept()
        req = cl.recv(1024).decode()
        if not req:
            cl.close()
            continue
        path = req.split(" ")[1]
    except OSError:
        # Socket timeout - check MQTT messages
        if mqtt and time.ticks_diff(time.ticks_ms(), last_mqtt_check) > 1000:
            last_mqtt_check = time.ticks_ms()

            if mqtt.connected:
                mqtt.check_messages()
            else:
                # Attempt reconnection every 60 seconds
                if time.ticks_diff(time.ticks_ms(), last_mqtt_reconnect) > 60000:
                    last_mqtt_reconnect = time.ticks_ms()
                    print("[MQTT] Attempting reconnection...")
                    mqtt.reconnect()

        continue

    # Process HTTP request (path is now available)

    if path.startswith("/api/set"):
        args = {}
        for p in path.split("?")[1].split("&"):
            if "=" in p:
                k, v = p.split("=")
                args[k] = v
        if AUTH_TOKEN and args.get("token") != AUTH_TOKEN:
            forbidden(cl)
        else:
            set_output(args.get("on") in ["1", "true"])
            cl.send("HTTP/1.1 200 OK\r\n\r\nOK")
        cl.close()
        continue

    if path.startswith("/api/state"):
        mqtt_status = "connected" if (mqtt and mqtt.connected) else "disconnected"
        mqtt_enabled = "true" if MQTT_ENABLED else "false"
        cl.send("HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n\r\n" +
                f'{{"on":{str(is_on).lower()},"last_ms":{time.ticks_ms()-last_change},"mqtt_status":"{mqtt_status}","mqtt_enabled":{mqtt_enabled}}}')
        cl.close()
        continue

    # GET /config - Serve configuration page
    if path.startswith("/config"):
        if not check_auth(req):
            forbidden(cl)
            cl.close()
            continue
        cl.send("HTTP/1.1 200 OK\r\nContent-Type: text/html\r\n\r\n" + config_page())
        cl.close()
        continue

    # POST /api/config - Save configuration
    if req.startswith("POST /api/config/reset"):
        if not check_auth(req):
            forbidden(cl)
            cl.close()
            continue

        # Reset to defaults
        try:
            import machine
            # Delete config file
            try:
                import os
                os.remove('/config.json')
                print("[CONFIG] Reset to defaults, config.json deleted")
            except:
                print("[CONFIG] No config file to delete")

            # Send success response
            cl.send("HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n\r\n" +
                    json.dumps({"success": True, "message": "Reset to defaults"}))
            cl.close()

            # Reboot after 3 seconds
            time.sleep(3)
            machine.reset()
        except Exception as e:
            print(f"[ERROR] Reset failed: {e}")
            cl.send("HTTP/1.1 500 Internal Server Error\r\nContent-Type: application/json\r\n\r\n" +
                    json.dumps({"success": False, "error": str(e)}))
            cl.close()
        continue

    if req.startswith("POST /api/config"):
        if not check_auth(req):
            forbidden(cl)
            cl.close()
            continue

        # Save configuration
        try:
            body = extract_post_body(req)
            if not body:
                cl.send("HTTP/1.1 400 Bad Request\r\nContent-Type: application/json\r\n\r\n" +
                        json.dumps({"success": False, "error": "No request body"}))
                cl.close()
                continue

            new_config = json.loads(body)

            # Validate configuration
            valid, error = config.validate_config(new_config)
            if not valid:
                cl.send("HTTP/1.1 400 Bad Request\r\nContent-Type: application/json\r\n\r\n" +
                        json.dumps({"success": False, "error": error}))
                cl.close()
                continue

            # Save configuration
            success, error = config.save_config(new_config)
            if not success:
                cl.send("HTTP/1.1 500 Internal Server Error\r\nContent-Type: application/json\r\n\r\n" +
                        json.dumps({"success": False, "error": error}))
                cl.close()
                continue

            # Success response
            cl.send("HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n\r\n" +
                    json.dumps({"success": True, "message": "Configuration saved"}))
            cl.close()

            # Reboot device after 3 seconds
            print("[CONFIG] Configuration saved, rebooting in 3 seconds...")
            time.sleep(3)
            import machine
            machine.reset()

        except ValueError as e:
            print(f"[ERROR] JSON parse error: {e}")
            cl.send("HTTP/1.1 400 Bad Request\r\nContent-Type: application/json\r\n\r\n" +
                    json.dumps({"success": False, "error": f"Invalid JSON: {e}"}))
            cl.close()
        except Exception as e:
            print(f"[ERROR] Config save error: {e}")
            cl.send("HTTP/1.1 500 Internal Server Error\r\nContent-Type: application/json\r\n\r\n" +
                    json.dumps({"success": False, "error": str(e)}))
            cl.close()
        continue

    cl.send("HTTP/1.1 200 OK\r\nContent-Type: text/html\r\n\r\n" + html_page())
    cl.close()
