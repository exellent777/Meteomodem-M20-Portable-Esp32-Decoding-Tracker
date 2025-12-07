# gdo0_bitstream.py — сбор бит с GDO0 CC1101 для M20 Tracker
# Новая версия:
#   - oversampling по времени с majority vote
#   - подготовка непрерывного битового потока
#   - поиск 32-битного заголовка M20 (как в rdz_ttgo_sonde)
#   - Манчестер-демодуляция «бит-1 / бит-2 → 0/1»
#   - сбор кадров M20 фиксированной длины

import time
import gc
from machine import Pin
import config

GDO0_PIN = config.CC1101_GDO0
gdo0 = Pin(GDO0_PIN, Pin.IN)

# М20: длина полезного кадра (как в M10M20.cpp)
M20_FRAMELEN = 88

# 32-битные паттерны заголовка (из анализа M20, такие же, как в M10M20.cpp)
M20_SYNC1 = 0xCCCCA64C
M20_SYNC2 = 0x333359B3


def _collect_raw_bits(num_bits, bitrate_hz, oversample):
    """Снимаем уровень с GDO0 с oversample× чаще битрейта и
    превращаем в «сырые» биты (majority vote по каждому битовому интервалу).

    Возвращает список 0/1 длиной ~num_bits.
    """
    if bitrate_hz is None or bitrate_hz <= 0:
        bitrate_hz = 9600

    if oversample < 1:
        oversample = 1

    # Сколько «сырых» отсчётов берём
    total_samples = num_bits * oversample

    # Период между выборками, мкс
    sample_rate = bitrate_hz * oversample
    if sample_rate <= 0:
        sample_rate = bitrate_hz * oversample
    period_us = int(1_000_000 // sample_rate) or 1

    samples = [0] * total_samples

    t0 = time.ticks_us()
    for i in range(total_samples):
        target = t0 + i * period_us
        # Ждём до нужного момента (busy-wait; num_bits небольшое)
        while time.ticks_diff(target, time.ticks_us()) > 0:
            pass
        samples[i] = 1 if gdo0.value() else 0

    # Превращаем oversample-отсчёты в один бит (majority)
    bits = []
    thr = (oversample // 2) + 1
    idx = 0
    for _ in range(num_bits):
        if idx + oversample > total_samples:
            break
        chunk = samples[idx:idx + oversample]
        idx += oversample
        ones = 0
        for v in chunk:
            ones += v
        bits.append(1 if ones >= thr else 0)

    return bits


def collect_bits_from_gdo0(num_bits, bitrate_hz=None, oversample=6, *_, **__):
    """Основная точка входа для main.py.

    num_bits    — сколько бит хотим получить (как BITS_PER_FRAME)
    bitrate_hz  — битрейт CC1101 (обычно 9600 для M20)
    oversample  — во сколько раз чаще сэмплируем (6 по умолчанию)

    Возвращает одномерный список 0/1.
    """
    gc.collect()
    try:
        return _collect_raw_bits(num_bits, bitrate_hz or 9600, oversample)
    except Exception as e:
        # В случае проблем возвращаем пустой поток, чтобы не завалить FSM
        print("collect_bits_from_gdo0 error:", e)
        return []


def bits_to_bytes(bits):
    """Преобразует битовый поток GDO0 → список кадров-кандидатов M20 (bytes).

    Здесь реализованы:
      * 32-битный поиск заголовка (M20_SYNC1 / M20_SYNC2)
      * Манчестер-демодуляция по схеме как в M10M20.cpp:
            - первый бит пары («bit1») только сдвигает накопитель
            - второй бит пары («bit2») делает XOR с предыдущим
        В итоге для пары (b1,b2): 01/10 → 1, 00/11 → 0.

    Выход: список frames, где каждый frame — bytes длиной M20_FRAMELEN.
    Их дальше уже проверяет m20_decoder.decode_m20().
    """
    gc.collect()

    buffers = []

    if not bits:
        return buffers

    rxdata = 0          # скользящее 32-битное окно
    rxbitc = 0          # счётчик битов внутри Манчестер-пары (0..15)
    rxbyte = 0          # текущий собираемый байт
    searching = True    # пока ищем заголовок
    frame = bytearray() # собираемый кадр

    for d in bits:
        d = 1 if d else 0

        # Обновляем 32-битное окно
        rxdata = ((rxdata << 1) | d) & 0xFFFFFFFF

        if searching:
            # Проверяем две известные сигнатуры
            if rxdata == M20_SYNC1 or rxdata == M20_SYNC2:
                # Заголовок найден — начинаем Манчестер-декод
                searching = False
                rxbitc = 0
                rxbyte = 0
                frame = bytearray()
            continue

        # Манчестер-демодуляция
        if (rxbitc & 1) == 0:
            # «bit1» — просто сдвиг и запись
            rxbyte = ((rxbyte << 1) | d) & 0xFF
        else:
            # «bit2» — XOR → 01/10 даёт 1, 00/11 даёт 0
            rxbyte = rxbyte ^ d

        rxbitc = (rxbitc + 1) & 0x0F  # mod 16, как в исходном коде

        if rxbitc == 0:
            # Набрали 8 данных бит → готов байт
            frame.append(rxbyte & 0xFF)

            # Быстрая фильтрация: M20 должен начинаться с 0x45 0x20
            if len(frame) == 2:
                if not (frame[0] == 0x45 and frame[1] == 0x20):
                    # Не похоже на M20 — сбрасываем поиск
                    searching = True
                    rxdata = 0
                    rxbitc = 0
                    rxbyte = 0
                    frame = bytearray()
                    continue

            # Как только набрали полноценный кадр — сохраняем
            if len(frame) >= M20_FRAMELEN:
                buffers.append(bytes(frame[:M20_FRAMELEN]))
                # Возвращаемся в режим поиска следующего заголовка
                searching = True
                rxdata = 0
                rxbitc = 0
                rxbyte = 0
                frame = bytearray()

    return buffers
