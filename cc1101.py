# cc1101.py
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
REG_IOCFG2   = 0x00
REG_IOCFG0   = 0x02
REG_FIFOTHR  = 0x03
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
REG_MDMCFG1  = 0x13
REG_MDMCFG0  = 0x14
REG_MCSM0    = 0x18
REG_FOCCFG   = 0x19
REG_AGCCTRL2 = 0x1B
REG_AGCCTRL1 = 0x1C
REG_AGCCTRL0 = 0x1D
REG_WORCTRL  = 0x20
REG_FREND1   = 0x21
REG_FREND0   = 0x22
REG_FSCAL3   = 0x23
REG_FSCAL2   = 0x24
REG_FSCAL1   = 0x25
REG_FSCAL0   = 0x26
REG_TEST2    = 0x2C
REG_TEST1    = 0x2D
REG_TEST0    = 0x2E

# Статус-регистры
REG_RSSI     = 0x34    # RSSI
REG_RXBYTES  = 0x3B    # количество байт в RX FIFO (status reg)
REG_RXFIFO   = 0x3F    # FIFO

# Кварц у CC1101 обычно 26 МГц
XTAL_HZ = 26_000_000


class CC1101ReceiveError(Exception):
    """Ошибка приёма кадра от CC1101 (таймаут/мусор и т.п.)."""
    pass


