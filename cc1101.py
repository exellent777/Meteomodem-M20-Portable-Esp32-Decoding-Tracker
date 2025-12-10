# cc1101.py — CC1101 в RAW 2-FSK режиме для M20

from machine import Pin, SPI
import time
from config import (
    CC1101_SCK, CC1101_MOSI, CC1101_MISO, CC1101_CS, CC1101_GDO0,
    M20_BITRATE, M20_BW_KHZ, M20_DEVIATION_KHZ
)

# Регистры CC1101 (по даташиту)
IOCFG2   = 0x00
IOCFG1   = 0x01
IOCFG0   = 0x02
FIFOTHR  = 0x03
PKTCTRL1 = 0x07
PKTCTRL0 = 0x08
FSCTRL1  = 0x0B
FSCTRL0  = 0x0C
FREQ2    = 0x0D
FREQ1    = 0x0E
FREQ0    = 0x0F
MDMCFG4  = 0x10
MDMCFG3  = 0x11
MDMCFG2  = 0x12
MDMCFG1  = 0x13
MDMCFG0  = 0x14
DEVIATN  = 0x15
MCSM2    = 0x16
MCSM1    = 0x17
MCSM0    = 0x18
FOCCFG   = 0x19
BSCFG    = 0x1A
AGCCTRL2 = 0x1B
AGCCTRL1 = 0x1C
AGCCTRL0 = 0x1D
WORCTRL  = 0x20
FREND1   = 0x21
FREND0   = 0x22
FSCAL3   = 0x23
FSCAL2   = 0x24
FSCAL1   = 0x25
FSCAL0   = 0x26
TEST2    = 0x2C
TEST1    = 0x2D
TEST0    = 0x2E
RSSI     = 0x34
MARCSTATE= 0x35
FREQEST  = 0x32

# Строб-команды
SRES   = 0x30
SFSTXON= 0x31
SXOFF  = 0x32
SCAL   = 0x33
SRX    = 0x34
STX    = 0x35
SIDLE  = 0x36
SFRX   = 0x3A
SFTX   = 0x3B

READ_SINGLE  = 0x80
READ_BURST   = 0xC0
WRITE_BURST  = 0x40

F_XOSC = 26_000_000.0


