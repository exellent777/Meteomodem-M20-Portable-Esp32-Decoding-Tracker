# main.py — главный цикл трекера (FSM: SCAN → VALIDATE → TRACK)

import time
import config
from track_store import track
from cc1101 import Radio
from gdo0_bitstream import collect_bits_from_gdo0, bits_to_bytes
from m20_decoder import decode_m20
from sonde_data import sonde
from afc import afc


BITRATE_M20 = 9600
BITS_PER_FRAME = 800

SCAN_START = 404000000
SCAN_END   = 406000000
SCAN_STEP  = 10000

# Сколько подряд валидных кадров (CRC ok) нужно,
# чтобы считать частоту действительно M20.
CONFIRM_FRAMES_REQUIRED = 3

# Максимум попыток на частоте в фазе VALIDATE
MAX_VALIDATE_ATTEMPTS = 8

# -------------------------------------------------------
#  FSM состояния
# -------------------------------------------------------
STATE_SCAN = 1
STATE_VALIDATE = 2
STATE_TRACK = 3


def run_tracker():
    radio = Radio()
    radio.configure_m20()

    print("[M20] Трекер запущен.")

    state = STATE_SCAN
    scan_freq = SCAN_START

    last_frame_ok = False

    # Счётчики для строгой валидации частоты
    validate_good = 0
    validate_total = 0

    while True:

        # ---------------------------
        # FIXED MODE из Web UI
        # ---------------------------
        mode, ff = track.get_rf_control_mode()
        if mode == "fixed_freq" and ff:
            radio.set_frequency(ff)
            track.rf_frequency_hz = ff
            freq = ff

            bits = collect_bits_from_gdo0(
                BITS_PER_FRAME,
                BITRATE_M20,
                source="FIXED",
                freq_hz=freq,
                rssi_dbm=None,
                use_oversample=True,
            )

            rssi = radio.read_rssi()
            track.update_rssi(rssi)

            buffers = bits_to_bytes(bits)
            frame = decode_m20(buffers)

            if frame:
                track.set_last_frame(frame)
                sonde.update_from_frame(frame)
                last_frame_ok = True
            else:
                last_frame_ok = False

            continue  # fixed mode не использует FSM

        # ---------------------------
        # AUTO SCAN / VALIDATE / TRACK
        # ---------------------------

        if state == STATE_SCAN:
            # Перебираем частоты
            radio.set_frequency(scan_freq)
            track.rf_frequency_hz = scan_freq

            bits = collect_bits_from_gdo0(
                BITS_PER_FRAME,
                BITRATE_M20,
                source="SCAN",
                freq_hz=scan_freq,
                rssi_dbm=None,
                use_oversample=True,
            )

            rssi = radio.read_rssi()
            track.update_rssi(rssi)

            # Проверка кандидата
            buffers = bits_to_bytes(bits)
            frame = decode_m20(buffers)

            if frame:
                print(f"[SCAN] Найден кандидат @ {scan_freq/1e6:.3f} МГц → VALIDATE")
                track.set_last_frame(frame)

                # Первая успешная CRC на этой частоте
                validate_good = 1
                validate_total = 1

                state = STATE_VALIDATE
                continue

            # Следующая частота
            scan_freq += SCAN_STEP
            if scan_freq > SCAN_END:
                scan_freq = SCAN_START

            continue

        # VALIDATE: пытаемся строго подтвердить наличие M20
        if state == STATE_VALIDATE:
            freq = track.rf_frequency_hz

            bits = collect_bits_from_gdo0(
                BITS_PER_FRAME,
                BITRATE_M20,
                source="VALIDATE",
                freq_hz=freq,
                rssi_dbm=None,
                use_oversample=True,
            )

            rssi = radio.read_rssi()
            track.update_rssi(rssi)

            buffers = bits_to_bytes(bits)
            frame = decode_m20(buffers)

            if frame:
                validate_good += 1
                validate_total += 1
                track.set_last_frame(frame)

                print(f"[VALIDATE] CRC ok ({validate_good}/{CONFIRM_FRAMES_REQUIRED})")

                if validate_good >= CONFIRM_FRAMES_REQUIRED:
                    print("[VALIDATE] Частота подтверждена → TRACK")
                    sonde.update_from_frame(frame)
                    last_frame_ok = True
                    state = STATE_TRACK
                    # Обнулим счётчики на будущее
                    validate_good = 0
                    validate_total = 0
                # иначе остаёмся в VALIDATE и продолжаем слушать эту же частоту

            else:
                validate_total += 1
                validate_good = 0  # последовательность прервалась
                print(f"[VALIDATE] Нет кадра (попытка {validate_total})")

                # Если слишком долго нет кадров или пропал сигнал — возвращаемся в SCAN
                if validate_total >= MAX_VALIDATE_ATTEMPTS or not track.signal_present:
                    print("[VALIDATE] Не удалось подтвердить → SCAN")
                    state = STATE_SCAN
                    validate_good = 0
                    validate_total = 0

            continue

        # TRACK: постоянное отслеживание
        if state == STATE_TRACK:
            freq = track.rf_frequency_hz

            bits = collect_bits_from_gdo0(
                BITS_PER_FRAME,
                BITRATE_M20,
                source="TRACK",
                freq_hz=freq,
                rssi_dbm=None,
                use_oversample=True,
            )

            rssi = radio.read_rssi()
            track.update_rssi(rssi)

            buffers = bits_to_bytes(bits)
            frame = decode_m20(buffers)

            if frame:
                track.set_last_frame(frame)
                sonde.update_from_frame(frame)
                last_frame_ok = True

                # мягкая AFC-подстройка
                new_freq = afc.correct_frequency(
                    radio, freq, rssi, frame_ok=True
                )
                track.rf_frequency_hz = new_freq

            else:
                last_frame_ok = False

                # Нет сигнала → возвращаемся к SCAN
                if not track.signal_present:
                    print("[TRACK] Сигнал потерян → SCAN")
                    state = STATE_SCAN

            continue
