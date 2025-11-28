# boot.py
# Автозапуск M20-трекера при подаче питания:
#   1) подключаемся к Wi-Fi
#   2) запускаем Web UI в отдельном потоке
#   3) запускаем основной трекер (main.run_tracker)

import network
import time
import _thread

import config
import web_ui
import main  # твой трекерный main.py (в нём есть run_tracker())


def connect_wifi():
    """Подключение к Wi-Fi по данным из config.py."""
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)

    if not wlan.isconnected():
        print("Подключаюсь к Wi-Fi...", config.WIFI_SSID)
        wlan.connect(config.WIFI_SSID, config.WIFI_PASS)

        for i in range(30):  # ~15 секунд ожидания
            if wlan.isconnected():
                break
            time.sleep(0.5)
            print(".", end="")
        print()

    if wlan.isconnected():
        print("Wi-Fi подключён:", wlan.ifconfig())
        return True
    else:
        print("Wi-Fi НЕ подключён — Web UI может быть недоступен.")
        return False


def start_web_ui():
    """Запуск встроенного web-сервера в отдельном потоке."""
    try:
        # web_ui.run_server(host="0.0.0.0", port=config.HTTP_PORT)
        # по умолчанию аргументы уже такие, поэтому просто:
        _thread.start_new_thread(web_ui.run_server, ())
        print("Web UI запущен в отдельном потоке.")
    except Exception as e:
        print("Ошибка запуска Web UI:", e)


def main_boot():
    print("==== BOOT: M20 Tracker ====")

    # 1) Wi-Fi
    connected = connect_wifi()

    # 2) Web UI (если есть Wi-Fi, но можно и без него — слушаем только локально)
    if connected:
        start_web_ui()
    else:
        # Можно всё равно попробовать запустить — вдруг потом поднимешь точку доступа
        try:
            start_web_ui()
        except:
            pass

    # 3) Трекер — бесконечный цикл
    print("Старт основного цикла трекера...")
    main.run_tracker()


# Автоматический запуск при старте платы
main_boot()
