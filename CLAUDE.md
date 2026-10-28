# Project development guidance

PushButtonDND is MicroPython firmware for a desk ESP32 transmitter and a door
ESP32 relay controller. It is not a hosted web application. See README.md for
user setup and docs/feature-audit.md for test scope and remaining hardware work.

## Runtime boundaries

- `door.py` becomes door `main.py`; its `run()` initializes hardware and serves
  HTTP on port 80. `initialize()` and `handle_client()` allow tests to execute
  the shipping firmware routes. Imports do not start hardware or a server.
- `desk.py` becomes desk `main.py`; `run()` selects setup AP or switch delivery.
  `handle_setup_client()` serves setup HTTP. `SwitchSynchronizer` handles debounce
  and retry. The desk needs current micropython-lib `requests` or compatible
  `urequests` with timeout support.
- Both boards require `config.py` and `http_utils.py`. The door also needs
  `mqtt_client.py`; MQTT uses current `umqtt.simple` with `connect(timeout=...)`.
- `config.py` stores `/config.json`, `/config.json.backup`, `/config.json.tmp`.
  Tests override path constants to temporary files. Do not commit credentials.
- `http_utils.py` parses bounded HTTP headers/body, exact URL parameters, UTF-8
  URL encoding, escaping, and complete responses. Keep it MicroPython compatible.
- `mqtt_client.py` caches offline state, emits discovery/LWT/availability,
  preserves bounded packet reads, sends keepalive PING, and schedules backoff.
  DNS remains platform dependent; avoid claiming fully asynchronous operations.
  Discovery uses the hardware client ID for nested prefixes and requests
  non-retained HA commands; retained state is a separate firmware behavior.

## Behavioral contracts

Door GPIO 2 starts LOW/OFF. Desk GPIO 15 uses pull-up; closed to GND requests ON.
Defaults have blank SSID/password/token. Blank SSID opens DND-Door-Setup or
DND-Desk-Setup. An existing but unreachable SSID is retried; serial reset is the
recovery path. Normal setup APs are plaintext and unauthenticated.

The public door page contains no embedded token. Mutating/config routes require
the configured token, using exact decoded query comparison or Authorization.
`/api/state` and `/api/log` stay public. Theme choice is page local. Settings
save/reset responds before reboot. Reset retains backup for explicit restore.
Events keep the most recent 20 entries and reset at boot.

The Teams tab is disabled; no Teams integration exists. MQTT TLS, HTTPS, mDNS
registration, OTA, and desk CAD are not implemented. The door CAD/DXF are
prototypes/placeholders rather than verified electrical/mechanical designs.

## Verification

```sh
python -m pip install -r requirements-dev.txt
python -m playwright install chromium firefox webkit
python -m pytest -v
```

The suite uses four distinct boundaries:

1. Firmware and helper tests fake network/GPIO/watchdog/clock conditions and
   inject filesystem/request failures.
2. Playwright executes actual firmware HTML and JavaScript against real TCP
   sockets using `tests/support.py`. Hardware and reboot are simulated.
3. Broker tests use real Mosquitto plus unmodified pinned upstream umqtt.simple
   with only a CPython socket-stream adapter. Upstream source/license provenance
   is in tests/vendor/README.md.
4. Desk-to-door integration uses unmodified pinned upstream requests, the actual
   desk sender/synchronizer, and the door handler over real TCP. Socket stream
   and text/bytes compatibility are adapted for CPython.

CI requires a broker (`REQUIRE_MQTT_BROKER=1`) and all three browser engines.
Locally use `MOSQUITTO_PATH` or a dedicated `MQTT_TEST_HOST`/`MQTT_TEST_PORT`.
Browser tests write traces/screenshots under test-results/. For a restricted
Windows temp directory, pass a writable `--basetemp` inside the workspace.

Do not report a physical board, Home Assistant UI, CAD rendering, flash durability,
or deployment as verified from these tests. Changes require appropriate tests
at the affected boundary; preserve firmware compatibility and avoid adding
CPython-only imports to shipped board files.
