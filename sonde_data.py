# sonde_data.py — парсер телеметрии M20 (кадр → физические величины)

import time
import struct
import math


class SondeData:
    def __init__(self):
        self.timestamp = None
        self.raw_frame = None

        self.lat = None
        self.lon = None
        self.alt = None
        self.vspeed = None
        self.hspeed = None
        self.temp = None
        self.humidity = None
        self.battery = None

    def reset(self):
        self.__init__()

    def update_from_frame(self, frame_bytes: bytes):
        """Получает полный кадр M20 (69 байт) и парсит основные параметры."""

        self.timestamp = time.time()
        self.raw_frame = frame_bytes

        # ожидаем кадр длиной 0x45
        if frame_bytes is None or len(frame_bytes) < 0x45:
            return

        try:
            f = frame_bytes  # короче именование

            # ----- Высота -----
            # 3 байта, signed, масштаб /100 (м)
            alt_raw = (f[0x08] << 16) | (f[0x09] << 8) | f[0x0A]
            if alt_raw & 0x800000:
                alt_raw -= 0x1000000  # sign-extend 24 бит
            self.alt = alt_raw / 100.0

            # ----- Скорости -----
            # vE, vN, vU — по 2 байта, signed, /100 (м/с)
            vE_raw = struct.unpack(">h", f[0x0B:0x0D])[0]
            vN_raw = struct.unpack(">h", f[0x0D:0x0F])[0]
            vU_raw = struct.unpack(">h", f[0x18:0x1A])[0]

            vE = vE_raw / 100.0
            vN = vN_raw / 100.0
            vU = vU_raw / 100.0

            self.vspeed = vU
            self.hspeed = math.sqrt(vE * vE + vN * vN)

            # ----- Координаты -----
            # lat/lon — 4 байта, signed, big-endian, /1e6 (градусы)
            lat_raw = struct.unpack(">i", f[0x1C:0x20])[0]
            lon_raw = struct.unpack(">i", f[0x20:0x24])[0]

            self.lat = lat_raw / 1e6
            self.lon = lon_raw / 1e6

            # ----- Батарея -----
            # 2 байта, big-endian, мВ (позиция около 0x40)
            bat_raw = struct.unpack(">H", f[0x40:0x42])[0]
            self.battery = bat_raw

            # Температура/влажность: формулы сложные (NTC и т.п.),
            # их можно добавить отдельно по m20mod, чтобы не городить
            # неточную физику сейчас.
            self.temp = None
            self.humidity = None

        except Exception as e:
            print("Sonde parse error:", e)

    def as_dict(self):
        return {
            "timestamp": self.timestamp,
            "lat": self.lat,
            "lon": self.lon,
            "alt": self.alt,
            "vspeed": self.vspeed,
            "hspeed": self.hspeed,
            "temp": self.temp,
            "humidity": self.humidity,
            "battery": self.battery,
            "raw_frame": self.raw_frame,
        }


sonde = SondeData()
