# m20_decoder.py — улучшенный robust sync + статистика для M20
# Работает с M20_SYNC_BYTES = b"\x99\x99\x4C\x99"

from config import M20_SYNC_BYTES
import time

SYNC = M20_SYNC_BYTES
SYNC_LEN = len(SYNC)

# Допуск по расстоянию Хэмминга для sync (в битах по всему 32-битному слову)
SYNC_HAMMING_THRESH = 4

MIN_FRAME_LEN = 10
MAX_FRAME_LEN = 300


def hamming_bytes(a, b):
    """Hamming distance между двумя byte-строками одинаковой длины."""
    d = 0
    for x, y in zip(a, b):
        v = x ^ y
        while v:
            d += 1
            v &= v - 1
    return d


def update_checkM10(c, b):
    """Алгоритм CHECKM10 (как в m20mod)."""
    b &= 0xFF
    b = ((b >> 1) | ((b & 1) << 7)) & 0xFF
    b ^= (b >> 2) & 0xFF
    c ^= b
    for _ in range(8):
        fb = c & 1
        c >>= 1
        if fb:
            c ^= 0x98
    return c & 0xFF


def checkM10(frame):
    """Полный CHECKM10 для кадра."""
    if len(frame) < 2:
        return False
    cs = 0
    for b in frame[:-1]:
        cs = update_checkM10(cs, b)
    return cs == frame[-1]


class M20Decoder:
    def __init__(self, callback, debug=False):
        # callback вызывается ТОЛЬКО для валидных кадров (CRC OK)
        self.cb = callback
        self.debug = debug

        # sliding window для поиска sync
        self.win = bytearray(SYNC_LEN)
        self.wpos = 0

        # состояние захвата кадра
        self.capturing = False
        self.buf = bytearray()
        self.expected = None

        # статистика
        self.sync_hits = 0
        self.frames_total = 0
        self.frames_valid = 0
        self.frames_crc_fail = 0
        self.last_valid_shift = None
        self.last_frame_ok = False
        self.last_sync_time = None

    # ============================================================
    # Основной вход: по одному байту из GDO0-декодера
    # ============================================================
    def feed_byte(self, b):
        b &= 0xFF

        # обновляем окно sync
        self.win[self.wpos] = b
        self.wpos = (self.wpos + 1) % SYNC_LEN

        # если НЕ в захвате → ищем sync
        if not self.capturing:
            if self._sync_match(bytes(self.win)):
                if self.debug:
                    print("[M20] SYNC detected")
                self._on_sync_hit()
                self.capturing = True
                self.buf = bytearray()
                self.expected = None
            return

        # ---- мы в режиме захвата кадра ----
        self.buf.append(b)

        # первый байт после sync — длина
        if self.expected is None:
            if len(self.buf) >= 1:
                L = self.buf[0]
                total = L + 1
                if not (MIN_FRAME_LEN <= total <= MAX_FRAME_LEN):
                    if self.debug:
                        print("[M20] bad length L=", L)
                    self._reset_state()
                    return
                self.expected = total
            return

        # если набрали нужную длину кадра
        if len(self.buf) >= self.expected:
            frame = bytes(self.buf)
            self._handle_frame(frame)
            self._reset_state()

    # ============================================================
    # Поиск sync: 8 фазовых сдвигов + расстояние Хэмминга
    # ============================================================
    def _sync_match(self, window):
        if len(window) != SYNC_LEN:
            return False

        best = 999
        for shift in range(8):
            shifted = self._shift_frame_bits(window, shift)
            d = hamming_bytes(shifted, SYNC)
            if d < best:
                best = d

        # Чем меньше порог, тем жёстче — 4 бита на 32-битный sync это довольно строго
        return best <= SYNC_HAMMING_THRESH

    def _on_sync_hit(self):
        self.sync_hits += 1
        self.last_sync_time = time.ticks_ms()

    # ============================================================
    # Обработка полного кадра
    # ============================================================
    def _handle_frame(self, frame):
        if self.debug:
            print("[M20] frame raw:", frame.hex())

        self.frames_total += 1
        ok = False
        last_shift = None

        # пробуем 8 фазовых сдвигов
        for shift in range(8):
            shifted = self._shift_frame_bits(frame, shift)
            if checkM10(shifted):
                ok = True
                last_shift = shift
                if self.debug:
                    print("[M20] VALID frame (shift=", shift, ")")
                # вызываем callback для валидного кадра
                self.cb(shifted)
                break

        if ok:
            self.frames_valid += 1
            self.last_valid_shift = last_shift
            self.last_frame_ok = True
        else:
            if self.debug:
                print("[M20] INVALID frame (CRC mismatch)")
            self.frames_crc_fail += 1
            self.last_frame_ok = False

    # ============================================================
    # Битовый сдвиг
    # ============================================================
    @staticmethod
    def _shift_frame_bits(frame, shift):
        if shift == 0:
            return frame
        out = bytearray(len(frame))
        carry = 0
        for i, b in enumerate(frame):
            new = ((b >> shift) | (carry << (8 - shift))) & 0xFF
            carry = b & ((1 << shift) - 1)
            out[i] = new
        return bytes(out)

    # ============================================================
    # Сброс состояния захвата
    # ============================================================
    def _reset_state(self):
        self.capturing = False
        self.buf = bytearray()
        self.expected = None
