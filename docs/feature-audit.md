# Feature audit — 2026-10-28

This audit distinguishes software behavior from physical hardware evidence.
Tests run the shipping firmware functions. Browser coverage uses real Chromium,
Firefox, and WebKit with a TCP server around those handlers; the hardware boundary
and reboot are simulated. MQTT integration uses a real Mosquitto broker and
pinned upstream umqtt.simple, with a CPython socket/clock adapter.
Desk-to-door integration uses pinned upstream requests and actual firmware
sender/handlers over TCP, adapting only socket stream and text/bytes compatibility.

| Advertised behavior | Automated evidence | Remaining limitation |
| --- | --- | --- |
| ON/OFF web buttons and API | Browser actions, relay-pin stub assertions, exact request/auth cases | No physical relay/bulb |
| Live status ring and theme | Browser polling observes external API change; theme toggles | No hardware state feedback sensor |
| MQTT status indicator | Browser Disabled/Connected/Disconnected displays | Status source simulated in browser test |
| WiFi/Security/MQTT settings tabs and password show/hide | Browser navigation, field edits, validation, complete save | AP radio/network transfer not tested |
| Token protection | Exact query/header comparison, wrong suffix/key rejection, public-page secret absence | HTTP is plaintext; reads are public |
| Long/Unicode/special-character settings | Real fragmented HTTP/parser tests and browser save/reload | Board RAM/flash capacity not measured |
| Persistent settings/reboot/reset | Real temporary files, save/reload, backup/failure paths, simulated browser reboot | No actual reboot/flash power-loss test |
| Corrupt/missing settings and initial setup | Firmware boot boundary tests; desk setup in browser | Radio AP/DHCP/captive behavior not verified |
| Desk switch delivery | Debounce/retry/recovery tests and TCP desk-to-door command tests | Physical switch timing/electrical bounce simulated |
| WiFi recovery/watchdog | Boot/recovery/feed logic with fake hardware and tick clock | RF reconnection and watchdog expiry need boards |
| Event log | API/browser state-source observation, ring size checks | Tick timestamps; volatile at boot |
| MQTT discovery/commands/state | Real broker retained discovery; ON reaches actual door callback, relay-pin stub and event log; HTTP OFF publishes retained state to broker and a second subscriber | Home Assistant application not run |
| MQTT LWT/availability | Real broker abrupt TCP closure and clean disconnect | Device power removal not tested |
| MQTT recovery/keepalive | Transport shutdown/reconnect/state replay/PINGRESP with real broker; clock/backoff/error cases | DNS remains synchronous/platform dependent |
| Teams | Browser verifies disabled Coming Soon UI | No integration implementation |
| Door enclosure and drill template | Source inspection only | No CAD render, print/fit, thermal/electrical test; DXF placeholder |
| Desk enclosure | Documentation audit | Model not provided |

## Defects addressed

- Door blank credentials previously had no reachable first-boot setup path.
- Single `recv(1024)` request reads truncated settings and could crash handlers;
  requests now have bounded incremental parsing and correct response framing.
- Loose auth and route matches accepted misleading request strings; request
  methods, paths, query values, and tokens are now checked exactly.
- Embedded token disclosure and unescaped config values broke/compromised the
  public UI; user-entered control tokens and escaped output replace them.
- HTTP load could starve WiFi/MQTT background work; each loop now services it.
- Config validation, atomic replacement, reset-without-file, and backup restore
  error paths now have regression coverage.
- Desk state delivery now retries after failure, sends the initial switch state,
  URL-encodes values, and uses a bounded HTTP request.
- MQTT topic/credential strings now match the upstream bytes API. Failed setup
  closes sockets, background reconnect retains the client, offline state is
  cached and republished, and keepalive PING/deadline/retry behavior is covered.
- MQTT prefixes with non-object-ID characters use a valid discovery object ID.
  Discovery requests non-retained Home Assistant commands while state remains
  retained; README documents removal of a legacy retained command if present.
- Incoming MQTT commands are deferred until the outer transport exchange
  completes, fixing a reproduced reentrant QoS 1 PUBACK race. Exact upstream
  packet-stream tests cover successful ACK ordering and failure-state caching.
  A bounded queue keeps the latest 16 commands and dispatches one per operation.
- Stale shared-default-token, TLS-port, guaranteed entity-ID, mDNS, DXF, and
  completed-hardware claims were corrected.

## Reproduce

See README.md for dependency installation and test commands. Full CI installs
Mosquitto and all three Playwright browsers and requires broker tests to run.
For an existing dedicated broker set MQTT_TEST_HOST and MQTT_TEST_PORT; otherwise
tests launch a locally installed Mosquitto. Local missing-broker skips are not
proof of MQTT correctness. Test traces/screenshots are written to test-results/.

## Physical acceptance still required

Use a low-voltage test load first. Verify safe relay LOW on power-up/reset,
physical switch behavior, long WiFi/broker outages, recovery, memory/soak under
HTTP+MQTT traffic, real watchdog expiry, and flash save/restore after power loss.
Then validate the selected mains relay, wiring/enclosure, socket, and print
material with qualified electrical/mechanical review. No deployment was
performed as part of this audit; there is no hosted service or OTA deployment.
