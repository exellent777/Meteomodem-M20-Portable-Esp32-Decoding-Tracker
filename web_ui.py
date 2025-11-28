# web_ui.py
# Веб-интерфейс для ESP32-C3 M20 Tracker.
#
# Эндпоинты:
#   GET  /             -> HTML-страница с JS
#   GET  /api/status   -> JSON со статусом (позиция, частота, RSSI)
#   POST /api/restart  -> установить флаг "перезапустить поиск" (для main.py)
#
# Работает на обычных сокетах MicroPython.

import socket
import time
import json
import config
import track_store  # вместо from track_store import ...


def _build_status_dict():
    """
    Готовим словарь со статусом для JSON API.
    """
    latest = track_store.latest

    if latest.time:
        t = time.localtime(latest.time)
        ts = "%04d-%02d-%02d %02d:%02d:%02d" % (
            t[0], t[1], t[2], t[3], t[4], t[5]
        )
    else:
        ts = None

    # DATA_POS = 0x04
    has_pos = bool(latest.fields & 0x04)

    return {
        "timestamp": ts,
        "has_position": has_pos,
        "lat": latest.lat,
        "lon": latest.lon,
        "alt": latest.alt,
        "rf_freq_hz": track_store.rf_freq_hz,
        "rf_rssi_dbm": track_store.rf_rssi_dbm,
    }


def _html_page():
    """
    Одностраничный интерфейс: JS опрашивает /api/status и
    по кнопке шлёт /api/restart.
    """
    return """<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8" />
  <title>M20 Tracker</title>
  <style>
    body {
      font-family: sans-serif;
      background: #0e141b;
      color: #e0e0e0;
      margin: 0;
      padding: 0;
    }
    header {
      padding: 12px 16px;
      background: #151c25;
      border-bottom: 1px solid #222a35;
      display: flex;
      align-items: center;
      justify-content: space-between;
    }
    h1 {
      margin: 0;
      font-size: 20px;
      color: #5fd7ff;
    }
    .btn {
      padding: 6px 10px;
      font-size: 13px;
      border-radius: 6px;
      border: 1px solid #374151;
      background: #1f2937;
      color: #e5e7eb;
      cursor: pointer;
    }
    .btn:hover {
      background: #111827;
    }
    .container {
      padding: 16px;
    }
    .card {
      background: #151c25;
      border: 1px solid #222a35;
      border-radius: 8px;
      padding: 12px 16px;
      margin-bottom: 12px;
    }
    .card h2 {
      margin: 0 0 8px 0;
      font-size: 16px;
      color: #9ad9ff;
    }
    .kv {
      display: flex;
      justify-content: space-between;
      margin: 4px 0;
      font-size: 14px;
    }
    .kv span.label {
      color: #9ca3af;
    }
    .kv span.value {
      font-weight: 500;
    }
    .status-ok {
      color: #4ade80;
    }
    .status-bad {
      color: #fb7185;
    }
    .rssi-bar {
      position: relative;
      width: 100%;
      height: 20px;
      background: #111827;
      border-radius: 10px;
      overflow: hidden;
      border: 1px solid #1f2933;
      margin-top: 6px;
    }
    .rssi-bar-inner {
      position: absolute;
      top: 0;
      left: 0;
      height: 100%;
      width: 0%;
      background: linear-gradient(90deg, #22c55e, #f97316, #ef4444);
      transition: width 0.2s ease-out;
    }
    .rssi-label {
      text-align: right;
      font-size: 12px;
      color: #9ca3af;
      margin-top: 2px;
    }
    .small {
      font-size: 12px;
      color: #6b7280;
    }
  </style>
</head>
<body>
  <header>
    <h1>Meteomodem M20 – ESP32-C3 Tracker</h1>
    <button class="btn" onclick="restartSearch()">Перезапустить поиск</button>
  </header>
  <div class="container">

    <div class="card">
      <h2>Состояние зонда</h2>
      <div class="kv">
        <span class="label">Последнее обновление</span>
        <span class="value" id="ts">—</span>
      </div>
      <div class="kv">
        <span class="label">Статус</span>
        <span class="value" id="status">нет данных</span>
      </div>
    </div>

    <div class="card">
      <h2>Координаты</h2>
      <div class="kv">
        <span class="label">Latitude</span>
        <span class="value" id="lat">—</span>
      </div>
      <div class="kv">
        <span class="label">Longitude</span>
        <span class="value" id="lon">—</span>
      </div>
      <div class="kv">
        <span class="label">Altitude</span>
        <span class="value" id="alt">—</span>
      </div>
      <div class="small">Высота в метрах по данным зонда.</div>
    </div>

    <div class="card">
      <h2>Радиоканал</h2>
      <div class="kv">
        <span class="label">Частота приёма</span>
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
      <div class="small">
        Бар показывает относительное качество сигнала:
        от шумового уровня до сильного зонда.
      </div>
    </div>

  </div>

  <script>
    function formatFreq(hz) {
      if (hz === null || hz === undefined) return "—";
      return (hz / 1e6).toFixed(3) + " MHz";
    }

    function formatAlt(alt) {
      if (alt === null || alt === undefined) return "—";
      return alt.toFixed(1) + " m";
    }

    function formatLatLon(x) {
      if (x === null || x === undefined) return "—";
      return x.toFixed(6);
    }

    function mapRssiToPercent(rssi) {
      // Простейшее отображение:
      // -110 dBm -> 0%
      // -90 dBm  -> 50%
      // -70 dBm  -> 100%
      if (rssi === null || rssi === undefined) return 0;
      var min = -110.0;
      var max = -70.0;
      var v = (rssi - min) / (max - min);
      if (v < 0) v = 0;
      if (v > 1) v = 1;
      return Math.round(v * 100);
    }

    function updateUI(data) {
      var tsEl = document.getElementById("ts");
      var statusEl = document.getElementById("status");
      var latEl = document.getElementById("lat");
      var lonEl = document.getElementById("lon");
      var altEl = document.getElementById("alt");
      var freqEl = document.getElementById("freq");
      var rssiEl = document.getElementById("rssi");
      var rssiBar = document.getElementById("rssiBar");
      var rssiLabel = document.getElementById("rssiLabel");

      tsEl.textContent = data.timestamp || "нет данных";

      if (data.has_position) {
        statusEl.textContent = "позиция получена";
        statusEl.className = "value status-ok";
      } else {
        statusEl.textContent = "зонд не обнаружен";
        statusEl.className = "value status-bad";
      }

      latEl.textContent = formatLatLon(data.lat);
      lonEl.textContent = formatLatLon(data.lon);
      altEl.textContent = formatAlt(data.alt);

      freqEl.textContent = formatFreq(data.rf_freq_hz);

      if (data.rf_rssi_dbm === null || data.rf_rssi_dbm === undefined) {
        rssiEl.textContent = "—";
        rssiBar.style.width = "0%";
        rssiLabel.textContent = "уровень сигнала";
      } else {
        rssiEl.textContent = data.rf_rssi_dbm.toFixed(1) + " dBm";
        var p = mapRssiToPercent(data.rf_rssi_dbm);
        rssiBar.style.width = p + "%";
        rssiLabel.textContent = "уровень сигнала: " + p + " %";
      }
    }

    function poll() {
      fetch("/api/status")
        .then(function(resp) { return resp.json(); })
        .then(function(data) { updateUI(data); })
        .catch(function(err) {
          console.log("poll error:", err);
        })
        .finally(function() {
          setTimeout(poll, 500);
        });
    }

    function restartSearch() {
      fetch("/api/restart", {
        method: "POST"
      }).catch(function(err) {
        console.log("restart error:", err);
      });
    }

    window.addEventListener("load", function() {
      poll();
    });
  </script>
</body>
</html>
"""


