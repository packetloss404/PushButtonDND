# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

PushButtonDND is an ESP32-based "Do Not Disturb" light system using MicroPython. It consists of two ESP32 units:
- **Desk unit** (transmitter): Monitors a toggle switch and sends HTTP requests
- **Door unit** (receiver): Hosts a web UI/REST API and controls an AC relay to drive a red bulb

The door unit provides both physical control (via desk toggle) and remote control (via web UI or API).

## Hardware Architecture

### Communication Flow
1. Desk ESP32 detects toggle switch state change (GPIO 15)
2. Sends HTTP GET to door ESP32's `/api/set` endpoint
3. Door ESP32 controls relay on GPIO 2 (active-HIGH)
4. Relay switches AC hot line to red bulb (normally-OFF configuration)

### Key Components
- **Relay Profile**: Single-channel, active-HIGH input, normally-OFF (NO contact)
- **Desk Switch**: Pull-up on GPIO 15, closes to GND (LOW = ON)
- **Door Relay**: GPIO 2 drives relay IN pin (HIGH = bulb ON)
- **Web UI**: Live polling status with dark/light theme toggle

## MicroPython Environment

### Flashing ESP32 Firmware
```bash
# Erase flash
esptool.py --port COM3 erase_flash

# Flash MicroPython (Windows example)
esptool.py --chip esp32 --port COM3 --baud 460800 write_flash -z 0x1000 esp32-*.bin
```

Use Thonny IDE for development:
- Interpreter: MicroPython (ESP32)
- Select appropriate COM port
- Use REPL for debugging and IP address discovery

### Deployment
1. **Door ESP32**: Upload `door.py` as `main.py`
   - Configure: `SSID`, `PASSWORD`, `AUTH_TOKEN` (optional security token)
   - Note IP address from REPL after reboot

2. **Desk ESP32**: Upload `desk.py` as `main.py`
   - Configure: `SSID`, `PASSWORD`, `RECEIVER_URL` (door IP), `TOKEN`
   - Match `TOKEN` to door's `AUTH_TOKEN`

## Code Structure

### door.py (Receiver)
- **Web server**: Listens on port 80, handles HTTP requests with 1-second timeout
- **Configuration**: Loads from `/config.json` via `config.py` module, fallback to hardcoded defaults
- **MQTT Client**: Connects to broker on startup if enabled, publishes state changes, subscribes to commands
- **Endpoints**:
  - `/` - HTML UI with live polling status ring and MQTT status indicator
  - `/config` - Web-based configuration UI with tabbed interface (WiFi, Security, MQTT, Teams)
  - `/api/set?on={0|1}&token={TOKEN}` - Control relay state
  - `/api/state` - JSON response with current state, uptime, and MQTT status
  - `/api/config` (POST) - Save new configuration and reboot
  - `/api/config/reset` (POST) - Reset to factory defaults and reboot
- **Authentication**: Optional token-based auth via `AUTH_TOKEN` (query param or header)
- **State management**: Global `is_on` flag, `last_change` timestamp
- **HTML includes**: Embedded CSS/JS with dark/light theme, live polling every 1 second
- **MQTT Integration**: Non-blocking message checking, automatic reconnection with exponential backoff

### desk.py (Transmitter)
- **Switch monitoring**: 50ms polling loop on GPIO 15
- **Debouncing**: 300ms delay after state change
- **HTTP client**: Uses `urequests` library to call door's `/api/set`
- **Logic inversion**: Switch LOW = send ON command (pull-up configuration)

### config.py (NEW - Configuration Management)
- **Functions**:
  - `load_config()` - Load from `/config.json`, fallback to defaults
  - `save_config()` - Atomic save with backup to `/config.json.backup`
  - `validate_config()` - Validate configuration structure and values
  - `get_default_config()` - Return hardcoded default configuration
  - `factory_reset()` - Delete config and reboot
  - `restore_backup()` - Restore from backup file
- **Storage**: JSON format on ESP32 flash filesystem
- **Schema**: Nested dict with wifi, security, mqtt, teams, features sections

### mqtt_client.py (NEW - MQTT Integration)
- **Class**: `MQTTClient` - Wrapper around `umqtt.simple`
- **Methods**:
  - `connect()` - Connect with Last Will and Testament (LWT)
  - `publish()` - Publish message to topic
  - `publish_state()` - Publish ON/OFF to state topic
  - `publish_discovery()` - Publish Home Assistant auto-discovery message
  - `check_messages()` - Non-blocking message check
  - `reconnect()` - Reconnect with exponential backoff
  - `disconnect()` - Clean disconnect
- **Features**:
  - Home Assistant MQTT auto-discovery
  - QoS 1 for reliable delivery
  - Retained messages for state and availability
  - Automatic reconnection (max 10 retries, 60s intervals)
  - Callback for incoming commands

## API Reference

### Door ESP32 REST API

```
# Control Endpoints
GET /api/set?on=1&token=SECRET123         # Turn ON
GET /api/set?on=0&token=SECRET123         # Turn OFF
GET /api/state                             # Get state: {"on":true,"last_ms":12345,"mqtt_status":"connected","mqtt_enabled":true}

# Configuration Endpoints
GET /config?token=SECRET123                # Serve configuration web UI
POST /api/config?token=SECRET123           # Save configuration (JSON body) and reboot
POST /api/config/reset?token=SECRET123     # Reset to factory defaults and reboot

# Web UI
GET /                                      # Main page with ON/OFF controls and MQTT status
```

### MQTT Topics

Topic structure (default prefix: `pushbuttondnd`):

