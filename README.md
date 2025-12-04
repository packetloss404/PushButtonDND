# PushButtonDND - ESP32 (MicroPython)

**Profile**: Single-channel relay, **light normally OFF**, **active-HIGH** relay input.

## What’s inside
- `desk.py` — Desk ESP32. Reads a toggle (GPIO 15, to GND) and sends HTTP to the door ESP32.
- `door.py` — Door ESP32. Hosts a tiny web UI and REST API and drives the relay on GPIO 2 (active HIGH).
- `wiring-diagram.svg` — A simple wiring diagram covering both boards and the AC relay wiring.
- `/desk_unit_3D/` — Folder that stores the 3D Priting files for the door unit with bulb
- `/door_unit_3D/DND_E26_DrillTemplate.dxf` — ?
- `/door_unit_3D/DND_E26_WallMount.scad` — ?
- `/door_unit_3D/README.md` — specific info for printing included
- `/desk_unit_3D` — Folder that stores the 3D Priting files the desk unit with switch
- This README.

## Flash MicroPython
1. Download latest ESP32 MicroPython firmware: https://micropython.org/download/ESP32/
2. Erase & flash (example on Windows COM3):
   ```
   esptool.py --port COM3 erase_flash
   esptool.py --chip esp32 --port COM3 --baud 460800 write_flash -z 0x1000 esp32-*.bin
   ```
3. In Thonny: Interpreter → **MicroPython (ESP32)** → select port → open REPL.

## Configure & Upload
1. Open `door.py` and set: `SSID`, `PASSWORD`, `AUTH_TOKEN` (optional), and keep `RELAY_PIN=2`.
2. Upload `door.py` to the **door ESP32** as `main.py`. Reboot → note its IP in the REPL logs.
3. Open `desk.py` and set: `SSID`, `PASSWORD`, `RECEIVER_HOST` to the door IP, and `TOKEN` to match.
4. Upload `desk.py` to the **desk ESP32** as `main.py`. Reboot.

## Use
- Visit `http://<door-ip>/` for the Web UI.
- API:
  - `GET /api/set?on=1&token=SECRET123` — Turn ON
  - `GET /api/set?on=0&token=SECRET123` — Turn OFF
  - `GET /api/state` — Read current state

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

## Safety
- Use a relay module rated for your mains voltage and bulb current.
- Keep AC wiring isolated in a proper enclosure with strain relief.
- Do not share low-voltage wiring inside the AC compartment.
- If unsure about mains wiring, consult a qualified electrician.

> Don't be a dumbass!