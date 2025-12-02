# cc1101.py — драйвер CC1101 для проекта M20 Tracker
# RAW битовый поток на GDO0, поддержка частоты и RSSI.

import time
from machine import Pin, SPI
import config

# CC1101 Registers
REG_IOCFG0   = 0x02
REG_PKTCTRL1 = 0x08
REG_PKTCTRL0 = 0x07
REG_FREQ2    = 0x0D
REG_FREQ1    = 0x0E
REG_FREQ0    = 0x0F
REG_MDMCFG4  = 0x10
REG_MDMCFG3  = 0x11
REG_MDMCFG2  = 0x12
REG_MDMCFG1  = 0x13
REG_MDMCFG0  = 0x14
REG_DEVIATN  = 0x15
REG_FOCCTRL  = 0x19
REG_BSCFG    = 0x1A
REG_AGCCTRL2 = 0x1B
REG_AGCCTRL1 = 0x1C
REG_AGCCTRL0 = 0x1D
REG_RSSI     = 0x34

# Commands
CMD_SRES  = 0x30
CMD_SCAL  = 0x33
CMD_SRX   = 0x34
CMD_SIDLE = 0x36
CMD_SFRX  = 0x3A
CMD_SFTX  = 0x3B


class Radio:
    def __init__(self):
        # SPI init
        self.spi = SPI(
            1,
            baudrate=2_000_000,
            polarity=0,
            phase=0,
            sck=Pin(config.CC1101_SCK),
            mosi=Pin(config.CC1101_MOSI),
            miso=Pin(config.CC1101_MISO),
        )
        self.cs = Pin(config.CC1101_CS, Pin.OUT, value=1)

        self.reset()
        self.configure_m20()

    # --------------------------
    # SPI helpers
    # --------------------------
    def _cs_low(self):
        self.cs.value(0)

    def _cs_high(self):
        self.cs.value(1)

    def write_reg(self, addr, value):
        self._cs_low()
        self.spi.write(bytearray([addr, value & 0xFF]))
        self._cs_high()

    def read_reg(self, addr):
        self._cs_low()
        self.spi.write(bytearray([addr | 0x80]))
        v = self.spi.read(1)[0]
        self._cs_high()
        return v

    def strobe(self, cmd):
        self._cs_low()
        self.spi.write(bytearray([cmd]))
        self._cs_high()

    # --------------------------
    # RESET
    # --------------------------
    def reset(self):
        # Жёсткая последовательность из даташита
        self._cs_high()
        time.sleep_us(30)
        self._cs_low()
        time.sleep_us(30)
        self._cs_high()
        time.sleep_us(45)

        self.strobe(CMD_SRES)
        time.sleep_ms(1)

    # --------------------------
    # Настройка под M20
    # --------------------------
    def configure_m20(self):
        """
        Настройка CC1101 под приём M20:
        - dev ≈ 6 kHz (разнос ≈ 12 kHz)
        - BW ≈ 100 kHz
        - 2-FSK, SYNC off, RAW async на GDO0
        """

        # В IDLE и чистим FIFO
        self.strobe(CMD_SIDLE)
        time.sleep_ms(1)
        self.strobe(CMD_SFRX)
        self.strobe(CMD_SFTX)

        # Девиация ≈ 6 kHz (DEVIATION_E=1, M=7 → ~5.9 kHz)
        self.write_reg(REG_DEVIATN, 0x17)

        # MDMCFG4: CHANBW_E=3, CHANBW_M=0 → BW ≈ 100 kHz
        #          DRATE_E=8  (с MDMCFG3=0x83 ≈ 9.6 ksym/s)
        self.write_reg(REG_MDMCFG4, 0xC8)
        self.write_reg(REG_MDMCFG3, 0x83)

        # 2-FSK, SYNC_MODE=0 (без sync), манчестер выкл, whitening выкл
        self.write_reg(REG_MDMCFG2, 0x13)
        self.write_reg(REG_MDMCFG1, 0x22)
        self.write_reg(REG_MDMCFG0, 0xF8)

        # RAW async mode: GDO0 = serial data, без CRC и whitening
        self.write_reg(REG_PKTCTRL0, 0x12)
        self.write_reg(REG_PKTCTRL1, 0x00)

        # GDO0 → serial data output
        self.write_reg(REG_IOCFG0, 0x0D)

        # AGC по-консервативнее
        self.write_reg(REG_AGCCTRL2, 0x07)
        self.write_reg(REG_AGCCTRL1, 0x00)
        self.write_reg(REG_AGCCTRL0, 0x90)

        # Frequency offset / bit sync
        self.write_reg(REG_FOCCTRL, 0x1D)
        self.write_reg(REG_BSCFG, 0x00)

        # В RX
        self.strobe(CMD_SRX)
        time.sleep_ms(2)

        print("CC1101 configured for M20 mode.")

    # --------------------------
    # Частота и RSSI
    # --------------------------
    def set_frequency(self, freq_hz):
        """
        Устанавливает частоту (Гц), например 405400000.
        Формула: FREQ = f_carrier * 2^16 / f_xosc, f_xosc = 26 МГц.
        """
        f_xosc = 26_000_000
        freq_word = int(freq_hz * (2**16) / f_xosc) & 0xFFFFFF

        f2 = (freq_word >> 16) & 0xFF
        f1 = (freq_word >> 8) & 0xFF
        f0 = freq_word & 0xFF

        self.write_reg(REG_FREQ2, f2)
        self.write_reg(REG_FREQ1, f1)
        self.write_reg(REG_FREQ0, f0)

        # Калибруем синтезатор
        self.strobe(CMD_SCAL)
        time.sleep_ms(1)

    def read_rssi(self):
        """
        Читает RSSI и переводит в dBm.
        Стандартная формула TI:
        RSSI_dec = регистр 0x34 (signed)
        RSSI_dBm ≈ RSSI_dec/2 - 74 (для 26 МГц).
        """
        raw = self.read_reg(REG_RSSI)
        if raw >= 128:
            raw -= 256  # sign extend
        return raw / 2.0 - 74.0
