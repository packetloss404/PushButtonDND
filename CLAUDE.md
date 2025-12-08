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
- **Web server**: Listens on port 80, handles HTTP requests
- **Endpoints**:
  - `/` - HTML UI with live polling status ring
  - `/api/set?on={0|1}&token={TOKEN}` - Control relay state
  - `/api/state` - JSON response with current state and uptime
- **Authentication**: Optional token-based auth via `AUTH_TOKEN`
- **State management**: Global `is_on` flag, `last_change` timestamp
- **HTML includes**: Embedded CSS/JS with dark/light theme, live polling every 1 second

### desk.py (Transmitter)
- **Switch monitoring**: 50ms polling loop on GPIO 15
- **Debouncing**: 300ms delay after state change
- **HTTP client**: Uses `urequests` library to call door's `/api/set`
- **Logic inversion**: Switch LOW = send ON command (pull-up configuration)

## API Reference

Door ESP32 REST API:

```
GET /api/set?on=1&token=SECRET123     # Turn ON
GET /api/set?on=0&token=SECRET123     # Turn OFF
GET /api/state                         # Get state: {"on":true,"last_ms":12345}
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
- Monitor REPL output for debugging (IP addresses, connection status, errors)
- Test web UI at `http://<door-ip>/` after uploading changes
- Verify API endpoints with direct HTTP requests before testing desk unit
- Check switch state changes in desk unit REPL logs

### Common Modifications
- **Change relay logic**: Modify `set_output()` in door.py and inversion in desk.py
- **Adjust polling rate**: Modify `setInterval(pollState, 1000)` in HTML for UI refresh
- **Disable authentication**: Set `AUTH_TOKEN = ""` in door.py
- **Change pins**: Update `led_pin = Pin(2, Pin.OUT)` or `switch_pin = Pin(15, Pin.IN, Pin.PULL_UP)`

### Known TODO Items
- Physical button override indicator when desk toggle is used
- Live JS polling status ring - COMPLETED 12/3/25
