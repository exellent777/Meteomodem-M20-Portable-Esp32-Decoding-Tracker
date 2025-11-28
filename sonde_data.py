# sonde_data.py
# Структура данных для метeoзонда M20 (или совместимого формата).
#
# Храним:
#   - type: тип фрейма (0x20 = позиционный)
#   - fields: битовая маска присутствующих данных
#   - time: unix timestamp (float)
#   - lat, lon, alt
#   - дополнительные служебные поля при необходимости

# Битовая маска для data.fields
# DATA_POS  - флаг "в пакете есть координаты"
# DATA_TIME - флаг "есть метка времени"
DATA_POS  = 0x04
DATA_TIME = 0x08


class SondeData:
    """
    Простая структура для хранения данных декодированного пакета метеозонда.
    """

    def __init__(self):
        self.type = None
        self.fields = 0

        self.time = None   # UTC timestamp
        self.lat = None
        self.lon = None
        self.alt = None

    def __repr__(self):
        return (
            f"SondeData(type={self.type}, fields=0x{self.fields:02X}, "
            f"time={self.time}, lat={self.lat}, lon={self.lon}, alt={self.alt})"
        )
