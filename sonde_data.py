# sonde_data.py
# Структура данных для хранения информации о метеозонде.
# Используется декодером, трекером и веб-интерфейсом.

DATA_NONE   = 0x00
DATA_PTU    = 0x01
DATA_TIME   = 0x02
DATA_POS    = 0x04
DATA_SPEED  = 0x08
DATA_SERIAL = 0x10


class SondeData:
    def __init__(self):
        self.fields = DATA_NONE

        # Позиция
        self.lat = None
        self.lon = None
        self.alt = None

        # Время пакета (или локальное время)
        self.time = None

        # Скорость/курс/вертикальная скорость — используем, если добавим позже
        self.speed = None
        self.heading = None
        self.climb = None

        # Серийный номер (если нужен)
        self.serial = None

    def as_dict(self):
        """Удобный вывод для JSON, отладки и веб-интерфейса."""
        return {
            "fields": self.fields,
            "lat": self.lat,
            "lon": self.lon,
            "alt": self.alt,
            "time": self.time,
            "speed": self.speed,
            "heading": self.heading,
            "climb": self.climb,
            "serial": self.serial,
        }
