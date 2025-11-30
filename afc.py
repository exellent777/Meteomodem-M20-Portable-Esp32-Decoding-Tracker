# afc.py
# Примитивный "AFC" / сканер диапазона для M20.
#
# Логика:
#   - coarse scan: проходим диапазон грубыми шагами, меряем RSSI, ищем максимум;
#   - считаем шум как медиану/среднее по всем RSSI;
#   - если максимум выше порога (noise + MARGIN) — делаем refine вокруг него
#     мелким шагом и возвращаем оптимальную частоту.
#
#   FIXED-режим:
#   - если rf_control_mode == "fixed_freq", НИЧЕГО не сканируем,
#     а просто сидим на заданной частоте, меряем RSSI и решаем,
#     есть ли кандидат (частота возвращается только если RSSI >= порога).

import time
import config
import track_store

# Диапазон сканирования (Hz)
SCAN_START_HZ = int(404.500e6)
SCAN_STOP_HZ  = int(406.500e6)
SCAN_STEP_HZ  = int(50e3)

# Минимальное количество точек, которое хотим набрать в coarse scan
MIN_POINTS = 10

# Порог детекции: best_rssi >= noise + MARGIN
RSSI_MARGIN_DB = 6.0  # на сколько dB лучший сигнал должен быть выше шума

# Абсолютный "пол" — если всё ниже этого, то считаем, что вообще пусто
ABSOLUTE_MIN_DBM = -110.0

# Кол-во измерений RSSI на одной частоте при скане
RSSI_SAMPLES_PER_FREQ = 3

# Кол-во измерений в FIXED-режиме (усреднение)
RSSI_SAMPLES_FIXED = 8


def _measure_rssi_avg(radio, n=RSSI_SAMPLES_PER_FREQ, delay_ms=50):
    """
    Несколько раз читаем RSSI у радиомодуля и возвращаем среднее.
    """
    total = 0.0
    count = 0
    for _ in range(n):
        time.sleep_ms(delay_ms)
        rssi = radio.read_rssi_dbm()
        total += rssi
        count += 1
    if count == 0:
        return None
    return total / count


def _median(values):
    """
    Простая медиана по списку чисел.
    """
    if not values:
        return None
    vals = sorted(values)
    n = len(vals)
    m = n // 2
    if n % 2 == 1:
        return vals[m]
    return 0.5 * (vals[m - 1] + vals[m])


