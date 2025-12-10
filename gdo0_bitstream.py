# gdo0_bitstream.py — oversampling ×4 GDO0 → байты (ESP32C3 совместимо)

from machine import Pin, Timer

class BitstreamCollector:
    OS_FACTOR = 4
    MIDPOINT = 2

    def __init__(self, cb, gdo0_pin=3, debug=False):
        self.cb = cb
        self.debug = debug
        self.gdo0 = Pin(gdo0_pin, Pin.IN)

        # НА ESP32C3 НУЖНО УКАЗАТЬ ID ТАЙМЕРА, например 0
        self.timer = Timer(0)

        self.samples = [0, 0, 0, 0]
        self.sample_pos = 0

        self.bit_acc = 0
        self.bit_count = 0
        self.running = False

    def start(self, bitrate_hz):
        if self.running:
            return
        self.running = True

        sample_rate = bitrate_hz * self.OS_FACTOR
        period_us = int(1_000_000 / sample_rate)

        if self.debug:
            print("[GDO0] start, rate", sample_rate, "Hz, period", period_us, "us")

        self.timer.init(
            period=period_us,
            mode=Timer.PERIODIC,
            callback=self._sample
        )

    def stop(self):
        if not self.running:
            return
        self.running = False
        self.timer.deinit()

    def _sample(self, t):
        v = self.gdo0() & 1
        self.samples[self.sample_pos] = v
        self.sample_pos += 1

        if self.sample_pos < self.OS_FACTOR:
            return

        self.sample_pos = 0
        bit = self.samples[self.MIDPOINT]

        self.bit_acc = ((self.bit_acc << 1) | bit) & 0xFF
        self.bit_count += 1

        if self.bit_count >= 8:
            if self.cb:
                try:
                    self.cb(self.bit_acc)
                except Exception as e:
                    if self.debug:
                        print("[GDO0] cb err", e)
            self.bit_acc = 0
            self.bit_count = 0