def _handle_api_status(cl):
    """
    Обработчик /api/status: отдаём JSON.
    """
    status = _build_status_dict()
    body = json.dumps(status)
    header = (
        "HTTP/1.1 200 OK\r\n"
        "Content-Type: application/json\r\n"
        "Connection: close\r\n\r\n"
    )
    cl.send(header)
    cl.send(body)


def _handle_api_restart(cl):
    """
    Обработчик /api/restart: ставим флаг перезапуска поиска.
    """
    track_store.request_restart()
    body = json.dumps({"ok": True})
    header = (
        "HTTP/1.1 200 OK\r\n"
        "Content-Type: application/json\r\n"
        "Connection: close\r\n\r\n"
    )
    cl.send(header)
    cl.send(body)


def _handle_root(cl):
    """
    Обработчик /: отдаём HTML-интерфейс.
    """
    body = _html_page()
    header = (
        "HTTP/1.1 200 OK\r\n"
        "Content-Type: text/html; charset=utf-8\r\n"
        "Connection: close\r\n\r\n"
    )
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

            try:
                line = req.split(b"\r\n", 1)[0]
            except Exception:
                line = b""

            # Примитивный роутер по первой строке HTTP-запроса
            if b"GET /api/status" in line:
                _handle_api_status(cl)
            elif b"POST /api/restart" in line:
                _handle_api_restart(cl)
            else:
                # Всё остальное считаем запросом на корень
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
