"""MQTT integration for MicroPython's current umqtt.simple package.

Backoff scheduling does not sleep. Network operations are synchronous, with a
one-second socket timeout; DNS resolution is still platform-dependent.
"""
import time
import json


def unique_id():
    """Return a stable hardware identifier for Home Assistant discovery."""
    try:
        import network
        import binascii
        return binascii.hexlify(network.WLAN(network.STA_IF).config('mac')).decode()
    except Exception:
        try:
            import machine
            import binascii
            return binascii.hexlify(machine.unique_id()).decode()
        except Exception:
            return "unknown"


def _bytes(value):
    return value.encode() if isinstance(value, str) else value


class _BoundedSocket:
    """Preserve the timeout when umqtt switches back to blocking packet reads."""
    def __init__(self, sock, timeout):
        self._sock = sock
        self._timeout = timeout
        self._deadline = None
        self._blocking = True

    def set_deadline(self, deadline):
        self._deadline = deadline

    def _prepare(self):
        timeout = self._timeout
        if self._deadline is not None:
            remaining = time.ticks_diff(self._deadline, time.ticks_ms())
            if remaining <= 0:
                raise OSError('MQTT operation deadline exceeded')
            timeout = min(timeout, remaining / 1000)
        if self._blocking:
            self._sock.settimeout(timeout)

    def settimeout(self, timeout):
        self._timeout = timeout
        self._blocking = True
        self._prepare()

    def setblocking(self, blocking):
        self._blocking = blocking
        if blocking:
            self._prepare()
        else:
            self._sock.setblocking(False)

    def read(self, *args):
        self._prepare()
        return self._sock.read(*args)

    def write(self, *args):
        self._prepare()
        return self._sock.write(*args)

    def __getattr__(self, name):
        return getattr(self._sock, name)


