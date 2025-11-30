# track_store.py
# Хранение последней точки зонда, трека и статуса радиочасти.
# Плюс флаги управления режимом поиска (SCAN/FIXED) и перезапуска из веб-интерфейса.

from sonde_data import SondeData
try:
    import config
except ImportError:
    config = None

# -----------------------------
# Данные по последнему кадру и треку
# -----------------------------

# Последние данные зонда (последний успешно декодированный пакет)
latest = SondeData()

# Трек (список SondeData с позицией)
track = []

# -----------------------------
# Статус радиочасти
# -----------------------------

# Последняя известная частота приёма (Hz) и RSSI (dBm)
rf_frequency_hz = None
rf_rssi_dbm = None

# Диагностика RF: шум, порог, счётчик потерь и т.п.
rf_noise_rssi_dbm = None
rf_signal_threshold_dbm = None
rf_lost_counter = 0
rf_had_signal = False
rf_mode = "idle"  # idle / scan / validate / tracking

# Режим управления приёмником:
#   "auto_scan"  — приёмник сам сканирует диапазон (основной режим);
#   "fixed_freq" — частота зафиксирована пользователем через Web UI.
rf_control_mode = "auto_scan"

# Если fixed_freq_hz не None — приёмник должен слушать только эту частоту.
fixed_freq_hz = None

# Флаг «нужно перезапустить поиск» (устанавливается из Web UI)
need_restart = False


# -----------------------------
# API для main.py и web_ui.py
# -----------------------------

def update_latest(data: SondeData) -> None:
    """
    Обновить структуру latest последним пакетом.
    """
    global latest
    latest = data


def append_track(data: SondeData) -> None:
    """
    Добавить точку в трек.
    """
    global track
    track.append(data)


def clear_track() -> None:
    """
    Очистить трек (например, при перезапуске поиска).
    """
    global track
    track = []


def get_latest() -> SondeData:
    """
    Вернуть последний пакет.
    """
    return latest


def get_track():
    """
    Вернуть текущий трек (список SondeData).
    """
    return track


# -----------------------------
# RF-статус
# -----------------------------

def set_rf_status(freq_hz, rssi_dbm) -> None:
    """
    Устанавливает последнюю известную частоту и RSSI.
    Это используется Web UI для отображения «куда сейчас смотрит» приёмник.
    """
    global rf_frequency_hz, rf_rssi_dbm
    rf_frequency_hz = freq_hz
    rf_rssi_dbm = rssi_dbm


def get_rf_status():
    """
    Возвращает (freq_hz, rssi_dbm).
    """
    return rf_frequency_hz, rf_rssi_dbm


def set_rf_diagnostics(
    noise_rssi_dbm=None,
    signal_threshold_dbm=None,
    lost_counter=0,
    had_signal=False,
    mode="idle",
) -> None:
    """
    Устанавливает диагностические параметры радиочасти.
    """
    global rf_noise_rssi_dbm, rf_signal_threshold_dbm
    global rf_lost_counter, rf_had_signal, rf_mode

    rf_noise_rssi_dbm = noise_rssi_dbm
    rf_signal_threshold_dbm = signal_threshold_dbm
    rf_lost_counter = lost_counter
    rf_had_signal = had_signal
    rf_mode = mode


def get_rf_diagnostics():
    """
    Возвращает диагностические параметры радиочасти.
    """
    return {
        "noise_rssi_dbm": rf_noise_rssi_dbm,
        "signal_threshold_dbm": rf_signal_threshold_dbm,
        "lost_counter": rf_lost_counter,
        "had_signal": rf_had_signal,
        "mode": rf_mode,
    }


# -----------------------------
# Режим управления частотой (auto_scan / fixed_freq)
# -----------------------------

def set_rf_control_mode(mode: str, freq_hz: int | None = None) -> None:
    """
    Устанавливает режим управления частотой.
      - mode = "auto_scan": частота определяется автоматически (AFC/scan_band);
      - mode = "fixed_freq": частота фиксируется на freq_hz.
    """
    global rf_control_mode, fixed_freq_hz
    if mode not in ("auto_scan", "fixed_freq"):
        raise ValueError("Unknown rf_control_mode: %r" % (mode,))

    rf_control_mode = mode
    fixed_freq_hz = freq_hz if mode == "fixed_freq" else None


def get_rf_control_mode():
    """
    Возвращает (mode, fixed_freq_hz).
    """
    return rf_control_mode, fixed_freq_hz


# -----------------------------
# Флаг перезапуска поиска
# -----------------------------

def request_restart() -> None:
    """
    Вызывается из web_ui.py, когда пользователь нажимает кнопку
    «Перезапустить поиск». Просто ставим флаг.
    """
    global need_restart
    need_restart = True


def clear_restart() -> None:
    """
    Вызывается из main.py, когда он увидел флаг need_restart
    и уже начал процедуру перезапуска поиска.
    """
    global need_restart
    need_restart = False


# -----------------------------
# Дополнительные обёртки для main.py
# -----------------------------

def reset_all() -> None:
    """Полный сброс состояния трекера (последний пакет и трек).
    Вызывается из main.py при старте и при возврате в режим SCAN."""
    global latest, track
    latest = SondeData()
    track = []


def get_restart_requested() -> bool:
    """Удобная обёртка для main.py: проверить, запрошен ли перезапуск поиска."""
    return need_restart


def clear_restart_request() -> None:
    """Сбрасывает флаг перезапуска поиска (обёртка над clear_restart)."""
    clear_restart()


def update_track_from_m20(data: SondeData) -> None:
    """Обновление последнего пакета и добавление точки в трек.
    Вызывается из main.py после успешного декода M20."""
    update_latest(data)
    append_track(data)
