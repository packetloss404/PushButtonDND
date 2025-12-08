# PushButtonDND - ESP32 (MicroPython)

**Profile**: Single-channel relay, **light normally OFF**, **active-HIGH** relay input.

## What's inside
- `desk.py` — Desk ESP32. Reads a toggle (GPIO 15, to GND) and sends HTTP to the door ESP32.
- `door.py` — Door ESP32. Hosts a tiny web UI and REST API and drives the relay on GPIO 2 (active HIGH).
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
1. Open `door.py` and set: `SSID`, `PASSWORD`, `AUTH_TOKEN` (optional). GPIO 2 is used for the relay.
2. Upload `door.py` to the **door ESP32** as `main.py`. Reboot → note its IP in the REPL logs.
3. Open `desk.py` and set: `SSID`, `PASSWORD`, `RECEIVER_URL` to the door IP (or use mDNS `http://esp-doorlight.local/api/set`), and `TOKEN` to match `AUTH_TOKEN`.
4. Upload `desk.py` to the **desk ESP32** as `main.py`. Reboot.

## Use
- Visit `http://<door-ip>/` for the Web UI.
  - Features a live status ring that updates every second
  - Dark/light theme toggle button
  - Large ON/OFF control buttons
- API:
  - `GET /api/set?on=1&token=SECRET123` — Turn ON
  - `GET /api/set?on=0&token=SECRET123` — Turn OFF
  - `GET /api/state` — Read current state (JSON: `{"on":true,"last_ms":12345}`)

> API's can be fun, ya'll

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

## mDNS Setup (Optional)
To use `esp-doorlight.local` instead of IP addresses, add this to `door.py` after WiFi connection:

```python
import network
# ... after wlan.connect() and isconnected() ...
wlan.config(dhcp_hostname="esp-doorlight")
# Or use the network module's mDNS if available in your MicroPython build
```

Note: mDNS support varies by MicroPython version and network environment.

## TODO

- Add physical button override indicator when the toggle switch on the desk side is used

## Completed Features

- Live JS polling status ring (12/3/25)