```
# State Publishing
pushbuttondnd/state                        # Payload: "ON" or "OFF" (retained, QoS 1)
pushbuttondnd/availability                 # Payload: "online" or "offline" (LWT, retained)

# Command Subscription
pushbuttondnd/set                          # Payload: "ON" or "OFF" (QoS 1)

# Home Assistant Discovery
homeassistant/light/pushbuttondnd/config  # Auto-discovery configuration (retained, QoS 1)
```

### Configuration Schema

`/config.json` structure:

```json
{
  "version": 1,
  "wifi": {"ssid": "...", "password": "..."},
  "security": {"auth_token": "..."},
  "mqtt": {
    "enabled": false,
    "broker": "homeassistant.local",
    "port": 1883,
    "username": "",
    "password": "",
    "topic_prefix": "pushbuttondnd",
    "device_name": "DND Light",
    "qos": 1
  },
  "teams": {
    "enabled": false,
    "client_id": "",
    "tenant_id": "",
    "client_secret": "",
    "polling_interval": 300
  },
  "features": {
    "enable_mqtt": false,
    "enable_teams": false
  }
}
```

## 3D Printing Components

### Door Unit (wall mount with E26 socket)
- **File**: `door_unit_3D/DND_E26_WallMount.scad`
- **Recommended material**: PETG (heat resistance) or PLA
- **Print settings**: 0.2mm layers, 3-4 perimeters, 20-30% infill, no supports
- **Orientation**: Backplate flat on bed
- **Socket fit**: ID = 48.8mm default (48mm + 0.8mm clearance), adjust if needed
- **Export**: Open in OpenSCAD, F6 to render, export STL
- **Drill template**: Uncomment drill template section in .scad, export as DXF

### Desk Unit
- Files in `desk_unit_3D/` (3D models still in development)

## Safety Requirements

- Use relay rated for mains voltage and load current
- AC wiring must be in proper enclosure with strain relief
- Keep low-voltage (ESP32) wiring separate from AC compartment
- Relay switches hot leg only (neutral direct to bulb)
- Follow local electrical codes for earth ground

## Development Notes

### Testing Changes
- Monitor REPL output for debugging (IP addresses, connection status, errors, MQTT messages)
- Test web UI at `http://<door-ip>/` after uploading changes
- Verify configuration UI at `http://<door-ip>/config?token=SECRET123`
- Verify API endpoints with direct HTTP requests before testing desk unit
- Check switch state changes in desk unit REPL logs
- Test MQTT with: `mosquitto_pub -h localhost -t 'pushbuttondnd/set' -m 'ON'`

### Configuration Workflow
1. **Initial Setup**: Device boots with hardcoded defaults from `config.get_default_config()`
2. **First Configuration**: Navigate to `/config`, modify settings, click "Save & Reboot"
3. **Subsequent Boots**: Device loads `/config.json`, falls back to defaults if corrupted
4. **Testing**: Make changes via web UI, verify they persist across reboots
5. **Reset**: Use "Reset to Defaults" button or call `config.factory_reset()` via REPL

### MQTT Development
- **Testing locally**: Install Mosquitto on dev machine
- **Monitor all topics**: `mosquitto_sub -h localhost -t '#' -v`
- **Test commands**: `mosquitto_pub -h localhost -t 'pushbuttondnd/set' -m 'ON'`
- **Check discovery**: `mosquitto_sub -h localhost -t 'homeassistant/#'`
- **Debug connection**: Check REPL for `[MQTT] Connected` or error messages
- **Memory monitoring**: Call `import gc; gc.mem_free()` in REPL

### Common Modifications
- **Change relay logic**: Modify `set_output()` in door.py and inversion in desk.py
- **Adjust polling rate**: Modify `setInterval(pollState, 1000)` in HTML for UI refresh
- **Disable authentication**: Set `auth_token = ""` in web UI or config.json
- **Change pins**: Update `led_pin = Pin(2, Pin.OUT)` or `switch_pin = Pin(15, Pin.IN, Pin.PULL_UP)`
- **Add config field**: Update `get_default_config()` in config.py, add to web UI form, update validation
- **Change MQTT topics**: Modify `topic_prefix` in configuration
- **Add new endpoint**: Follow pattern in server loop, add auth check, handle request

### Troubleshooting Development Issues

**Config not loading**:
- Check REPL for "[CONFIG] No config file found" or JSON parse errors
- Verify `/config.json` exists: `import os; os.listdir('/')`
- Read raw file: `open('/config.json', 'r').read()`

**MQTT not connecting**:
- Check `umqtt.simple` library is available: `import umqtt.simple`
- Verify broker is reachable from ESP32 network
- Check REPL for "[MQTT] Connected" or error messages
- Test with minimal script outside main code

**Web UI changes not appearing**:
- Browser cache issue: Hard refresh (Ctrl+F5)
- Verify file was uploaded correctly
- Check for Python syntax errors in REPL

**Device won't reboot after config save**:
- Check for exception in REPL logs
- Verify `import machine; machine.reset()` works in REPL
- May need to manually reboot via power cycle

### File Structure

```
/                           # ESP32 flash root
├── main.py                 # door.py uploaded as main.py
├── config.py               # Configuration management
├── mqtt_client.py          # MQTT client wrapper
├── config.json             # Active configuration (created after first save)
├── config.json.backup      # Backup of previous config
└── config.json.tmp         # Temporary file during atomic write
```

### Known TODO Items
- Physical button override indicator when desk toggle is used

### Completed Features
- Live JS polling status ring (12/3/25)
- Web-based configuration UI with persistent storage (12/9/25)
- MQTT integration with Home Assistant auto-discovery (12/9/25)
- Real-time MQTT connection status indicator (12/9/25)
- Teams integration UI placeholder (12/9/25)
