# m20_decoder.py
# Декодер координат Meteomodem M20 (frame type 0x20)
# по структуре M20Frame_20 из m20mod.c / protocol.h:
#  - frame[0] = framelen (stdFLEN = 0x45)
#  - frame[1] = type (0x20)
#  - frame[0x08..0x0A] = высота (24-бит, сантиметры)
#  - frame[0x1C..0x1F] = широта (signed 32-бит, 1e-6 градуса)
#  - frame[0x20..0x23] = долгота (signed 32-бит, 1e-6 градуса)
#
# Мы предполагаем, что в поток из CC1101 уже попадает именно такой массив байт,
# начиная с байта framelen (sync-маркер M20 выброшен до нас).

from sonde_data import *
import time

# ---------------- Константы формата M20 (как в m20mod.c) ----------------

STD_FLEN    = 0x45      # значение frame[0] для обычного M20
FRAME_LEN_MIN = STD_FLEN + 1  # минимум байт, которые нам нужны (с учётом CRC)

# Смещения внутри кадра (относительно frame[0])
OFF_TYPE = 0x01         # тип кадра (0x20)
TYPE_M20 = 0x20

OFF_ALT  = 0x08         # GPS altitude, 3 байта, сантиметры
OFF_LAT  = 0x1C         # GPS latitude, 4 байта, signed, 1e-6 градуса
OFF_LON  = 0x20         # GPS longitude, 4 байта, signed, 1e-6 градуса


def _s32_be(b: bytes) -> int:
    """ signed 32-битное целое из 4 байт big-endian. """
    return int.from_bytes(b, "big", signed=True)


# ---------------- CRC M10/M20 (checkM10 из m20mod.c) ----------------


def _update_check_m10(c: int, b: int) -> int:
    """
    Порт функции update_checkM10() из m20mod.c.
    Полностью повторяет побитовую логику оригинала.
    """
    c1 = c & 0xFF

    # B-шаг: немного крутим байт и XOR-им
    b = ((b >> 1) | ((b & 1) << 7)) & 0xFF
    b ^= (b >> 2) & 0xFF

    # A1
    t6 = (c & 1) ^ ((c >> 2) & 1) ^ ((c >> 4) & 1)
    t7 = ((c >> 1) & 1) ^ ((c >> 3) & 1) ^ ((c >> 5) & 1)
    t = (c & 0x3F) | (t6 << 6) | (t7 << 7)

    # A2
    s = (c >> 7) & 0xFF
    s ^= (s >> 2) & 0xFF

    c0 = (b ^ t ^ s) & 0xFF
    return ((c1 << 8) | c0) & 0xFFFF


def _check_m10(msg: bytes, length: int) -> int:
    """
    Аналог checkM10(msg,len) из m20mod.c.
    len — сколько байт из msg участвуют в расчёте (обычно pos_check).
    """
    cs = 0
    for i in range(length):
        cs = _update_check_m10(cs, msg[i])
    return cs & 0xFFFF


def _validate_crc(frame: bytes) -> bool:
    """
    Проверка frame check в конце кадра M20.
    Ожидаем, что:
      * frame[0] == STD_FLEN (0x45) или STD_FLEN-2 (редкий вариант),
      * два байта checksum лежат в позиции (len-1, len).
    """
    if len(frame) < FRAME_LEN_MIN:
        return False

    flen = frame[0]
    if flen not in (STD_FLEN, STD_FLEN - 2):
        return False

    pos_check = flen - 1  # для 0x45 это 0x44
    if pos_check + 1 >= len(frame):
        return False

    cs1 = (frame[pos_check] << 8) | frame[pos_check + 1]
    cs2 = _check_m10(frame, pos_check)

    return cs1 == cs2


# ---------------- Основной декодер ----------------


def decode_m20_frame(frame: bytes) -> SondeData:
    """
    Декодирование одного кадра M20 (тип 0x20).

    Ожидается минимум 70 байт, начиная с байта frame[0] = framelen (0x45).
    Берём:
      * alt — метры
      * lat / lon — градусы
      * time — локальное время приёма (UNIX timestamp)

    При успешном декодировании выставляются флаги DATA_POS и DATA_TIME.
    При любой ошибке (не тот тип, плохая CRC, мало байт) возвращается
    пустой SondeData() без исключений.
    """

    d = SondeData()

    try:
        if not frame or len(frame) < FRAME_LEN_MIN:
            return d

        # 1) Проверяем тип
        if frame[OFF_TYPE] != TYPE_M20:
            return d

        # 2) Проверяем checksum по алгоритму M10/M20
        if not _validate_crc(frame):
            return d

        # 3) Высота: 3-байтовое беззнаковое целое, big-endian, сантиметры
        alt_raw = int.from_bytes(frame[OFF_ALT:OFF_ALT + 3], "big", signed=False)
        d.alt = alt_raw / 100.0  # -> метры

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
