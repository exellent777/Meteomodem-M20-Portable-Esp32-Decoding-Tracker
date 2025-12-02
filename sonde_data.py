# sonde_data.py — хранение последнего принятого кадра M20 + парсер телеметрии

import time
import struct

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

    def update_from_frame(self, frame_bytes):
        """Получает полный M20 кадр и парсит основные параметры."""

        self.timestamp = time.time()
        self.raw_frame = frame_bytes

        # Нужно минимум 0x1A байт после sync
        if len(frame_bytes) < 0x1A:
            return

        try:
            # M20 данные начинаются сразу после sync (sync ищет decoder)
            payload = frame_bytes[4:]  # пропускаем синк

            self.lat = struct.unpack_from("<f", payload, 0x00)[0]
            self.lon = struct.unpack_from("<f", payload, 0x04)[0]
            self.alt = struct.unpack_from("<f", payload, 0x08)[0]

            self.vspeed = struct.unpack_from("<f", payload, 0x0C)[0]
            self.hspeed = struct.unpack_from("<f", payload, 0x10)[0]

            raw_temp = struct.unpack_from("<h", payload, 0x14)[0]
            self.temp = raw_temp / 100.0

            raw_hum = struct.unpack_from("<H", payload, 0x16)[0]
            self.humidity = raw_hum / 100.0

            raw_bat = struct.unpack_from("<H", payload, 0x18)[0]
            self.battery = raw_bat

        except Exception as e:
            # Мягкая обработка — не ломаем проект
            print("Parser error:", e)

    def as_dict(self):
        """Данные для Web UI."""
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
