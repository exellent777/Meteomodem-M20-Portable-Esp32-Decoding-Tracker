# afc.py — AFC с дополнительной статистикой для Web UI

import time

class AFC:
    def __init__(self, radio, track, step_hz=400, min_streak=3,
                 loss_timeout=6.0, use_freqest=True, debug=False):
        self.radio = radio
        self.track = track

        self.step = step_hz
        self.min_streak = min_streak
        self.loss_timeout = loss_timeout
        self.use_freqest = use_freqest
        self.debug = debug

        self.streak = 0
        self.last_ok = 0
        self.confirmed_freq = None

        # новые поля для UI
        self.last_freqest = 0   # последнее значение FREQEST (signed)
        self.last_df = 0        # последний шаг Δf по FREQEST

    def on_valid_frame(self, frame):
        self.streak += 1
        self.last_ok = time.ticks_ms()

        if self.debug:
            print("[AFC] valid frame, streak", self.streak)

        if self.streak == self.min_streak:
            self.confirmed_freq = self.track.freq
            if self.debug:
                print("[AFC] freq confirmed", self.confirmed_freq)
            self._refine_frequency()

        if self.use_freqest and self.confirmed_freq is not None:
            self._apply_freqest()

    def check_loss(self):
        if self.last_ok == 0:
            return False
        dt = time.ticks_diff(time.ticks_ms(), self.last_ok) / 1000.0
        if dt > self.loss_timeout:
            if self.debug:
                print("[AFC] loss, reset")
            self.reset()
            return True
        return False

    def reset(self):
        self.streak = 0
        self.confirmed_freq = None
        self.last_ok = 0
        self.last_freqest = 0
        self.last_df = 0

    def _refine_frequency(self):
        base = self.confirmed_freq
        if base is None:
            return

        candidates = [base, base - self.step, base + self.step]
        best_freq = base
        best_score = -1e9

        if self.debug:
            print("[AFC] refine…")

        for f in candidates:
            self.radio.set_frequency(f)
            time.sleep_ms(150)
            score = (self.track.signal * 10.0) + self.track.snr
            if self.debug:
                print("  f=", f, "score=", score)
            if score > best_score:
                best_score = score
                best_freq = f

        if self.debug:
            print("[AFC] best", best_freq)

        self.radio.set_frequency(best_freq)
        self.track.freq = best_freq
        self.confirmed_freq = best_freq

    def _apply_freqest(self):
        try:
            fe = self.radio.read_freqest()
        except Exception:
            return

        if fe > 127:
            fe -= 256

        self.last_freqest = fe

        if abs(fe) < 2:
            self.last_df = 0
            return

        df = fe * 400
        new_f = int(self.track.freq + df)
        self.last_df = df

        if self.debug:
            print("[AFC] FREQEST", fe, "df", df, "new", new_f)

        self.radio.set_frequency(new_f)
        self.track.freq = new_f
        self.confirmed_freq = new_f
