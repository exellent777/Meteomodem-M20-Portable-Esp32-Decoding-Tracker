# web_ui.py
# Веб-интерфейс для ESP32-C3 M20 Tracker.
#
# Эндпоинты:
#   GET  /              -> HTML-страница с JS
#   GET  /api/status    -> JSON со статусом (позиция, частота, RSSI, диагностика приёмника)
#   POST /api/restart   -> установить флаг "перезапустить поиск"
#   POST /api/mode/scan -> включить режим сканирования диапазона
#   POST /api/mode/fixed-> включить режим фиксированной частоты

import socket
import time
import json
import config
import track_store


def _build_status_dict():
    """
    Готовим словарь со статусом для JSON API.
    """
    latest = track_store.latest

    # Человекочитаемое время последнего валидного кадра
    if getattr(latest, "time", None):
        t = time.localtime(latest.time)
        ts = "%04d-%02d-%02d %02d:%02d:%02d" % (
            t[0], t[1], t[2], t[3], t[4], t[5]
        )
        age = max(0, int(time.time() - latest.time))
    else:
        ts = None
        age = None

    track_len = len(track_store.track)

    # Защита от отсутствующих атрибутов (если прошивка обновлялась по частям)
    rf_freq_hz = getattr(track_store, "rf_freq_hz", None)
    rf_rssi_dbm = getattr(track_store, "rf_rssi_dbm", None)
    rf_mode = getattr(track_store, "rf_mode", "idle")
    rf_noise_rssi_dbm = getattr(track_store, "rf_noise_rssi_dbm", None)
    rf_signal_threshold_dbm = getattr(track_store, "rf_signal_threshold_dbm", None)
    rf_lost_counter = getattr(track_store, "rf_lost_counter", 0)
    rf_had_signal = getattr(track_store, "rf_had_signal", False)

    rf_control_mode = getattr(track_store, "rf_control_mode", "scan")
    rf_fixed_freq_hz = getattr(track_store, "rf_fixed_freq_hz", None)

    need_restart = getattr(track_store, "need_restart", False)

    has_pos = (
        getattr(latest, "lat", None) is not None
        and getattr(latest, "lon", None) is not None
    )

    return {
        "ts": ts,
        "age_sec": age,
        "has_position": has_pos,
        "lat": getattr(latest, "lat", None),
        "lon": getattr(latest, "lon", None),
        "alt": getattr(latest, "alt", None),
        "track_len": track_len,

        # Радиочасть
        "rf_freq_hz": rf_freq_hz,
        "rf_rssi_dbm": rf_rssi_dbm,

        # Управление режимом поиска
        "rf_control_mode": rf_control_mode,
        "rf_fixed_freq_hz": rf_fixed_freq_hz,

        # Доп. диагностика радиочасти
        "rf_mode": rf_mode,
        "rf_noise_rssi_dbm": rf_noise_rssi_dbm,
        "rf_signal_threshold_dbm": rf_signal_threshold_dbm,
        "rf_lost_counter": rf_lost_counter,
        "rf_had_signal": rf_had_signal,

        # Флаг «запрошен рестарт поиска»
        "need_restart": need_restart,
    }


