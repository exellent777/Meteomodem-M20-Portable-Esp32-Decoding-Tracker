# m20_decoder.py — декодер кадров M20
# Совместим с:
#   main.py (использует decode_m20(buffers))
#   gdo0_bitstream.py (даёт список буферов со сдвигами)
#   sonde_data.py (получает полный кадр для парсинга)

import gc

# Примерная синхрометка M20 — здесь достаточно сигнатуры для поиска
SYNC = b"\x55\x55\x55\x56"   # типичный паттерн преамбулы+sync

# Минимальная длина кадра (в байтах), чтобы имело смысл считать CRC.
# С учётом sync, полезной нагрузки и CRC.
MIN_FRAME_LEN = 40

# Диапазон длин кадра, по которому будем искать корректный CRC.
# Мы не знаем точную длину, поэтому перебираем разумное окно.
FRAME_LEN_MIN = 40
FRAME_LEN_MAX = 80

CRC_POLY = 0x1021


def crc16(data: bytes) -> int:
    """CRC-16/X.25 (как в большинстве реализаций M20)."""
    crc = 0xFFFF
    for b in data:
        crc ^= (b << 8)
        for _ in range(8):
            if crc & 0x8000:
                crc = ((crc << 1) ^ CRC_POLY) & 0xFFFF
            else:
                crc = (crc << 1) & 0xFFFF
    return crc


def _find_sync(buf: bytes, start: int = 0) -> int:
    """Поиск sync-последовательности в буфере, начиная с позиции start.
    Возвращает индекс или -1, если не найдено.
    """
    try:
        return buf.index(SYNC, start)
    except ValueError:
        return -1


def _try_decode_from(buf, si):
    """Пробует найти валидный кадр, начиная с позиции sync (si).

    Мы НЕ берём весь хвост до конца буфера, а перебираем возможные длины
    кадра в диапазоне [FRAME_LEN_MIN, FRAME_LEN_MAX] и для каждого варианта
    считаем CRC по data[:-2].
    """
    max_len = min(FRAME_LEN_MAX, len(buf) - si)

    # Слишком короткий хвост — нечего декодировать
    if max_len < MIN_FRAME_LEN:
        return None

    for flen in range(FRAME_LEN_MIN, max_len + 1):
        frame = buf[si : si + flen]
        if len(frame) < MIN_FRAME_LEN:
            continue
        if len(frame) < 4:
            continue

        data = frame[:-2]
        recv_crc = (frame[-2] << 8) | frame[-1]
        calc_crc = crc16(data)

        if calc_crc == recv_crc:
            # Нашли консистентный кадр
            return frame

    return None


def decode_m20(buffers):
    """Принимает список bytes-буферов (разные битовые сдвиги),
    ищет в них sync + валидный CRC на разумной длине кадра.
    Возвращает полный кадр (bytes), начинающийся с sync, либо None.
    """
    if not buffers:
        return None

    try:
        gc.collect()
    except Exception:
        pass

    for bbuf in buffers:
        if not bbuf or len(bbuf) < MIN_FRAME_LEN:
            continue

        # В одном буфере может быть несколько sync — перебираем все.
        pos = 0
        while True:
            si = _find_sync(bbuf, pos)
            if si < 0:
                break

            frame = _try_decode_from(bbuf, si)
            if frame is not None:
                return frame

            # Продолжаем поиск следующей sync внутри того же буфера
            pos = si + 1

    return None
