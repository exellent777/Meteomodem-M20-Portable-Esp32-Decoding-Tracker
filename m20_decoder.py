# m20_decoder.py — декодер кадров M20 по мотивам m20mod.c
# Совместим с:
#   main.py (вызывает decode_m20(buffers))
#   gdo0_bitstream.py (даёт список байтовых буферов разных битовых фаз)
#   sonde_data.py (получает полный кадр для парсинга)

import gc

TYPE_M20 = 0x20  # тип кадра M20


# -----------------------------
# Специальный checksum M10/M20
# (update_checkM10 / checkM10 из m20mod.c)
# -----------------------------
def update_checkM10(c, b):
    """
    Порт функции update_checkM10(int c, ui8_t b) из m20mod.c.
    c: 16-битное состояние (int)
    b: байт (0..255)
    """
    c &= 0xFFFF
    b &= 0xFF

    c1 = c & 0xFF

    # B
    b = ((b >> 1) | ((b & 1) << 7)) & 0xFF
    b ^= (b >> 2) & 0xFF

    # A1
    t6 = (c & 1) ^ ((c >> 2) & 1) ^ ((c >> 4) & 1)
    t7 = ((c >> 1) & 1) ^ ((c >> 3) & 1) ^ ((c >> 5) & 1)
    t = (c & 0x3F) | (t6 << 6) | (t7 << 7)

    # A2
    s = (c >> 7) & 0xFF
    s ^= (s >> 2) & 0xFF

    c0 = b ^ t ^ s
    return ((c1 << 8) | c0) & 0xFFFF


def checkM10(data, length):
    """
    Порт функции checkM10(ui8_t *msg, int len):
        cs = 0;
        for (i=0; i<len; i++)
            cs = update_checkM10(cs, msg[i]);
        return cs & 0xFFFF;
    """
    cs = 0
    for i in range(length):
        cs = update_checkM10(cs, data[i])
    return cs & 0xFFFF


# -----------------------------
# Поиск кадра в одном буфере
# -----------------------------
def _find_frame_in_buffer(buf):
    """
    Ищет в buf корректный кадр M20:
    - первый байт = длина flen (ожидаем 0x45 или 0x43)
    - второй байт = тип 0x20
    - checksum по алгоритму M10/M20 совпадает
    Возвращает frame (bytes) либо None.
    """
    n = len(buf)
    if n < 16:
        return None

    # Перебираем все возможные позиции начала кадра
    for start in range(0, n - 6):
        flen = buf[start]

        # Разумные рамки длины: M20 использует 0x45 (иногда 0x43)
        if flen not in (0x45, 0x43):
            continue

        # В буфере должен быть как минимум flen+1 байт (данные + 2 байта chk)
        frame_total_len = flen + 1  # как в m20mod: len(block+chk16) = flen
        if start + frame_total_len > n:
            continue

        # Проверяем тип
        ftype = buf[start + 1]
        if ftype != TYPE_M20:
            continue

        frame = buf[start : start + frame_total_len]

        # Позиция checksum: pos_check = flen-1 (как в m20mod)
        pos_check = flen - 1
        if pos_check + 1 >= len(frame):
            continue

        recv_crc = (frame[pos_check] << 8) | frame[pos_check + 1]
        calc_crc = checkM10(frame, pos_check)

        if recv_crc == calc_crc:
            return frame

    return None


# -----------------------------
# Внешний интерфейс
# -----------------------------
def decode_m20(buffers):
    """
    Принимает список bytes-буферов (разные битовые сдвиги),
    ищет в них кадр M20 по параметрам (len/type) и checksum.
    Возвращает полный кадр (bytes) либо None.
    """
    if not buffers:
        return None

    try:
        gc.collect()
    except Exception:
        pass

    for bbuf in buffers:
        if not bbuf:
            continue
        frame = _find_frame_in_buffer(bbuf)
        if frame is not None:
            return frame

    return None