def _html_page():
    """
    Одностраничный интерфейс: JS опрашивает /api/status и
    по кнопкам шлёт /api/restart и /api/mode/...
    """
    return """<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8" />
  <title>M20 Tracker</title>
  <style>
    body {
      font-family: system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
      background: #020617;
      color: #e5e7eb;
      margin: 0;
      padding: 0;
    }
    header {
      padding: 12px 16px;
      background: #020617;
      border-bottom: 1px solid #1f2937;
      display: flex;
      justify-content: space-between;
      align-items: center;
    }
    header .title {
      font-size: 16px;
      font-weight: 600;
    }
    header .subtitle {
      font-size: 11px;
      color: #9ca3af;
    }
    main {
      padding: 12px 16px 32px 16px;
    }
    .cards-row {
      display: flex;
      flex-wrap: wrap;
      gap: 12px;
      margin-bottom: 12px;
    }
    .card {
      background: #020617;
      border-radius: 10px;
      border: 1px solid #1f2937;
      padding: 10px 12px;
      min-width: 220px;
      flex: 1 1 220px;
      box-sizing: border-box;
      box-shadow: 0 8px 24px rgba(0,0,0,0.35);
    }
    .card h2 {
      margin: 0 0 8px 0;
      font-size: 14px;
      font-weight: 600;
    }
    .card .small {
      font-size: 11px;
      color: #9ca3af;
      margin-top: 4px;
    }
    .kv {
      display: flex;
      justify-content: space-between;
      align-items: baseline;
      margin: 2px 0;
      font-size: 12px;
    }
    .kv .label {
      color: #9ca3af;
      margin-right: 4px;
    }
    .kv .value {
      font-variant-numeric: tabular-nums;
    }
    .status-ok {
      color: #22c55e;
    }
    .status-warn {
      color: #eab308;
    }
    .status-bad {
      color: #f97373;
    }
    .rssi-bar {
      margin-top: 4px;
      width: 100%%;
      height: 6px;
      border-radius: 999px;
      background: #020617;
      border: 1px solid #374151;
      overflow: hidden;
    }
    .rssi-bar-inner {
      height: 100%%;
      width: 0%%;
      background: linear-gradient(90deg, #22c55e, #eab308, #ef4444);
      transition: width 0.2s ease-out;
    }
    .rssi-label {
      margin-top: 4px;
      font-size: 11px;
      color: #9ca3af;
    }
    button {
      font-size: 12px;
      padding: 5px 9px;
      border-radius: 6px;
      border: none;
      cursor: pointer;
      outline: none;
      background: #2563eb;
      color: #e5e7eb;
      margin-right: 4px;
    }
    button.secondary {
      background: #334155;
    }
    button:disabled {
      opacity: 0.45;
      cursor: default;
    }
    #info {
      margin-top: 8px;
      font-size: 11px;
      color: #9ca3af;
    }
  </style>
</head>
<body>
  <header>
    <div>
      <div class="title">M20 Tracker</div>
      <div class="subtitle">ESP32-C3 + CC1101 · локальный приёмник метеозондов</div>
    </div>
    <div class="subtitle">
      Частота по умолчанию: %.3f MHz
    </div>
  </header>
  <main>
    <div class="cards-row">
      <div class="card">
        <h2>Состояние зонда</h2>
        <div class="kv">
          <span class="label">Время последнего кадра</span>
          <span class="value" id="ts">—</span>
        </div>
        <div class="kv">
          <span class="label">Возраст данных</span>
          <span class="value" id="age">—</span>
        </div>
        <div class="kv">
          <span class="label">Статус</span>
          <span class="value" id="status">—</span>
        </div>
        <div class="kv">
          <span class="label">Длина трека</span>
          <span class="value" id="trackLen">0</span>
        </div>
        <div class="small">
          Здесь видно, поймали ли мы уже хоть один валидный кадр M20.
        </div>
      </div>

      <div class="card">
        <h2>Последняя позиция</h2>
        <div class="kv">
          <span class="label">Широта</span>
          <span class="value" id="lat">—</span>
        </div>
        <div class="kv">
          <span class="label">Долгота</span>
          <span class="value" id="lon">—</span>
        </div>
        <div class="kv">
          <span class="label">Высота</span>
          <span class="value" id="alt">—</span>
        </div>
        <div class="small">
          Координаты последнего успешно декодированного кадра.
        </div>
      </div>
    </div>

    <div class="cards-row">
      <div class="card">
        <h2>Радиоканал</h2>
        <div class="kv">
          <span class="label">Текущая частота</span>
          <span class="value" id="freq">—</span>
        </div>
        <div class="kv">
          <span class="label">RSSI</span>
          <span class="value" id="rssi">—</span>
        </div>
        <div class="rssi-bar">
          <div class="rssi-bar-inner" id="rssiBar"></div>
        </div>
        <div class="rssi-label" id="rssiLabel">уровень сигнала</div>
        <div class="kv">
          <span class="label">Режим приёмника</span>
          <span class="value" id="mode">—</span>
        </div>
        <div class="kv">
          <span class="label">Шум</span>
          <span class="value" id="noise">—</span>
        </div>
        <div class="kv">
          <span class="label">Порог сигнала</span>
          <span class="value" id="threshold">—</span>
        </div>
        <div class="kv">
          <span class="label">Слабых циклов подряд</span>
          <span class="value" id="lost">—</span>
        </div>
        <div class="kv">
          <span class="label">Сигнал когда-либо был</span>
          <span class="value" id="hadSignal">—</span>
        </div>
        <div class="kv">
          <span class="label">Режим поиска</span>
          <span class="value" id="controlMode">—</span>
        </div>
        <div class="kv">
          <span class="label">Фикс. частота</span>
          <span class="value" id="fixedFreq">—</span>
        </div>
        <div class="kv">
          <span class="label">Флаг рестарта</span>
          <span class="value" id="restartFlag">—</span>
        </div>
      </div>

      <div class="card">
        <h2>Управление</h2>
        <div class="kv">
          <span class="label">Поиск</span>
          <span class="value">
            <button id="btnModeScan" class="secondary">Сканирование</button>
            <button id="btnModeFixed">Фикс %.3f MHz</button>
          </span>
        </div>
        <div class="kv">
          <span class="label">Перезапуск</span>
          <span class="value">
            <button id="btnRestart">Перезапустить поиск</button>
          </span>
        </div>
        <div id="info" class="small">
          Режим переключается мгновенно, но при смене режима основной
          цикл заново инициализирует поиск.
        </div>
      </div>
    </div>
  </main>

  <script>
    function formatLatLon(v) {
      if (v === null || v === undefined) return "\\u2014";
      return v.toFixed(5);
    }
    function formatAlt(a) {
      if (a === null || a === undefined) return "\\u2014";
      return a.toFixed(1) + " м";
    }
    function formatFreq(hz) {
      if (hz === null || hz === undefined) return "\\u2014";
      return (hz / 1e6).toFixed(3) + " MHz";
    }
    function formatDbm(v) {
      if (v === null || v === undefined) return "\\u2014";
      return v.toFixed(1) + " dBm";
    }

    function updateUI(data) {
      var tsEl = document.getElementById("ts");
      var ageEl = document.getElementById("age");
      var statusEl = document.getElementById("status");
      var trackLenEl = document.getElementById("trackLen");

      var latEl = document.getElementById("lat");
      var lonEl = document.getElementById("lon");
      var altEl = document.getElementById("alt");

      var freqEl = document.getElementById("freq");
      var rssiEl = document.getElementById("rssi");
      var rssiBar = document.getElementById("rssiBar");
      var rssiLabel = document.getElementById("rssiLabel");

      var modeEl = document.getElementById("mode");
      var noiseEl = document.getElementById("noise");
      var thrEl = document.getElementById("threshold");
      var lostEl = document.getElementById("lost");
      var hadSignalEl = document.getElementById("hadSignal");
      var restartFlagEl = document.getElementById("restartFlag");

      var controlModeEl = document.getElementById("controlMode");
      var fixedFreqEl = document.getElementById("fixedFreq");

      var btnModeScan = document.getElementById("btnModeScan");
      var btnModeFixed = document.getElementById("btnModeFixed");

      tsEl.textContent = data.ts || "\\u2014";
      if (data.age_sec !== null && data.age_sec !== undefined) {
        ageEl.textContent = data.age_sec + " с";
      } else {
        ageEl.textContent = "\\u2014";
      }
      trackLenEl.textContent = data.track_len || 0;

      // Статус
      if (data.has_position) {
        statusEl.textContent = "позиция получена";
        statusEl.className = "status-ok";
      } else if (data.rf_mode === "tracking") {
        statusEl.textContent = "есть сигнал, ждём позицию";
        statusEl.className = "status-warn";
      } else if (data.rf_mode === "lost") {
        statusEl.textContent = "зонд потерян";
        statusEl.className = "status-warn";
      } else {
        statusEl.textContent = "зонд не обнаружен";
        statusEl.className = "status-bad";
      }

      latEl.textContent = formatLatLon(data.lat);
      lonEl.textContent = formatLatLon(data.lon);
      altEl.textContent = formatAlt(data.alt);

      freqEl.textContent = formatFreq(data.rf_freq_hz);
      rssiEl.textContent = formatDbm(data.rf_rssi_dbm);

      // Простая шкала RSSI: -120 .. 0 dBm -> 0..100%%
      if (data.rf_rssi_dbm === null || data.rf_rssi_dbm === undefined) {
        rssiBar.style.width = "0%%";
        rssiLabel.textContent = "нет измерения RSSI";
      } else {
        var v = data.rf_rssi_dbm;
        var pct = (v + 120) / 120;
        if (pct < 0) pct = 0;
        if (pct > 1) pct = 1;
        rssiBar.style.width = (pct * 100).toFixed(0) + "%%";
        rssiLabel.textContent = "RSSI " + formatDbm(v);
      }

      modeEl.textContent = data.rf_mode || "\\u2014";
      noiseEl.textContent = formatDbm(data.rf_noise_rssi_dbm);
      thrEl.textContent = formatDbm(data.rf_signal_threshold_dbm);
      lostEl.textContent = (data.rf_lost_counter != null) ? data.rf_lost_counter : "\\u2014";
      hadSignalEl.textContent = data.rf_had_signal ? "да" : "нет";

      restartFlagEl.textContent = data.need_restart ? "да" : "нет";

      // Режим поиска
      var cm = data.rf_control_mode || "scan";
      if (cm === "fixed") {
        controlModeEl.textContent = "фиксированная";
        if (btnModeFixed) btnModeFixed.disabled = true;
        if (btnModeScan) btnModeScan.disabled = false;
      } else {
        controlModeEl.textContent = "сканирование";
        if (btnModeScan) btnModeScan.disabled = true;
        if (btnModeFixed) btnModeFixed.disabled = false;
      }
      fixedFreqEl.textContent = formatFreq(data.rf_fixed_freq_hz);
    }

    function poll() {
      fetch("/api/status")
        .then(function(resp) { return resp.json(); })
        .then(function(data) { updateUI(data); })
        .catch(function(err) { console.log("poll error:", err); })
        .finally(function() {
          setTimeout(poll, 800);
        });
    }

    function setupControls() {
      var infoEl = document.getElementById("info");
      var btnRestart = document.getElementById("btnRestart");
      var btnModeScan = document.getElementById("btnModeScan");
      var btnModeFixed = document.getElementById("btnModeFixed");

      if (btnRestart) {
        btnRestart.addEventListener("click", function() {
          var btn = btnRestart;
          btn.disabled = true;
          infoEl.textContent = "Отправляю запрос перезапуска...";
          fetch("/api/restart", { method: "POST" })
            .then(function(resp) { return resp.text(); })
            .then(function(text) {
              infoEl.textContent = "Перезапуск поиска запросен.";
            })
            .catch(function(err) {
              console.log("restart error:", err);
              infoEl.textContent = "Ошибка при запросе перезапуска.";
            })
            .finally(function() {
              setTimeout(function() {
                btn.disabled = false;
              }, 1500);
            });
        });
      }

      function setMode(mode) {
        infoEl.textContent = "Переключаю режим на " + mode + "...";
        fetch("/api/mode/" + mode, { method: "POST" })
          .then(function(resp) { return resp.text(); })
          .then(function(text) {
            infoEl.textContent = "Режим " + mode + " установлен.";
          })
          .catch(function(err) {
            console.log("mode error:", err);
            infoEl.textContent = "Ошибка при переключении режима.";
          });
      }

      if (btnModeScan) {
        btnModeScan.addEventListener("click", function() {
          setMode("scan");
        });
      }
      if (btnModeFixed) {
        btnModeFixed.addEventListener("click", function() {
          setMode("fixed");
        });
      }
    }

    window.addEventListener("load", function() {
      setupControls();
      poll();
    });
  </script>
</body>
</html>
""" % (config.RF_FREQUENCY_HZ / 1e6, config.RF_FREQUENCY_HZ / 1e6)


