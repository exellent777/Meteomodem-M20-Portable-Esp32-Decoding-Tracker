# afc.py
# Сканирование диапазона для поиска максимального сигнала (M20).
#
# Логика:
#   - пройти от 400 до 410 МГц с шагом SCAN_STEP_HZ,
#   - на каждой частоте усреднить несколько измерений RSSI,
#   - выбрать частоту с максимумом RSSI,
#   - если лучший RSSI ниже порога MIN_DETECT_RSSI -> считаем, что зондов нет,
#   - иначе вернуть (best_freq_hz, best_rssi_dbm).

import time

# Диапазон сканирования (можешь подстроить под свой регион/частоты зондов)
SCAN_START_HZ = 400_000_000
SCAN_END_HZ   = 410_000_000
SCAN_STEP_HZ  = 50_000      # шаг 50 кГц; можно уменьшить до 25_000 для точности

DWELL_MS      = 40          # время "посидеть" на частоте перед измерением RSSI
RSSI_SAMPLES  = 3           # сколько раз мерить RSSI на каждой частоте

# Порог "это зонд, а не просто шум".
# Если лучший RSSI ниже этого порога — считаем, что зондов нет.
# Типичный шум CC1101 ~ -105 .. -110 dBm, далёкий зонд ~ -95 dBm, ближе -80, -70 и выше.
MIN_DETECT_RSSI = -95.0     # dBm


def scan_band(radio):
    """
    Сканирует диапазон SCAN_START_HZ–SCAN_END_HZ, измеряет RSSI,
    возвращает (best_freq_hz, best_rssi_dbm), если найден сигнал выше порога.
    Если ничего значимого не найдено — возвращает (None, None).

    radio — экземпляр CC1101 (из cc1101.CC1101).
    """
    best_freq = None
    best_rssi = -999.0

    f = SCAN_START_HZ
    print("Начинаю сканирование диапазона %d–%d Гц, шаг %d Гц" %
          (SCAN_START_HZ, SCAN_END_HZ, SCAN_STEP_HZ))

    # Включаем приём, чтобы RSSI был валидным на всех частотах
    try:
        radio.enter_rx()
    except Exception as e:
        print("Не удалось перейти в RX перед сканированием:", e)

    while f <= SCAN_END_HZ:
        try:
            # Устанавливаем частоту
            radio.set_frequency(f)
            # даём PLL и AGC устаканиться
            time.sleep_ms(10)

            # Собираем несколько измерений RSSI и усредняем
            acc = 0.0
            for _ in range(RSSI_SAMPLES):
                time.sleep_ms(DWELL_MS)
                rssi = radio.read_rssi_dbm()
                acc += rssi

            avg_rssi = acc / RSSI_SAMPLES

            print("freq = %.3f MHz, RSSI ≈ %.1f dBm" % (f / 1e6, avg_rssi))

            if avg_rssi > best_rssi:
                best_rssi = avg_rssi
                best_freq = f

            f += SCAN_STEP_HZ

        except Exception as e:
            print("Ошибка при сканировании на частоте", f, ":", e)
            f += SCAN_STEP_HZ

    print("Сканирование завершено")

    # Проверяем, достаточно ли сильный сигнал, чтобы считать это зондом
    if best_freq is None or best_rssi < MIN_DETECT_RSSI:
        print("Значимого сигнала не найдено (max RSSI = %.1f dBm). Зондов нет."
              % best_rssi)
        return None, None

    print("Обнаружен возможный зонд: freq = %.3f MHz, RSSI ≈ %.1f dBm" %
          (best_freq / 1e6, best_rssi))

    return best_freq, best_rssi
