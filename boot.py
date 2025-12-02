# boot.py — стабильный запуск для ESP32-C3
import network
import time
import _thread
import web_ui
import main

WIFI_SSID = "Red Magic 5G"
WIFI_PASS = "12345678"

def connect_wifi():

    # На всякий случай выключаем ВСЁ Wi-Fi перед стартом
    try:
        network.WLAN(network.AP_IF).active(False)
        network.WLAN(network.STA_IF).active(False)
        time.sleep_ms(200)
    except:
        pass

    sta = network.WLAN(network.STA_IF)
    sta.active(True)

    try:
        sta.connect(WIFI_SSID, WIFI_PASS)
    except Exception as e:
        print("Ошибка при sta.connect:", e)
        return False

    for _ in range(40):
        if sta.isconnected():
            print("Wi-Fi подключён:", sta.ifconfig())
            return True
        time.sleep_ms(200)

    print("Wi-Fi: не удалось подключиться.")
    return False


def main_boot():
    # Сначала включаем Wi-Fi
    connect_wifi()

    # Поднимаем Web UI в отдельном потоке
    try:
        _thread.start_new_thread(web_ui.start_server, ())
        print("Web UI запущен в отдельном потоке.")
    except Exception as e:
        print("Ошибка запуска Web UI:", e)

    print("Старт основного цикла трекера...")
    main.run_tracker()


main_boot()