def _handle_root(cl):
    """
    Отдаём HTML-страницу.
    """
    body = _html_page()
    header = (
        "HTTP/1.1 200 OK\r\n"
        "Content-Type: text/html; charset=utf-8\r\n"
        "Connection: close\r\n\r\n"
    )
    cl.send(header)
    cl.send(body)


def _handle_api_status(cl):
    """
    Обработчик /api/status — отдаём JSON.
    """
    try:
        status = _build_status_dict()
        body = json.dumps(status)
        code = "200 OK"
    except Exception as e:
        body = json.dumps({"error": str(e)})
        code = "500 Internal Server Error"

    header = (
        "HTTP/1.1 %s\r\n"
        "Content-Type: application/json; charset=utf-8\r\n"
        "Connection: close\r\n\r\n"
    ) % code
    cl.send(header)
    cl.send(body)


def _handle_api_restart(cl):
    """
    Обработчик /api/restart — ставим флаг в track_store.
    """
    try:
        track_store.request_restart()
        body = "OK"
        code = "200 OK"
    except Exception as e:
        body = "ERROR: %s" % e
        code = "500 Internal Server Error"

    header = (
        "HTTP/1.1 %s\r\n"
        "Content-Type: text/plain; charset=utf-8\r\n"
        "Connection: close\r\n\r\n"
    ) % code
    cl.send(header)
    cl.send(body)


