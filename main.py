# main.py
#
# Главный цикл M20 tracker:
#   - приём на фиксированной частоте (из config.RF_FREQUENCY_HZ, сейчас 405 МГц),
#   - приём и декодирование M20,
#   - обновление track_store,
#   - уход в "потерю" при отсутствии валидных пакетов,
#   - по запросу Web UI — мягкий "рестарт" приёма (но без сканирования).

import time
from cc1101 import CC1101, CC1101ReceiveError
from m20_decoder import decode_m20_frame
from sonde_data import DATA_POS
import track_store
from config import PIN_SCK, PIN_MOSI, PIN_MISO, PIN_CS, PIN_GDO0, RF_FREQUENCY_HZ


def run_tracker():
    # Инициализация CC1101
    radio = CC1101(
        sck=PIN_SCK,
        mosi=PIN_MOSI,
        miso=PIN_MISO,
        cs=PIN_CS,
        gdo0=PIN_GDO0,
    )
    print("CC1101 инициализирован.")

    # Фиксируем рабочую частоту (сейчас 405 МГц)
    base_freq = RF_FREQUENCY_HZ
    print("Устанавливаю фиксированную частоту приёма: %.3f MHz" % (base_freq / 1e6))
    radio.set_frequency(base_freq)
    radio.enter_rx()
    track_store.set_rf_status(base_freq, None)

    # TRACKING PARAMS
    LOST_LIMIT = 40         # сколько циклов без валидного пакета можно терпеть
    RSSI_LOST_MARGIN = 5    # запас по RSSI относительно порога "нормального" сигнала
    MIN_SIGNAL_RSSI = -95.0 # dBm: ориентировочный порог "что-то есть"

    lost_counter = 0

    while True:
        # -------------------------------
        # Обработка запроса "рестарт"
        # -------------------------------
        if track_store.need_restart:
            print("Запрос перезапуска от Web UI: сбрасываю состояние приёма.")
            track_store.clear_restart()
            lost_counter = 0
            # Перезапускаем приём на той же частоте
            try:
                radio.flush_rx()
            except Exception:
                pass
            radio.set_frequency(base_freq)
            radio.enter_rx()
            track_store.set_rf_status(base_freq, None)
            time.sleep_ms(200)

        # -------------------------------
        # Текущий RSSI
        # -------------------------------
        try:
            cur_rssi = radio.read_rssi_dbm()
        except Exception:
            cur_rssi = None

        track_store.set_rf_status(base_freq, cur_rssi)

        # Логика "сигнал потерян / слабый"
        if cur_rssi is None:
            lost_counter += 1
            print("RSSI: None, lost_counter=%d" % lost_counter)
        elif cur_rssi < MIN_SIGNAL_RSSI - RSSI_LOST_MARGIN:
            lost_counter += 1
            print("Слабый RSSI (%.1f dBm), lost_counter=%d" %
                  (cur_rssi, lost_counter))
        else:
            # сигнал вроде живой — потихоньку уменьшаем счётчик потерь
            lost_counter = max(0, lost_counter - 1)

        if lost_counter > LOST_LIMIT:
            # Здесь мы не "пересканируем", а просто констатируем, что зонд потерян.
            print("Зонд потерян по RSSI на частоте %.3f MHz." % (base_freq / 1e6))
            # Можно сделать небольшую паузу и продолжать слушать — вдруг появится новый зонд.
            time.sleep(1)
            continue

        # -------------------------------
        # Попытка приёма одного кадра
        # -------------------------------
        try:
            frame = radio.receive_frame()
            # Если дошли до сюда, что-то прочитали — обновим RSSI "по факту кадра"
            try:
                latest_rssi = radio.read_rssi_dbm()
            except Exception:
                latest_rssi = cur_rssi
            track_store.set_rf_status(base_freq, latest_rssi)

        except CC1101ReceiveError:
            # Таймаут / мусор — считаем "ещё один промах"
            lost_counter += 1
            continue
        except Exception as e:
            print("Ошибка приёма:", e)
            lost_counter += 1
            continue

        # -------------------------------
        # ДЕКОДИРОВАНИЕ M20
        # -------------------------------
        data = decode_m20_frame(frame)

        # Если декодер вернул пустую структуру или без координат — игнорируем
        if (data is None) or not (data.fields & DATA_POS):
            lost_counter += 1
            continue

        # Валидный пакет с координатами → сбрасываем счётчик потерь
        lost_counter = 0

        print("Получена точка: lat=%.5f lon=%.5f alt=%.1f" %
              (data.lat, data.lon, data.alt))

        track_store.update_latest(data)
        track_store.append_track(data)

        # Небольшая пауза, чтобы не грузить CPU
        time.sleep_ms(30)


if __name__ == "__main__":
    # Если запускать main.py напрямую (без boot.py),
    # трекер всё равно стартанёт.
    run_tracker()
