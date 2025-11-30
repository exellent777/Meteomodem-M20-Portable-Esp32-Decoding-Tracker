# web_ui.py
# Веб-интерфейс для ESP32-C3 M20 Tracker.
#
# Эндпоинты:
#   GET  /               -> HTML-страница с JS
#   GET  /api/status     -> JSON со статусом
#   POST /api/restart    -> запрос перезапуска поиска
#   POST /api/mode/scan  -> включить режим сканирования диапазона (auto_scan)
#   POST /api/mode/fixed -> включить режим фиксированной частоты (fixed_freq)
#   POST /api/set_freq   -> выставить фикс. частоту (MHz) и включить fixed-режим

import socket
import time
import json
import config
import track_store


def _build_status_dict():
    """
    Собираем словарь со статусом для JSON API.
    """
    latest = track_store.latest

    # Время последнего кадра (человекочитаемое) и возраст данных
    if getattr(latest, "time", None):
        t = time.localtime(latest.time)
        ts = "%04d-%02d-%02d %02d:%02d:%02d" % (
            t[0], t[1], t[2], t[3], t[4], t[5]
        )
        age = max(0, int(time.time() - latest.time))
    else:
        ts = None
        age = None

    has_pos = (
        getattr(latest, "lat", None) is not None
        and getattr(latest, "lon", None) is not None
    )

    # Радиостатус и режимы
    rf_freq_hz = getattr(track_store, "rf_frequency_hz", None)
    rf_rssi_dbm = getattr(track_store, "rf_rssi_dbm", None)
    rf_mode = getattr(track_store, "rf_mode", "idle")
    rf_noise_rssi_dbm = getattr(track_store, "rf_noise_rssi_dbm", None)
    rf_signal_threshold_dbm = getattr(track_store, "rf_signal_threshold_dbm", None)
    rf_lost_counter = getattr(track_store, "rf_lost_counter", 0)
    rf_had_signal = getattr(track_store, "rf_had_signal", False)

    try:
        rf_control_mode, rf_fixed_freq_hz = track_store.get_rf_control_mode()
    except AttributeError:
        rf_control_mode = getattr(track_store, "rf_control_mode", "auto_scan")
        rf_fixed_freq_hz = getattr(track_store, "fixed_freq_hz", None)

    need_restart = getattr(track_store, "need_restart", False)

    return {
        "ts": ts,
        "age_sec": age,
        "has_position": has_pos,
        "lat": getattr(latest, "lat", None),
        "lon": getattr(latest, "lon", None),
        "alt": getattr(latest, "alt", None),
        "track_len": len(track_store.track),

        "rf_freq_hz": rf_freq_hz,
        "rf_rssi_dbm": rf_rssi_dbm,
        "rf_mode": rf_mode,
        "rf_noise_rssi_dbm": rf_noise_rssi_dbm,
        "rf_signal_threshold_dbm": rf_signal_threshold_dbm,
        "rf_lost_counter": rf_lost_counter,
        "rf_had_signal": rf_had_signal,

        "rf_control_mode": rf_control_mode,
        "rf_fixed_freq_hz": rf_fixed_freq_hz,
        "need_restart": need_restart,
    }


def _html_page():
    """
    Одностраничный интерфейс: JS опрашивает /api/status и
    по кнопкам шлёт /api/restart, /api/mode/* и /api/set_freq.
    """
    base_mhz = config.RF_FREQUENCY_HZ / 1e6
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
      min-width: 230px;
      flex: 1 1 230px;
      box-sizing: border-box;
    }
    .card-title {
      font-size: 12px;
      font-weight: 600;
      margin-bottom: 6px;
      color: #e5e7eb;
    }
    .card-body {
      font-size: 11px;
      color: #9ca3af;
      line-height: 1.5;
    }
    .muted {
      color: #6b7280;
    }
    .value {
      color: #e5e7eb;
      font-weight: 500;
    }
    .controls {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-top: 6px;
      align-items: center;
    }
    button {
      font-size: 11px;
      border-radius: 999px;
      border: 1px solid #1f2937;
      background: #111827;
      color: #e5e7eb;
      padding: 4px 10px;
      cursor: pointer;
    }
    button.primary {
      background: #16a34a;
      border-color: #16a34a;
      color: #ecfdf5;
    }
    button.danger {
      background: #b91c1c;
      border-color: #b91c1c;
      color: #fee2e2;
    }
    button:disabled {
      opacity: 0.5;
      cursor: default;
    }
    input.freq {
      width: 80px;
      padding: 3px 6px;
      border-radius: 999px;
      border: 1px solid #1f2937;
      background: #020617;
      color: #e5e7eb;
      font-size: 11px;
      text-align: center;
    }
    .status-line {
      margin-top: 10px;
      font-size: 11px;
      color: #9ca3af;
    }
    .status-line span.value {
      color: #e5e7eb;
    }
  </style>
