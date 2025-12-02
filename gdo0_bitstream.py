# gdo0_bitstream.py — сбор бит с GDO0 CC1101 для M20 Tracker
# Реализует:
#   - oversampling (OVERSAMPLE = 6)
#   - мини-PLL по фронтам для выбора фазы
#   - фильтрацию дребезга и быстрых переходов
#   - преобразование бит → bytes со всеми 8 сдвигами

import time
import gc
from machine import Pin
import config

# Получаем пин GDO0
GDO0_PIN = config.CC1101_GDO0
gdo0 = Pin(GDO0_PIN, Pin.IN)

# Oversampling params
OVERSAMPLE = config.OVERSAMPLE
USE_PLL_PHASE = True
PREAMBLE_BITS_FOR_PLL = config.PREAMBLE_BITS_FOR_PLL


# -------------------------------------------------------
#  Сбор сырых сэмплов с GDO0
# -------------------------------------------------------
def _sample_raw(num_bits, bitrate_hz, oversample):
    total_samples = num_bits * oversample
    period_us = int(1_000_000 // (bitrate_hz * oversample))

    samples = []
    t_next = time.ticks_us()

    for _ in range(total_samples):
        now = time.ticks_us()
        dt = time.ticks_diff(t_next, now)
        if dt > 0:
            time.sleep_us(dt)
        samples.append(1 if gdo0.value() else 0)
        t_next = time.ticks_add(t_next, period_us)

    return samples


# -------------------------------------------------------
#  Мини-PLL: определение фазы
# -------------------------------------------------------
def _detect_best_phase(raw, oversample):
    if not raw:
        return oversample // 2

    transitions = [0] * oversample
    limit = min(len(raw), PREAMBLE_BITS_FOR_PLL * oversample)

    prev = raw[0]
    last_edge = -9999
    min_sep = max(1, oversample // 2)   # минимальная дистанция между фронтами

    for i in range(1, limit):
        cur = raw[i]
        if cur != prev:
            if i - last_edge >= min_sep:
                phase = i % oversample
                transitions[phase] += 1
                last_edge = i
        prev = cur

    # Фаза с наибольшим количеством устойчивых переходов
    max_val = max(transitions)
    if max_val == 0:
        return oversample // 2

    edge_phase = transitions.index(max_val)
    sample_phase = (edge_phase + oversample // 2) % oversample
    return sample_phase


# -------------------------------------------------------
#  Преобразование сэмплов в биты
# -------------------------------------------------------
def _samples_to_bits(raw, oversample, phase):
    bits = []
    total_bits = len(raw) // oversample
    idx = phase

    for _ in range(total_bits):
        bits.append(raw[idx])
        idx += oversample

    return bits


# -------------------------------------------------------
#  Основная функция для main.py
# -------------------------------------------------------
def collect_bits_from_gdo0(num_bits,
                           bitrate_hz,
                           source="TRACK",
                           freq_hz=None,
                           rssi_dbm=None,
                           use_oversample=True):

    try:
        gc.collect()
    except:
        pass

    # Без oversampling — fallback
    if not use_oversample or OVERSAMPLE <= 1:
        bits = []
        period_us = int(1_000_000 // bitrate_hz)
        t_next = time.ticks_us()

        for _ in range(num_bits):
            now = time.ticks_us()
            dt = time.ticks_diff(t_next, now)
            if dt > 0:
                time.sleep_us(dt)
            bits.append(1 if gdo0.value() else 0)
            t_next = time.ticks_add(t_next, period_us)

        return bits

    # Сбор oversample-сэмплов
    raw = _sample_raw(num_bits, bitrate_hz, OVERSAMPLE)

    # Мини-PLL (фазовый выбор)
    if USE_PLL_PHASE:
        phase = _detect_best_phase(raw, OVERSAMPLE)
    else:
        phase = OVERSAMPLE // 2

    bits = _samples_to_bits(raw, OVERSAMPLE, phase)

    return bits


# -------------------------------------------------------
#  Преобразование бит → bytes со всеми сдвигами
# -------------------------------------------------------
def bits_to_bytes(bits):
    if bits is None:
        return []

    n = len(bits)
    buffers = []

    for shift in range(8):
        n_bits = n - shift
        if n_bits < 8:
            continue

        n_bytes = n_bits // 8
        arr = bytearray()
        idx = shift

        for _ in range(n_bytes):
            v = 0
            for _ in range(8):
                v = (v << 1) | (bits[idx] & 1)
                idx += 1
            arr.append(v)

        buffers.append(bytes(arr))

    return buffers
