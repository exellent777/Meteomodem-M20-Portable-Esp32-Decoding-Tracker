# afc.py
# Сканирование диапазона 404.5–406.5 MHz для поиска максимального сигнала (M20).
#
# Логика:
#   1) Грубый проход диапазона 404.5–406.5 MHz с шагом 50 kHz, измеряем RSSI.
#   2) Выбираем частоту с максимальным средним RSSI.
#   3) Делаем уточняющий скан вокруг найденного пика с мелким шагом (5 kHz)
#      в окне ±25 kHz и снова выбираем максимум.
#   4) Если лучший RSSI ниже порога MIN_DETECT_RSSI — считаем, что зондов нет,
#      возвращаем (None, None).
#   5) Иначе возвращаем (best_freq_hz, best_rssi_dbm).
#
# Весь прогресс сканирования отдаём в track_store, чтобы это было видно в Web UI.

import time
import track_store

# Диапазон сканирования: 405.0–406.0 MHz
SCAN_START_HZ = 405_350_000
SCAN_END_HZ   = 405_450_000
SCAN_STEP_HZ  = 50_000     # шаг грубого скана, 50 kHz

DWELL_MS      = 40         # время "посидеть" на частоте перед измерением RSSI
RSSI_SAMPLES  = 2          # сколько раз мерить RSSI на каждой частоте

# Уточняющий скан вокруг найденного пика
REFINE_SPAN_HZ = 25_000    # ±25 kHz вокруг грубого пика
REFINE_STEP_HZ = 5_000     # мелкий шаг, 5 kHz

# Порог "это зонд, а не просто шум".
# Типичный шум CC1101 ~ -105 .. -110 dBm, дальний зонд может быть в районе -95 .. -85 dBm,
# а близкий — вообще -60 .. -40 dBm.
MIN_DETECT_RSSI = -90.0


def _measure_rssi(radio, freq_hz):
    """
    Установить частоту, немного подождать, несколько раз измерить RSSI
    и вернуть среднее значение.
    """
    try:
        radio.set_frequency(freq_hz)
        radio.enter_rx()
    except Exception as e:
        print("Ошибка установки частоты", freq_hz, ":", e)
        return None

    # Даём приёмнику "устаканиться"
    time.sleep_ms(DWELL_MS)

    acc = 0.0
    cnt = 0

    for _ in range(RSSI_SAMPLES):
        try:
            rssi = radio.read_rssi_dbm()
            acc += rssi
            cnt += 1
            time.sleep_ms(5)
        except Exception as e:
            print("Ошибка чтения RSSI:", e)

    if cnt == 0:
        return None

    return acc / cnt


