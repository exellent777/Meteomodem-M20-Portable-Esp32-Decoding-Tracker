# config.py — базовые настройки проекта M20 Tracker (m20mod-style)

# ---- CC1101 SPI pins (ESP32-C3) ----
CC1101_SCK  = 6
CC1101_MOSI = 7
CC1101_MISO = 5
CC1101_CS   = 4
CC1101_GDO0 = 3

# ---- Web server ----
HTTP_PORT = 80

# ---- Радионастройки для M20 ----
M20_BITRATE        = 9600          # бод
M20_BW_KHZ         = 100           # полоса RX
M20_DEVIATION_KHZ  = 40            # девиация FSK

# Sync для RAW-битового потока
M20_SYNC_BYTES = b"\x99\x99\x4C\x99"

# ---- Параметры сканирования ----
SCAN_START_HZ = 404000000
SCAN_END_HZ   = 406000000
SCAN_STEP_HZ  = 50000

SCAN_DWELL_MS    = 120          # задержка на частоте при SCAN
TRACK_TIMEOUT_MS = 4000        # потеря сигнала = возврат в SCAN

# ---- Детектор сигнала ----
RSSI_THRESHOLD = -110
