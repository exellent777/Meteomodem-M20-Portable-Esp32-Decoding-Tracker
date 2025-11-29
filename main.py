#
# Главный цикл M20 tracker c AFC:
#   - режим SCAN: непрерывно сканируем 404.5–406.5 MHz (afc.scan_band),
#                 пока не найдём частоту с сигналом выше порога;
#   - режим VALIDATE: фиксируемся на частоте-кандидате и проверяем,
#       что есть несколько подряд валидных M20-кадров (CRC/структура);
#       только после этого считаем частоту «настоящим M20»;
#   - режим TRACK: в режиме трекинга принимаем кадры, декодируем M20, ведём трек;
#   - если долго нет валидных кадров (даже при наличии RSSI) — считаем зонд
#     потерянным и снова переходим в SCAN;
#   - из Web UI кнопка «Перезапустить поиск» также переводит в режим SCAN.

import time
from cc1101 import CC1101, CC1101ReceiveError
from m20_decoder import decode_m20_frame
from sonde_data import DATA_POS
import track_store
import afc
from config import PIN_SCK, PIN_MOSI, PIN_MISO, PIN_CS, PIN_GDO0, RF_FREQUENCY_HZ, M20_FRAME_LEN


def find_m20_in_buffer(buf: bytes):
    """
    Скользящий поиск валидного кадра M20 внутри произвольного буфера байтов.

    Идём по всем сдвигам 0..len(buf)-M20_FRAME_LEN, на каждом:
      - берём окно длиной M20_FRAME_LEN
      - прогоняем через decode_m20_frame()
      - если CRC/структура ок (DATA_POS выставлен) — считаем кадр валидным.

    Возвращает:
        (data, True)  — если найден валидный кадр;
        (None, False) — если в буфере ничего похожего на M20 нет.
    """
    if not buf or len(buf) < M20_FRAME_LEN:
        return None, False

    limit = len(buf) - M20_FRAME_LEN + 1

    for offset in range(limit):
        frame = buf[offset:offset + M20_FRAME_LEN]
        data = decode_m20_frame(frame)
        if data is not None and bool(data.fields & DATA_POS):
            return data, True

    return None, False


