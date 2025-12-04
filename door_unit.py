import network
import socket
from machine import Pin
import time

SSID = "***REMOVED***"
PASSWORD = "***REMOVED***"
AUTH_TOKEN = "SECRET123"  # "" to disable

led_pin = Pin(2, Pin.OUT)
is_on = False
last_change = time.ticks_ms()

# Wi-Fi setup
wlan = network.WLAN(network.STA_IF)
wlan.active(True)
wlan.connect(SSID, PASSWORD)
print("Connecting to Wi-Fi...")
while not wlan.isconnected():
    time.sleep(0.5)
print("Connected:", wlan.ifconfig())

# Helper functions
def set_output(on):
    global is_on, last_change
    is_on = on
    led_pin.value(on)
    last_change = time.ticks_ms()
    print("Light", "ON" if on else "OFF")

def html_page():
    status = "ON" if is_on else "OFF"
    color = "#f44336" if is_on else "#4CAF50"
    return f"""<!doctype html><html><head>
    <meta name="viewport" content="width=device-width,initial-scale=1">
    <title>Do Not Disturb Light</title>
    <style>
      body {{ font-family: sans-serif; text-align:center; margin-top:30px; }}
      button {{ font-size:22px; padding:15px 40px; margin:10px; border:0; border-radius:10px; color:#fff; }}
    </style></head>
    <body>
      <h1>Status: <span style='color:{color}'>{status}</span></h1>
      <button style='background:#f44336' onclick="location='/api/set?on=1{('&token='+AUTH_TOKEN) if AUTH_TOKEN else ''}'">ON</button>
      <button style='background:#4CAF50' onclick="location='/api/set?on=0{('&token='+AUTH_TOKEN) if AUTH_TOKEN else ''}'">OFF</button>
    </body></html>"""

def forbidden(s):
    s.send("HTTP/1.1 403 Forbidden\r\n\r\nForbidden")

# Start web server
addr = socket.getaddrinfo("0.0.0.0", 80)[0][-1]
s = socket.socket()
s.bind(addr)
s.listen(1)
print("Web server running on:", wlan.ifconfig()[0])

while True:
    cl, addr = s.accept()
    req = cl.recv(1024).decode()
    if not req:
        cl.close()
        continue
    path = req.split(" ")[1]

    if path.startswith("/api/set"):
        args = {}
        for p in path.split("?")[1].split("&"):
            if "=" in p:
                k, v = p.split("=")
                args[k] = v
        if AUTH_TOKEN and args.get("token") != AUTH_TOKEN:
            forbidden(cl)
        else:
            set_output(args.get("on") in ["1", "true"])
            cl.send("HTTP/1.1 200 OK\r\n\r\nOK")
        cl.close()
        continue

    if path.startswith("/api/state"):
        cl.send("HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n\r\n" +
                f'{{"on":{str(is_on).lower()},"last_ms":{time.ticks_ms()-last_change}}}')
        cl.close()
        continue

    cl.send("HTTP/1.1 200 OK\r\nContent-Type: text/html\r\n\r\n" + html_page())
    cl.close()
