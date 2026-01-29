# PushButtonDND - ESP32 (MicroPython)

**Profile**: Single-channel relay, **light normally OFF**, **active-HIGH** relay input.

## What's inside
- `desk.py` — Desk ESP32. Reads a toggle (GPIO 15, to GND) and sends HTTP to the door ESP32. On first boot, creates an AP (`DND-Desk-Setup`) for WiFi/config setup.
- `door.py` — Door ESP32. Hosts a tiny web UI and REST API and drives the relay on GPIO 2 (active HIGH).
- `config.py` — Configuration management module. Loads/saves `/config.json`, validates settings, handles factory reset and backup.
- `mqtt_client.py` — MQTT client wrapper. Handles Home Assistant auto-discovery, state publishing, command subscription, and reconnection.
- `wiring-diagram.svg` — A simple wiring diagram covering both boards and the AC relay wiring.
- `/door_unit_3D/` — Folder that stores the 3D Printing files for the door unit with bulb
- `/door_unit_3D/DND_E26_DrillTemplate.dxf` — DXF template for wall mounting holes (export from .scad)
- `/door_unit_3D/DND_E26_WallMount.scad` — OpenSCAD parametric model for E26 socket wall mount
- `/door_unit_3D/README.md` — specific info for printing included
- `/desk_unit_3D/` — Folder that stores the 3D Printing files for the desk unit with switch
- This README.

> Still building out the 3D models and final designs

## Flash MicroPython
1. Download latest ESP32 MicroPython firmware: https://micropython.org/download/ESP32/
2. Erase & flash (example on Windows COM3):
   ```
   esptool.py --port COM3 erase_flash
   esptool.py --chip esp32 --port COM3 --baud 460800 write_flash -z 0x1000 esp32-*.bin
   ```
3. In Thonny: Interpreter → **MicroPython (ESP32)** → select port → open REPL.

## Configure & Upload
1. Upload `door.py`, `config.py`, and `mqtt_client.py` to the **door ESP32** (rename `door.py` to `main.py`). Default credentials are configured in `config.py` via `get_default_config()` and can be changed via the web configuration UI at `/config`. Reboot → note its IP in the REPL logs.
2. Upload `desk.py` and `config.py` to the **desk ESP32** (rename `desk.py` to `main.py`).
3. On first boot, the desk unit creates a WiFi AP named `DND-Desk-Setup`. Connect to it and navigate to `http://192.168.4.1` to configure WiFi credentials, door unit URL, and auth token.
4. After saving, the desk unit reboots and connects to your WiFi network. Subsequent boots skip setup.

## Use
- Visit `http://<door-ip>/` for the Web UI.
  - Features a live status ring that updates every second
  - Dark/light theme toggle button
  - Large ON/OFF control buttons
- API:
  - `GET /api/set?on=1&token=SECRET123` — Turn ON
  - `GET /api/set?on=0&token=SECRET123` — Turn OFF
  - `GET /api/state` — Read current state (JSON: `{"on":true,"last_ms":12345,"mqtt_status":"connected","mqtt_enabled":true}`)
  - `GET /api/log` — Event log (JSON array of last 20 events with timestamps, types, and details)

> API's can be fun, ya'll

## Configuration

### Web-Based Configuration UI

Navigate to `http://<door-ip>/config?token=SECRET123` (replace with your AUTH_TOKEN) to access the configuration interface.

**Available Settings**:

1. **WiFi Tab**:
   - SSID: WiFi network name
   - Password: WiFi password
   - Changes require device reboot

2. **Security Tab**:
   - AUTH_TOKEN: Required for /api/set and /config endpoints
   - Leave blank to disable authentication

3. **MQTT Tab**:
   - Enable MQTT Integration checkbox
   - Broker Host: IP or hostname of MQTT broker (e.g., `homeassistant.local`)
   - Port: Default 1883 (unencrypted) or 8883 (TLS)
   - Username/Password: Optional credentials
   - Topic Prefix: Base topic name (default: `pushbuttondnd`)
   - Device Name: Friendly name shown in Home Assistant

