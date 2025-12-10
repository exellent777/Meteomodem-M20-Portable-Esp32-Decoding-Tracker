# track_store.py — хранение состояния трека и параметров сигнала

import time

# Порог, на сколько dB сигнал должен быть выше шума, чтобы считать "есть сигнал"
RSSI_SIGNAL_DELTA_DB = 6.0


class TrackStore:
    def __init__(self):
        # частота, на которой сейчас "сидит" приёмник
        self.freq = 0

        # параметры сигнала
        self.rssi = None       # сглаженный RSSI
        self.raw_rssi = None   # сырое мгновенное значение RSSI
        self.noise = None      # оценка шума (фоновый уровень)
        self.snr = None        # SNR = rssi - noise
        self.signal = 0        # 1 = есть сигнал над шумом, 0 = нет

        # время последнего валидного кадра (ms ticks)
        self.last_frame_time = None

        # последняя телеметрия M20
        self.last_lat = None
        self.last_lon = None
        self.last_alt = None
        self.last_velE = None
        self.last_velN = None
        self.last_velU = None
        self.last_serial = None
        self.last_batt_v = None

    def update_rssi(self, radio):
        """Обновить RSSI/шум/SNR/флаг signal по данным CC1101."""
        raw = radio.read_rssi_dbm()
        self.raw_rssi = raw

        if raw is None:
            return

        # экспоненциальное сглаживание RSSI
        if self.rssi is None:
            self.rssi = raw
        else:
            self.rssi = 0.3 * raw + 0.7 * self.rssi

        # если давно не было валидных кадров — считаем текущий уровень шумом
        now = time.ticks_ms()
        if (self.last_frame_time is None) or \
           (time.ticks_diff(now, self.last_frame_time) > 5000):
            if self.noise is None:
                self.noise = self.rssi
            else:
                self.noise = 0.2 * self.rssi + 0.8 * self.noise

        # считаем SNR и бинарный флаг наличия сигнала
        if self.noise is not None:
            self.snr = self.rssi - self.noise
            self.signal = 1 if self.snr > RSSI_SIGNAL_DELTA_DB else 0
        else:
            self.snr = None
            self.signal = 0

    def update_from_frame(self, frame):
        """Обновить телеметрию и отметку времени по валидному M20-кадру."""
        self.last_lat = frame.lat
        self.last_lon = frame.lon
        self.last_alt = frame.alt

        self.last_velE = frame.velE
        self.last_velN = frame.velN
        self.last_velU = frame.velU

        self.last_serial = frame.serial
        self.last_batt_v = frame.batt_v

        self.last_frame_time = time.ticks_ms()

    def lost(self):
        """Вызывается, когда трекер считает зонд потерянным."""
        self.signal = 0