def scan_band(radio):
    """
    Полный проход диапазона 405.0–406.0 MHz + локальное уточнение пика.

    Возвращает:
        (best_freq_hz, best_rssi_dbm) — если найден сигнал выше MIN_DETECT_RSSI,
        (None, None) — если в диапазоне ничего разумного не нашли.
    """
    # Проверяем, не включён ли режим FIXED (фиксированная частота).
    # В этом режиме не сканируем диапазон, а просто сидим на rf_fixed_freq_hz
    # и решаем, есть ли там достаточно сильный сигнал, чтобы считать это зондом.
    ctrl_mode = getattr(track_store, "rf_control_mode", "scan")
    if ctrl_mode == "fixed":
        fixed_hz = getattr(track_store, "rf_fixed_freq_hz", None)
        if fixed_hz is None:
            # запасной вариант, если что-то пошло не так
            fixed_hz = SCAN_START_HZ

        try:
            radio.set_frequency(fixed_hz)
            radio.enter_rx()
        except Exception as e:
            print("Ошибка установки частоты в FIXED-режиме:", e)
            return None, None

        # Несколько измерений RSSI для усреднения
        samples = 0
        acc = 0.0
        for _ in range(8):
            try:
                rssi = radio.read_rssi_dbm()
                acc += rssi
                samples += 1
                # публикуем в Web UI, чтобы было видно уровень на фиксированной частоте
                track_store.set_rf_status(fixed_hz, rssi)
                time.sleep_ms(20)
            except Exception as e:
                print("Ошибка чтения RSSI в FIXED-режиме:", e)
                time.sleep_ms(20)

        if samples == 0:
            return None, None

        avg = acc / samples
        print("FIXED: freq = %.3f MHz, avg RSSI ≈ %.1f dBm" % (fixed_hz / 1e6, avg))

        # Если сигнал слабый — считаем, что зонда нет
        if avg < MIN_DETECT_RSSI:
            return None, None

        # Иначе считаем фиксированную частоту кандидатом «зонда»
        return fixed_hz, avg

    # ----- обычный режим сканирования диапазона -----

    best_freq = None
    best_rssi = -999.0

    f = SCAN_START_HZ
    print("Начинаю сканирование диапазона %.3f–%.3f MHz, шаг %.1f kHz" %
          (SCAN_START_HZ / 1e6, SCAN_END_HZ / 1e6, SCAN_STEP_HZ / 1e3))

    # Грубый проход
    while f <= SCAN_END_HZ:
        try:
            avg_rssi = _measure_rssi(radio, f)
            if avg_rssi is None:
                f += SCAN_STEP_HZ
                continue

            # Обновляем статус для Web UI: сейчас слушаем частоту f
            track_store.set_rf_status(f, avg_rssi)
            track_store.set_rf_diagnostics(
                noise_rssi_dbm=None,
                signal_threshold_dbm=None,
                lost_counter=0,
                had_signal=track_store.rf_had_signal,
                mode="search",
            )

            print("[scan] freq = %.3f MHz, RSSI ≈ %.1f dBm" % (f / 1e6, avg_rssi))

            if avg_rssi > best_rssi:
                best_rssi = avg_rssi
                best_freq = f

        except Exception as e:
            print("Ошибка при сканировании частоты", f, ":", e)

        f += SCAN_STEP_HZ

    if best_freq is None:
        print("Сканирование: ни одной частоты измерить не удалось.")
        return None, None

    print("Сканирование (грубое) завершено, max RSSI ≈ %.1f dBm" % best_rssi)

    # Если максимум и так очень слабый — дальше не уточняем
    if best_rssi < MIN_DETECT_RSSI:
        print("Максимум слишком слабый для зонда (%.1f dBm < %.1f dBm)." %
              (best_rssi, MIN_DETECT_RSSI))
        return None, None

    # Уточняющий скан вокруг best_freq
    refine_start = best_freq - REFINE_SPAN_HZ
    refine_end = best_freq + REFINE_SPAN_HZ

    refined_freq = best_freq
    refined_rssi = best_rssi

    print("Уточняющий скан в окне %.3f–%.3f MHz, шаг %.1f kHz" %
          (refine_start / 1e6, refine_end / 1e6, REFINE_STEP_HZ / 1e3))

    f = refine_start
    while f <= refine_end:
        try:
            avg_rssi = _measure_rssi(radio, f)
            if avg_rssi is None:
                f += REFINE_STEP_HZ
                continue

            track_store.set_rf_status(f, avg_rssi)
            print("[refine] freq = %.3f MHz, RSSI ≈ %.1f dBm" % (f / 1e6, avg_rssi))

            if avg_rssi > refined_rssi:
                refined_rssi = avg_rssi
                refined_freq = f
        except Exception as e:
            print("Ошибка при уточняющем скане на частоте", f, ":", e)
        f += REFINE_STEP_HZ

    print("Итог сканирования: freq = %.3f MHz, RSSI ≈ %.1f dBm" %
          (refined_freq / 1e6, refined_rssi))

    if refined_rssi < MIN_DETECT_RSSI:
        print("Даже после уточнения максимум слишком слабый для зонда.")
        return None, None

    print("Обнаружен возможный зонд: freq = %.3f MHz, RSSI ≈ %.1f dBm" %
          (refined_freq / 1e6, refined_rssi))

    return refined_freq, refined_rssi
