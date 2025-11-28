# track_store.py
# Хранение последней точки зонда, трека и статуса радиочасти.
# Плюс флаг для перезапуска поиска зондов из веб-интерфейса.

from sonde_data import SondeData

# Последние данные зонда (последний успешно декодированный пакет)
latest = SondeData()

# История полёта (список точек).
# Для простоты храним кортежи (t, lat, lon, alt).
track = []

# Максимальное количество точек в треке
MAX_TRACK_POINTS = 500

# Статус радиочасти (для отображения в веб-интерфейсе)
rf_freq_hz = None      # текущая рабочая частота CC1101 (Гц)
rf_rssi_dbm = None     # текущий RSSI (dBm), по возможности «живой»

# Флаг запроса перезапуска поиска (из веб-интерфейса)
need_restart = False


# -------------------- Работа с данными зонда --------------------

def update_latest(data: SondeData):
    """
    Обновить структуру с последними данными зонда.
    Обычно вызывается из main.py, когда успешно декодирован пакет.
    """
    global latest
    latest = data


def append_track(data: SondeData):
    """
    Добавить точку в трек.
    Храним (time, lat, lon, alt), чтобы можно было потом визуализировать.
    Ограничиваем длину трека до MAX_TRACK_POINTS.
    """
    global track

    t = data.time if getattr(data, "time", None) is not None else 0.0
    lat = getattr(data, "lat", None)
    lon = getattr(data, "lon", None)
    alt = getattr(data, "alt", None)

    track.append((t, lat, lon, alt))

    if len(track) > MAX_TRACK_POINTS:
        # оставляем только последние MAX_TRACK_POINTS
        track = track[-MAX_TRACK_POINTS:]


# -------------------- Статус радиочасти --------------------

def set_rf_status(freq_hz, rssi_dbm):
    """
    Обновить статус радиочасти (частота и RSSI).
    Вызывается из main.py как в режиме AFC, так и при трекинге.
    """
    global rf_freq_hz, rf_rssi_dbm
    rf_freq_hz = freq_hz
    rf_rssi_dbm = rssi_dbm


# -------------------- Рестарт поиска (из Web UI) --------------------

def request_restart():
    """
    Вызывается из web_ui.py, когда пользователь нажимает кнопку
    «Перезапустить поиск». Просто ставим флаг.
    """
    global need_restart
    need_restart = True


def clear_restart():
    """
    Вызывается из main.py, когда он увидел флаг need_restart
    и уже начал процедуру перезапуска поиска.
    """
    global need_restart
    need_restart = False
