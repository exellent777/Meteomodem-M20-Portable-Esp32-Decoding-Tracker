M20 Radiosonde Receiver on ESP32-C3 (MicroPython + CC1101)

This project implements a lightweight M20 radiosonde receiver using an ESP32-C3, a CC1101 transceiver module, and MicroPython.
The goal is to build a compact, low-power, fully standalone device capable of receiving, demodulating, decoding, and forwarding data from M20 weather balloons.

✨ Features

Uses CC1101 as the RF front-end (433 MHz band)

Works on MicroPython – no need for Arduino or full SDR

Reads demodulated M20 frames from a custom decoder

Parses frame length defined by M20_FRAME_LEN

Connects to Wi-Fi and pushes data to external services (SondeHub, custom API, or local dashboard)

Performs soft-restarts safely (useful when Wi-Fi or decoder blocks execution)

Designed for ESP32-C3 but can run on any MicroPython board

📡 Architecture Overview

CC1101 captures raw FSK bursts from an M20 radiosonde.

A simple demodulator outputs binary symbols to MicroPython (UART/SPI/GPIO).

ESP32-C3 receives and validates frames based on expected length (M20_FRAME_LEN).

Decoded telemetry (GPS, temperature, pressure, ascent rate) can be printed or sent via Wi-Fi.

A watchdog/soft-reset mechanism (machine.soft_reset()) helps recover from deadlocks during Wi-Fi connect attempts.

🛠 Requirements

ESP32-C3 module

CC1101 433 MHz transceiver

MicroPython v1.20+

Thonny or any MicroPython-compatible IDE

Correct wiring for CC1101 (SCK, MOSI, MISO, CS, GDO0/GDO2)

📁 Code Structure

main.py – program entry point, Wi-Fi connection, event loop

cc1101.py – driver for the transceiver (if used externally)

m20_decode.py – frame parser and validation

config.py – Wi-Fi settings and constants

🔧 Configuration

Set the frame length in your decoder according to the real M20 output:

M20_FRAME_LEN = 105


Then update Wi-Fi settings in config.py:

WIFI_SSID = "your_wifi"
WIFI_PASS = "your_pass"

🚀 Running

Flash MicroPython to ESP32-C3

Upload project files

Open REPL and run:

import main


To soft-reboot while debugging:

Ctrl+D

📡 Output

Decoded radiosonde data may include:

GPS latitude/longitude

Altitude

Vertical velocity

Temperature & humidity

Battery voltage

You can forward it to:

SondeHub APRS

Your own MQTT/HTTP endpoint

Local dashboard on ESP32-C3

📍 Status

This project is in active development and intended for hobbyist experimentation with radiosondes.
Future improvements may include:

Automatic frequency tracking

Improved FSK demodulator

OLED/TFT display output

Logging to SD card

Full SondeHub ingestion support
