# Простейший драйвер CC1101 для MicroPython (ESP32-C3 / ESP32-S3 / XIAO).
# Работаем по SPI, читаем сырые байты из RX FIFO, умеем мерить RSSI,
# переключаться в RX и задавать частоту.

from machine import SPI, Pin
import time
import config

# ----- Команды CC1101 (strobe) -----
SRES    = 0x30  # reset
SRX     = 0x34  # enter RX
SIDLE   = 0x36  # go IDLE
SFRX    = 0x3A  # flush RX FIFO

# ----- SPI режимы чтения/записи -----
WRITE_BURST = 0x40
READ_SINGLE = 0x80
READ_BURST  = 0xC0

# ----- Регистры CC1101 -----
# (имена и адреса взяты из даташита, только минимум нужного)
REG_IOCFG2   = 0x00
REG_IOCFG0   = 0x02
REG_FIFOTHR  = 0x03
REG_SYNC1    = 0x04
REG_SYNC0    = 0x05
REG_PKTLEN   = 0x06
REG_PKTCTRL1 = 0x07
REG_PKTCTRL0 = 0x08
REG_ADDR     = 0x09
REG_CHANNR   = 0x0A
REG_FSCTRL1  = 0x0B
REG_FSCTRL0  = 0x0C
REG_FREQ2    = 0x0D
REG_FREQ1    = 0x0E
REG_FREQ0    = 0x0F
REG_MDMCFG4  = 0x10
REG_MDMCFG3  = 0x11
REG_MDMCFG2  = 0x12
REG_DEVIATN  = 0x15
REG_MCSM0    = 0x18
REG_FOCCFG   = 0x19
REG_BSCFG    = 0x1A
REG_AGCCTRL2 = 0x1B
REG_AGCCTRL1 = 0x1C
REG_AGCCTRL0 = 0x1D
REG_FREND1   = 0x21
REG_FSCAL3   = 0x23
REG_FSCAL2   = 0x24
REG_FSCAL1   = 0x25
REG_FSCAL0   = 0x26
REG_TEST2    = 0x2C
REG_TEST1    = 0x2D
REG_TEST0    = 0x2E

# ----- Регистры статуса (читаются с флагом READ_SINGLE) -----
REG_RSSI     = 0x34
REG_MARCSTATE= 0x35
REG_PKTSTATUS= 0x38
REG_RXBYTES  = 0x3B

# ----- Ошибка приёма -----
class CC1101ReceiveError(Exception):
    pass


