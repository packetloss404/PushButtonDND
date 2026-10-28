# PushButtonDND

Two ESP32 boards run MicroPython: a desk switch sends HTTP commands to a door
unit, whose web interface, API, and optional MQTT integration control a relay.
The relay input is active HIGH on GPIO 2; the light starts OFF on every boot.

## Implemented features and verification

- Door web controls, one-second status polling, theme toggle, and MQTT indicator.
- Token-protected control and configuration; public state and event-log reads.
- Door and desk first-boot WiFi setup pages; persistent JSON settings, backup,
  explicit restore, and factory reset.
- Desk switch debounce, initial state delivery, failed-delivery retry, and WiFi
  recovery. Door background WiFi/MQTT work continues during HTTP traffic.
- MQTT retained state, command subscription, Home Assistant discovery payload,
  availability/LWT, keepalive ping, and scheduled reconnect attempts.

Automated tests exercise the actual firmware HTTP handlers using real TCP
sockets and Playwright browsers. GPIO, WiFi, watchdog, and reboot are simulated
at the hardware boundary. Separate tests use a real Mosquitto broker and the
unmodified upstream MicroPython MQTT protocol client. This does **not** establish
physical ESP32, relay, electrical, RF, or Home Assistant UI compatibility.
See [feature coverage and remaining checks](docs/feature-audit.md).

Teams is a disabled UI placeholder: there is no presence integration or OAuth
implementation. MQTT TLS, HTTPS serving, automatic mDNS registration, and the
desk enclosure model are not implemented. The door CAD is a prototype, and its
DXF file is a placeholder. `website_preview.png` is a historical image.

## Firmware files and first setup

