# boot.py — старт Wi-Fi, WebUI и трекера

import network
import time
import _thread
import main
import web_ui

WIFI_SSID = "Red Magic 5G"
WIFI_PASS = "12345678"

def connect_wifi():
    sta = network.WLAN(network.STA_IF)
    sta.active(True)
    sta.connect(WIFI_SSID, WIFI_PASS)

    for _ in range(40):
        if sta.isconnected():
            print("WiFi OK:", sta.ifconfig())
            return True
        time.sleep_ms(200)

    print("WiFi FAIL")
    return False


def main_boot():
    connect_wifi()

    tracker = main.Tracker()

    # Web UI в отдельном потоке
    _thread.start_new_thread(web_ui.start_server, (tracker,))
    print("Web UI запущен.")

    print("Запуск трекера…")
    tracker.run()


main_boot()
