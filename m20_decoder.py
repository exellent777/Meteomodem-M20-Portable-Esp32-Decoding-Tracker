# m20_decoder.py
# Декодер координат Meteomodem M20 (frame type 0x20)
# по структуре M20Frame_20 из protocol.h.

from sonde_data import *
import time

# Байтовая раскладка M20Frame_20 (по protocol.h):
#   0-2   sync_mark[3]
#   3     len
#   4     type (0x20)
#   5-6   rh_counts[2]
#   7-8   adc_temp[2]
#   9-10  adc_rh_temp[2]
#   11-13 alt[3]
#   14-15 dlat[2]
#   16-17 dlon[2]
#   18-20 time[3]
#   21-23 sn[3]
#   24    seq
#   25-26 BlkChk[2]
#   27-28 dalt[2]
#   29-30 week[2]
#   31-34 lat[4]
#   35-38 lon[4]
#   39-49 unk1[11]
#   50-51 rh_ref[2]
#   52-83 data[32]
#
# Суммарно: 84 байта.

FRAME_LEN = 84

OFF_TYPE   = 4      # type (0x20)
TYPE_M20   = 0x20

OFF_ALT    = 11     # alt[0..2]
OFF_LAT    = 31     # lat[0..3]
OFF_LON    = 35     # lon[0..3]


def _s32_be(b: bytes) -> int:
    """Собираем signed 32-bit big-endian."""
    return int.from_bytes(b, "big", signed=True)


def decode_m20_frame(frame: bytes) -> SondeData:
    """
    frame — один декодированный кадр M20 (M20Frame_20),
    начиная с sync_mark[0] (байт 0), len[3], type[4], далее поля.

    Возвращает SondeData с заполненными lat / lon / alt.
    Если кадр не M20 (type != 0x20) или битый — возвращает пустой SondeData.
    """
    d = SondeData()

    # 1) Проверяем длину кадра
    if len(frame) != FRAME_LEN:
        # Неправильный размер – не трогаем
        return d

    # 2) Проверяем тип
    ftype = frame[OFF_TYPE]
    if ftype != TYPE_M20:
        # Это не data-кадр M20 (0x20)
        return d

    try:
        # 3) Высота: 3 байта, беззнаковое, делим на 1e2 (как в m20_20_alt в C)
        alt_raw = int.from_bytes(
            frame[OFF_ALT:OFF_ALT + 3],
            "big",
            signed=False
        )
        d.alt = alt_raw / 1e2  # метры

        # 4) Широта и долгота: int32 big-endian, делим на 1e6 (m20_20_lat/lon)
        lat_raw = _s32_be(frame[OFF_LAT:OFF_LAT + 4])
        lon_raw = _s32_be(frame[OFF_LON:OFF_LON + 4])

        d.lat = lat_raw / 1e6
        d.lon = lon_raw / 1e6

        d.fields |= DATA_POS

        # 5) Время — для простоты ставим текущее локальное,
        # чтобы не было None (чисто для веб-интерфейса/лога)
        d.time = int(time.time())
        d.fields |= DATA_TIME

    except Exception:
        # Любая ошибка парсинга -> пустая структура
        return d

    return d