class CC1101:
    def __init__(self, sck, mosi, miso, cs, gdo0):
        # Инициализация SPI
        self.cs = Pin(cs, Pin.OUT, value=1)
        self.spi = SPI(
            1,
            baudrate=4_000_000,
            polarity=0,
            phase=0,
            sck=Pin(sck),
            mosi=Pin(mosi),
            miso=Pin(miso),
        )
        self.gdo0 = Pin(gdo0, Pin.IN)

        # Сброс и базовая настройка
        self.reset()
        self.configure_radio()

    # ---------------------- Низкоуровневые операции ----------------------

    def _cs_low(self):
        self.cs.value(0)

    def _cs_high(self):
        self.cs.value(1)

    def strobe(self, cmd):
        """Отправить strobe-команду (SRES/SRX/SIDLE/SFRX...)."""
        self._cs_low()
        self.spi.write(bytearray([cmd]))
        self._cs_high()

    def write_reg(self, addr, value):
        """Запись одного регистра."""
        self._cs_low()
        self.spi.write(bytearray([addr & 0x3F]))
        self.spi.write(bytearray([value & 0xFF]))
        self._cs_high()

    def read_reg(self, addr):
        """Чтение одного конфигурационного регистра."""
        self._cs_low()
        self.spi.write(bytearray([addr | READ_SINGLE]))
        val = self.spi.read(1)[0]
        self._cs_high()
        return val

    def _read_status(self, addr):
        """Чтение статус-регистра (RSSI, RXBYTES и т.п.)."""
        self._cs_low()
        self.spi.write(bytearray([addr | READ_BURST]))
        val = self.spi.read(1)[0]
        self._cs_high()
        return val

    def burst_read_fifo(self, length):
        """Чтение нескольких байт из RX FIFO."""
        self._cs_low()
        # RX FIFO = 0x3F, читаем в burst-режиме
        self.spi.write(bytearray([REG_RXFIFO | READ_BURST]))
        data = self.spi.read(length)
        self._cs_high()
        return data

    def flush_rx(self):
        """Очистка RX FIFO."""
        self.strobe(SIDLE)
        time.sleep_ms(1)
        self.strobe(SFRX)
        time.sleep_ms(1)

    # ---------------------- Конфигурация радиочасти ----------------------

    def reset(self):
        """Жёсткий сброс CC1101 (SRES)."""
        self.strobe(SRES)
        time.sleep_ms(5)

    def configure_radio(self):
        """
        Примерная базовая настройка CC1101 в непрерывный приём сырых байтов.
        Эти значения можно потом тонко подстроить.
        """
        self.strobe(SIDLE)
        self.flush_rx()

        # Настраиваем выводы GDO
        # GDO2 / GDO0 — по умолчанию можно оставить как "пакет / sync".
        self.write_reg(REG_IOCFG2, 0x0D)  # GDO2: serial clock or sync
        self.write_reg(REG_IOCFG0, 0x0D)  # GDO0: sync / end of packet

        # FIFO пороги
        self.write_reg(REG_FIFOTHR, 0x07)

        # Режим пакетов: сырые байты, без адресации, без CRC
        self.write_reg(REG_PKTLEN, config.M20_FRAME_LEN & 0xFF)
        self.write_reg(REG_PKTCTRL1, 0x00)
        self.write_reg(REG_PKTCTRL0, 0x00)

        # Частотный синтезатор
        self.write_reg(REG_FSCTRL1, 0x06)
        self.write_reg(REG_FSCTRL0, 0x00)

        # Параметры модема (пример: 4.8 кбит/с, узкая полоса; потом можно уточнить)
        self.write_reg(REG_MDMCFG4, 0xC7)
        self.write_reg(REG_MDMCFG3, 0x83)
        self.write_reg(REG_MDMCFG2, 0x13)
        self.write_reg(REG_MDMCFG1, 0x22)
        self.write_reg(REG_MDMCFG0, 0xF8)

        # Автоматические режимы, частотная коррекция, AGC и т.д.
        self.write_reg(REG_MCSM0, 0x18)
        self.write_reg(REG_FOCCFG, 0x16)
        self.write_reg(REG_AGCCTRL2, 0x43)
        self.write_reg(REG_AGCCTRL1, 0x40)
        self.write_reg(REG_AGCCTRL0, 0x91)

        # Калибровка, тестовые регистры — типичные рекомендуемые значения
        self.write_reg(REG_FREND1, 0x56)
        self.write_reg(REG_FREND0, 0x10)
        self.write_reg(REG_FSCAL3, 0xE9)
        self.write_reg(REG_FSCAL2, 0x2A)
        self.write_reg(REG_FSCAL1, 0x00)
        self.write_reg(REG_FSCAL0, 0x1F)
        self.write_reg(REG_TEST2,  0x81)
        self.write_reg(REG_TEST1,  0x35)
        self.write_reg(REG_TEST0,  0x09)

        # Установить рабочую частоту
        self.set_frequency(config.RF_FREQUENCY_HZ)

        # Вход в RX режим
        self.enter_rx()

    def set_frequency(self, freq_hz):
        """
        Установка частоты.
        Формула из даташита:
            FREQ = int(freq_hz * 2^16 / f_xtal)
        """
        # Защита от None
        if not freq_hz:
            return

        f = int(freq_hz * (1 << 16) // XTAL_HZ)
        freq2 = (f >> 16) & 0xFF
        freq1 = (f >> 8) & 0xFF
        freq0 = f & 0xFF

        self.write_reg(REG_FREQ2, freq2)
        self.write_reg(REG_FREQ1, freq1)
        self.write_reg(REG_FREQ0, freq0)

    def enter_rx(self):
        """Перейти в режим приёма."""
        self.strobe(SRX)

    # ---------------------- Измерение RSSI ----------------------

    def read_rssi_dbm(self):
        """
        Чтение RSSI в dBm.
        Формула из даташита:
            rssi_dec = RSSI_REG (signed, 2's complement)
            RSSI_dBm = rssi_dec / 2 - RSSI_OFFSET
        Для 433 МГц типичный RSSI_OFFSET ≈ 74.
        """
        rssi_reg = self._read_status(REG_RSSI)
        if rssi_reg >= 128:
            rssi_dec = rssi_reg - 256
        else:
            rssi_dec = rssi_reg
        rssi_dbm = rssi_dec / 2.0 - 74.0
        return rssi_dbm

    # ---------------------- Приём кадра ----------------------

    def receive_frame(self, expected_len=None, timeout_ms=500):
        """
        Ожидание одного кадра фиксированной длины из RX FIFO.

        expected_len — длина кадра (по умолчанию config.M20_FRAME_LEN).
        timeout_ms   — таймаут ожидания.

        При успехе:
            возвращает bytes длиной expected_len
        При таймауте или ошибке:
            поднимает CC1101ReceiveError.
        """
        if expected_len is None:
            expected_len = config.M20_FRAME_LEN

        self.flush_rx()
        self.enter_rx()

        buf = bytearray()
        t_start = time.ticks_ms()

        while time.ticks_diff(time.ticks_ms(), t_start) < timeout_ms:
            # Смотрим, сколько байт в RX FIFO
            rxbytes = self._read_status(REG_RXBYTES) & 0x7F
            if rxbytes > 0:
                to_read = min(rxbytes, expected_len - len(buf))
                if to_read > 0:
                    chunk = self.burst_read_fifo(to_read)
                    buf.extend(chunk)

                    if len(buf) >= expected_len:
                        # получили полный кадр
                        self.flush_rx()
                        return bytes(buf[:expected_len])

            time.sleep_ms(5)

        # Таймаут
        self.flush_rx()
        raise CC1101ReceiveError("Timeout waiting for frame")