class CC1101:
    def __init__(self, spi_id=1, sck=None, mosi=None, miso=None, cs=None):
        # Инициализация SPI и пина CS
        self.cs = Pin(cs, Pin.OUT, value=1)
        self.spi = SPI(
            spi_id,
            baudrate=4000000,
            polarity=0,
            phase=0,
            sck=Pin(sck),
            mosi=Pin(mosi),
            miso=Pin(miso),
        )
        time.sleep_ms(10)

        # Сбрасываем чип и настраиваем его под приём M20
        self.reset()
        self.configure_radio()

    # ---------------------- Низкоуровневый SPI ----------------------

    def _select(self):
        self.cs.value(0)
        # Небольшая задержка для надёжности
        time.sleep_us(5)

    def _deselect(self):
        self.cs.value(1)
        time.sleep_us(5)

    def strobe(self, cmd):
        """Отправка strobe-команды (SRES, SRX, SIDLE, SFRX, и т.д.)"""
        self._select()
        self.spi.write(bytearray([cmd]))
        self._deselect()

    def write_reg(self, addr, value):
        """Запись одного регистра."""
        self._select()
        self.spi.write(bytearray([addr | WRITE_BURST, value & 0xFF]))
        self._deselect()

    def read_reg(self, addr):
        """Чтение одного регистра."""
        self._select()
        self.spi.write(bytearray([addr | READ_SINGLE]))
        data = self.spi.read(1)
        self._deselect()
        return data[0]

    def read_burst(self, addr, length):
        """Чтение нескольких байт (например, RX FIFO)."""
        self._select()
        self.spi.write(bytearray([addr | READ_BURST]))
        data = self.spi.read(length)
        self._deselect()
        return data

    # ---------------------- Базовые операции ----------------------

    def reset(self):
        """Аппаратный сброс CC1101."""
        self.strobe(SRES)
        time.sleep_ms(5)

    def enter_rx(self):
        """Перевод в RX-режим."""
        self.strobe(SRX)

    def enter_idle(self):
        """Перевод в IDLE."""
        self.strobe(SIDLE)

    def flush_rx(self):
        """Очистить RX FIFO."""
        self.strobe(SFRX)

    # ---------------------- Настройка под M20 ----------------------

    def configure_radio(self):
        """
        Базовая конфигурация под приём M20:
          - 400–406 MHz диапазон (частоту задаём позже отдельно);
          - 2-FSK
          - скорость ~9.6 kbit/s
          - полоса приёма ~100 kHz (чтобы не бояться сдвига по частоте)
        """
        self.strobe(SIDLE)
        self.flush_rx()

        # Настройка выводов GDO:
        #   GDO0/GDO2 в режим 0x0D: Serial Data Output (асинхронный поток RX-данных). GDO0 читаем таймером.
        self.write_reg(REG_IOCFG2, 0x0D)
        self.write_reg(REG_IOCFG0, 0x0D)

        # FIFO пороги
        self.write_reg(REG_FIFOTHR, 0x07)

        # Пакетный режим: бесконечная длина пакета, CRC выключен.
        # Границы кадров M20 ищем сами в Python.
        self.write_reg(REG_PKTLEN, 0xFF)
        self.write_reg(REG_PKTCTRL1, 0x00)
        # PKTCTRL0:
        #   [1:0] LENGTH_CONFIG = 2 (infinite length)
        #   [2]   CRC_EN = 0 (CRC считаем сами)
        self.write_reg(REG_PKTCTRL0, 0x02)

        # Номер устройства и канал (не используются в нашем режиме)
        self.write_reg(REG_ADDR, 0x00)
        self.write_reg(REG_CHANNR, 0x00)

        # Частотный синтезатор, девиация и пр. (значения подобраны под 400–406 MHz и ~9.6 kbit/s)
        # Эти регистры можно тонко подстроить под реальный M20 позже.
        self.write_reg(REG_FSCTRL1, 0x08)   # IF frequency
        self.write_reg(REG_FSCTRL0, 0x00)

        # Пример настройки на ~9.6 kbit/s и BW ~100 kHz:
        self.write_reg(REG_MDMCFG4, 0xCA)   # chan BW и др.
        self.write_reg(REG_MDMCFG3, 0x83)   # data rate
        self.write_reg(REG_MDMCFG2, 0x30)   # 2-FSK, sync mode и т.д.

        # Девиация частоты (нужно будет подогнать под M20, сейчас ~47 kHz)
        self.write_reg(REG_DEVIATN, 0x47)

        # State machine config
        self.write_reg(REG_MCSM0, 0x18)
        self.write_reg(REG_FOCCFG, 0x16)
        self.write_reg(REG_BSCFG, 0x6C)

        # AGC
        self.write_reg(REG_AGCCTRL2, 0x43)
        self.write_reg(REG_AGCCTRL1, 0x40)
        self.write_reg(REG_AGCCTRL0, 0x91)

        # Front-end
        self.write_reg(REG_FREND1, 0x56)

        # Calibration
        self.write_reg(REG_FSCAL3, 0xE9)
        self.write_reg(REG_FSCAL2, 0x2A)
        self.write_reg(REG_FSCAL1, 0x00)
        self.write_reg(REG_FSCAL0, 0x1F)
        self.write_reg(REG_TEST2,  0x81)
        self.write_reg(REG_TEST1,  0x35)
        self.write_reg(REG_TEST0,  0x09)

        # Вход в RX режим
        self.enter_rx()

    # ---------------------- Частота и RSSI ----------------------

    def set_frequency(self, freq_hz):
        """
        Установка рабочей частоты в Hz.
        """
        # Формулы из даташита:
        # FREQ = freq_hz * 2^16 / f_ref, где f_ref ~ 26 MHz
        f_ref = 26_000_000
        freq_reg = int(freq_hz * (1 << 16) / f_ref) & 0xFFFFFF

        freq2 = (freq_reg >> 16) & 0xFF
        freq1 = (freq_reg >> 8) & 0xFF
        freq0 = freq_reg & 0xFF

        self.write_reg(REG_FREQ2, freq2)
        self.write_reg(REG_FREQ1, freq1)
        self.write_reg(REG_FREQ0, freq0)

    def read_rssi_raw(self):
        """Читает сырой RSSI из регистра."""
        return self.read_reg(REG_RSSI)

    def read_rssi_dbm(self):
        """
        Преобразование RSSI в dBm по примеру из даташита:
          rssi_dBm = RSSI_DEC/2 - RSSI_OFFSET
        """
        rssi = self.read_rssi_raw()
        # RSSI представляется как signed int8
        if rssi >= 128:
            rssi -= 256
        # RSSI_OFFSET по даташиту обычно ~74
        rssi_dbm = rssi / 2.0 - 74
        return rssi_dbm

    # ---------------------- Чтение RX FIFO (если понадобится) ----------------------

    def read_rx_fifo(self, max_len=64):
        """
        Чтение данных из RX FIFO. Здесь мы им почти не пользуемся,
        т.к. для M20 планируем читать сырые биты с GDO0.
        """
        rxbytes = self.read_reg(REG_RXBYTES) & 0x7F
        if rxbytes == 0:
            raise CC1101ReceiveError("RX FIFO empty")

        to_read = min(rxbytes, max_len)
        data = self.read_burst(0x3F, to_read)  # 0x3F = FIFO
        if not data:
            raise CC1101ReceiveError("no data from RX FIFO")
        return data