</head>
<body>
  <header>
    <div>
      <div class="title">M20 Tracker</div>
      <div class="subtitle">ESP32-C3 + CC1101 · Web UI</div>
    </div>
    <div id="status-led" class="subtitle">offline</div>
  </header>
  <main>
    <div class="cards-row">
      <div class="card">
        <div class="card-title">Зонд</div>
        <div class="card-body" id="card-sonde">
          Нет данных
        </div>
      </div>
      <div class="card">
        <div class="card-title">Радио</div>
        <div class="card-body" id="card-radio">
          ...
        </div>
      </div>
      <div class="card">
        <div class="card-title">Режим</div>
        <div class="card-body">
          <div class="controls">
            <button id="btn-mode-scan">AUTO SCAN</button>
            <button id="btn-mode-fixed">FIXED</button>
            <button id="btn-restart" class="danger">Перезапустить поиск</button>
          </div>
          <div class="controls" style="margin-top:6px;">
            <input id="freq-input" class="freq" type="number" step="0.001" min="400" max="410" value="%.3f" />
            <button id="btn-set-freq" class="primary">SET MHz</button>
          </div>
          <div class="status-line" id="mode-info"></div>
        </div>
      </div>
    </div>
    <div class="status-line" id="last-info"></div>
  </main>
  <script>
    function formatNumber(v, digits) {
      if (v === null || v === undefined) return "—";
      return v.toFixed(digits);
    }

    function formatRssi(r) {
      if (r === null || r === undefined) return "—";
      return r.toFixed(1) + " dBm";
    }

    function updateUI(status) {
      var led = document.getElementById("status-led");
      var cardSonde = document.getElementById("card-sonde");
      var cardRadio = document.getElementById("card-radio");
      var modeInfo = document.getElementById("mode-info");
      var lastInfo = document.getElementById("last-info");
      var freqInput = document.getElementById("freq-input");

      if (!status || status.error) {
        led.textContent = "offline";
        if (cardSonde) cardSonde.textContent = "Нет данных";
        if (cardRadio) cardRadio.textContent = "Нет данных";
        if (modeInfo) modeInfo.textContent = "Нет связи с трекером.";
        return;
      }

      led.textContent = "online";

      // Зонд
      if (cardSonde) {
        if (status.has_position) {
          cardSonde.innerHTML =
            "Lat: <span class='value'>" + formatNumber(status.lat, 5) + "</span><br>" +
            "Lon: <span class='value'>" + formatNumber(status.lon, 5) + "</span><br>" +
            "Alt: <span class='value'>" + (status.alt !== null ? status.alt : "—") + "</span> m<br>" +
            "Точек в треке: <span class='value'>" + status.track_len + "</span><br>" +
            "Обновлено: <span class='value'>" + (status.ts || "—") + "</span><br>" +
            "Возраст: <span class='value'>" + (status.age_sec !== null ? status.age_sec + " с" : "—") + "</span>";
        } else {
          cardSonde.innerHTML = "Позиция ещё не получена.";
        }
      }

      // Радио
      if (cardRadio) {
        var mhz = status.rf_freq_hz ? (status.rf_freq_hz / 1e6).toFixed(3) + " MHz" : "—";
        var mode = status.rf_mode || "idle";
        var rssi = formatRssi(status.rf_rssi_dbm);
        var noise = formatRssi(status.rf_noise_rssi_dbm);
        var thr = formatRssi(status.rf_signal_threshold_dbm);
        var lost = status.rf_lost_counter || 0;
        var had = status.rf_had_signal ? "да" : "нет";
        cardRadio.innerHTML =
          "Частота: <span class='value'>" + mhz + "</span><br>" +
          "RSSI: <span class='value'>" + rssi + "</span><br>" +
          "Шум: <span class='value'>" + noise + "</span><br>" +
          "Порог: <span class='value'>" + thr + "</span><br>" +
          "Потери: <span class='value'>" + lost + "</span><br>" +
          "Был сигнал: <span class='value'>" + had + "</span><br>" +
          "Режим RF: <span class='value'>" + mode + "</span>";
      }

      // Информация о режиме управления частотой
      if (modeInfo) {
        var cm = status.rf_control_mode || "auto_scan";
        var cmt = (cm === "fixed_freq") ? "FIXED" : "AUTO SCAN";
        var fixMhz = status.rf_fixed_freq_hz ? (status.rf_fixed_freq_hz / 1e6).toFixed(3) + " MHz" : "—";
        modeInfo.textContent =
          "Режим поиска: " + cmt +
          ", фиксированная частота: " + fixMhz +
          (status.need_restart ? " · ожидается перезапуск" : "");
      }

      if (freqInput && status.rf_fixed_freq_hz) {
        freqInput.value = (status.rf_fixed_freq_hz / 1e6).toFixed(3);
      }

      if (lastInfo) {
        lastInfo.textContent = "Последний статус обновлён: " + (new Date()).toLocaleTimeString();
      }
    }

    function poll() {
      fetch("/api/status")
        .then(function(resp) { return resp.json(); })
        .then(function(json) { updateUI(json); })
        .catch(function(err) {
          console.log("status error:", err);
          updateUI(null);
        })
        .finally(function() {
          setTimeout(poll, 1000);
        });
    }

    function setupControls() {
      var btnRestart = document.getElementById("btn-restart");
      var btnModeScan = document.getElementById("btn-mode-scan");
      var btnModeFixed = document.getElementById("btn-mode-fixed");
      var btnSetFreq = document.getElementById("btn-set-freq");
      var freqInput = document.getElementById("freq-input");
      var infoEl = document.getElementById("mode-info");

      if (btnRestart) {
        btnRestart.addEventListener("click", function() {
          fetch("/api/restart", { method: "POST" })
            .then(function(resp) { return resp.text(); })
            .then(function(text) {
              infoEl.textContent = "Запрошен перезапуск поиска...";
            })
            .catch(function(err) {
              console.log("restart error:", err);
              infoEl.textContent = "Ошибка при запросе перезапуска.";
            });
        });
      }

      function setMode(mode) {
        var url = "/api/mode/" + encodeURIComponent(mode);
        infoEl.textContent = "Переключаю режим на " + mode.toUpperCase() + "...";
        fetch(url, { method: "POST" })
          .then(function(resp) { return resp.text(); })
          .then(function(text) {
            infoEl.textContent = "Режим переключён: " + mode.toUpperCase() + ".";
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

      if (btnSetFreq && freqInput) {
        btnSetFreq.addEventListener("click", function() {
          var v = parseFloat(freqInput.value);
          if (isNaN(v) || v < 400 || v > 410) {
            infoEl.textContent = "Введите частоту в MHz в разумных пределах (400–410).";
            return;
          }
          infoEl.textContent = "Устанавливаю частоту " + v.toFixed(3) + " MHz...";
          var url = "/api/set_freq?mhz=" + encodeURIComponent(v.toFixed(3));
          fetch(url, { method: "POST" })
            .then(function(resp) { return resp.text(); })
            .then(function(text) {
              infoEl.textContent = "Фиксированная частота обновлена: " + v.toFixed(3) + " MHz.";
            })
            .catch(function(err) {
              console.log("set_freq error:", err);
              infoEl.textContent = "Ошибка при установке частоты.";
            });
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
""" % (base_mhz)


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
        ui_mode = "scan"
        if path.startswith("/api/mode/"):
            tail = path[len("/api/mode/"):]
            if tail.startswith("fixed"):
                ui_mode = "fixed"
            elif tail.startswith("scan"):
                ui_mode = "scan"
            else:
                raise ValueError("unknown mode '%s'" % tail)
        else:
            if "mode=fixed" in path:
                ui_mode = "fixed"
            elif "mode=scan" in path:
                ui_mode = "scan"

        if ui_mode == "scan":
            # Авто-сканирование диапазона
            track_store.set_rf_control_mode("auto_scan", None)
        else:
            # FIXED: оставляем текущую фиксированную частоту
            try:
                cur_mode, cur_freq = track_store.get_rf_control_mode()
            except AttributeError:
                cur_mode, cur_freq = "auto_scan", None

            if cur_freq is None:
                cur_freq = getattr(config, "RF_FREQUENCY_HZ", 405400000)

            track_store.set_rf_control_mode("fixed_freq", cur_freq)

        # После смены режима просим main.py перезапуститься
        track_store.request_restart()

        body = "OK %s" % ui_mode
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


def _handle_api_set_freq(cl, path: str):
    """
    Обработчик /api/set_freq?mhz=405.403 — установить фиксированную частоту
    (в MHz), перевести трекер в FIXED-режим и запросить перезапуск.
    """
    try:
        mhz = None
        # Простейший парсер query string
        idx = path.find("mhz=")
        if idx != -1:
            sub = path[idx + 4:]
            # отрезаем по '&', если есть
            amp = sub.find("&")
            if amp != -1:
                sub = sub[:amp]
            mhz = float(sub)

        if mhz is None:
            raise ValueError("mhz not specified")

        hz = int(mhz * 1e6)

        # Устанавливаем режим фиксированной частоты
        track_store.set_rf_control_mode("fixed_freq", hz)
        # Просим основной цикл перезапуститься
        track_store.request_restart()

        body = "OK %.3f MHz" % mhz
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
            elif path.startswith("/api/set_freq") and method in (b"POST", b"GET"):
                _handle_api_set_freq(cl, path)
            else:
                _handle_root(cl)

        except Exception as e:
            print("HTTP error:", e)
        finally:
            cl.close()


def run_server(host="0.0.0.0", port=config.HTTP_PORT):
    """
    Обёртка для совместимости с boot.py.
    """
    start_server()
