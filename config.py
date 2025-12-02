# config.py — базовые настройки проекта M20 Tracker

# ---- CC1101 SPI pins (ESP32-C3) ----
CC1101_SCK  = 6   # GPIO6  -> SCK
CC1101_MOSI = 7   # GPIO7  -> MOSI
CC1101_MISO = 5   # GPIO5  -> MISO
CC1101_CS   = 4   # GPIO4  -> CSN
CC1101_GDO0 = 3   # GPIO3  -> GDO0 (data output)

# ---- Web server ----
HTTP_PORT = 80

# ---- Радионастройки ----
RF_FREQUENCY_HZ = 405400000   # дефолт при fixed mode

# ---- Oversampling ----
OVERSAMPLE = 6                # оптимальное значение
PREAMBLE_BITS_FOR_PLL = 80    # сколько бит анализировать для мини-PLL

# ---- Логирование ----
ENABLE_RAW_LOG = False        # сырые логи отключены (экономия памяти)
