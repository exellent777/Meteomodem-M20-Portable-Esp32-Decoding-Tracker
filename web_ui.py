# web_ui.py — живой Web UI для M20 Tracker
# - Живое обновление через /status (JS fetch)
# - Умный ввод частоты (405.400 / 405400 / 405400000)
# - Чёткий статус: SCAN / FIXED
# - Полная частота в Гц и МГц

import socket
import time
import config
from track_store import track
from sonde_data import sonde

try:
    import ujson as json
except ImportError:
    import json


# ------------------------------------------------------
# HTML-страница (отдаётся один раз, дальше всё делает JS)
# ------------------------------------------------------
PAGE = """\
<html>
<head>
<meta charset="utf-8">
<title>M20 Tracker</title>
<style>
body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Arial, sans-serif;
    background: #181a1f;
    color: #e0e0e0;
    margin: 0;
    padding: 0;
}
.header {
    padding: 12px 18px;
    background: #20232a;
    border-bottom: 1px solid #30343c;
}
.header h2 {
    margin: 0;
}
.container {
    padding: 10px;
}
.card {
    background: #20232a;
    padding: 12px 14px;
    margin: 10px 0;
    border-radius: 8px;
    box-shadow: 0 0 6px rgba(0,0,0,0.4);
}
h3 {
    margin-top: 0;
}
label {
    display: inline-block;
    min-width: 150px;
}
input {
    font-size: 16px;
    padding: 4px 6px;
    border-radius: 4px;
    border: 1px solid #444;
    background: #111;
    color: #eee;
}
button {
    font-size: 15px;
    padding: 5px 10px;
    margin-left: 4px;
    border-radius: 4px;
    border: 1px solid #555;
    background: #2b5fd9;
    color: #fff;
}
button.secondary {
    background: #444;
}
.status-pill {
    display: inline-block;
    padding: 2px 8px;
    border-radius: 999px;
    font-size: 13px;
    margin-left: 6px;
}
.status-fixed {
    background: #2b5fd9;
}
.status-scan {
    background: #ffaa33;
}
.status-bad {
    background: #aa3333;
}
.good { color: #55ff55; }
.bad  { color: #ff5555; }
.mid  { color: #ffd966; }
.mono { font-family: "SF Mono", "Consolas", "Menlo", monospace; }
.row {
    display: flex;
    flex-wrap: wrap;
}
.col {
    flex: 1;
    min-width: 220px;
    padding-right: 10px;
}
</style>
<script>
function fmt(v, digits) {
    if (v === null || v === undefined) return "—";
    if (typeof v === "number") {
        if (digits !== undefined) return v.toFixed(digits);
        return v.toString();
    }
    return v;
}

async function refreshStatus() {
    try {
        const r = await fetch("/status");
        const j = await r.json();

        // Режим
        const modeSpan = document.getElementById("mode");
        const pill = document.getElementById("mode_pill");
        if (j.mode === "fixed_freq") {
            modeSpan.innerText = "FIXED";
            pill.innerText = "FIXED";
            pill.className = "status-pill status-fixed";
        } else {
            modeSpan.innerText = "SCAN";
            pill.innerText = "SCAN";
            pill.className = "status-pill status-scan";
        }

        // Частота
        document.getElementById("freq_hz").innerText  = fmt(j.freq_hz, 0);
        document.getElementById("freq_mhz").innerText = fmt(j.freq_mhz, 3);

        // RF
        document.getElementById("rssi").innerText   = fmt(j.rssi, 1);
        document.getElementById("rssi_f").innerText = fmt(j.rssi_filt, 1);
        document.getElementById("noise").innerText  = fmt(j.noise, 1);
        const sigEl = document.getElementById("signal");
        sigEl.innerText = j.signal ? "ДА" : "нет";
        sigEl.className = j.signal ? "good" : "bad";

        // Кадр
        document.getElementById("last_time").innerText = fmt(j.last_timestamp, 0);
        document.getElementById("lat").innerText       = fmt(j.lat, 6);
        document.getElementById("lon").innerText       = fmt(j.lon, 6);
        document.getElementById("alt").innerText       = fmt(j.alt, 1);
        document.getElementById("vspeed").innerText    = fmt(j.vspeed, 2);
        document.getElementById("hspeed").innerText    = fmt(j.hspeed, 2);
        document.getElementById("temp").innerText      = fmt(j.temp, 2);
        document.getElementById("hum").innerText       = fmt(j.humidity, 1);
        document.getElementById("bat").innerText       = fmt(j.battery, 0);
    } catch (e) {
        // тихо игнорируем сетевые ошибки
    }
}

async function setFixed() {
    const val = document.getElementById("freq_input").value.trim();
    if (!val) return;
    await fetch("/set_fixed?freq=" + encodeURIComponent(val));
    setTimeout(refreshStatus, 500);
}

async function setScan() {
    await fetch("/set_scan");
    setTimeout(refreshStatus, 500);
}

window.onload = function () {
    refreshStatus();
    setInterval(refreshStatus, 1000);
};
</script>
</head>

<body>
<div class="header">
  <h2>M20 Tracker Web UI</h2>
</div>
<div class="container">

<div class="card">
  <h3>Режим и частота</h3>
  <div>
    <b>Режим:</b> <span id="mode">—</span>
    <span id="mode_pill" class="status-pill status-bad">—</span>
  </div>
  <div class="mono">
    <b>Текущая частота:</b>
    <span id="freq_hz">—</span> Гц
    (<span id="freq_mhz">—</span> МГц)
  </div>
  <br>
  <div>
    <label>Ручной ввод (Гц / МГц):</label>
    <input id="freq_input" type="text" placeholder="405.400 или 405400000">
    <button onclick="setFixed()">FIXED</button>
    <button class="secondary" onclick="setScan()">SCAN</button>
  </div>
</div>

<div class="card">
  <h3>RF мониторинг</h3>
  <div class="row">
    <div class="col">
      RSSI raw: <span id="rssi">—</span> dBm<br>
      RSSI фильтр.: <span id="rssi_f">—</span> dBm<br>
      Уровень шума: <span id="noise">—</span> dBm<br>
      Сигнал: <span id="signal" class="mid">—</span><br>
    </div>
  </div>
</div>

<div class="card">
  <h3>Последний принятый кадр</h3>
  Время (timestamp): <span id="last_time">—</span><br><br>

  <div class="row">
    <div class="col">
      <b>Координаты:</b><br>
      lat: <span id="lat">—</span><br>
      lon: <span id="lon">—</span><br>
      alt: <span id="alt">—</span> м<br><br>
    </div>
    <div class="col">
      <b>Скорости:</b><br>
      V: <span id="vspeed">—</span> м/с<br>
      H: <span id="hspeed">—</span> м/с<br><br>
      <b>Погода:</b><br>
      T: <span id="temp">—</span> °C<br>
      RH: <span id="hum">—</span> %<br><br>
      <b>Батарея:</b> <span id="bat">—</span> мВ<br>
    </div>
  </div>
</div>

</div>
</body>
</html>
"""


