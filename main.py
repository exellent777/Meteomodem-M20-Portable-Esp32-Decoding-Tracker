#
# Главный цикл M20 tracker c AFC:
#   - режим SCAN (auto_scan): сканируем 404.5–406.5 MHz (afc.scan_band),
#       пока не найдём частоту с сигналом выше порога;
#   - режим VALIDATE: фиксируемся на частоте-кандидате и проверяем,
#       что есть несколько подряд валидных M20-кадров (CRC/структура);
#   - режим TRACK: в режиме трекинга принимаем кадры, декодируем M20, ведём трек;
#   - режим FIXED (rf_control_mode="fixed_freq"): не сканируем диапазон,
#       а всё время сидим на заданной частоте и мониторим её;
#   - если долго нет валидных кадров — считаем зонд потерян и
#       для auto_scan возвращаемся в сканирование, для fixed_freq — продолжаем
#       слушать ту же частоту;
#   - из Web UI кнопка «Перезапустить поиск» переводит в state="scan" и
#       переинициализирует приёмник с учётом rf_control_mode.
#

import time
from cc1101 import CC1101, CC1101ReceiveError
from m20_decoder import decode_m20_frame
from sonde_data import DATA_POS
import track_store
import afc
from config import PIN_SCK, PIN_MOSI, PIN_MISO, PIN_CS, PIN_GDO0, RF_FREQUENCY_HZ, M20_FRAME_LEN
from gdo0_bitstream import collect_bits_from_gdo0, bits_to_bytes


def find_m20_in_buffer(buf: bytes):
    """
    Скользящий поиск валидного кадра M20 внутри произвольного буфера байтов.
    Возвращает (SondeData, True/False) — данные и флаг "это позиционный кадр".
    """
    n = len(buf)
    if n < M20_FRAME_LEN:
        return None, False

    for offset in range(0, n - M20_FRAME_LEN + 1):
        frame = buf[offset:offset + M20_FRAME_LEN]
        data = decode_m20_frame(frame)
        if data is not None and bool(data.fields & DATA_POS):
            return data, True

    return None, False


def _get_rf_control_mode():
    """Безопасный доступ к (rf_control_mode, fixed_freq_hz)."""
    try:
        return track_store.get_rf_control_mode()
    except AttributeError:
        # Старый track_store без этой функции — считаем, что auto_scan
        return "auto_scan", None


