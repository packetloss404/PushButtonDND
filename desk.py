import network
import urequests
import time
from machine import Pin

# Wi-Fi credentials
SSID = "***REMOVED***"
PASSWORD = "***REMOVED***"

# Receiver ESP32 URL (use IP or mDNS if available)
RECEIVER_URL = "http://esp-doorlight.local/api/set"
TOKEN = "SECRET123"  # leave blank if not using

# Pin setup
switch_pin = Pin(15, Pin.IN, Pin.PULL_UP)
last_state = switch_pin.value()

# Connect to Wi-Fi
wifi = network.WLAN(network.STA_IF)
wifi.active(True)
wifi.connect(SSID, PASSWORD)
print("Connecting to Wi-Fi...")
while not wifi.isconnected():
    time.sleep(0.5)
print("Connected:", wifi.ifconfig())

def send_state(state):
    try:
        url = f"{RECEIVER_URL}?on={1 if state else 0}"
        if TOKEN:
            url += f"&token={TOKEN}"
        print("Sending", url)
        resp = urequests.get(url)
        print(resp.text)
        resp.close()
    except Exception as e:
        print("Error sending:", e)

print("Monitoring switch...")

while True:
    state = switch_pin.value()
    if state != last_state:
        last_state = state
        send_state(not state)  # LOW = ON
        time.sleep(0.3)
    time.sleep(0.05)
