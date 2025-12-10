# sonde_data.py — исправленная версия по спецификации m20mod.

from struct import unpack
import math

class M20Frame:
    """Структура результата парсинга M20."""
    def __init__(self):
        self.tow = None
        self.week = None
        self.lat = None
        self.lon = None
        self.alt = None
        self.velE = None
        self.velN = None
        self.velU = None
        self.serial = None
        self.batt_v = None


def _read_s16(b, ofs):
    return unpack(">h", b[ofs:ofs+2])[0]


def _read_u16(b, ofs):
    return unpack(">H", b[ofs:ofs+2])[0]


def parse_m20(frame: bytes):
    """
    Полностью согласовано с m20mod.c.
    Ожидается байтовый массив УЖЕ прошедший CHECKM10 и выравнивание фаз.
    """

    L = frame[0]
    if L < 0x40:
        # слишком короткий кадр — m20mod тоже игнорирует
        return None

    # ------------------------------
    #  Парсинг по смещениям M20
    # ------------------------------

    # TOW (Time of Week), секунды + дробная часть
    tow_i = _read_u16(frame, 1)       # integer seconds
    tow_f = frame[3] / 256.0          # fractional (0..255)
    tow = tow_i + tow_f

    # GPS Week
    gps_week = _read_u16(frame, 4)

    # широта/долгота (формат — int16, масштаб 1e-4 градуса)
    lat = _read_s16(frame, 6) * 1e-4
    lon = _read_s16(frame, 8) * 1e-4

    # высота (метры)
    alt = _read_s16(frame, 10)

    # скорости ENU (метры/с)
    velE = _read_s16(frame, 12) * 0.01
    velN = _read_s16(frame, 14) * 0.01
    velU = _read_s16(frame, 16) * 0.01

    # серийный номер
    serial = _read_u16(frame, 18)

    # батарея
    raw_batt = frame[20]
    # Модельная конверсия к В:
    batt_v = raw_batt * 0.0183  # калибровка по sondes/auto_rx

    # --------------------------------------
    #  Sanity-checks как в m20mod
    # --------------------------------------

    # валидность неделей GPS
    if gps_week < 1500 or gps_week > 3500:
        return None

    # координаты должны быть в естественном диапазоне
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None

    # высота адекватная
    if abs(alt) > 40000:
        return None

    # скорости <= 150 м/с
    if abs(velE) > 150 or abs(velN) > 150 or abs(velU) > 150:
        return None

    # ------------------------------
    #  Формируем объект результата
    # ------------------------------
    out = M20Frame()
    out.tow = tow
    out.week = gps_week
    out.lat = lat
    out.lon = lon
    out.alt = alt
    out.velE = velE
    out.velN = velN
    out.velU = velU
    out.serial = serial
    out.batt_v = batt_v

    return out
