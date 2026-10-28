"""Small, bounded HTTP/1.x helpers shared by the ESP32 servers."""

import time

MAX_HEADERS = 4096
MAX_BODY = 8192
REQUEST_TIMEOUT_MS = 3000


class HTTPError(Exception):
    def __init__(self, status, message):
        self.status = status
        self.message = message
        super().__init__(message)


def _now():
    return time.ticks_ms() if hasattr(time, 'ticks_ms') else int(time.monotonic() * 1000)


def _elapsed(start):
    return time.ticks_diff(_now(), start) if hasattr(time, 'ticks_diff') else _now() - start


def read_request(client):
    """Read one complete request; cap bytes and total read time below the WDT."""
    start = _now()

    def receive(size):
        remaining = REQUEST_TIMEOUT_MS - _elapsed(start)
        if remaining <= 0:
            raise HTTPError(408, 'Request timeout')
        client.settimeout(remaining / 1000)
        try:
            chunk = client.recv(size)
        except OSError:
            raise HTTPError(408, 'Request timeout')
        if not chunk:
            raise HTTPError(400, 'Incomplete request')
        return chunk

    data = b''
    while b'\r\n\r\n' not in data:
        data += receive(512)
        if len(data.split(b'\r\n\r\n', 1)[0]) > MAX_HEADERS:
            raise HTTPError(431, 'Headers too large')
    raw_headers, body = data.split(b'\r\n\r\n', 1)
    try:
        lines = raw_headers.decode('utf-8').split('\r\n')
        method, path, version = lines[0].split(' ')
        if version not in ('HTTP/1.0', 'HTTP/1.1') or not path.startswith('/'):
            raise ValueError()
        headers = {}
        for line in lines[1:]:
            name, value = line.split(':', 1)
            name = name.strip().lower()
            if not name or name in headers:
                raise ValueError()
            headers[name] = value.strip()
        if 'transfer-encoding' in headers:
            raise HTTPError(400, 'Transfer encoding is unsupported')
        length = int(headers.get('content-length', '0'))
        if length < 0:
            raise ValueError()
    except (ValueError, UnicodeError):
        raise HTTPError(400, 'Malformed request')
    if length > MAX_BODY:
        raise HTTPError(413, 'Request body too large')
    if method == 'POST' and 'content-length' not in headers:
        raise HTTPError(411, 'Content-Length required')
    while len(body) < length:
        body += receive(min(512, length - len(body)))
    client.settimeout(2)
    try:
        return method, path, headers, body[:length].decode('utf-8')
    except UnicodeError:
        raise HTTPError(400, 'Body must be UTF-8')


def _url_decode(value):
    data = bytearray()
    value = value.replace('+', ' ')
    i = 0
    try:
        while i < len(value):
            if value[i] == '%':
                if i + 2 >= len(value):
                    raise ValueError()
                data.append(int(value[i + 1:i + 3], 16))
                i += 3
            else:
                data.extend(value[i].encode('utf-8'))
                i += 1
        return bytes(data).decode('utf-8')
    except (ValueError, UnicodeError):
        raise HTTPError(400, 'Invalid URL encoding')


def parse_query(path):
    args = {}
    if '?' not in path:
        return args
    for pair in path.split('?', 1)[1].split('&'):
        if not pair:
            continue
        parts = pair.split('=', 1)
        key = _url_decode(parts[0])
        if key in args:
            raise HTTPError(400, 'Duplicate query parameter')
        args[key] = _url_decode(parts[1] if len(parts) == 2 else '')
    return args


def url_encode(value):
    result = ''
    for byte in str(value).encode('utf-8'):
        if (65 <= byte <= 90 or 97 <= byte <= 122 or 48 <= byte <= 57
                or byte in (45, 46, 95, 126)):
            result += chr(byte)
        else:
            result += '%%%02X' % byte
    return result


def html_escape(value):
    return (str(value).replace('&', '&amp;').replace('<', '&lt;')
            .replace('>', '&gt;').replace('"', '&quot;').replace("'", '&#39;'))


def send_response(client, status, body, content_type='text/plain'):
    reasons = {200: 'OK', 400: 'Bad Request', 403: 'Forbidden', 404: 'Not Found',
               405: 'Method Not Allowed', 408: 'Request Timeout',
               411: 'Length Required', 413: 'Payload Too Large', 415: 'Unsupported Media Type',
               431: 'Request Header Fields Too Large', 500: 'Internal Server Error'}
    payload = body.encode('utf-8') if isinstance(body, str) else body
    if 'charset=' not in content_type:
        content_type += '; charset=utf-8'
    header = ('HTTP/1.1 %d %s\r\nContent-Type: %s\r\n'
              'Content-Length: %d\r\nConnection: close\r\nCache-Control: no-store\r\n'
              'X-Content-Type-Options: nosniff\r\n\r\n' %
              (status, reasons.get(status, 'Error'), content_type, len(payload))).encode('utf-8')
    # send() may make short writes, including on MicroPython.
    start = _now()
    for data in (header, payload):
        offset = 0
        while offset < len(data):
            remaining = REQUEST_TIMEOUT_MS - _elapsed(start)
            if remaining <= 0:
                raise OSError('Response timeout')
            client.settimeout(remaining / 1000)
            count = client.send(data[offset:offset + 1024])
            if not count:
                raise OSError('Socket closed during response')
            offset += count
