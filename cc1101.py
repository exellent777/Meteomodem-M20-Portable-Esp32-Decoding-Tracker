# cc1101.py
# Простейший драйвер CC1101 для MicroPython (ESP32-C3 / XIAO)
# Работаем по SPI, читаем сырые байты из RX FIFO, умеем мерить RSSI.

from machine import SPI, Pin
import time
import config

# Команды CC1101 (strobe)
SRES    = 0x30
SRX     = 0x34
SIDLE   = 0x36
SFRX    = 0x3A

WRITE_BURST = 0x40
READ_SINGLE = 0x80
READ_BURST  = 0xC0

# Регистры
REG_IOCFG0   = 0x02
REG_FIFOTHR  = 0x03
REG_PKTLEN   = 0x06
REG_PKTCTRL1 = 0x07
REG_PKTCTRL0 = 0x08
REG_FSCTRL1  = 0x0B
REG_FREQ2    = 0x0D
REG_FREQ1    = 0x0E
REG_FREQ0    = 0x0F
REG_MDMCFG4  = 0x10
REG_MDMCFG3  = 0x11
REG_MDMCFG2  = 0x12
REG_MDMCFG1  = 0x13
REG_MDMCFG0  = 0x14
REG_DEVIATN  = 0x15
REG_MCSM0    = 0x18
REG_FOCCFG   = 0x19
REG_AGCCTRL2 = 0x1B
REG_AGCCTRL1 = 0x1C
REG_AGCCTRL0 = 0x1D
REG_FSCAL3   = 0x23
REG_FSCAL2   = 0x24
REG_FSCAL1   = 0x25
REG_FSCAL0   = 0x26
REG_TEST2    = 0x2C
REG_TEST1    = 0x2D
REG_TEST0    = 0x2E

REG_RSSI     = 0x34
REG_RXBYTES  = 0x3B
REG_FIFO     = 0x3F

F_XOSC = 26_000_000  # кварц CC1101, 26 МГц