# ------------------------------------------------------
# Формирование статуса для /status (JSON)
# ------------------------------------------------------
def _status_dict():
    mode, fixed_freq = track.get_rf_control_mode()
    last = sonde.as_dict()

    freq_hz = track.rf_frequency_hz
    if freq_hz is None and fixed_freq:
        freq_hz = fixed_freq

    if freq_hz:
        freq_mhz = freq_hz / 1_000_000.0
    else:
        freq_mhz = None

    return {
        "mode": mode,
        "freq_hz": freq_hz,
        "freq_mhz": freq_mhz,
        "rssi": track.rf_rssi_dbm,
        "rssi_filt": track.rf_rssi_filt,
        "noise": track.noise_floor,
        "signal": track.signal_present,
        "last_timestamp": last["timestamp"],
        "lat": last["lat"],
        "lon": last["lon"],
        "alt": last["alt"],
        "vspeed": last["vspeed"],
        "hspeed": last["hspeed"],
        "temp": last["temp"],
        "humidity": last["humidity"],
        "battery": last["battery"],
    }


# ------------------------------------------------------
# Парсер частоты из строки
#  - "405.400"    -> 405400000
#  - "405400"     -> 405400000
#  - "405400000"  -> 405400000
# ------------------------------------------------------
def _parse_freq_hz(s):
    s = s.strip().replace(",", ".")
    if not s:
        return None

    # Есть точка → явно MHz
    if "." in s:
        try:
            mhz = float(s)
            return int(mhz * 1_000_000)
        except:
            return None

    # Только цифры
    try:
        v = int(s)
    except:
        return None

    # Если число маленькое (< 1e6), трактуем как кГц (405400 -> 405.4 MHz)
    if v < 1_000_000:
        return v * 1000
    else:
        # Уже в Гц
        return v


# ------------------------------------------------------
# Обработка команд управления режимом
# ------------------------------------------------------
def _handle_command(first_line):
    # /set_fixed?freq=...
    if first_line.startswith("GET /set_fixed"):
        try:
            path = first_line.split(" ", 2)[1]  # "/set_fixed?freq=..."
            if "freq=" in path:
                part = path.split("freq=", 1)[1]
                val = ""
                for ch in part:
                    if ch in "0123456789.,":  # допускаем точку и запятую
                        val += ch
                    else:
                        break
                freq = _parse_freq_hz(val)
                if freq:
                    track.set_rf_control_mode("fixed_freq", freq)
        except Exception as e:
            print("WEB set_fixed error:", e)

    # /set_scan
    elif first_line.startswith("GET /set_scan"):
        track.set_rf_control_mode("auto_scan")


# ------------------------------------------------------
# HTTP сервер
# ------------------------------------------------------
def start_server():
    addr = socket.getaddrinfo("0.0.0.0", config.HTTP_PORT)[0][-1]
    s = socket.socket()
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    try:
        s.bind(addr)
        s.listen(2)
        print("HTTP server listening on port", config.HTTP_PORT)
    except Exception as e:
        print("Web UI: bind error:", e)
        return

    while True:
        try:
            client, a = s.accept()
            req = client.recv(1024).decode("utf-8", "ignore")
            if not req:
                client.close()
                continue

            first_line = req.split("\r\n", 1)[0]

            # JSON статус
            if first_line.startswith("GET /status"):
                st = _status_dict()
                body = json.dumps(st)
                client.send("HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nConnection: close\r\n\r\n")
                client.send(body)
                client.close()
                continue

            # Команды управления режимом
            if first_line.startswith("GET /set_fixed") or first_line.startswith("GET /set_scan"):
                _handle_command(first_line)
                client.send("HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\nConnection: close\r\n\r\nOK")
                client.close()
                continue

            # Основная страница "/"
            client.send("HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nConnection: close\r\n\r\n")
            client.sendall(PAGE)
            client.close()

        except Exception as e:
            print("Web UI client error:", e)
            try:
                client.close()
            except:
                pass
            time.sleep_ms(100)
