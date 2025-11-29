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

# История полёта (список точек). Для простоты храним кортежи (t, lat, lon, alt).
track = []

# Максимальное количество точек в треке
MAX_TRACK_POINTS = 500


def update_latest(data: SondeData) -> None:
    """
    Обновить объект latest целиком.
    Вызывается из main.py после успешного декодирования кадра.
    """
    global latest
    latest = data


def append_track(data: SondeData) -> None:
    """
    Добавить точку в трек. Храним с ограничением по длине.
    """
    global track
    if data is None:
        return
    t = getattr(data, "time", None) or 0
    lat = getattr(data, "lat", None)
    lon = getattr(data, "lon", None)
    alt = getattr(data, "alt", None)
    track.append((t, lat, lon, alt))
    if len(track) > MAX_TRACK_POINTS:
        track = track[-MAX_TRACK_POINTS:]


def clear_track() -> None:
    """
    Очистить историю трека.
    """
    global track
    track = []


# -----------------------------
# Статус радиочасти (текущая частота, RSSI)
# -----------------------------

# Текущая частота приёмника (Гц) и последний RSSI (dBm)
rf_freq_hz = None
rf_rssi_dbm = None


def set_rf_status(freq_hz, rssi_dbm) -> None:
    """
    Вызывается из main.py/afc.py для обновления текущей частоты и RSSI.
    """
    global rf_freq_hz, rf_rssi_dbm
    rf_freq_hz = freq_hz
    rf_rssi_dbm = rssi_dbm


# -----------------------------
# Диагностика радиочасти (режим, шум, порог, счётчик потерь)
# -----------------------------

rf_mode = "idle"                # "init" / "search" / "tracking" / "lost"
rf_noise_rssi_dbm = None        # оценка шумового уровня
rf_signal_threshold_dbm = None  # порог "есть сигнал"
rf_lost_counter = 0             # сколько слабых/пустых циклов подряд
rf_had_signal = False           # был ли когда-то уверенный сигнал


def set_rf_diagnostics(
    noise_rssi_dbm,
    signal_threshold_dbm,
    lost_counter,
    had_signal,
    mode,
) -> None:
    """
    Вызывается из main.py, чтобы обновить расширенную диагностику радиочасти.
    """
    global rf_noise_rssi_dbm, rf_signal_threshold_dbm
    global rf_lost_counter, rf_had_signal, rf_mode

    rf_noise_rssi_dbm = noise_rssi_dbm
    rf_signal_threshold_dbm = signal_threshold_dbm
    rf_lost_counter = lost_counter
    rf_had_signal = had_signal
    rf_mode = mode


# -----------------------------
# Режим управления поиском: SCAN vs FIXED
# -----------------------------

# По умолчанию используем сканирование диапазона
rf_control_mode = "scan"  # "scan" или "fixed"

# Фиксированная частота, на которую садимся в режиме FIXED
if config is not None and hasattr(config, "RF_FREQUENCY_HZ"):
    rf_fixed_freq_hz = config.RF_FREQUENCY_HZ
else:
    rf_fixed_freq_hz = None


def set_rf_control_mode(mode: str, fixed_freq_hz=None) -> None:
    """
    Установить режим поиска:
      - "scan"  — автоматически сканировать диапазон (afc.scan_band)
      - "fixed" — сидим на одной частоте (rf_fixed_freq_hz)
    При смене режима можно (опционально) поднимать флаг need_restart, чтобы главный
    цикл переинициализировал состояние.
    """
    global rf_control_mode, rf_fixed_freq_hz, need_restart

    if mode not in ("scan", "fixed"):
        mode = "scan"

    rf_control_mode = mode

    if fixed_freq_hz is not None:
        rf_fixed_freq_hz = fixed_freq_hz

    # Попросим главный цикл начать поиск заново с новым режимом
    need_restart = True


def get_rf_control_mode():
    """
    Вернуть (режим, фиксированная_частота).
    Удобно вызывать из main.py и web_ui.py.
    """
    return rf_control_mode, rf_fixed_freq_hz


# -----------------------------
# Флаг «перезапустить поиск» из Web UI
# -----------------------------

need_restart = False


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