def _handle_api_mode(cl, path: str):
    """
    Обработчик /api/mode/scan или /api/mode/fixed — переключаем режим поиска.
    """
    try:
        mode = "scan"
        if path.startswith("/api/mode/"):
            tail = path[len("/api/mode/"):]
            if tail.startswith("fixed"):
                mode = "fixed"
            elif tail.startswith("scan"):
                mode = "scan"
            else:
                raise ValueError("unknown mode '%s'" % tail)
        else:
            # запасной вариант: /api/mode?mode=fixed
            if "mode=fixed" in path:
                mode = "fixed"
            elif "mode=scan" in path:
                mode = "scan"

        track_store.set_rf_control_mode(mode)
        body = "OK %s" % mode
        code = "200 OK"
    except Exception as e:
        body = "ERROR: %s" % e
        code = "500 Internal Server Error"

    header = (
        "HTTP/1.1 %s\r\n"
        "Content-Type: text/plain; charset=utf-8\r\n"
        "Connection: close\r\n\r\n"
    ) % code
    cl.send(header)
    cl.send(body)


def start_server():
    addr = socket.getaddrinfo("0.0.0.0", config.HTTP_PORT)[0][-1]
    s = socket.socket()
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(addr)
    s.listen(1)
    print("HTTP server listening on port", config.HTTP_PORT)

    while True:
        cl, remote = s.accept()
        try:
            req = cl.recv(512)
            if not req:
                cl.close()
                continue

            # Первая строка: "GET /path HTTP/1.1"
            try:
                line = req.split(b"\r\n", 1)[0]
                parts = line.split()
                method = parts[0]
                path = parts[1].decode()
            except Exception:
                method = b"GET"
                path = "/"

            if path.startswith("/api/status"):
                _handle_api_status(cl)
            elif path.startswith("/api/restart") and method in (b"POST", b"GET"):
                _handle_api_restart(cl)
            elif path.startswith("/api/mode") and method in (b"POST", b"GET"):
                _handle_api_mode(cl, path)
            else:
                _handle_root(cl)

        except Exception as e:
            print("HTTP error:", e)
        finally:
            cl.close()


def run_server(host="0.0.0.0", port=config.HTTP_PORT):
    """
    Обёртка для совместимости с boot.py.
    host/port сейчас игнорируем, но при желании можно прокинуть их в start_server().
    """
    start_server()
