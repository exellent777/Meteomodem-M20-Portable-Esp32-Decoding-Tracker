# m20_decoder.py
# Декодер координат Meteomodem M20 (frame type 0x20)
# по структуре M20Frame_20 / m20mod.c (упрощённо — берём только высоту и координаты).

from sonde_data import *
import time

# Байтовая раскладка нашего кадра (как мы читаем его с CC1101):
#   0-2   неиспользуемый префикс/синхро (3 байта)  <-- это то, чего нет в auto_rx
#   3     len   (должен быть 0x45 для M20)
#   4     type  (0x20)
#   11-13 alt[3]      — высота, беззнаковое 24-битное целое (см в M20 → сантиметры)
#   31-34 lat[4]      — широта, signed 32-bit, в 1e-6 градуса
#   35-38 lon[4]      — долгота, signed 32-bit, в 1e-6 градуса
#
# Весь кадр, как мы его читаем, 84 байта.
# Первые 3 байта — наш «хвост» до настоящего frame[0] из m20mod.c.

FRAME_LEN = 84

OFF_TYPE = 4       # type (0x20)
TYPE_M20 = 0x20

OFF_ALT = 11       # alt[0..2]
OFF_LAT = 31       # lat[0..3]
OFF_LON = 35       # lon[0..3]

# Смещение, чтобы получить "канонический" массив как в m20mod.c:
# там frame[0] = framelen, frame[1] = 0x20 и т.д.
HEADER_LEN = 3

# Константы из m20mod.c
STD_FLEN    = 0x45    # ожидаемая длина полезной части M20 (без наших 3 байт префикса)
POS_BLKCHK  = 0x16    # позиция блок-чекса в "каноническом" кадре (пока не используем)
LEN_BLKCHK  = 0x16    # длина блока для blk_checkM10 (пока не используем)


def _s32_be(b: bytes) -> int:
    """Собираем signed 32-bit big-endian."""
    return int.from_bytes(b, "big", signed=True)


# ------------------------- CRC M10 (из m20mod.c) -------------------------


def _update_check_m10(c: int, b: int) -> int:
    """
    Порт функции update_checkM10() из m20mod.c.
    Работает в чистом Python, без внешних зависимостей.
    """
    c1 = c & 0xFF

    # B: немножко крутим байт и XOR-им
    b = ((b >> 1) | ((b & 1) << 7)) & 0xFF
    b ^= (b >> 2) & 0xFF

    # A1
    t6 = ((c >> 0) & 1) ^ ((c >> 2) & 1) ^ ((c >> 4) & 1)
    t7 = ((c >> 1) & 1) ^ ((c >> 3) & 1) ^ ((c >> 5) & 1)
    t = (c & 0x3F) | (t6 << 6) | (t7 << 7)

    # A2
    s = (c >> 7) & 0xFF
    s ^= (s >> 2) & 0xFF

    c0 = b ^ t ^ s
    return ((c1 << 8) | c0) & 0xFFFF


def _check_m10(msg: bytes, length: int) -> int:
    """
    Аналог checkM10(msg, len) из m20mod.c.
    len — количество байт, которые участвуют в расчёте.
    """
    cs = 0
    for i in range(length):
        cs = _update_check_m10(cs, msg[i])
    return cs & 0xFFFF


def _validate_crc(frame: bytes) -> bool:
    """
    Проверка frame check (frame[0x44..0x45]) как в m20mod.c.
    frame — наш полный кадр длиной 84 байта (с 3 байтами префикса).

    Возвращает True, если CRC сходится, иначе False.
    """
    # Сначала проверим общую длину
    if len(frame) < FRAME_LEN:
        return False

    # Сдвигаемся на 3 байта, чтобы получить layout как в m20mod.c
    canon = frame[HEADER_LEN:]

    # Нужны хотя бы STD_FLEN+1 байт (чтобы достать два байта checksum)
    if len(canon) < STD_FLEN + 1:
        return False

    # Опциональная проверка длины в байте canon[0]
    flen = canon[0]
    if flen not in (STD_FLEN, STD_FLEN - 2, STD_FLEN):  # допускаем 0x43 и 0x45
        # Если тут мусор — скорее всего это не M20
        return False

    # Позиция checksum в "каноническом" кадре
    pos_check = STD_FLEN - 1  # 0x44
    if pos_check + 1 >= len(canon):
        return False

    cs1 = (canon[pos_check] << 8) | canon[pos_check + 1]
    cs2 = _check_m10(canon, STD_FLEN - 1)

    return cs1 == cs2


# --------------------------- Основной декодер ----------------------------


def decode_m20_frame(frame: bytes) -> SondeData:
    """
    Декодирование одного кадра M20 (тип 0x20).

    Ожидается полный кадр длиной не менее 84 байт, начиная с наших 3 байт префикса.
    Заполняем:
      * type      — 0x20
      * lat / lon — в градусах (float)
      * alt       — в метрах (float)
      * time      — локальное время приёма (UNIX timestamp)

    При успешном декодировании выставляются биты DATA_POS и DATA_TIME.
    При любой ошибке (не тот тип, плохая CRC, недостаточная длина) возвращается
    пустой SondeData() без исключений.
    """

    d = SondeData()

    try:
        # 1) Базовые проверки
        if not frame:
            return d

        if len(frame) < FRAME_LEN:
            # Кадр обрезан — не пытаемся его декодировать
            return d

        # Проверяем тип кадра в нашей раскладке
        if frame[OFF_TYPE] != TYPE_M20:
            return d

        # 2) Проверяем checksum по алгоритму из m20mod.c
        if not _validate_crc(frame):
            # CRC не сошлась — считаем, что это шум, не зонд
            return d

        # 3) Высота: 3-байтовое беззнаковое целое, big-endian.
        # В M20 это сантиметры → делим на 100.0, чтобы получить метры.
        alt_raw = int.from_bytes(frame[OFF_ALT:OFF_ALT + 3], "big", signed=False)
        d.alt = alt_raw / 100.0

        # 4) Координаты: signed 32-bit big-endian, масштаб 1e-6 градуса
        lat_raw = _s32_be(frame[OFF_LAT:OFF_LAT + 4])
        lon_raw = _s32_be(frame[OFF_LON:OFF_LON + 4])

        d.lat = lat_raw / 1e6
        d.lon = lon_raw / 1e6

        # Тип и флаги
        d.type = TYPE_M20
        d.fields |= DATA_POS

        # 5) Время — ставим текущее локальное (приблизительно время приёма)
        d.time = int(time.time())
        d.fields |= DATA_TIME

    except Exception:
        # Любая ошибка парсинга -> возвращаем то, что есть (обычно пустую структуру)
        return d

    return d