class CC1101Radio:
    def __init__(self):
        self.spi = SPI(
            1,
            baudrate=4_000_000,
            polarity=0,
            phase=0,
            sck=Pin(CC1101_SCK, Pin.OUT),
            mosi=Pin(CC1101_MOSI, Pin.OUT),
            miso=Pin(CC1101_MISO, Pin.IN),
        )
        self.cs = Pin(CC1101_CS, Pin.OUT, value=1)
        self.gdo0 = Pin(CC1101_GDO0, Pin.IN)

        self.reset()
        self._basic_init()

    # -------- низкоуровневый SPI --------
    def _xfer(self, b):
        self.spi.write(bytearray([b]))

    def _w_reg(self, addr, val):
        self.cs.off()
        self._xfer(addr & 0x3F)
        self._xfer(val & 0xFF)
        self.cs.on()

    def _r_reg(self, addr):
        self.cs.off()
        self._xfer((addr & 0x3F) | READ_SINGLE)
        buf = bytearray(1)
        self.spi.readinto(buf)
        self.cs.on()
        return buf[0]

    def _strobe(self, cmd):
        self.cs.off()
        self._xfer(cmd)
        self.cs.on()

    # --------- базовая инициализация ---------
    def reset(self):
        self.cs.on()
        time.sleep_ms(1)
        self.cs.off()
        time.sleep_ms(1)
        self.cs.on()
        time.sleep_ms(1)
        self._strobe(SRES)
        time.sleep_ms(1)

    def _basic_init(self):
        # Flush FIFO
        self._strobe(SIDLE)
        self._strobe(SFRX)
        self._strobe(SFTX)

        # GDO0 = асинхронные серийные данные (RAW data)
        self._w_reg(IOCFG0, 0x0D)   # GDO0_CFG=0x0D: async serial data out
        self._w_reg(IOCFG1, 0x2E)
        self._w_reg(IOCFG2, 0x2E)

        # Пакетный движок: асинхронный serial, CRC/addr off
        self._w_reg(PKTCTRL1, 0x00)
        # PKT_FORMAT=3 (async serial), LENGTH_CONFIG=2 (infinite), CRC off
        # 0b0011_0010 = 0x32
        self._w_reg(PKTCTRL0, 0x32)
        self._w_reg(FIFOTHR,  0x47)

        # 2-FSK, SYNC_MODE=000 (off), Manchester off
        self._w_reg(MDMCFG2, 0x00)

        # AGC / bit sync / FOC — типовые, как в многих примерах TI
        self._w_reg(FOCCFG,   0x16)
        self._w_reg(BSCFG,    0x6C)
        self._w_reg(AGCCTRL2, 0x43)
        self._w_reg(AGCCTRL1, 0x40)
        self._w_reg(AGCCTRL0, 0x91)

        # MCSM: после RX остаёмся в RX, автокалибровка
        self._w_reg(MCSM0, 0x18)
        self._w_reg(MCSM1, 0x0C)
        self._w_reg(MCSM2, 0x07)

        # Калибровка, тестовые регистры — типовые значения TI
        self._w_reg(FREND1, 0x56)
        self._w_reg(FREND0, 0x10)
        self._w_reg(FSCAL3, 0xE9)
        self._w_reg(FSCAL2, 0x2A)
        self._w_reg(FSCAL1, 0x00)
        self._w_reg(FSCAL0, 0x1F)
        self._w_reg(TEST2,  0x81)
        self._w_reg(TEST1,  0x35)
        self._w_reg(TEST0,  0x09)

    # ---------- расчёт частоты / скорости / девиации ----------
    def _calc_freq_regs(self, freq_hz):
        # Freq = F_XOSC * FREQ / 2^16
        f = int(freq_hz * (1 << 16) / F_XOSC)
        return (f >> 16) & 0xFF, (f >> 8) & 0xFF, f & 0xFF

    def _calc_drate_regs(self, bitrate_hz):
        best_err = 1e9
        best_e = 0
        best_m = 0
        for e in range(16):
            m = int(bitrate_hz * (2**28) / (F_XOSC * (2**e)) - 256)
            if m < 0 or m > 255:
                continue
            drate = (256 + m) * (2**e) * F_XOSC / (2**28)
            err = abs(drate - bitrate_hz)
            if err < best_err:
                best_err = err
                best_e = e
                best_m = m
        return best_e, best_m

    def _calc_rx_bw_regs(self, bw_hz):
        # BW = Fxosc / (8 * (4 + M) * 2^E)
        fx = F_XOSC
        best_err = 1e9
        best_e = 0
        best_m = 0
        for e in range(4):
            for m in range(4):
                bw = fx / (8.0 * (4 + m) * (2**e))
                err = abs(bw - bw_hz)
                if err < best_err:
                    best_err = err
                    best_e = e
                    best_m = m
        return best_e, best_m

    def _calc_deviation_regs(self, dev_hz):
        fx = F_XOSC
        best_err = 1e9
        best_e = 0
        best_m = 0
        for e in range(8):
            for m in range(8):
                dev = (8 + m) * (2**e) * fx / (2**17)
                err = abs(dev - dev_hz)
                if err < best_err:
                    best_err = err
                    best_e = e
                    best_m = m
        return best_e, best_m

    # ------------------- публичные методы -------------------
    def configure_m20(self):
        # Скорость
        e, m = self._calc_drate_regs(M20_BITRATE)
        # Полоса
        bw_e, bw_m = self._calc_rx_bw_regs(M20_BW_KHZ * 1000)
        # Девиация
        dev_e, dev_m = self._calc_deviation_regs(M20_DEVIATION_KHZ * 1000)

        mdmcfg4 = ((bw_e & 0x3) << 6) | ((bw_m & 0x3) << 4) | (e & 0x0F)
        self._w_reg(MDMCFG4, mdmcfg4)
        self._w_reg(MDMCFG3, m & 0xFF)
        self._w_reg(DEVIATN, ((dev_e & 0x7) << 4) | (dev_m & 0x7))

    def set_frequency(self, freq_hz):
        f2, f1, f0 = self._calc_freq_regs(freq_hz)
        self._w_reg(FREQ2, f2)
        self._w_reg(FREQ1, f1)
        self._w_reg(FREQ0, f0)
        # пересинтез
        self._strobe(SCAL)
        time.sleep_ms(1)

    def enter_rx(self):
        self._strobe(SRX)

    def read_rssi_dbm(self):
        raw = self._r_reg(RSSI)
        if raw >= 128:
            raw -= 256
        # RSSI_dBm ~= (RSSI_REG/2) - 74
        return raw / 2.0 - 74.0

    def read_freqest(self):
        """Считать FREQEST (signed int8)."""
        fe = self._r_reg(FREQEST)
        if fe >= 128:
            fe -= 256
        return fe
