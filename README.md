
## ESP32-C3 Meteomodem M20 Radiosonde Tracker (MicroPython)

This project turns an ESP32-C3 board plus a CC1101 RF module into a **standalone Meteomodem M20 radiosonde tracker** with Wi-Fi web UI, automatic band scan, and basic flight track logging. 

The firmware is written in MicroPython and is designed to sit in a box on the roof: once powered, it connects to Wi-Fi, starts an HTTP server with a simple dashboard, and continuously searches for M20 sondes around 405 MHz.

### Features

* **ESP32-C3 + CC1101 based receiver**

  * Custom MicroPython CC1101 driver:

    * 2-FSK, ~9.6 kbit/s, ≈100 kHz RX bandwidth
    * Infinite packet length (raw byte stream, no CC1101 packet engine)
    * On-chip RSSI in dBm for signal strength / noise estimation 

* **Automatic boot and Wi-Fi**

  * On power-up the board:

    * Connects to Wi-Fi using credentials from `config.py`
    * Starts the web UI in a separate thread
    * Enters the main tracking loop 

* **Local Web UI dashboard**

  * Built-in HTTP server on port 80
  * Single-page dashboard showing:

    * Last valid frame time, age, status, and track length
    * Latest position (lat/lon/alt) if available
    * Current RF frequency, RSSI with a signal bar, noise level estimate, signal threshold, lost-cycles counter, and state machine mode
  * Control buttons:

    * Switch between **scan mode** and **fixed-frequency mode**
    * Request **“restart search”** from the main loop
  * JSON API endpoints:

    * `GET /api/status` — current tracking and RF status
    * `POST /api/restart` — ask the tracker to re-enter scan
    * `POST /api/mode/{scan|fixed}` — change search mode 

* **AFC / band scan for M20 signals**

  * Scans **405.0–406.0 MHz** with a coarse step (50 kHz), measuring averaged RSSI
  * Picks the best candidate frequency and runs a **refined scan** around the peak with 5 kHz steps
  * Applies an RSSI threshold (`MIN_DETECT_RSSI`) to distinguish sondes from pure noise
  * In **fixed mode**, it just sits on a single frequency and decides whether a real signal is present based on averaged RSSI 

* **Robust M20 detection logic**

  * Main state machine:

    * **SCAN** — sweep the band until a candidate frequency with strong RSSI is found (via AFC)
    * **VALIDATE** — lock to that frequency and require several **consecutive valid M20 frames with CRC OK** before accepting it as a real M20
    * **TRACK** — continuously decode frames and build a flight track
  * Automatic fallback:

    * If RSSI collapses or no valid frames for too long, the tracker marks the sonde as lost and returns to SCAN 

* **M20 frame decoder (ported from `m20mod`)**

  * Decodes M20 type-0x20 frames:

    * Altitude (3-byte unsigned, centimetres → meters)
    * Latitude/longitude (signed 32-bit, 1e-6 degrees)
  * Implements original M10/M20 frame checksum (`checkM10`) logic
  * Valid frames set flags for `DATA_POS` and `DATA_TIME` and are wrapped in a simple `SondeData` container 

* **Track storage and status sharing**

  * `track_store.py` keeps:

    * Last decoded sonde data
    * Limited-length flight track (timestamp, lat, lon, alt)
    * Current RF frequency, RSSI, noise estimate, signal threshold, lost counter, and “had signal” flag
    * Control flags for SCAN vs FIXED mode and a `need_restart` flag set by the web UI and consumed by the main loop 
  * All Web UI data is read from this shared store, so you can observe the whole RF & tracking state live.

### Hardware

* ESP32-C3 board supported by MicroPython
* CC1101 400–433 MHz module wired to the SPI pins configured in `config.py`
* Simple 400 MHz antenna (¼-wave, GP, etc.) tuned for around 405 MHz
* Wi-Fi network for the web interface

The idea is to have a **small, always-on local M20 receiver** that you can open in a browser, watch RSSI and status in real time, and use as a field tracker when driving to recover weather balloons.

---

Если нужно, могу дописать разделы `Installation` / `Flashing` и пример схемы подключения в том же стиле.