class MQTTClient:
    """Retained light state, discovery, availability, and scheduled reconnects."""
    def __init__(self, mqtt_config):
        self.config = mqtt_config
        self.client = None
        self.connected = False
        self.retry_count = 0
        self.max_retries = 10
        self.retry_delays = [5, 10, 30, 60]
        self.message_callback = None
        self.client_id = "pushbuttondnd_" + unique_id()
        self.socket_timeout = 1
        self.keepalive = 60
        self._last_ping = time.ticks_ms()
        self._state = False
        self._reconnect_pending = False
        self._reconnect_after = 0
        self._gave_up = False
        self._connect_deadline = None
        self._transport_depth = 0
        self._dispatching_commands = False
        self._pending_commands = []
        self.max_pending_commands = 16

    def _leave_transport(self):
        self._transport_depth -= 1
        self._dispatch_commands()

    def _dispatch_commands(self):
        # umqtt invokes callbacks from wait_msg(), including inside a QoS 1
        # publish. Publishing a response there can consume the outer PUBACK.
        if self._transport_depth or self._dispatching_commands:
            return
        self._dispatching_commands = True
        try:
            # Apply one command per main-loop operation. A burst cannot turn
            # several individually bounded state publishes into a WDT timeout.
            if self._pending_commands:
                topic, message = self._pending_commands.pop(0)
                try:
                    if self.message_callback:
                        self.message_callback(topic, message)
                except Exception as error:
                    print('[MQTT] Command callback failed: {}'.format(error))
        finally:
            self._dispatching_commands = False

    def _drop_connection(self):
        self.connected = False
        client, self.client = self.client, None
        if client is not None:
            try:
                if client.sock:
                    client.sock.close()
            except Exception:
                pass

    def _bound_socket(self):
        if self.client and self.client.sock:
            deadline = self._connect_deadline
            if deadline is None:
                deadline = time.ticks_add(time.ticks_ms(), 1500)
            self.client.sock.set_deadline(deadline)
            self.client.sock.settimeout(self.socket_timeout)

    def connect(self):
        """Complete subscription and retained publications before reporting success.

        Requires umqtt.simple with connect(timeout=...). An old package fails
        safely instead of falling back to an unbounded connection attempt.
        """
        self._drop_connection()
        self._transport_depth += 1
        self._connect_deadline = time.ticks_add(time.ticks_ms(), 4000)
        try:
            from umqtt.simple import MQTTClient as MQTT
            self.client = MQTT(
                client_id=_bytes(self.client_id), server=self.config['broker'],
                port=self.config['port'],
                user=_bytes(self.config['username']) if self.config['username'] else None,
                password=_bytes(self.config['password']) if self.config['username'] else None,
                keepalive=self.keepalive,
            )
            availability = _bytes(self.config['topic_prefix'] + '/availability')
            self.client.set_last_will(availability, b'offline', retain=True, qos=1)
            self.client.set_callback(self._on_message_internal)
            self.client.connect(timeout=self.socket_timeout)
            self.client.sock = _BoundedSocket(self.client.sock, self.socket_timeout)
            self.connected = True
            self._bound_socket()
            self.client.subscribe(_bytes(self.config['topic_prefix'] + '/set'),
                                  qos=self.config['qos'])
            if not self.publish_discovery():
                raise OSError('Discovery publication failed')
            if not self.publish_state(self._state):
                raise OSError('State publication failed')
            if not self.publish(availability, b'online', retain=True, qos=1):
                raise OSError('Availability publication failed')
            self.retry_count = 0
            self._reconnect_pending = False
            self._gave_up = False
            self._last_ping = time.ticks_ms()
            print('[MQTT] Connected and subscribed to ' + self.config['topic_prefix'] + '/set')
        except Exception as error:
            print('[MQTT] Connection failed: {}'.format(error))
            self._drop_connection()
        finally:
            self._connect_deadline = None
            self._leave_transport()
        return self.connected

    def publish(self, topic, payload, retain=False, qos=1):
        if not self.connected or not self.client:
            return False
        self._transport_depth += 1
        try:
            self._bound_socket()
            self.client.publish(_bytes(topic), _bytes(payload), retain=retain, qos=qos)
            return True
        except Exception as error:
            print('[MQTT] Publish failed: {}'.format(error))
            self._drop_connection()
            return False
        finally:
            self._leave_transport()

    def publish_state(self, is_on):
        # Cache even while offline, so a reconnect never restores stale state.
        self._state = bool(is_on)
        return self.publish(self.config['topic_prefix'] + '/state',
                            'ON' if self._state else 'OFF', retain=True,
                            qos=self.config['qos'])

    def publish_discovery(self):
        payload = {
            'name': self.config.get('device_name', 'DND Light'),
            'unique_id': self.client_id,
            'state_topic': self.config['topic_prefix'] + '/state',
            'command_topic': self.config['topic_prefix'] + '/set',
            'availability_topic': self.config['topic_prefix'] + '/availability',
            'payload_on': 'ON', 'payload_off': 'OFF',
            # HA commands should not replay an old retained ON after reboot.
            # State publications themselves are still retained by publish_state.
            'optimistic': False, 'qos': self.config['qos'], 'retain': False,
            'device': {
                'identifiers': [self.client_id], 'name': 'PushButtonDND',
                'manufacturer': 'DIY', 'model': 'ESP32 DND Light', 'sw_version': '1.0',
            },
        }
        # A nested MQTT prefix is valid for state/command topics but cannot be
        # used as a discovery object_id (it adds unsupported path components).
        object_id = self.config['topic_prefix']
        if any(not ('a' <= char <= 'z' or 'A' <= char <= 'Z' or
                    '0' <= char <= '9' or char in '_-') for char in object_id):
            object_id = self.client_id
        return self.publish('homeassistant/light/' + object_id + '/config',
                            json.dumps(payload), retain=True, qos=1)

    def _on_message_internal(self, topic, message):
        if topic != _bytes(self.config['topic_prefix'] + '/set'):
            return
        # Light commands represent desired state. Retain the most recent
        # commands during bursts without allocating an unbounded ESP32 queue.
        if len(self._pending_commands) >= self.max_pending_commands:
            self._pending_commands.pop(0)
        self._pending_commands.append((topic, message))

    def check_messages(self):
        """Poll input and send a PING every half keepalive interval.

        umqtt's initial poll is non-blocking; pending packet reads and QoS 1
        acknowledgements use the bounded socket timeout.
        """
        if not self.connected or not self.client:
            self._dispatch_commands()
            return
        self._transport_depth += 1
        try:
            self._bound_socket()
            self.client.check_msg()
            now = time.ticks_ms()
            if time.ticks_diff(now, self._last_ping) >= self.keepalive * 500:
                self._bound_socket()
                self.client.ping()
                self._last_ping = now
        except Exception as error:
            print('[MQTT] Message check failed: {}'.format(error))
            self._drop_connection()
        finally:
            self._leave_transport()

    def reconnect_nonblocking(self):
        """Schedule one bounded connection attempt without sleeping for backoff."""
        self._dispatch_commands()
        if self.connected:
            return 'connected'
        if self._gave_up or self.retry_count >= self.max_retries:
            self._gave_up = True
            return 'gave_up'
        now = time.ticks_ms()
        if not self._reconnect_pending:
            delay = self.retry_delays[min(self.retry_count, len(self.retry_delays) - 1)]
            self._reconnect_after = time.ticks_add(now, delay * 1000)
            self._reconnect_pending = True
            return 'waiting'
        if time.ticks_diff(now, self._reconnect_after) < 0:
            return 'waiting'
        self._reconnect_pending = False
        self.retry_count += 1
        if self.connect():
            return 'connected'
        if self.retry_count >= self.max_retries:
            self._gave_up = True
            return 'gave_up'
        return 'waiting'

    def reconnect(self):
        """Compatibility alias; no longer sleeps for retry delays."""
        return self.reconnect_nonblocking() == 'connected'

    def reset_retries(self):
        self.retry_count = 0
        self._reconnect_pending = False
        self._gave_up = False

    def disconnect(self):
        if self.connected and self.client:
            client = self.client
            try:
                self.publish(self.config['topic_prefix'] + '/availability',
                             'offline', retain=True, qos=1)
                self._bound_socket()
                client.disconnect()
            except Exception as error:
                print('[MQTT] Disconnect failed: {}'.format(error))
        self._drop_connection()