Choose the MicroPython image and flashing procedure for your exact board from
[the official ESP32 downloads](https://micropython.org/download/ESP32/). Board
variants can use different images and flash offsets. This audit did not flash a
physical board.

Upload these files to each board's filesystem root using Thonny or mpremote:

| Board | Files |
| --- | --- |
| Door | `door.py` renamed to `main.py`, `config.py`, `http_utils.py`, `mqtt_client.py` |
| Desk | `desk.py` renamed to `main.py`, `config.py`, `http_utils.py` |

The desk also needs current `requests` (or a compatible legacy `urequests`)
with the `timeout` argument. The door needs current `umqtt.simple` only when
MQTT is enabled; it must support `connect(timeout=...)`. Old packages fail safely
rather than silently performing an unbounded request. Install dependencies from
your computer, substituting the correct serial port:

```sh
mpremote connect COM3 mip install umqtt.simple
mpremote connect COM4 mip install requests
```

On a network-connected board the equivalent is `import mip` followed by
`mip.install("umqtt.simple")` or `mip.install("requests")`. See the official
[MicroPython package installation guide](https://docs.micropython.org/en/latest/reference/packages.html).
The integration tests pin the upstream MQTT source and license in
[tests/vendor](tests/vendor/README.md); test that version when updating libraries.

Defaults contain **blank WiFi credentials and a blank authentication token**.
There is no shipped shared secret.

1. Boot the door. With no configured SSID it opens the unencrypted
   `DND-Door-Setup` AP. Connect and open `http://192.168.4.1/config` (confirm its
   address in serial output if different). Enter WiFi and a token, then save.
2. After reboot, note the door's station IP in serial output or the router's
   DHCP list. Open `http://<door-ip>/`.
3. Boot the desk. It opens `DND-Desk-Setup` when settings are missing, invalid,
   or have a blank SSID. Open `http://192.168.4.1`, enter WiFi, the door URL
   `http://<door-ip>/api/set`, and the same token. Save and reconnect to WiFi.
4. Close the desk toggle to GND to request ON; open it to request OFF.
   The desk sends its physical state at startup, so it can override a web state.

Setup APs and HTTP send credentials in plaintext. Provision on a trusted local
network and set a token before normal use. The door public page does not embed
the token: enter it in the API token field to use ON/OFF or Settings. A blank
token intentionally disables authentication. State and event logs stay public.

A configured SSID with incorrect credentials is retried; it does not
necessarily enter setup mode. To recover inaccessible settings, delete
`/config.json` through the serial REPL and reboot. Hostname resolution for the
default `esp-doorlight.local` URL depends on your network; the firmware does not
register that mDNS name. Use the observed IP address if needed.

## Web configuration and REST API

Open Settings from the control page after entering your token, or use
`/config?token=<URL-encoded-token>`. WiFi, Security, and MQTT tabs are editable.
Teams fields are disabled. Password visibility buttons and the light/dark theme
are available. Save validates settings, writes `/config.json`, returns a success
response, then reboots after about three seconds.

| Method and path | Behavior | Authentication |
| --- | --- | --- |
| `GET /` | Control page | Public |
| `GET /api/state` | State and MQTT connection flags | Public |
| `GET /api/log` | Last 20 state/WiFi/MQTT events | Public |
| `GET /api/set?on=1` | Turn ON (`0` turns OFF; `true`/`false` also accepted) | Token if configured |
| `GET /config` | Settings page | Token if configured |
| `POST /api/config` | JSON configuration save and reboot | Token if configured |
| `POST /api/config/reset` | Delete active configuration and reboot | Token if configured |

Pass the exact token as a URL-encoded `token` query parameter or an
`Authorization: Bearer <token>` header. A `source` query value on `/api/set`
appears in the event log; it is caller supplied, not proof of origin. Unknown
routes return 404, unsupported methods 405, bad values/JSON 400, invalid tokens
403, and oversized requests 413.

```sh
curl -H "Authorization: Bearer YOUR_TOKEN" "http://DOOR_IP/api/set?on=1&source=api"
curl "http://DOOR_IP/api/state"
curl "http://DOOR_IP/api/log"
```

Example state response:

```json
{"on":true,"last_ms":12345,"mqtt_status":"connected","mqtt_enabled":true}
```

`last_ms` is elapsed time since the last command, using a wrap-aware tick
calculation. Event timestamps are monotonic device ticks, not wall-clock dates.
State and logs are in memory and reset at boot.

`config.py` merges missing fields with defaults and rejects malformed settings.
Successful saves keep the prior configuration in `/config.json.backup` and
replace the active file through a temporary file. Missing/corrupt configuration
falls back to blank defaults; a backup is not automatically restored.

Reset preserves the backup for deliberate recovery. Through the serial REPL:

```python
import config
config.factory_reset()  # Delete active settings and reboot into initial setup.
```

To restore an existing valid backup:

```python
import config
success, error = config.restore_backup()
print(success, error)
if success:
    import machine
    machine.reset()
```

Changing the token takes effect after reboot. Re-enter the new token on the
control page. A reset removes WiFi and token settings; reconnect to the setup AP.

## MQTT and Home Assistant

Enable MQTT in Settings and enter a reachable broker, port, optional username
and password, topic prefix, and device name. MQTT is plaintext TCP only. Port
1883 is the usual plaintext default; selecting 8883 does **not** enable TLS.
QoS 0 or 1 is supported by the API; the web form uses QoS 1. Give each door a
separate topic prefix to avoid overlapping command/state/discovery topics.

With the default prefix `pushbuttondnd`:

| Topic | Direction and payload |
| --- | --- |
| `pushbuttondnd/set` | Subscribe: `ON` or `OFF` |
| `pushbuttondnd/state` | Retained publish: `ON` or `OFF` |
| `pushbuttondnd/availability` | Retained `online`; LWT/clean disconnect `offline` |
| `homeassistant/light/pushbuttondnd/config` | Retained Home Assistant discovery JSON |

For a prefix containing characters outside ASCII letters, digits, `_`, and `-`
(including `/`, spaces, periods, or Unicode), discovery instead uses
`homeassistant/light/<hardware-client-id>/config` so its object ID remains one
path segment; state, command, and availability topics keep the full prefix.

Connection publishes discovery and current state before reporting online.
Changes made while disconnected are cached and published after reconnection.
Home Assistant's MQTT integration must be enabled; its entity ID is assigned by
Home Assistant and is not guaranteed to be `light.dnd_light`. Discovery payload
and broker behavior are tested, including broker commands reaching the actual
door relay logic and HTTP control publishing state back to the broker. The
Home Assistant application was not run.

Discovery asks Home Assistant to send **non-retained commands**; firmware state
is still retained. If an older configuration left an `ON` command retained on
the broker, clear that old command deliberately before relying on OFF at boot:

```sh
mosquitto_pub -h BROKER_IP -t 'pushbuttondnd/set' -r -n
```

Substitute your actual command topic and broker credentials. This only clears
the retained command; the firmware does not silently delete broker messages.

The UI displays Connected, Disconnected, or Disabled from the door's live state.
Backoff waits do not sleep: reconnect delays are 5, 10, 30, then 60 seconds, with
at most ten attempts before giving up. WiFi recovery resets retries; rebooting
also resets them. TCP/MQTT operations remain synchronous, with one-second socket
timeouts and operation deadlines. DNS resolution can still block according to
the MicroPython platform. This is not a fully asynchronous MQTT client.
Incoming commands wait until the active MQTT exchange finishes, preventing
overlapping QoS 1 acknowledgements. A burst keeps the latest 16 commands and
applies one per loop operation so state replies do not monopolize the watchdog.

For local diagnosis:

```sh
mosquitto_sub -h BROKER_IP -t 'pushbuttondnd/#' -v
mosquitto_pub -h BROKER_IP -t 'pushbuttondnd/set' -m 'ON' -q 1
```

## Tests and CI

Use Python 3.11 or newer on your development computer (local verification used
Python 3.13):

```sh
python -m pip install -r requirements-dev.txt
python -m playwright install chromium firefox webkit
python -m pytest -v
```

On Linux, install system dependencies too:

```sh
python -m playwright install --with-deps chromium firefox webkit
```

Broker tests launch a locally installed `mosquitto` executable;
set `MOSQUITTO_PATH` if it is outside PATH. Alternatively, point them at a
**dedicated disposable broker** with `MQTT_TEST_HOST` and `MQTT_TEST_PORT` (tests
use retained topics and intentionally drop connections). Missing Mosquitto skips
broker tests locally; `REQUIRE_MQTT_BROKER=1` makes that a failure, as CI requires.
Set `BROWSER_ENGINES=chromium` for a shorter local browser run; the default runs
all three engines. For firmware/helper and desk TCP tests only:

```sh
python -m pytest -m "not browser and not broker" -v
```

GitHub Actions installs the browsers and Mosquitto, runs the full suite, and
retains browser screenshots/traces as test artifacts. Browser tests start real
socket servers using the shipping handlers; no frontend routes are mocked.
They simulate configuration-triggered reboot by reloading saved settings.
Desk-to-door tests also use the actual sender and unmodified upstream requests
over real TCP, including rejected-token retry and connection-failure recovery.
Physical watchdog reset, WiFi radios, relay contacts, and flash power loss still
need board testing. This project has no hosted website deployment or OTA updater;
firmware is uploaded to each ESP32 explicitly. No deployment was performed in
this audit.

## Wiring and mechanical prototype

| Connection | Purpose |
| --- | --- |
| Desk GPIO 15 to toggle, other side to GND | Pull-up input; LOW requests ON |
| Door GPIO 2 to compatible relay IN | Active HIGH output |
| Door/relay common GND and suitable supplies | Verify the relay's voltage/current and logic compatibility |
| Relay COM to mains hot; NO to load hot | Normally OFF load; neutral bypasses relay |

See [wiring-diagram.svg](wiring-diagram.svg) and the
[door CAD notes](door_unit_3D/README.md). The OpenSCAD source is a prototype; the
checked-in DXF is not a usable drill template. Desk CAD is still planned.

Use a relay and enclosure suitable for the actual mains/load ratings. Isolate
mains from low-voltage wiring, provide strain relief, and follow applicable earth
and electrical requirements with qualified help. Software tests do not verify
mains safety, thermal performance, print material, socket fit, or relay behavior.
