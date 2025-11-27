# track_store.py
# Хранение последней точки зонда, трека и статуса радиочасти.
# Плюс флаг для перезапуска поиска зондов из веб-интерфейса.

from sonde_data import *

# Последние данные зонда
latest = SondeData()

# История полёта (time, lat, lon, alt)
track = []

MAX_TRACK_POINTS = 500

# Статус радиочасти (для отображения в веб-интерфейсе)
rf_freq_hz = None
rf_rssi_dbm = None

# Флаг "перезапустить поиск" (ставится из web_ui, читается в main.py)
restart_search_flag = False


def append_data_point(data: SondeData):
    """
    Обновляет глобальный latest и добавляет точку в трек,
    если есть координаты.
    """
    global latest, track

    if data.fields == DATA_NONE:
        return

    if data.fields & DATA_POS:
        latest.lat = data.lat
        latest.lon = data.lon
        latest.alt = data.alt
        latest.fields |= DATA_POS

    if data.fields & DATA_TIME:
        latest.time = data.time
        latest.fields |= DATA_TIME

    if data.fields & DATA_SPEED:
        latest.speed = data.speed
        latest.heading = data.heading
        latest.climb = data.climb
        latest.fields |= DATA_SPEED

    if data.fields & DATA_SERIAL and data.serial:
        latest.serial = data.serial
        latest.fields |= DATA_SERIAL

    # Добавляем точку в трек, если координаты известны
    if latest.lat is not None and latest.lon is not None:
        track.append((latest.time, latest.lat, latest.lon, latest.alt))
        if len(track) > MAX_TRACK_POINTS:
            track.pop(0)


def update_rf_status(freq_hz, rssi_dbm):
    """
    Обновляет текущую частоту и RSSI, чтобы web_ui мог их показать.
    """
    global rf_freq_hz, rf_rssi_dbm
    rf_freq_hz = freq_hz
    rf_rssi_dbm = rssi_dbm


def request_restart():
    """
    Вызывается из web_ui при нажатии на кнопку 'Перезапустить поиск'.
    Просто ставит флаг.
    """
    global restart_search_flag
    restart_search_flag = True


def consume_restart_flag():
    """
    Читается в main.py.
    Если флаг был установлен — сбрасываем его и возвращаем True.
    Если не был — возвращаем False.
    """
    global restart_search_flag
    if restart_search_flag:
        restart_search_flag = False
        return True
    return False
