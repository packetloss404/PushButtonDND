"""Host actual firmware handlers on TCP; substitute only board APIs and resets.

There are no copied routes, HTML fixtures, or Playwright request interceptions.
Each instance has isolated config files, and a reset reloads them through the
firmware's initialize function. This is a host simulation, not ESP32 validation.
"""
import importlib.util
import socket
import sys
import threading
import time
import types
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


class Pin:
    OUT, IN, PULL_UP = 1, 0, 2

    def __init__(self, pin, mode, pull=None, value=0):
        self.state = value

    def value(self, value=None):
        if value is not None:
            self.state = value
        return self.state


class HostClock:
    @staticmethod
    def ticks_ms():
        return int(time.monotonic() * 1000) % (1 << 30)

    @staticmethod
    def ticks_diff(new, old):
        return (new - old + (1 << 29)) % (1 << 30) - (1 << 29)

    sleep = staticmethod(time.sleep)


def load_module(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FirmwareServer:
    def __init__(self, directory, kind='door'):
        self.kind = kind
        self.config = load_module('host_config_' + kind, 'config.py')
        self.config.CONFIG_PATH = str(directory / 'config.json')
        self.config.BACKUP_PATH = str(directory / 'config.json.backup')
        self.config.TEMP_PATH = str(directory / 'config.json.tmp')
        machine = types.SimpleNamespace(Pin=Pin)
        network = types.SimpleNamespace(STA_IF=0, AP_IF=1)
        with patch.dict(sys.modules, config=self.config, machine=machine, network=network):
            self.firmware = load_module('host_' + kind, kind + '.py')
        self.firmware.time = HostClock
        self.settings = self.config.get_default_config()
        self.settings['wifi']['ssid'] = 'Browser Test WiFi'
        self.settings['security']['auth_token'] = "test'&= +é</script>"
        self.config.save_config(self.settings)
        if kind == 'door':
            self.firmware.initialize(self.settings, connect_wifi=False)
        self.reboots = 0
        self.errors = []
        self.socket = socket.socket()
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.socket.bind(('127.0.0.1', 0))
        self.socket.listen(8)
        self.socket.settimeout(0.05)
        self.url = 'http://127.0.0.1:' + str(self.socket.getsockname()[1])
        self.stopping = threading.Event()
        self.thread = threading.Thread(target=self._serve, daemon=True)

    @property
    def token(self):
        return self.settings['security']['auth_token']

    def _serve(self):
        while not self.stopping.is_set():
            try:
                client, _ = self.socket.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            try:
                handler = (self.firmware.handle_client if self.kind == 'door'
                           else self.firmware.handle_setup_client)
                reboot = handler(client)
                if reboot:
                    self.reboots += 1
                    self.settings, error = self.config.load_config()
                    if error:
                        raise AssertionError(error)
                    if self.kind == 'door':
                        self.firmware.initialize(self.settings, connect_wifi=False)
            except Exception as error:
                self.errors.append(error)
                client.close()

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *args):
        self.stopping.set()
        self.socket.close()
        self.thread.join(5)
        assert not self.thread.is_alive(), 'Firmware server did not stop'
        assert not self.errors, self.errors
