# web_ui.py — расширенный Web UI для M20 трекера (MicroPython ESP32-C3)
import socket
import ujson as json
import time


PAGE = (
    "HTTP/1.1 200 OK\r\n"
    "Content-Type: text/html\r\n\r\n"
    "<html><head><meta charset='utf-8'><title>M20 Tracker</title></head>"
    "<body style='font-family:sans-serif;background:#f4f4f4'>"
    "<h2>M20 Tracker</h2>"

    "<div style='background:white;padding:10px;border-radius:8px;margin-bottom:10px;'>"
    "<h3>Состояние</h3>"
    "<div id='state'>State: —</div>"
    "<div id='mode_fixed'>FIXED: —</div>"
    "<div id='freq'>Freq: —</div>"
    "<div id='afc_conf'>AFC confirmed: —</div>"
    "<div id='afc_streak'>AFC streak: —</div>"
    "</div>"

    "<div style='background:white;padding:10px;border-radius:8px;margin-bottom:10px;'>"
    "<h3>Радио</h3>"
    "<div id='rssi'>RSSI: —</div>"
    "<div id='raw_rssi'>Raw RSSI: —</div>"
    "<div id='noise'>Noise: —</div>"
    "<div id='snr'>SNR: —</div>"
    "<div id='signal'>Signal: —</div>"
    "<div id='freqest'>FREQEST/Δf: —</div>"
    "</div>"

    "<div style='background:white;padding:10px;border-radius:8px;margin-bottom:10px;'>"
    "<h3>Кадры M20</h3>"
    "<div id='frames'>Frames: —</div>"
    "<div id='sync_hits'>Sync hits: —</div>"
    "<div id='last_shift'>Last valid shift: —</div>"
    "<div id='last_age'>Last frame age: —</div>"
    "</div>"

    "<div style='background:white;padding:10px;border-radius:8px;margin-bottom:10px;'>"
    "<h3>Телеметрия</h3>"
    "<div id='lat'>lat: —</div>"
    "<div id='lon'>lon: —</div>"
    "<div id='alt'>alt: —</div>"
    "<div id='batt'>Vbat: —</div>"
    "</div>"

    "<div style='background:white;padding:10px;border-radius:8px;margin-bottom:10px;'>"
    "<h3>Управление частотой (FIXED)</h3>"
    "<form action='/set?' method='GET'>"
    "<input name='f' placeholder='405400000 или 405.4M или 405400k' size='32'>"
    "<input type='submit' value='SET FIXED'>"
    "</form>"
    "<br>"
    "<a href='/clear'>Сброс FIXED (SCAN)</a>"
    "</div>"

    "<script>"
    "async function upd(){"
    " try{"
    "  let r = await fetch('/status');"
    "  let j = await r.json();"
    "  document.getElementById('state').innerText = 'State: ' + j.state;"
    "  document.getElementById('mode_fixed').innerText = 'FIXED: ' + (j.fixed ? 'YES' : 'NO');"
    "  document.getElementById('freq').innerText = 'Freq: ' + j.freq + ' Hz';"
    "  document.getElementById('afc_conf').innerText = 'AFC confirmed: ' + (j.afc_conf || '—');"
    "  document.getElementById('afc_streak').innerText = 'AFC streak: ' + j.afc_streak;"

    "  document.getElementById('rssi').innerText = 'RSSI: ' + (j.rssi === null ? '—' : j.rssi.toFixed(1) + ' dBm');"
    "  document.getElementById('raw_rssi').innerText = 'Raw RSSI: ' + (j.raw_rssi === null ? '—' : j.raw_rssi.toFixed(1) + ' dBm');"
    "  document.getElementById('noise').innerText = 'Noise: ' + (j.noise === null ? '—' : j.noise.toFixed(1) + ' dBm');"
    "  document.getElementById('snr').innerText = 'SNR: ' + (j.snr === null ? '—' : j.snr.toFixed(1) + ' dB');"
    "  document.getElementById('signal').innerText = 'Signal: ' + (j.signal ? 'есть' : 'нет');"

    "  document.getElementById('freqest').innerText = 'FREQEST: ' + j.afc_freqest + '  Δf: ' + j.afc_df + ' Hz';"

    "  document.getElementById('frames').innerText = 'Frames: total=' + j.frames_total + ', valid=' + j.frames_valid + ', crc_fail=' + j.frames_crc_fail;"
    "  document.getElementById('sync_hits').innerText = 'Sync hits: ' + j.sync_hits;"
    "  document.getElementById('last_shift').innerText = 'Last valid shift: ' + (j.last_shift === null ? '—' : j.last_shift);"
    "  document.getElementById('last_age').innerText = 'Last frame age: ' + (j.last_frame_age === null ? '—' : j.last_frame_age.toFixed(1) + ' s');"

    "  document.getElementById('lat').innerText = 'lat: ' + (j.lat === null ? '—' : j.lat);"
    "  document.getElementById('lon').innerText = 'lon: ' + (j.lon === null ? '—' : j.lon);"
    "  document.getElementById('alt').innerText = 'alt: ' + (j.alt === null ? '—' : j.alt + ' m');"
    "  document.getElementById('batt').innerText = 'Vbat: ' + (j.batt_v === null ? '—' : j.batt_v.toFixed(2) + ' V');"
    " }catch(e){}"
    "}"
    "setInterval(upd, 1000);"
    "</script>"

    "</body></html>"
)


