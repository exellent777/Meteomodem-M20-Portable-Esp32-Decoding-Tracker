# afc.py — мягкое автоподстройка частоты (AFC) для M20 Tracker
# Работает вместе с main.py и cc1101.py
# Не ломает RAW-поток, корректно действует только когда есть устойчивый сигнал.

import time

# Ограничение максимального отклонения за раз (Гц)
MAX_STEP_HZ = 1500          # мягкая подстройка
GOOD_RSSI_THRESHOLD = -102  # если RSSI лучше — можно смещать частоту

# Исторический фильтр drift
DRIFT_ALPHA = 0.3


class AFC:
    def __init__(self):
        self.last_drift = 0.0

    def _smooth(self, drift):
        """Экспоненциальное сглаживание смещения."""
        self.last_drift = DRIFT_ALPHA * drift + (1 - DRIFT_ALPHA) * self.last_drift
        return self.last_drift

    def correct_frequency(self, radio, freq_hz, rssi_dbm, frame_ok=False):
        """
        Корректирует частоту:
          - Если сильный сигнал → используем RSSI-подстройку.
          - Если есть валидный кадр → добавляем небольшое усиление коррекции.
          - Если слабый сигнал → АФК не применяется.
        """

        if rssi_dbm is None:
            return freq_hz

        # Если сигнал слабый — не корректируем
        if rssi_dbm < GOOD_RSSI_THRESHOLD:
            return freq_hz

        # Предполагаем, что оптимальная частота — там, где RSSI максимален
        # Фиктивная оценка: чем ближе к центру демодуляции, тем выше RSSI.
        drift = (rssi_dbm + 100) * 20   # 20 Гц изменения на 1 dB

        if frame_ok:
            drift *= 1.4  # сильнее тянем к центру, если кадр валиден

        drift = self._smooth(drift)

        # Ограничиваем максимальный шаг
        if drift > MAX_STEP_HZ:
            drift = MAX_STEP_HZ
        elif drift < -MAX_STEP_HZ:
            drift = -MAX_STEP_HZ

        new_freq = int(freq_hz + drift)

        # Применяем
        try:
            radio.set_frequency(new_freq)
        except Exception:
            return freq_hz

        return new_freq


# Экземпляр
afc = AFC()
