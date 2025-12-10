# main.py — SCAN/TRACK логика + FIXED режим "сидим на частоте и слушаем"

import time

from cc1101 import CC1101Radio
from gdo0_bitstream import BitstreamCollector
from m20_decoder import M20Decoder
from sonde_data import parse_m20
from track_store import TrackStore
from afc import AFC
from config import (
    SCAN_START_HZ,
    SCAN_END_HZ,
    SCAN_STEP_HZ,
    SCAN_DWELL_MS,
    M20_BITRATE,
)


class Tracker:
    def __init__(self):
        # режимы работы логики
        # "SCAN" — автоскан по диапазону
        # "TRACK" — сидим на найденной частоте и ждём кадры
        self.state = "SCAN"

        # Радио и состояние
        self.radio = CC1101Radio()
        self.track = TrackStore()

        # Декодер M20
        self.decoder = M20Decoder(self._on_m20_frame, debug=False)

        # Сборщик бит с GDO0 (oversampling ×4)
        self.bitcol = BitstreamCollector(self.decoder.feed_byte, debug=False)

        # AFC
        self.afc = AFC(
            radio=self.radio,
            track=self.track,
            step_hz=400,
            min_streak=3,
            loss_timeout=6.0,
            use_freqest=True,
            debug=False,
        )

        # текущее положение сканера
        self.scan_freq = SCAN_START_HZ

        # FIXED режим:
        # True  — сидим на заданной частоте ВСЕГДА
        # False — обычная логика SCAN/TRACK
        self.fixed_mode = False

    # ------------------------------------------------------
    # Вызывается при ВАЛИДНОМ кадре (CHECKM10 + parse OK)
    # ------------------------------------------------------
    def _on_m20_frame(self, frame_bytes):
        frame = parse_m20(frame_bytes)
        if frame is None:
            return

        # обновляем трек
        self.track.update_from_frame(frame)

        # сообщаем AFC
        self.afc.on_valid_frame(frame)

        # при сканировании — переходим в TRACK
        if self.state == "SCAN" and not self.fixed_mode:
            self.state = "TRACK"

    # ------------------------------------------------------
    # Режим SCAN — ходим по диапазону
    # ------------------------------------------------------
    def _run_scan(self):
        self.radio.set_frequency(self.scan_freq)
        self.track.freq = self.scan_freq

        # даём радиочипу устаканиться
        time.sleep_ms(30)

        # обновляем RSSI/шум
        self.track.update_rssi(self.radio)

        # следующий шаг по частоте
        self.scan_freq += SCAN_STEP_HZ
        if self.scan_freq > SCAN_END_HZ:
            self.scan_freq = SCAN_START_HZ

        time.sleep_ms(SCAN_DWELL_MS)

    # ------------------------------------------------------
    # Режим TRACK — сидим на частоте и ждём кадры
    # ------------------------------------------------------
    def _run_track(self):
        # всегда обновляем RSSI/шум
        self.track.update_rssi(self.radio)

        # Если мы в FIXED-режиме — НИКОГДА не выходим в SCAN.
        # Просто постоянно слушаем поток на этой частоте, даже без сигналов.
        if self.fixed_mode:
            time.sleep_ms(50)
            return

        # Нормальный TRACK-режим с AFC и возвратом в SCAN по потере кадров
        if self.afc.check_loss():
            # потеряли — возвращаемся в SCAN
            self.state = "SCAN"
            self.track.lost()
            return

        time.sleep_ms(50)

    # ------------------------------------------------------
    # Фиксированная частота (задаётся извне, например WebUI)
    # ------------------------------------------------------
    def set_fixed_frequency(self, freq_hz):
        """Включаем FIXED-режим: сидим на freq_hz и постоянно декодируем поток."""
        self.fixed_mode = True
        self.state = "TRACK"        # логически: слушаем, а не сканируем
        self.scan_freq = freq_hz

        self.radio.set_frequency(freq_hz)
        self.track.freq = freq_hz

        # Сброс AFC, чтобы он не тащил нас куда-то ещё
        self.afc.reset()

    def clear_fixed_mode(self):
        """Выходим из FIXED, возвращаем обычную SCAN/TRACK-логику."""
        self.fixed_mode = False
        self.state = "SCAN"
        self.afc.reset()

    # ------------------------------------------------------
    # Главный цикл
    # ------------------------------------------------------
    def run(self):
        print("Tracker starting…")

        # настраиваем CC1101 под M20 и уходим в RX
        self.radio.configure_m20()
        self.radio.enter_rx()

        # запускаем сборщик потока GDO0
        self.bitcol.start(M20_BITRATE)

        # основной цикл
        while True:
            if self.state == "SCAN" and not self.fixed_mode:
                self._run_scan()
            else:
                self._run_track()