def parse_freq(x):
    try:
        x = x.lower().strip()
        if x.endswith("mhz") or x.endswith("m"):
            return int(float(x.rstrip("mhz").rstrip("m")) * 1_000_000)
        if x.endswith("khz") or x.endswith("k"):
            return int(float(x.rstrip("khz").rstrip("k")) * 1000)
        if "." in x:
            return int(float(x))
        return int(x)
    except:
        return None


def start_server(tracker):
    print("[WEB] start on :80")

    addr = socket.getaddrinfo("0.0.0.0", 80)[0][-1]
    s = socket.socket()
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(addr)
    s.listen(2)

    while True:
        cl, addr = s.accept()
        try:
            req = cl.recv(512).decode()
        except:
            cl.close()
            continue

        if not req:
            cl.close()
            continue

        first = req.split("\n")[0]

        # ---------- STATUS ----------
        if "GET /status" in first:
            t = tracker
            d = {}

            # базовое состояние
            d["state"] = t.state
            d["fixed"] = t.fixed_mode
            d["freq"] = t.track.freq

            # радио
            d["rssi"] = t.track.rssi
            d["raw_rssi"] = getattr(t.track, "raw_rssi", None)
            d["noise"] = getattr(t.track, "noise", None)
            d["snr"] = getattr(t.track, "snr", None)
            d["signal"] = getattr(t.track, "signal", 0)

            # AFC
            d["afc_conf"] = t.afc.confirmed_freq
            d["afc_streak"] = t.afc.streak
            d["afc_freqest"] = t.afc.last_freqest
            d["afc_df"] = t.afc.last_df

            # статистика декодера
            dec = t.decoder
            d["frames_total"] = dec.frames_total
            d["frames_valid"] = dec.frames_valid
            d["frames_crc_fail"] = dec.frames_crc_fail
            d["sync_hits"] = dec.sync_hits
            d["last_shift"] = dec.last_valid_shift

            # возраст последнего успешного кадра
            if t.track.last_frame_time is not None:
                age_ms = time.ticks_diff(time.ticks_ms(), t.track.last_frame_time)
                d["last_frame_age"] = age_ms / 1000.0
            else:
                d["last_frame_age"] = None

            # телеметрия
            d["lat"] = t.track.last_lat
            d["lon"] = t.track.last_lon
            d["alt"] = t.track.last_alt
            d["batt_v"] = t.track.last_batt_v

            js = json.dumps(d)
            cl.send("HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n\r\n")
            cl.send(js)
            cl.close()
            continue

        # ---------- SET FIXED ----------
        if "GET /set?" in first:
            try:
                q = first.split("?", 1)[1]
                q = q.split(" ", 1)[0]
                kv = q.split("=")
                if len(kv) == 2:
                    f = parse_freq(kv[1])
                    if f:
                        print("[WEB] set FIXED freq:", f)
                        tracker.set_fixed_frequency(f)
            except:
                pass
            cl.send("HTTP/1.1 302 Found\r\nLocation: /\r\n\r\n")
            cl.close()
            continue

        # ---------- CLEAR FIXED ----------
        if "GET /clear" in first:
            tracker.clear_fixed_mode()
            cl.send("HTTP/1.1 302 Found\r\nLocation: /\r\n\r\n")
            cl.close()
            continue

        # ---------- MAIN PAGE ----------
        cl.sendall(PAGE)
        cl.close()