4. **Teams Tab** (Coming Soon):
   - Placeholder for future Microsoft Teams integration
   - Currently disabled

**Saving Configuration**:
- Click "Save & Reboot" to save changes
- Device will reboot automatically in 3 seconds
- Configuration persists across reboots in `/config.json`

**Reset to Defaults**:
- Click "Reset to Defaults" to restore factory settings
- Deletes `/config.json` and reboots with hardcoded defaults

**Fallback Behavior**:
- If config file is corrupted or missing, device uses hardcoded defaults
- Hardcoded values in code serve as backup configuration

## MQTT Integration

### Prerequisites

- MQTT broker running on your network (e.g., Mosquitto)
- For Home Assistant: MQTT integration enabled

### Setup with Home Assistant

1. **Enable MQTT in Door ESP32**:
   - Navigate to `http://<door-ip>/config`
   - Go to MQTT tab
   - Check "Enable MQTT Integration"
   - Enter your broker details:
     - Broker: `homeassistant.local` (or broker IP)
     - Port: `1883`
     - Username/Password: (if required by broker)
   - Click "Save & Reboot"

2. **Auto-Discovery**:
   - Device automatically publishes Home Assistant discovery message
   - In Home Assistant, check Settings → Devices & Services → MQTT
   - "DND Light" should appear automatically
   - Entity ID: `light.dnd_light`

3. **Control from Home Assistant**:
   - Use the light entity in automations, scripts, dashboards
   - State syncs bidirectionally (web UI ↔ MQTT ↔ Home Assistant)

### MQTT Topics

The device uses the following topic structure (prefix: `pushbuttondnd`):

- **State Topic**: `pushbuttondnd/state`
  - Payload: `ON` or `OFF`
  - Published when light state changes
  - Retained: Yes

- **Command Topic**: `pushbuttondnd/set`
  - Payload: `ON` or `OFF`
  - Subscribe to control light remotely
  - QoS: 1

- **Availability Topic**: `pushbuttondnd/availability`
  - Payload: `online` or `offline`
  - Last Will and Testament (LWT)
  - Indicates device connectivity

- **Discovery Topic**: `homeassistant/light/pushbuttondnd/config`
  - Published once on connection
  - Contains Home Assistant auto-discovery configuration

### MQTT Status Indicator

The web UI shows MQTT connection status in the top-right corner:
- **Green "MQTT: Connected"**: Successfully connected to broker
- **Red "MQTT: Disconnected"**: Connection lost, attempting reconnection
- **Grey "MQTT: Disabled"**: MQTT not enabled in configuration

### Troubleshooting MQTT

**Connection Failed**:
- Verify broker is running: `mosquitto -v` or check Home Assistant logs
- Check broker hostname/IP is correct and reachable
- Ensure port 1883 is not blocked by firewall
- Test with MQTT client: `mosquitto_sub -h homeassistant.local -t '#'`

**Auto-Discovery Not Working**:
- Verify Home Assistant MQTT integration is enabled
- Check MQTT integration settings show the device
- Look for discovery message: `mosquitto_sub -h localhost -t 'homeassistant/#'`
- Try restarting Home Assistant MQTT integration

**Commands Not Working**:
- Check device is subscribed: Look for "[MQTT] Subscribed to pushbuttondnd/set" in REPL
- Test command: `mosquitto_pub -h localhost -t 'pushbuttondnd/set' -m 'ON'`
- Verify QoS settings match

**Reconnection Loop**:
- Device attempts reconnection every 60 seconds with exponential backoff
- After 10 failed attempts, stops trying (reboot device to retry)
- Check broker logs for connection errors

## Wiring (summary)
### Desk unit (transmitter)
- **ESP32 GPIO 15** → one side of toggle switch
- **ESP32 GND** → other side of switch
- **USB 5 V** powers ESP32