def run_tracker():
    """
    Главный цикл поиска/валидации/трекинга M20 с поддержкой FIXED-режима.
    """
    # Инициализация CC1101
    radio = CC1101(
        spi_id=1,
        sck=PIN_SCK,
        mosi=PIN_MOSI,
        miso=PIN_MISO,
        cs=PIN_CS,
    )

    # Выбор базовой частоты с учётом режима управления
    ctrl_mode, fixed_freq = _get_rf_control_mode()
    if ctrl_mode == "fixed_freq" and fixed_freq:
        base_freq = fixed_freq
        print("Старт в FIXED-режиме на %.3f MHz" % (base_freq / 1e6))
    else:
        base_freq = RF_FREQUENCY_HZ
        print("Старт в AUTO_SCAN-режиме, базовая частота %.3f MHz" % (base_freq / 1e6))

    # Начальное состояние
    state = "scan"  # "scan" / "validate" / "track"
    candidate_freq = None
    candidate_rssi = None
    validate_valid_count = 0
    validate_start_time = None
    last_valid_time = None
    lost_counter = 0
    had_signal = False
    noise_rssi = -100.0

    # Жёсткие параметры логики
    VALID_FRAMES_REQUIRED = 3          # сколько подряд валидных кадров считаем достаточным
    VALIDATE_TIMEOUT_SEC = 20          # сколько максимально ждём валидные кадры в VALIDATE
    TRACK_VALID_TIMEOUT_SEC = 30       # сколько секунд без валидных кадров считаем "зонд потерян"
    BITRATE_M20 = 9600                 # битрейт M20 для GDO0-сэмплирования

    # Уведомим Web UI, что пока ничего не знаем
    track_store.reset_all()
    track_store.set_rf_status(base_freq, None)
    track_store.set_rf_diagnostics(
        noise_rssi_dbm=noise_rssi,
        signal_threshold_dbm=None,
        lost_counter=lost_counter,
        had_signal=had_signal,
        mode="scan",
    )

    # Переводим CC1101 в RX на базовой частоте
    try:
        radio.set_frequency(base_freq)
        radio.flush_rx()
        radio.enter_rx()
    except Exception as e:
        print("Ошибка установки базовой частоты при старте:", e)

    print("Запуск главного цикла трекера (SCAN/VALIDATE/TRACK + FIXED).")

    while True:
        now = time.time()

        # -----------------------------------
        # 1. Проверяем запросы от Web UI
        # -----------------------------------
        if track_store.get_restart_requested():
            print("Запрос перезапуска от Web UI.")

            # Сбрасываем флаг
            track_store.clear_restart_request()

            # Ещё раз читаем режим управления частотой
            ctrl_mode, fixed_freq = _get_rf_control_mode()
            if ctrl_mode == "fixed_freq" and fixed_freq:
                base_freq = fixed_freq
                print("Перезапуск в FIXED-режиме: %.3f MHz" % (base_freq / 1e6))
            else:
                base_freq = RF_FREQUENCY_HZ
                print("Перезапуск в AUTO_SCAN-режиме, базовая %.3f MHz" % (base_freq / 1e6))

            # Сброс внутреннего состояния
            state = "scan"
            candidate_freq = None
            candidate_rssi = None
            validate_valid_count = 0
            validate_start_time = None
            last_valid_time = None
            lost_counter = 0
            had_signal = False
            noise_rssi = -100.0

            # Сброс трека/последнего пакета и RF-диагностики
            track_store.reset_all()
            track_store.set_rf_status(base_freq, None)
            track_store.set_rf_diagnostics(
                noise_rssi_dbm=noise_rssi,
                signal_threshold_dbm=None,
                lost_counter=lost_counter,
                had_signal=had_signal,
                mode="scan",
            )

            # Возвращаем приёмник на базовую частоту
            try:
                radio.set_frequency(base_freq)
                radio.flush_rx()
                radio.enter_rx()
            except Exception as e:
                print("Ошибка при возврате в базовый RX:", e)

            time.sleep(1)
            continue

        # -----------------------------------
        # 2. Основная логика по состояниям
        # -----------------------------------

        # SCAN: либо используем AFC (auto_scan), либо сразу переходим
        # на фиксированную частоту (fixed_freq) без сканирования.
        if state == "scan":
            ctrl_mode, fixed_freq = _get_rf_control_mode()

            # ---------- FIXED-режим: не сканируем диапазон ----------
            if ctrl_mode == "fixed_freq" and fixed_freq:
                candidate_freq = fixed_freq
                print("FIXED: слушаем фиксированную частоту %.3f MHz" % (candidate_freq / 1e6))

                # Перестраховка — выставим частоту явно
                try:
                    radio.set_frequency(candidate_freq)
                    radio.flush_rx()
                    radio.enter_rx()
                except Exception as e:
                    print("Ошибка установки фиксированной частоты:", e)
                    candidate_freq = None
                    candidate_rssi = None
                    time.sleep(1)
                    continue

                # Попробуем сразу оценить RSSI
                try:
                    candidate_rssi = radio.read_rssi_dbm()
                except Exception:
                    candidate_rssi = None

                # Переходим в VALIDATE, дальше логика такая же
                state = "validate"
                validate_valid_count = 0
                validate_start_time = now
                last_valid_time = None
                had_signal = False
                lost_counter = 0

                track_store.set_rf_status(candidate_freq, candidate_rssi)
                track_store.set_rf_diagnostics(
                    noise_rssi_dbm=noise_rssi,
                    signal_threshold_dbm=None,
                    lost_counter=lost_counter,
                    had_signal=had_signal,
                    mode="validate",
                )

                try:
                    time.sleep_ms(200)
                except AttributeError:
                    time.sleep(0.2)
                continue

            # ---------- AUTO_SCAN: используем afc.scan_band ----------
            print("SCAN: auto_scan по диапазону...")
            freq, rssi = afc.scan_band(radio)

            if freq is None:
                # ничего не нашли — обновим диагностику и крутимся дальше
                track_store.set_rf_status(base_freq, None)
                track_store.set_rf_diagnostics(
                    noise_rssi_dbm=noise_rssi,
                    signal_threshold_dbm=None,
                    lost_counter=lost_counter,
                    had_signal=had_signal,
                    mode="scan",
                )
                try:
                    time.sleep_ms(200)
                except AttributeError:
                    time.sleep(0.2)
                continue

            # Нашли частоту-кандидат
            candidate_freq = freq
            candidate_rssi = rssi
            print("SCAN: найдена частота-кандидат %.3f MHz, RSSI=%.1f dBm" %
                  (candidate_freq / 1e6, candidate_rssi))

            # Фиксируемся на этой частоте и переходим в VALIDATE
            try:
                radio.set_frequency(candidate_freq)
                radio.flush_rx()
                radio.enter_rx()
            except Exception as e:
                print("Ошибка установки частоты-кандидата:", e)
                # если не получилось — обратно в SCAN
                candidate_freq = None
                candidate_rssi = None
                time.sleep(1)
                continue

            state = "validate"
            validate_valid_count = 0
            validate_start_time = now
            last_valid_time = None
            had_signal = False
            lost_counter = 0

            # Обновим Web UI
            track_store.set_rf_status(candidate_freq, candidate_rssi)
            track_store.set_rf_diagnostics(
                noise_rssi_dbm=noise_rssi,
                signal_threshold_dbm=candidate_rssi,  # временно порог = RSSI кандидата
                lost_counter=lost_counter,
                had_signal=had_signal,
                mode="validate",
            )

            try:
                time.sleep_ms(200)
            except AttributeError:
                time.sleep(0.2)
            continue

        # VALIDATE / TRACK: работаем на candidate_freq (если она задана)
        if candidate_freq is None:
            # Странное состояние — нет candidate_freq, но мы не в SCAN.
            # На всякий случай возвращаемся в SCAN.
            print("WARN: state=%s, но candidate_freq=None — назад в SCAN." % state)
            state = "scan"
            candidate_rssi = None
            continue

        # Для TRACK считаем таймаут "зонд потерян"
        if state == "track" and last_valid_time is not None:
            if (now - last_valid_time) > TRACK_VALID_TIMEOUT_SEC:
                print("TRACK: слишком долго нет валидных кадров — считаем зонд потерян, назад в SCAN.")
                state = "scan"
                candidate_freq = None
                candidate_rssi = None
                validate_valid_count = 0
                validate_start_time = None
                last_valid_time = None
                lost_counter = 0
                had_signal = False
                noise_rssi = -100.0

                track_store.reset_all()
                track_store.set_rf_status(base_freq, None)
                track_store.set_rf_diagnostics(
                    noise_rssi_dbm=noise_rssi,
                    signal_threshold_dbm=None,
                    lost_counter=lost_counter,
                    had_signal=had_signal,
                    mode="scan",
                )
                try:
                    radio.set_frequency(base_freq)
                    radio.flush_rx()
                    radio.enter_rx()
                except Exception as e:
                    print("Ошибка при возврате в SCAN после потери зонда:", e)
                time.sleep(1)
                continue

        # Пробуем оценить текущий RSSI на candidate_freq
        try:
            cur_rssi = radio.read_rssi_dbm()
        except Exception:
            cur_rssi = None

        # На основе текущего RSSI можно оценить «есть сигнал/нет сигнала»
        if cur_rssi is not None:
            # Обновляем оценку шума (минимум из того, что видели)
            noise_rssi = min(noise_rssi, cur_rssi)
            # Порог — шум + 6 dB
            signal_threshold = noise_rssi + 6.0
        else:
            signal_threshold = None

        # Обновляем в Web UI
        current_freq_for_ui = candidate_freq or base_freq
        track_store.set_rf_status(current_freq_for_ui, cur_rssi)

        mode_label = "validate" if state == "validate" else "tracking"
        track_store.set_rf_diagnostics(
            noise_rssi_dbm=noise_rssi,
            signal_threshold_dbm=signal_threshold,
            lost_counter=lost_counter,
            had_signal=had_signal,
            mode=mode_label,
        )

        # Проверяем, есть ли сигнал выше порога (если можем его оценить)
        weak = True
        if cur_rssi is not None and signal_threshold is not None:
            weak = cur_rssi < signal_threshold

        if weak:
            # Нет сигнала выше порога
            if state == "validate":
                # Проверяем таймаут валидации
                if validate_start_time is not None and (now - validate_start_time) > VALIDATE_TIMEOUT_SEC:
                    print("VALIDATE: частота %.3f MHz не прошла проверку по таймауту — назад в SCAN."
                          % (candidate_freq / 1e6))
                    # Возвращаемся к SCAN
                    state = "scan"
                    candidate_freq = None
                    candidate_rssi = None
                    validate_valid_count = 0
                    validate_start_time = None
                    last_valid_time = None
                    lost_counter = 0
                    had_signal = False
                    noise_rssi = -100.0
                    track_store.reset_all()
                    track_store.set_rf_status(base_freq, None)
                    track_store.set_rf_diagnostics(
                        noise_rssi_dbm=noise_rssi,
                        signal_threshold_dbm=None,
                        lost_counter=lost_counter,
                        had_signal=had_signal,
                        mode="scan",
                    )
                    try:
                        radio.set_frequency(base_freq)
                        radio.flush_rx()
                        radio.enter_rx()
                    except Exception as e:
                        print("Ошибка при возврате в SCAN:", e)
                    time.sleep(1)
                    continue
                # Иначе просто ждём ещё
                try:
                    time.sleep_ms(100)
                except AttributeError:
                    time.sleep(0.1)
                continue
            else:
                # TRACK: просто считаем, что этот цикл был «пустой»
                lost_counter += 1
                try:
                    time.sleep_ms(50)
                except AttributeError:
                    time.sleep(0.05)
                continue

        # Если дошли сюда — есть сигнал выше порога, пробуем вытащить кадр M20
        had_signal = True

        # Попытка приёма куска потока и поиск M20-кадра внутри (битовый режим)
        try:
            # Считываем сырые биты с GDO0, не используя RX FIFO:
            #   - длина с запасом: 2 кадра * 8 бит
            #   - CC1101 уже в RX и демодулирует 2-FSK под M20
            bits = collect_bits_from_gdo0(
                PIN_GDO0,
                bitrate_hz=BITRATE_M20,
                n_bits=M20_FRAME_LEN * 2 * 8,
                timeout_ms=500,
            )

            # Если бит мало — считаем, что попытка не удалась
            if bits is None or len(bits) < M20_FRAME_LEN * 8:
                raise CC1101ReceiveError("not enough bits from GDO0")

            # Преобразуем сырые биты в набор буферов байт для всех 8 фаз (битовых сдвигов)
            byte_buffers = bits_to_bytes(bits)

            data = None
            found = False

            # Для каждого сдвига ищем M20-кадр
            for buf in byte_buffers:
                d, ok = find_m20_in_buffer(buf)
                if ok and d is not None:
                    data = d
                    found = True
                    break

            if not found or data is None:
                raise CC1101ReceiveError("no valid M20 frame found in bitstream")

            # Успешно получили валидный кадр M20
            try:
                latest_rssi = radio.read_rssi_dbm()
            except Exception:
                latest_rssi = cur_rssi

            track_store.set_rf_status(candidate_freq if candidate_freq else base_freq, latest_rssi)

        except CC1101ReceiveError:
            # нет данных — в VALIDATE это считается «пустой попыткой»
            if state == "validate":
                # проверим тайм-аут валидации
                if validate_start_time is not None and (now - validate_start_time) > VALIDATE_TIMEOUT_SEC:
                    print("VALIDATE: на частоте %.3f MHz не удалось получить достаточно валидных кадров — назад в SCAN."
                          % ((candidate_freq if candidate_freq else base_freq) / 1e6))
                    state = "scan"
                    candidate_freq = None
                    candidate_rssi = None
                    lost_counter = 0
                    noise_rssi = -100.0
                    validate_valid_count = 0
                    validate_start_time = None
                    last_valid_time = None
                    had_signal = False
                    time.sleep(1)
            else:
                # В TRACK: просто увеличиваем счётчик «потерянных» циклов
                lost_counter += 1
            continue

        # Если дошли сюда — нашли валидный кадр M20
        last_valid_time = now
        lost_counter = 0

        # Режим VALIDATE: считаем количество подряд валидных кадров
        if state == "validate":
            validate_valid_count += 1
            print("VALIDATE: валидный кадр #%d на частоте %.3f MHz" %
                  (validate_valid_count, candidate_freq / 1e6))

            if validate_valid_count >= VALID_FRAMES_REQUIRED:
                # Частота считается «настоящим M20» — переходим в TRACK
                print("VALIDATE: частота %.3f MHz признана M20 — переходим в TRACK."
                      % (candidate_freq / 1e6))
                state = "track"
                track_store.set_rf_status(candidate_freq, latest_rssi)
                track_store.set_rf_diagnostics(
                    noise_rssi_dbm=noise_rssi,
                    signal_threshold_dbm=signal_threshold,
                    lost_counter=lost_counter,
                    had_signal=had_signal,
                    mode="tracking",
                )

        # В любом случае, если state == "track" — обновляем трек
        if state == "track" and data is not None:
            # Обновляем трек в track_store
            track_store.update_track_from_m20(data)

            # Для Web UI обновим RF-диагностику
            track_store.set_rf_diagnostics(
                noise_rssi_dbm=noise_rssi,
                signal_threshold_dbm=signal_threshold,
                lost_counter=lost_counter,
                had_signal=had_signal,
                mode="tracking",
            )

            # Небольшая задержка, чтобы не забивать ЦП
            try:
                time.sleep_ms(50)
            except AttributeError:
                time.sleep(0.05)
