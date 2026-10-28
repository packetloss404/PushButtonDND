# MicroPython transport test dependencies

`umqtt_simple.py` is an unmodified copy of MicroPython's `umqtt.simple` from
`micropython/micropython-lib`, commit
`660ddd89dd958d8d835ecbbcb323f3cfcd891c30` (retrieved 2026-10-28).

Source: <https://github.com/micropython/micropython-lib/blob/660ddd89dd958d8d835ecbbcb323f3cfcd891c30/micropython/umqtt.simple/umqtt/simple.py>

`requests.py` is an unmodified copy of `python-ecosys/requests/requests/__init__.py`
from the same commit:
<https://github.com/micropython/micropython-lib/blob/660ddd89dd958d8d835ecbbcb323f3cfcd891c30/python-ecosys/requests/requests/__init__.py>

Upstream licensing text is included in `MICROPYTHON_LIB_LICENSE`. These copies
are used only by the real Mosquitto and desk-to-door TCP integration tests.
Firmware installs `umqtt.simple` and `requests` separately. Tests adapt CPython
socket stream methods and text/bytes compatibility; they do not replace the MQTT
or HTTP protocol implementation, broker, or firmware routes.