### Door unit (receiver)
- **ESP32 GPIO 2** → **Relay IN** (active HIGH)
- **ESP32 5 V (USB)** → **Relay VCC**
- **ESP32 GND** → **Relay GND**
- **Relay COM ↔ AC hot (from mains)**
- **Relay NO ↔ Load hot (to red bulb)**
- Neutral goes directly to the bulb. Earth ground per local code.

> The relay **only** switches the **hot leg**. With NO contact the light is **normally off**.

## Hardware Requirements
- **ESP32 Dev Boards** (2) — Any ESP32 with WiFi support
- **Relay Module** — Single-channel, active-HIGH, rated for your mains voltage (e.g., 120V/240V AC) and bulb wattage
  - Common options: SRD-05VDC-SL-C relay boards, SSR modules
  - Minimum 5A rating recommended for most bulbs
- **Toggle Switch** — SPST or SPDT for desk unit
- **Red Bulb** — E26 socket, standard wattage (check relay rating)
- **Power Supplies** — USB power for both ESP32 boards (5V, 500mA+)
- **Wire** — 18-22 AWG for low voltage, appropriate gauge for AC (per local code)

## Safety
- Use a relay module rated for your mains voltage and bulb current.
- Keep AC wiring isolated in a proper enclosure with strain relief.
- Do not share low-voltage wiring inside the AC compartment.
- If unsure about mains wiring, consult a qualified electrician.

> Don't be a dumbass!

## Troubleshooting

