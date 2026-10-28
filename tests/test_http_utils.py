import unittest
import http_utils as http


class Socket:
    def __init__(self, data, fragment=7):
        self.data, self.fragment, self.sent = data, fragment, b''

    def settimeout(self, value):
        self.timeout = value

    def recv(self, size):
        result, self.data = self.data[:min(size, self.fragment)], self.data[min(size, self.fragment):]
        return result

    def send(self, data):
        part = data[:self.fragment]
        self.sent += part
        return len(part)


class HTTPTests(unittest.TestCase):
    def test_fragmented_unicode_body_larger_than_original_buffer(self):
        body = ('{"ssid":"' + 'é' * 1500 + '"}').encode()
        request = b'POST /api/config HTTP/1.1\r\nContent-Length: ' + str(len(body)).encode() + b'\r\n\r\n' + body
        method, path, headers, result = http.read_request(Socket(request))
        self.assertEqual((method, path, result), ('POST', '/api/config', body.decode()))

    def test_short_writes_and_byte_content_length(self):
        client = Socket(b'')
        http.send_response(client, 200, 'é☃')
        header, body = client.sent.split(b'\r\n\r\n')
        self.assertIn(b'Content-Length: 5', header)
        self.assertEqual(body.decode(), 'é☃')

    def test_encoding_round_trip(self):
        token = "quote'&= +é/☃"
        self.assertEqual(http.parse_query('/?token=' + http.url_encode(token))['token'], token)
        self.assertEqual(http.parse_query('/?ssid=Test+Network'), {'ssid': 'Test Network'})

    def test_reject_bad_framing(self):
        for headers, status in [(b'Content-Length: 9000', 413),
                                (b'Content-Length: -1', 400),
                                (b'Transfer-Encoding: chunked', 400),
                                (b'Content-Length: 1\r\nContent-Length: 1', 400),
                                (b'X: y', 411)]:
            with self.subTest(headers=headers), self.assertRaises(http.HTTPError) as cm:
                http.read_request(Socket(b'POST / HTTP/1.1\r\n' + headers + b'\r\n\r\n'))
            self.assertEqual(cm.exception.status, status)

    def test_duplicate_and_malformed_query(self):
        for path in ('/?token=bad&token=good', '/?x=%', '/?x=%zz', '/?x=%ff'):
            with self.subTest(path=path), self.assertRaises(http.HTTPError):
                http.parse_query(path)

    def test_timeout_is_error(self):
        class TimeoutSocket(Socket):
            def recv(self, size):
                raise OSError('timeout')
        with self.assertRaises(http.HTTPError) as cm:
            http.read_request(TimeoutSocket(b''))
        self.assertEqual(cm.exception.status, 408)
