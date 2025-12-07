# m20_decoder.py — декодер кадров M20 для M20 Tracker
#
# Вход:
#   decode_m20(buffers)
#     buffers — список байтовых кадров-кандидатов (bytes), как возвращает
#               gdo0_bitstream.bits_to_bytes().
#
# Задача:
#   - проверить базовую сигнатуру (0x45 0x20)
#   - посчитать CRC так же, как в M10/M20-декодере (update_checkM10M20 / crc_M10M20)
#   - использовать длину кадра из первого байта (frame[0] + 1)
#   - вернуть первый валидный кадр (bytes) или None.

import gc

TYPE_M20 = 0x20      # тип кадра для M20
MIN_LEN  = 40        # минимальная разумная длина (байт)
MAX_LEN  = 100       # чтобы отсеивать откровенный мусор


def update_checkM10M20(c, b):
    """
    Порт функции update_checkM10M20 из M10M20.cpp.

    """
    c &= 0xFFFF
    b &= 0xFF

    c1 = c & 0xFF

    # B
    b = ((b >> 1) | ((b & 0x01) << 7)) & 0xFF
    b ^= (b >> 2) & 0xFF

    # A1
    t6 = ((c >> 0) & 1) ^ ((c >> 2) & 1) ^ ((c >> 4) & 1)
    t7 = ((c >> 1) & 1) ^ ((c >> 3) & 1) ^ ((c >> 5) & 1)
    t = (c & 0x3F) | (t6 << 6) | (t7 << 7)

    # A2
    s = (c >> 7) & 0xFF
    s ^= (s >> 2) & 0xFF

    c0 = (b ^ t ^ s) & 0xFF

    return ((c1 << 8) | c0) & 0xFFFF


def crc_M10M20(buf, length):
    """
    crc_M10M20(int len, uint8_t *msg)

    uint16_t cs = 0;
    for (int i = 0; i < len; i++) {
        cs = update_checkM10M20(cs, msg[i]);
    }
    return cs;
    """
    cs = 0
    if length <= 0:
        return 0

    if length > len(buf):
        length = len(buf)

    for i in range(length):
        cs = update_checkM10M20(cs, buf[i])

    return cs & 0xFFFF


def checkM10M20crc(crcpos, frame):
    """
    checkM10M20crc(int crcpos, uint8_t *msg):

        uint16_t cs, cs1;
        cs = crc_M10M20(crcpos, msg);
        cs1 = (msg[crcpos] << 8) | msg[crcpos+1];
        return (cs1 == cs);
    """
    # crcpos — позиция старшего байта CRC
    if crcpos < 0:
        return False
    if crcpos + 1 >= len(frame):
        return False

    cs = crc_M10M20(frame, crcpos)
    cs1 = ((frame[crcpos] << 8) | frame[crcpos + 1]) & 0xFFFF
    return cs1 == cs


def _frame_looks_like_m20(frame):
    """
    Быстрая фильтрация мусора до CRC.

    M20:
      frame[0] ≈ длина (0x45 для основной посылки)
      frame[1] = 0x20 (тип кадра)
    """
    if not frame or len(frame) < 4:
        return False

    # Тип кадра
    if frame[1] != TYPE_M20:
        return False

    fl = frame[0]
    # Не даём длине выходить за пределы разумного
    if fl < MIN_LEN or fl > MAX_LEN:
        return False

    return True


def decode_m20(buffers):
    """
    Перебирает все кадры-кандидаты и ищет первый с корректной M10/M20-CRC.

    Логика максимально близка к decodeframeM20 в M10M20.cpp:
      - фактическая длина берётся как (frame[0] + 1),
      - CRC считается по байтам 0 .. (frl-3),
      - сравнение идёт с frame[frl-2], frame[frl-1].

    Возвращает bytes(кадр) или None.
    """
    gc.collect()

    if not buffers:
        return None

    for frame in buffers:
        if not frame:
            continue

        f = bytes(frame)

        if not _frame_looks_like_m20(f):
            continue

        # Фактическая длина кадра (как в TTGO: frl = data[0] + 1)
        frl = f[0] + 1
        if frl > len(f):
            frl = len(f)

        crcpos = frl - 2
        if crcpos <= 0:
            continue

        if checkM10M20crc(crcpos, f):
            # Возвращаем кадр, обрезанный до фактической длины
            return f[:frl]

    return None