### ESP32 won't connect to WiFi
- Verify SSID and PASSWORD are correct (case-sensitive)
- Check WiFi is 2.4 GHz (ESP32 doesn't support 5 GHz)
- Monitor REPL in Thonny to see connection status
- Try rebooting the ESP32 or reflashing firmware

### Desk unit can't reach door unit
- Verify both ESP32s are on the same WiFi network
- Check `RECEIVER_URL` in `desk.py` matches door IP or mDNS hostname
- Test door API manually: `curl http://<door-ip>/api/state`
- Ensure firewall isn't blocking port 80 on door ESP32
- If using mDNS (`esp-doorlight.local`), ensure your router supports it

### Lost door IP address
- Connect to door ESP32 via Thonny and check REPL output
- Look in your router's DHCP client list
- Set a static IP in `door.py` using `wlan.ifconfig()` after connection
- Use mDNS: `http://esp-doorlight.local/` (if supported by network)

### Relay not switching
- Verify GPIO 2 is going HIGH (use multimeter or LED test)
- Check relay VCC and GND are connected to ESP32 5V/GND
- Confirm relay module is active-HIGH (some are active-LOW)
- Test relay manually by connecting IN pin directly to 5V

### Web UI shows wrong state
- The live polling updates every second; give it time to sync
- Hard refresh browser (Ctrl+F5) to clear cached page
- Check `/api/state` endpoint directly for actual state
- Verify desk toggle changes are reaching door unit (check REPL logs)

### Factory Reset / Restore Defaults

**Method 1: Via Web UI** (Recommended)
1. Navigate to `http://<door-ip>/config?token=SECRET123`
2. Click "Reset to Defaults" button at bottom of page
3. Confirm the reset
4. Device deletes `/config.json` and reboots with hardcoded defaults

**Method 2: Via Thonny REPL** (If web UI is inaccessible)
1. Connect to ESP32 via USB using Thonny IDE
2. Open REPL (bottom panel)
3. Run the following commands:
   ```python
   import config
   config.factory_reset()
   ```
4. Device will delete `/config.json` and reboot automatically

**Method 3: Manual File Deletion** (Advanced)
1. Connect via Thonny REPL
2. Delete config file manually:
   ```python
   import os
   os.remove('/config.json')
   ```
3. Reboot device:
   ```python
   import machine
   machine.reset()
   ```

**After Factory Reset**:
- Device boots with hardcoded defaults from code
- WiFi credentials: `SSID = "***REMOVED***"`, `PASSWORD = "***REMOVED***"`
- Auth token: `SECRET123`
- MQTT: Disabled
- All settings can be reconfigured via web UI

**Restore from Backup**:
If you accidentally reset and want to restore previous settings:
1. Via REPL: `import config; config.restore_backup()`
2. This restores from `/config.json.backup` (if it exists)
3. Device will use the backed-up configuration

## mDNS Setup (Optional)
To use `esp-doorlight.local` instead of IP addresses, add this to `door.py` after WiFi connection:

```python
import network
# ... after wlan.connect() and isconnected() ...
wlan.config(dhcp_hostname="esp-doorlight")
# Or use the network module's mDNS if available in your MicroPython build
```

Note: mDNS support varies by MicroPython version and network environment.

## Future: Microsoft Teams Integration

The configuration UI includes placeholders for Microsoft Teams integration (currently disabled).

### Planned Functionality

When implemented, this feature will:
1. Poll Microsoft Graph API for user presence status
2. Automatically turn ON DND light when status is "In a meeting", "Busy", or "Do not disturb"
3. Turn OFF light when status returns to "Available"
4. Bidirectional sync: Manual light control can update Teams status

### Implementation Requirements

**Azure AD App Registration**:
- Register application in Azure AD portal (https://portal.azure.com)
- Grant permissions: `Presence.Read`, `Presence.Read.All`, `User.Read`
- Generate client secret
- Note Client ID, Tenant ID, and Client Secret

**MicroPython Challenges**:
- OAuth 2.0 token acquisition and refresh workflow
- HTTPS requests to Graph API (requires TLS/SSL support)
- Token caching and expiration handling
- Limited RAM for TLS connections (~40-60 KB overhead)

**Recommended Approaches**:

1. **Proxy Server Approach** (Recommended):
   - Deploy intermediate proxy server (Node.js, Python Flask, etc.)
   - Proxy handles OAuth flow and Graph API calls
   - ESP32 polls simple HTTP endpoint on proxy
   - Reduces memory footprint and complexity
   - Example: Proxy returns `{"status": "busy"}` in JSON

2. **Power Automate / Logic Apps**:
   - Use Microsoft Power Automate flow
   - Trigger: Teams presence changes
   - Action: POST to ESP32 `/api/set` endpoint
   - No polling needed, event-driven
   - Requires Power Automate Premium license

3. **Webhook Approach**:
   - Microsoft Teams webhook sends presence updates
   - ESP32 receives webhooks via HTTP POST
   - Requires public IP or VPN for ESP32 accessibility

### Configuration

Teams settings are pre-configured in the web UI but currently disabled:
- Navigate to Settings → Teams tab
- Fields are greyed out with "Coming Soon" badge
- When feature is implemented, simply enable the checkbox

### Development Status

- **UI**: Complete (disabled)
- **Configuration storage**: Complete
- **Integration code**: Not implemented
- **Estimated complexity**: Medium-High

Contributions welcome! See implementation plan in project documentation.

## TODO

- Add physical button override indicator when the toggle switch on the desk side is used

## Completed Features

- Live JS polling status ring (12/3/25)
- Web-based configuration UI with persistent storage (12/9/25)
- MQTT integration with Home Assistant auto-discovery (12/9/25)
- Real-time MQTT connection status indicator (12/9/25)
- Teams integration UI placeholder (12/9/25)
- WiFi reconnection with 30-second boot timeout and automatic recovery (1/28/26)
- Hardware watchdog timer on both units (8-second timeout) (1/28/26)
- Non-blocking MQTT reconnection with exponential backoff (1/28/26)
- Desk unit AP mode setup (`DND-Desk-Setup`) for first-boot configuration (1/28/26)
- Desk unit config persistence via `config.py` (no more hardcoded credentials) (1/28/26)
- Event log: in-memory ring buffer of last 20 events via `/api/log` endpoint (1/28/26)