class CC1101:
    def __init__(self):
        # Инициализируем SPI-шину
        self.spi = SPI(
            1,
            baudrate=4_000_000,
            sck=Pin(config.CC1101_SCK),
            mosi=Pin(config.CC1101_MOSI),
            miso=Pin(config.CC1101_MISO),
        )
        self.cs   = Pin(config.CC1101_CS, Pin.OUT, value=1)
        self.gdo0 = Pin(config.CC1101_GDO0, Pin.IN)

        self.reset()
        self.configure_radio()

    # ---------- низкоуровневые функции ----------
    def _select(self):
        self.cs.value(0)

    def _unselect(self):
        self.cs.value(1)

    def strobe(self, cmd):
        self._select()
        self.spi.write(bytearray([cmd]))
        self._unselect()

    def write_reg(self, addr, value):
        self._select()
        self.spi.write(bytearray([addr & 0x3F, value & 0xFF]))
        self._unselect()

    def read_reg(self, addr):
        self._select()
        self.spi.write(bytearray([addr | READ_SINGLE]))
        data = self.spi.read(1)
        self._unselect()
        return data[0]

    def burst_read_fifo(self, length):
        self._select()
        self.spi.write(bytearray([REG_FIFO | READ_BURST]))
        data = self.spi.read(length)
        self._unselect()
        return data

    # ---------- инициализация ----------
    def reset(self):
        # Процедура сброса из даташита
        self._unselect()
        time.sleep_us(5)
        self._select()
        time.sleep_us(10)
        self._unselect()
        time.sleep_us(41)
        self.strobe(SRES)
        time.sleep_ms(1)

    def set_frequency(self, freq_hz):
        """
        Устанавливает рабочую частоту CC1101.
        freq_hz — в Гц, например 403_000_000.
        """
        f = int(freq_hz * (1 << 16) / F_XOSC)
        f2 = (f >> 16) & 0xFF
        f1 = (f >> 8) & 0xFF
        f0 = f & 0xFF
        self.write_reg(REG_FREQ2, f2)
        self.write_reg(REG_FREQ1, f1)
        self.write_reg(REG_FREQ0, f0)

    def configure_radio(self):
        """
        Базовая конфигурация модема: GFSK, ~4.8 kbps, узкая полоса.
        Это стартовая точка — под M20 можно будет подстроить.
        """
        # GDO0 выводим как "asserted when sync word has been sent/received,
        # and de-asserted at the end of the packet"
        self.write_reg(REG_IOCFG0, 0x06)

        # Порог FIFO
        self.write_reg(REG_FIFOTHR, 0x47)

        # Отключаем встроенный packet handler (читаем сырые байты)
        self.write_reg(REG_PKTLEN,   0xFF)
        self.write_reg(REG_PKTCTRL1, 0x00)
        self.write_reg(REG_PKTCTRL0, 0x00)

        # Частотный синтезатор
        self.write_reg(REG_FSCTRL1, 0x06)
        self.set_frequency(config.RF_FREQUENCY_HZ)

        # Параметры модема (примерная настройка, потом можно уточнить)
        self.write_reg(REG_MDMCFG4, 0xC7)
        self.write_reg(REG_MDMCFG3, 0x83)
        self.write_reg(REG_MDMCFG2, 0x13)
        self.write_reg(REG_MDMCFG1, 0x22)
        self.write_reg(REG_MDMCFG0, 0xF8)

        self.write_reg(REG_DEVIATN, 0x34)

        self.write_reg(REG_FOCCFG,   0x16)
        self.write_reg(REG_AGCCTRL2, 0x43)
        self.write_reg(REG_AGCCTRL1, 0x40)
        self.write_reg(REG_AGCCTRL0, 0x91)

        self.write_reg(REG_MCSM0, 0x18)

        self.write_reg(REG_FSCAL3, 0xE9)
        self.write_reg(REG_FSCAL2, 0x2A)
        self.write_reg(REG_FSCAL1, 0x00)
        self.write_reg(REG_FSCAL0, 0x1F)

        self.write_reg(REG_TEST2, 0x81)
        self.write_reg(REG_TEST1, 0x35)
        self.write_reg(REG_TEST0, 0x09)

        # Чистим RX FIFO
        self.strobe(SFRX)

    # ---------- служебные методы ----------
    def get_rx_bytes(self):
        """
        Возвращает количество байт в RX FIFO.
        """
        self._select()
        self.spi.write(bytearray([REG_RXBYTES | READ_SINGLE]))
        data = self.spi.read(1)
        self._unselect()
        return data[0] & 0x7F  # старший бит — флаг переполнения

    def enter_rx(self):
        self.strobe(SRX)

    def flush_rx(self):
        self.strobe(SFRX)

    # ---------- RSSI ----------
    def read_rssi_raw(self):
        """
        Считает сырое значение RSSI (0..255), как в регистре RSSI.
        """
        return self.read_reg(REG_RSSI)

    def read_rssi_dbm(self):
        """
        Возвращает RSSI в dBm по формуле из даташита CC1101:
        RSSI_dBm ≈ (RSSI_dec / 2) - RSSI_offset, где RSSI_offset ≈ 74.
        """
        raw = self.read_rssi_raw()
        if raw >= 128:
            raw -= 256  # преобразуем к signed
        return (raw / 2.0) - 74.0

    # ---------- приём фиксированной длины ----------
    def receive_frame(self, expected_len, timeout_ms=1000):
        """
        Собирает кадр длиной expected_len байт из RX FIFO CC1101.
        Стратегия:
          - чистим FIFO, переходим в RX,
          - в течение timeout_ms читаем, сколько есть байт,
          - накапливаем в буфере, пока не наберём expected_len,
          - если не успели за таймаут — возвращаем None.
        """
        self.flush_rx()
        self.enter_rx()

        buf = bytearray()
        t0 = time.ticks_ms()

        while time.ticks_diff(time.ticks_ms(), t0) < timeout_ms:
            available = self.get_rx_bytes()
            if available > 0:
                to_read = min(available, expected_len - len(buf))
                if to_read > 0:
                    chunk = self.burst_read_fifo(to_read)
                    buf.extend(chunk)
                    if len(buf) >= expected_len:
                        # получили полный кадр
                        self.flush_rx()
                        return bytes(buf[:expected_len])
            time.sleep_ms(5)

        # таймаут
        self.flush_rx()
        return None