def run_tracker():
    # Инициализация CC1101
    radio = CC1101(
        sck=PIN_SCK,
        mosi=PIN_MOSI,
        miso=PIN_MISO,
        cs=PIN_CS,
        gdo0=PIN_GDO0,
    )
    print("CC1101 инициализирован.")

    # Базовая (резервная) частота — то, что в config.RF_FREQUENCY_HZ
    base_freq = RF_FREQUENCY_HZ

    # Параметры трекинга / валидации
    LOST_LIMIT = 40              # сколько слабых/пустых циклов подряд терпим в TRACK
    NOISE_ALPHA = 0.01           # скорость обновления оценки шума
    RSSI_MARGIN_DB = 8.0         # на сколько dB сигнал должен быть выше шума

    VALID_FRAMES_REQUIRED = 3    # сколько подряд валидных кадров нужно для признания частоты «M20»
    VALIDATE_TIMEOUT_SEC = 10    # максимум времени в режиме VALIDATE на одну частоту
    TRACK_VALID_TIMEOUT_SEC = 30 # если столько секунд нет валидных кадров — уходим обратно в SCAN

    noise_rssi = -100.0          # начальная оценка шумового уровня
    lost_counter = 0
    had_signal = False           # был ли когда-то уверенный сигнал в текущей сессии TRACK
    mode = "init"                # текущий режим приёмника для веб-интерфейса
    state = "scan"               # "scan" / "validate" / "track"

    # Для жёсткого критерия по CRC
    validate_valid_count = 0     # сколько валидных кадров подряд увидели на частоте-кандидате
    validate_start_time = None   # когда начали проверять эту частоту

    # Для тайм-аута по отсутствию валидных кадров в TRACK
    last_valid_time = None       # время последнего валидного M20-кадра

    # Текущая частота-кандидат (в режиме VALIDATE) и её RSSI
    candidate_freq = None
    candidate_rssi = None

    print("Старт: вхожу в режим сканирования (state = scan).")

    while True:
        # -------------------------------
        # Обработка запроса «перезапустить поиск» из Web UI
        # -------------------------------
        if track_store.need_restart:
            print("Запрос перезапуска от Web UI: перехожу в режим SCAN.")
            track_store.clear_restart()
            lost_counter = 0
            noise_rssi = -100.0
            had_signal = False
            mode = "init"
            state = "scan"
            validate_valid_count = 0
            validate_start_time = None
            last_valid_time = None
            candidate_freq = None
            candidate_rssi = None
            try:
                radio.flush_rx()
                radio.enter_rx()
            except Exception:
                pass
            track_store.set_rf_diagnostics(
                noise_rssi_dbm=None,
                signal_threshold_dbm=None,
                lost_counter=0,
                had_signal=False,
                mode="init",
            )
            # сразу переходим к следующей итерации, где state="scan"
            continue

        # ===============================
        # РЕЖИМ SCAN: непрерывно сканируем диапазон,
        # пока не найдём частоту-кандидат по RSSI
        # ===============================
        if state == "scan":
            # Обновим режим для веб-морды
            track_store.set_rf_diagnostics(
                noise_rssi_dbm=None,
                signal_threshold_dbm=None,
                lost_counter=0,
                had_signal=had_signal,
                mode="search",
            )

            best_freq, best_rssi = afc.scan_band(radio)

            if best_freq is None:
                # В диапазоне ничего убедительного не нашли — продолжаем скан
                time.sleep_ms(200)
                continue

            # Нашли максимум — переходим в режим VALIDATE для проверки CRC
            candidate_freq = best_freq
            candidate_rssi = best_rssi
            validate_valid_count = 0
            validate_start_time = time.time()
            last_valid_time = None
            base_freq = candidate_freq

            print("Кандидат на M20: %.3f MHz (RSSI ≈ %.1f dBm), перехожу в VALIDATE." %
                  (candidate_freq / 1e6, candidate_rssi))

            try:
                radio.set_frequency(candidate_freq)
                radio.enter_rx()
            except Exception as e:
                print("Ошибка установки частоты для VALIDATE:", e)
                # если что-то пошло не так, вернёмся в scan
                state = "scan"
                time.sleep_ms(200)
                continue

            lost_counter = 0
            noise_rssi = -100.0
            had_signal = False
            mode = "search"

            track_store.set_rf_status(candidate_freq, candidate_rssi)
            track_store.set_rf_diagnostics(
                noise_rssi_dbm=noise_rssi,
                signal_threshold_dbm=None,
                lost_counter=lost_counter,
                had_signal=had_signal,
                mode=mode,
            )

            state = "validate"
            continue

        # ===============================
        # РЕЖИМЫ VALIDATE и TRACK:
        #   - сидим на base_freq, меряем RSSI, принимаем кадры
        #   - в VALIDATE считаем валидные кадры подряд
        #   - в TRACK ведём трек и следим за тайм-аутом по валидным кадрам
        # ===============================
        # Текущий RSSI и обновление оценки шума
        try:
            cur_rssi = radio.read_rssi_dbm()
        except Exception:
            cur_rssi = None

        weak = True  # по умолчанию считаем, что сигнала нет
        signal_threshold = None

        if cur_rssi is not None:
            # обновляем оценку шумового фона, когда явно «тишина»
            if cur_rssi < -95.0:
                noise_rssi = (1.0 - NOISE_ALPHA) * noise_rssi + NOISE_ALPHA * cur_rssi

            # порог "есть сигнал" = шум + запас по dB
            signal_threshold = noise_rssi + RSSI_MARGIN_DB
            if cur_rssi > signal_threshold:
                weak = False

        # Обновляем базовый статус радиочасти для Web UI
        track_store.set_rf_status(base_freq, cur_rssi)

        # Логика "сигнал потерян / слабый" по RSSI
        if weak:
            lost_counter += 1
        else:
            lost_counter = max(0, lost_counter - 1)

        # Определяем режим приёмника для отображения
        if lost_counter > LOST_LIMIT:
            mode = "lost"
        elif had_signal:
            mode = "tracking"
        else:
            mode = "search"

        # Обновляем диагностическую информацию для Web UI
        track_store.set_rf_diagnostics(
            noise_rssi_dbm=noise_rssi,
            signal_threshold_dbm=signal_threshold,
            lost_counter=lost_counter,
            had_signal=had_signal,
            mode=mode,
        )

        now = time.time()

        # Если мы уже в TRACK и давно не видели валидных кадров — уходим в SCAN,
        # даже если RSSI ещё что-то показывает.
        if state == "track" and last_valid_time is not None:
            if (now - last_valid_time) > TRACK_VALID_TIMEOUT_SEC:
                print("Давно не было валидных M20-кадров (%.0f с) на частоте %.3f MHz — возвращаюсь в SCAN." %
                      (now - last_valid_time, base_freq / 1e6))
                had_signal = False
                state = "scan"
                lost_counter = 0
                noise_rssi = -100.0
                validate_valid_count = 0
                validate_start_time = None
                last_valid_time = None
                time.sleep(1)
                continue

        # Если по RSSI всё совсем плохо — тоже считаем, что частота не годится
        if lost_counter > LOST_LIMIT:
            if state == "track" and had_signal:
                print("Зонд потерян по RSSI на частоте %.3f MHz." % (base_freq / 1e6))
            else:
                print("На частоте %.3f MHz ничего уверенного не найдено, возвращаюсь к скану." %
                      (base_freq / 1e6))

            had_signal = False
            state = "scan"
            lost_counter = 0
            noise_rssi = -100.0
            validate_valid_count = 0
            validate_start_time = None
            last_valid_time = None
            time.sleep(1)
            continue

        if not weak:
            # Сигнал видим, но это ещё не значит, что это M20
            had_signal = True

        # -------------------------------
        # Попытка приёма куска потока и поиск M20-кадра внутри
        # -------------------------------
        try:
            # читаем немного больше, чем один кадр: 2 * M20_FRAME_LEN
            buf = radio.receive_frame(expected_len=M20_FRAME_LEN * 2)
            # после приёма обновим RSSI по факту
            try:
                latest_rssi = radio.read_rssi_dbm()
            except Exception:
                latest_rssi = cur_rssi
            track_store.set_rf_status(base_freq, latest_rssi)

        except CC1101ReceiveError:
            # нет данных — в VALIDATE это считается «пустой попыткой»
            if state == "validate":
                # проверим тайм-аут валидации
                if validate_start_time is not None and (now - validate_start_time) > VALIDATE_TIMEOUT_SEC:
                    print("На частоте %.3f MHz не удалось получить достаточно валидных кадров — назад в SCAN." %
                          (base_freq / 1e6))
                    state = "scan"
                    lost_counter = 0
                    noise_rssi = -100.0
                    validate_valid_count = 0
                    validate_start_time = None
                    last_valid_time = None
                    had_signal = False
                    time.sleep(1)
            else:
                lost_counter += 1
            continue
        except Exception as e:
            print("Ошибка приёма:", e)
            if state == "validate":
                if validate_start_time is not None and (now - validate_start_time) > VALIDATE_TIMEOUT_SEC:
                    print("На частоте %.3f MHz постоянно ошибки приёма — назад в SCAN." %
                          (base_freq / 1e6))
                    state = "scan"
                    lost_counter = 0
                    noise_rssi = -100.0
                    validate_valid_count = 0
                    validate_start_time = None
                    last_valid_time = None
                    had_signal = False
                    time.sleep(1)
            else:
                lost_counter += 1
            continue

        # -------------------------------
        # ДЕКОДИРОВАНИЕ M20 (поиск внутри буфера)
        # -------------------------------
        data, is_valid = find_m20_in_buffer(buf)

        if state == "validate":
            # Валидация частоты-кандидата: считаем только кадры с валидной CRC/структурой
            if is_valid:
                validate_valid_count += 1
                last_valid_time = now
                print("VALIDATE: валидный M20-кадр #%d на %.3f MHz" %
                      (validate_valid_count, base_freq / 1e6))
            else:
                # Как только прилетел кусок без валидного кадра — сбиваем серию
                if validate_valid_count > 0:
                    print("VALIDATE: нет валидного кадра в буфере, сбрасываю серию (freq=%.3f MHz)." %
                          (base_freq / 1e6))
                validate_valid_count = 0

            # Проверяем, набрали ли нужное количество подряд
            if validate_valid_count >= VALID_FRAMES_REQUIRED:
                print("Частота %.3f MHz подтверждена как M20 (%d подряд валидных кадров). Переход в TRACK." %
                      (base_freq / 1e6, validate_valid_count))
                state = "track"
                had_signal = True
                lost_counter = 0
                mode = "tracking"
                # Диагностика: сразу обновим статус
                track_store.set_rf_diagnostics(
                    noise_rssi_dbm=noise_rssi,
                    signal_threshold_dbm=signal_threshold,
                    lost_counter=lost_counter,
                    had_signal=had_signal,
                    mode=mode,
                )
                continue

            # Если истёк тайм-аут валидации — считаем, что это не зонд
            if validate_start_time is not None and (now - validate_start_time) > VALIDATE_TIMEOUT_SEC:
                print("VALIDATE: не удалось подтвердить частоту %.3f MHz как M20 за %.0f с — назад в SCAN." %
                      (base_freq / 1e6, now - validate_start_time))
                state = "scan"
                lost_counter = 0
                noise_rssi = -100.0
                validate_valid_count = 0
                validate_start_time = None
                last_valid_time = None
                had_signal = False
                time.sleep(1)
            # В режиме VALIDATE пока не сохраняем координаты и не ведём трек,
            # просто крутимся и считаем серию.
            continue

        # ---- Здесь state == "track" ----
        if not is_valid or data is None:
            # в этом буфере нет валидного кадра — считаем промахом
            lost_counter += 1
            continue

        # Валидный пакет в режиме TRACK
        lost_counter = 0
        had_signal = True
        mode = "tracking"
        last_valid_time = now

        print("TRACK: получена точка: lat=%.5f lon=%.5f alt=%.1f" %
              (data.lat, data.lon, data.alt))

        track_store.update_latest(data)
        track_store.append_track(data)

        # Обновим диагностику ещё раз с актуальными значениями
        track_store.set_rf_diagnostics(
            noise_rssi_dbm=noise_rssi,
            signal_threshold_dbm=signal_threshold,
            lost_counter=lost_counter,
            had_signal=had_signal,
            mode=mode,
        )

        # Небольшая пауза, чтобы не грузить CPU
        time.sleep_ms(30)


if __name__ == "__main__":
    run_tracker()
