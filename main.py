# main.py
# ESP32-C3 (Seeed XIAO) + CC1101 + Meteomodem M20
#
# Функции:
#   - подключение к Wi-Fi
#   - запуск веб-интерфейса
#   - циклический автопоиск частоты в диапазоне 400–410 МГц
#   - приём и декодирование кадров M20
#   - онлайн RSSI для поиска зонда
#   - возврат к поиску, если зонд пропал или нажата кнопка "Перезапустить поиск"

import network
import time
import _thread

import config
from cc1101 import CC1101
from m20_decoder import decode_m20_frame
from track_store import append_data_point, update_rf_status, consume_restart_flag
import web_ui
import afc


def connect_wifi():
    """
    Подключение к Wi-Fi. Если не удалось за 5 секунд —
    просто продолжаем без сети (радио и так будет работать).
    """
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)

    try:
        if not wlan.isconnected():
            print("Подключаюсь к Wi-Fi:", config.WIFI_SSID)
            wlan.connect(config.WIFI_SSID, config.WIFI_PASS)
            t0 = time.ticks_ms()
            # даём до 5 секунд на подключение
            while (not wlan.isconnected()
                   and time.ticks_diff(time.ticks_ms(), t0) < 5000):
                time.sleep_ms(200)

        if wlan.isconnected():
            ip, mask, gw, dns = wlan.ifconfig()
            print("Wi-Fi OK, IP:", ip)
        else:
            print("Wi-Fi не подключен (продолжаю без сети)")

    except KeyboardInterrupt:
        print("Прервано подключение к Wi-Fi")
    except Exception as e:
        print("Ошибка Wi-Fi:", e)

    return wlan


def http_thread():
    """
    Поток для HTTP-сервера.
    """
    web_ui.start_server()


def main():
    # 1. Подключаем Wi-Fi (если получится)
    connect_wifi()

    # 2. Стартуем HTTP-сервер в отдельном потоке
    try:
        _thread.start_new_thread(http_thread, ())
        print("HTTP сервер запущен на порту", config.HTTP_PORT)
    except Exception as e:
        print("Не удалось стартовать HTTP-сервер:", e)

    # 3. Инициализируем радио
    radio = CC1101()
    print("CC1101 инициализирован, стартовая частота:",
          config.RF_FREQUENCY_HZ, "Гц")

    # Порог потери зонда:
    RSSI_LOST_MARGIN = 3.0   # дБ запас относительно порога обнаружения
    LOST_LIMIT = 40          # сколько циклов подряд считать "нет пакетов", чтобы признать зонд потерянным

    try:
        # -------- Главный вечный цикл: поиск зонда -> трекинг -> снова поиск --------
        while True:
            print("\n=== Режим поиска зондов ===")
            update_rf_status(None, None)

            # 4. Автопоиск частоты в диапазоне 400–410 МГц
            best_freq, best_rssi = afc.scan_band(radio)

            if best_freq is None:
                # зондов нет — подождём и попробуем ещё раз
                print("Зондов не найдено. Повторю поиск через 10 секунд.\n")
                update_rf_status(None, None)
                # небольшая задержка, чтобы не молотить диапазон постоянно
                time.sleep(10)
                continue

            # 5. Нашли сигнал выше порога — считаем, что это зонд
            print("Обнаружен возможный зонд, фиксируюсь на частоте: %.3f MHz"
                  % (best_freq / 1e6))
            radio.set_frequency(best_freq)
            update_rf_status(best_freq, best_rssi)

            print("Перехожу в режим трекинга. Ожидаю кадры длиной",
                  config.M20_FRAME_LEN, "байт")

            # -------- Режим трекинга --------
            lost_counter = 0

            while True:
                # Проверяем, не попросил ли веб-интерфейс перезапуск поиска
                if consume_restart_flag():
                    print("\nПолучен запрос на перезапуск поиска из веб-интерфейса.")
                    print("Выход из трекинга и возврат в режим сканирования...\n")
                    update_rf_status(None, None)
                    break

                # Текущий RSSI — для веб-интерфейса и "пеленгации"
                rssi_now = radio.read_rssi_dbm()
                update_rf_status(best_freq, rssi_now)

                # Принимаем один кадр M20
                frame = radio.receive_frame(config.M20_FRAME_LEN, timeout_ms=500)

                if frame is not None:
                    data = decode_m20_frame(frame)

                    if data.fields & 0x04:  # DATA_POS
                        # получили валидную позицию — сбрасываем счётчик потерь
                        lost_counter = 0
                        append_data_point(data)

                        lat_str = "lat=%.6f" % data.lat if data.lat is not None else "lat=None"
                        lon_str = "lon=%.6f" % data.lon if data.lon is not None else "lon=None"
                        alt_str = "alt=%.1f m" % data.alt if data.alt is not None else "alt=None"
                        print(
                            "M20:",
                            lat_str,
                            lon_str,
                            alt_str,
                            "RSSI=%.1f dBm" % rssi_now,
                        )
                    else:
                        # кадр пришёл, но позиция не декодировалась
                        lost_counter += 1
                else:
                    # вовсе нет кадра
                    lost_counter += 1

                # Условия потери зонда:
                #   1) долго нет валидных пакетов
                #   2) RSSI опустился ниже порога обнаружения - margin
                if lost_counter > LOST_LIMIT or \
                   (rssi_now < (afc.MIN_DETECT_RSSI - RSSI_LOST_MARGIN)):
                    print("\nПохоже, зонд потерян (нет пакетов / низкий RSSI).")
                    print("Возвращаюсь в режим поиска...\n")
                    update_rf_status(None, None)
                    break

                # Небольшая пауза, чтобы не забивать UART и дать системе подышать
                time.sleep_ms(50)

    except KeyboardInterrupt:
        print("Остановка main() по KeyboardInterrupt")
    except Exception as e:
        print("Фатальная ошибка в main():", e)


if __name__ == "__main__":
    main()
