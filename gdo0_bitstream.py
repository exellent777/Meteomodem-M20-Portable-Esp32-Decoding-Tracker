# gdo0_bitstream.py
# Чтение сырых битов с выхода GDO0 CC1101 и превращение их в байты.
#
# Расчёт простой:
#   - CC1101 демодулирует 2-FSK и выдаёт "цифровой" поток на GDO0 (IOCFG0 сконфигурирован как асинхронный data out)
#   - ESP32-C3/S3 по таймеру с частотой ≈ битрейта (обычно ~9.6 kbit/s для M20) семплит GDO0.
#   - Полученный массив 0/1 собираем в байты с разными битовыми сдвигами.

from machine import Pin, Timer
import time


class GDO0BitCollector:
    """Сборщик битов с GDO0 по аппаратному таймеру.

    Таймер дёргается с частотой bitrate_hz, на каждом тике читаем pin.value()
    и записываем 0/1 в буфер. Используется для приёма «сырых» бит M20.
    """

    def __init__(self, pin_id, bitrate_hz=9600, timer_id=1):
        self.pin = Pin(pin_id, Pin.IN)
        self.timer = Timer(timer_id)
        self.bitrate = bitrate_hz

        self.buf = None
        self.n_bits = 0
        self.idx = 0

    def _cb(self, t):
        """callback таймера: максимально короткий, только чтение пина и запись в буфер"""
        i = self.idx
        if i >= self.n_bits:
            # Уже всё набрали — просто выходим. Остановка таймера произойдёт снаружи.
            return

        v = self.pin.value()
        # safety: приводим к 0/1
        self.buf[i] = 1 if v else 0
        self.idx = i + 1

    def collect(self, n_bits, timeout_ms=300):
        """Синхронно собирает n_bits битов с GDO0 (или меньше, если таймаут).
        Возвращает bytes длиной фактически собранных битов (массив 0/1).
        """
        if n_bits <= 0:
            return b""

        # Выделяем буфер под биты
        self.buf = bytearray(n_bits)
        self.n_bits = n_bits
        self.idx = 0

        # Запускаем таймер с частотой битрейта M20
        self.timer.init(freq=self.bitrate, mode=Timer.PERIODIC, callback=self._cb)

        t0 = time.ticks_ms()
        # Ждём, пока либо не наберём нужное количество бит, либо не выйдем по таймауту
        while self.idx < self.n_bits and time.ticks_diff(time.ticks_ms(), t0) < timeout_ms:
            time.sleep_ms(1)

        # Останавливаем таймер
        self.timer.deinit()

        # Возвращаем только реально набранные биты
        return bytes(self.buf[:self.idx])


def collect_bits_from_gdo0(pin_id, bitrate_hz, n_bits, timeout_ms=300, timer_id=1):
    """Одноразовый сбор n_bits битов с GDO0.

    pin_id      — номер GPIO ESP32, куда посажен GDO0 (PIN_GDO0 из config.py)
    bitrate_hz  — битрейт демодулятора CC1101 (под M20 ≈ 9600)
    n_bits      — сколько бит хотим собрать (например, 2 * M20_FRAME_LEN * 8)
    timeout_ms  — таймаут на сбор
    timer_id    — номер аппаратного таймера (0..3 на ESP32)
    """
    collector = GDO0BitCollector(pin_id, bitrate_hz=bitrate_hz, timer_id=timer_id)
    return collector.collect(n_bits, timeout_ms=timeout_ms)


def bits_to_bytes(bits):
    """Преобразует массив бит (bytes/bytearray с 0/1) в список буферов байт
    для всех 8 возможных битовых сдвигов (0..7), MSB first.

    Используется, чтобы попробовать все 8 возможных «фаз» относительно
    настоящей байтовой сетки M20.
    """
    if bits is None:
        return []

    n_bits = len(bits)
    if n_bits <= 0:
        return []

    buffers = []

    for bit_offset in range(8):
        available = n_bits - bit_offset
        if available < 8:
            buffers.append(b"")
            continue

        n_bytes = available // 8
        if n_bytes <= 0:
            buffers.append(b"")
            continue

        out = bytearray(n_bytes)
        pos = bit_offset

        for i in range(n_bytes):
            b = 0
            for _ in range(8):
                # bits[pos] — 0/1
                b = (b << 1) | (1 if bits[pos] else 0)
                pos += 1
            out[i] = b

        buffers.append(bytes(out))

    return buffers
