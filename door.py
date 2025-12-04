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
    token_query = f"&token={AUTH_TOKEN}" if AUTH_TOKEN else ""

    return f"""<!doctype html>
<html>
<head>
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>PushButtonDND</title>

<style>
  :root {{
    --bg: #1e1e1e;
    --text: #ffffff;
    --card: #2c2c2c;
  }}

  body.light {{
    --bg: #f0f0f0;
    --text: #000000;
    --card: #ffffff;
  }}

  body {{
    background: var(--bg);
    color: var(--text);
    font-family: "Segoe UI", sans-serif;
    margin: 0;
    padding: 40px 20px;
    text-align: center;
    transition: background 0.3s, color 0.3s;
  }}

  #themeToggle {{
    position: fixed;
    top: 20px;
    right: 20px;
    background: var(--card);
    border: 0;
    border-radius: 20px;
    padding: 8px 14px;
    font-size: 14px;
    cursor: pointer;
    color: var(--text);
    box-shadow: 0 0 10px rgba(0,0,0,0.2);
    transition: background 0.3s, color 0.3s, transform 0.2s;
  }}
  #themeToggle:hover {{
    transform: scale(1.07);
  }}

  h1 {{
    margin-top: 50px;
    font-size: 32px;
    text-shadow: 0 0 10px rgba(255,255,255,0.2);
  }}

  .glow-ring {{
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 140px;
    height: 140px;
    border-radius: 50%;
    border: 5px solid {color};
    margin: 40px auto;
    font-size: 32px;
    color: {color};
    font-weight: bold;
    animation: pulseGlow 1.7s infinite ease-in-out;
    box-shadow: 0 0 20px {color}, 0 0 40px {color};
    transition: border 0.3s, color 0.3s, box-shadow 0.3s;
  }}

  @keyframes pulseGlow {{
    0%, 100% {{
      transform: scale(1);
    }}
    50% {{
      transform: scale(1.05);
    }}
  }}

  button.action {{
    font-size: 22px;
    padding: 15px 50px;
    margin: 15px;
    border: 0;
    border-radius: 12px;
    color: #fff;
    cursor: pointer;
    transition: transform 0.2s, box-shadow 0.2s;
  }}
  button.action:hover {{
    transform: scale(1.08);
    box-shadow: 0 0 15px rgba(255,255,255,0.3);
  }}

  .btn-on {{
    background: linear-gradient(135deg, #d32f2f, #ff5252);
  }}

  .btn-off {{
    background: linear-gradient(135deg, #2e7d32, #66bb6a);
  }}
</style>
</head>

<body>

<button id="themeToggle" onclick="toggleTheme()">Dark</button>

<h1>DND Status:</h1>

<div id="glow" class="glow-ring">{status}</div>

<button class="action btn-on"
 onclick="location='/api/set?on=1{token_query}'">
  ON
</button>

<button class="action btn-off"
 onclick="location='/api/set?on=0{token_query}'">
  OFF
</button>

<script>
function toggleTheme() {{
  document.body.classList.toggle("light");
  let isLight = document.body.classList.contains("light");
  document.getElementById("themeToggle").textContent =
    isLight ? "Light" : "Dark";
}}

/* ========== LIVE POLLING ========== */
function pollState() {{
  fetch('/api/state')
    .then(r => r.json())
    .then(data => {{
      let on = data.on;
      let glow = document.getElementById("glow");

      // Update ring text
      glow.textContent = on ? "ON" : "OFF";

      // Colors
      let c = on ? "#f44336" : "#4CAF50";

      // Apply updates
      glow.style.borderColor = c;
      glow.style.color = c;
      glow.style.boxShadow = "0 0 20px " + c + ", 0 0 40px " + c;
    }})
    .catch(e => console.log("Polling error:", e));
}}

// Poll every second
setInterval(pollState, 1000);
</script>

</body>
</html>
"""

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
