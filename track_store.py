# track_store.py — хранение состояния системы + фильтры RSSI

import time

class TrackStore:
    def __init__(self):
        # -------- RF monitoring --------
        self.rf_frequency_hz = None       # текущая частота
        self.rf_rssi_dbm = None           # последний RSSI
        self.rf_rssi_filt = None          # сглаженный RSSI
        self.noise_floor = None           # уровень шума
        self.signal_threshold = 6         # сколько dB над шумом считаем сигналом
        self.signal_present = False       # флаг "есть сигнал"

        # -------- RF control --------
        self.rf_mode = "auto_scan"        # режим: auto_scan / fixed_freq
        self.rf_fixed_freq_hz = None

        # -------- Track info --------
        self.last_frame = None
        self.last_frame_time = None

        # -------- Internal flags --------
        self._need_restart = False

    # ------------------------------------------------------
    #  RSSI filtering + detection of real signal
    # ------------------------------------------------------
    def update_rssi(self, rssi_dbm: float):
        """Обновляет RAW RSSI, сглаженный RSSI, шум и флаг сигнала."""

        self.rf_rssi_dbm = rssi_dbm

        if rssi_dbm is None:
            return

        # 1) Сглаживание RSSI (экспоненциальное)
        if self.rf_rssi_filt is None:
            self.rf_rssi_filt = rssi_dbm
        else:
            self.rf_rssi_filt = 0.3 * rssi_dbm + 0.7 * self.rf_rssi_filt

        # 2) Обновление шумового уровня:
        #    если давно нет кадра — значит это шум.
        if self.last_frame_time is None or (time.time() - self.last_frame_time) > 5:
            if self.noise_floor is None:
                self.noise_floor = self.rf_rssi_filt
            else:
                self.noise_floor = 0.2 * self.rf_rssi_filt + 0.8 * self.noise_floor

        # 3) Детектор сигнала
        if self.noise_floor is not None:
            self.signal_present = (self.rf_rssi_filt > self.noise_floor + self.signal_threshold)
        else:
            self.signal_present = False

    # ------------------------------------------------------
    #  Frames
    # ------------------------------------------------------
    def set_last_frame(self, frame):
        self.last_frame = frame
        self.last_frame_time = time.time()

    def get_last_frame(self):
        return self.last_frame

    # ------------------------------------------------------
    #  RF modes
    # ------------------------------------------------------
    def set_rf_control_mode(self, mode, freq=None):
        self.rf_mode = mode
        self.rf_fixed_freq_hz = freq

    def get_rf_control_mode(self):
        return self.rf_mode, self.rf_fixed_freq_hz

    # ------------------------------------------------------
    #  Restart requests (FSM interaction)
    # ------------------------------------------------------
    def request_restart(self):
        self._need_restart = True

    def consume_restart_request(self):
        if self._need_restart:
            self._need_restart = False
            return True
        return False


# Глобальный экземпляр (используется во всех модулях)
track = TrackStore()