def scan_band(radio):
    """
    Основная функция:
      - если rf_control_mode == "auto_scan":
            сканируем диапазон и возвращаем (freq_hz, rssi_dbm)
        или (None, None), если кандидата нет.
      - если rf_control_mode == "fixed_freq":
            сидим на одной частоте, меряем RSSI, логируем в track_store
            и возвращаем (freq_hz, rssi_dbm) только если RSSI >= порога,
            иначе (None, None).
    """
    # Узнаём режим управления частотой
    rf_control_mode, fixed_freq_hz = track_store.get_rf_control_mode()

    # ---------------- FIXED-режим ----------------
    if rf_control_mode == "fixed_freq":
        # Частота: либо заданная, либо хотя бы SCAN_START_HZ как запасной вариант
        if fixed_freq_hz is None:
            freq_hz = SCAN_START_HZ
        else:
            freq_hz = int(fixed_freq_hz)

        # Выставляем частоту, входим в RX
        radio.set_frequency(freq_hz)
        radio.enter_rx()

        # Меряем RSSI несколько раз, усредняем
        avg_rssi = _measure_rssi_avg(
            radio,
            n=RSSI_SAMPLES_FIXED,
            delay_ms=30,
        )

        # Если измерить не получилось — считаем, что кандидата нет
        if avg_rssi is None:
            track_store.set_rf_status(freq_hz, None)
            track_store.set_rf_diagnostics(
                noise_rssi_dbm=None,
                signal_threshold_dbm=None,
                lost_counter=0,
                had_signal=False,
                mode="fixed",
            )
            print("FIXED: freq=%.3f MHz, RSSI: нет данных" % (freq_hz / 1e6))
            return None, None

        # Порог: либо noise+margin (который мы здесь не знаем), либо просто "адекватный минимум"
        # Чтобы не усложнять, используем фиксированный порог, но можно подстроить.
        MIN_DETECT_RSSI = ABSOLUTE_MIN_DBM + 10.0  # примерно -100 dBm

        had_signal = avg_rssi >= MIN_DETECT_RSSI

        # Логируем в track_store для Web UI
        track_store.set_rf_status(freq_hz, avg_rssi)
        track_store.set_rf_diagnostics(
            noise_rssi_dbm=None,
            signal_threshold_dbm=MIN_DETECT_RSSI,
            lost_counter=0,
            had_signal=had_signal,
            mode="fixed",
        )

        if not had_signal:
            print(
                "FIXED: freq=%.3f MHz, avg RSSI=%.1f dBm < threshold (%.1f dBm) -> нет кандидата"
                % (freq_hz / 1e6, avg_rssi, MIN_DETECT_RSSI)
            )
            return None, None

        print(
            "FIXED: freq=%.3f MHz, avg RSSI=%.1f dBm >= threshold (%.1f dBm) -> кандидат"
            % (freq_hz / 1e6, avg_rssi, MIN_DETECT_RSSI)
        )
        return freq_hz, avg_rssi

    # ---------------- AUTO SCAN режим ----------------
    # Коурс-скан: идём от SCAN_START_HZ до SCAN_STOP_HZ шагом SCAN_STEP_HZ
    best_freq = None
    best_rssi = None
    rssi_values = []

    freq = SCAN_START_HZ
    print(
        "Начинаю сканирование диапазона %.3f–%.3f MHz, шаг %.1f kHz"
        % (SCAN_START_HZ / 1e6, SCAN_STOP_HZ / 1e6, SCAN_STEP_HZ / 1e3)
    )

    while freq <= SCAN_STOP_HZ:
        # Выставляем частоту и меряем средний RSSI
        radio.set_frequency(freq)
        radio.enter_rx()

        avg_rssi = _measure_rssi_avg(radio, n=RSSI_SAMPLES_PER_FREQ, delay_ms=50)
        if avg_rssi is None:
            freq += SCAN_STEP_HZ
            continue

        print("SCAN: freq = %.3f MHz, RSSI ≈ %.1f dBm" % (freq / 1e6, avg_rssi))
        rssi_values.append(avg_rssi)

        # Обновляем лучший найденный сигнал
        if best_rssi is None or avg_rssi > best_rssi:
            best_rssi = avg_rssi
            best_freq = freq

        # Обновляем статус для Web UI
        track_store.set_rf_status(freq, avg_rssi)
        track_store.set_rf_diagnostics(
            noise_rssi_dbm=None,
            signal_threshold_dbm=None,
            lost_counter=0,
            had_signal=False,
            mode="scan",
        )

        freq += SCAN_STEP_HZ

    # Если вообще ничего не померили — возвращаем None
    if not rssi_values or best_freq is None:
        print("SCAN: нет ни одного измерения RSSI, возвращаю (None, None)")
        return None, None

    # Оценка шума — по медиане
    noise = _median(rssi_values)
    if noise is None:
        noise = ABSOLUTE_MIN_DBM

    threshold = max(noise + RSSI_MARGIN_DB, ABSOLUTE_MIN_DBM)
    print(
        "SCAN: шум ≈ %.1f dBm, порог детекции = max(noise + %.1f, %.1f) = %.1f dBm"
        % (noise, RSSI_MARGIN_DB, ABSOLUTE_MIN_DBM, threshold)
    )
    print(
        "SCAN: лучший найденный сигнал: freq=%.3f MHz, RSSI=%.1f dBm"
        % (best_freq / 1e6, best_rssi)
    )

    # Если лучший сигнал ниже порога — кандидата нет
    if best_rssi < threshold:
        print(
            "SCAN: best_rssi=%.1f dBm < threshold=%.1f dBm => кандидата нет, продолжаем сканирование позже"
            % (best_rssi, threshold)
        )
        # Логируем диагностику шума
        track_store.set_rf_diagnostics(
            noise_rssi_dbm=noise,
            signal_threshold_dbm=threshold,
            lost_counter=0,
            had_signal=False,
            mode="scan",
        )
        return None, None

    # ----- уточняющий проход вокруг лучшей частоты -----
    fine_step = int(5e3)  # 5 kHz для уточнения
    span = int(50e3)      # ±50 kHz от best_freq

    refine_start = max(SCAN_START_HZ, best_freq - span)
    refine_stop  = min(SCAN_STOP_HZ, best_freq + span)

    print(
        "SCAN refine: уточняем вокруг %.3f MHz в диапазоне %.3f–%.3f MHz шагом %.1f kHz"
        % (best_freq / 1e6, refine_start / 1e6, refine_stop / 1e6, fine_step / 1e3)
    )

    refine_best_freq = best_freq
    refine_best_rssi = best_rssi

    freq = refine_start
    while freq <= refine_stop:
        radio.set_frequency(freq)
        radio.enter_rx()

        avg_rssi = _measure_rssi_avg(radio, n=4, delay_ms=40)
        if avg_rssi is None:
            freq += fine_step
            continue

        print("SCAN refine: freq = %.3f MHz, RSSI ≈ %.1f dBm" % (freq / 1e6, avg_rssi))

        # Обновляем лучший результат
        if avg_rssi > refine_best_rssi:
            refine_best_rssi = avg_rssi
            refine_best_freq = freq

        # Логируем для Web UI "живой" процесс
        track_store.set_rf_status(freq, avg_rssi)
        track_store.set_rf_diagnostics(
            noise_rssi_dbm=noise,
            signal_threshold_dbm=threshold,
            lost_counter=0,
            had_signal=True,
            mode="scan-refine",
        )

        freq += fine_step

    print(
        "SCAN refine: итоговая частота-кандидат: %.3f MHz, RSSI=%.1f dBm"
        % (refine_best_freq / 1e6, refine_best_rssi)
    )

    # Финальная проверка на порог
    if refine_best_rssi < threshold:
        print(
            "SCAN refine: даже уточнённый максимум ниже порога (%.1f < %.1f), кандидата нет"
            % (refine_best_rssi, threshold)
        )
        track_store.set_rf_diagnostics(
            noise_rssi_dbm=noise,
            signal_threshold_dbm=threshold,
            lost_counter=0,
            had_signal=False,
            mode="scan",
        )
        return None, None

    # Вернём частоту-кандидат и её RSSI
    track_store.set_rf_status(refine_best_freq, refine_best_rssi)
    track_store.set_rf_diagnostics(
        noise_rssi_dbm=noise,
        signal_threshold_dbm=threshold,
        lost_counter=0,
        had_signal=True,
        mode="scan",
    )

    return refine_best_freq, refine_best_rssi
