
### M20 Tracker – ESP32 + CC1101 radiosonde receiver

This project is a standalone receiver for Graw **M20** meteorological radiosondes based on an **ESP32-C3** and a **CC1101** RF transceiver. The goal is to have a small, low-power tracker that can automatically search for active sondes around 400–406 MHz, lock onto the signal, and decode telemetry (position, altitude, velocities, temperature, humidity, battery voltage) without needing a PC or SDR.

The CC1101 is configured in **raw 2-FSK mode**: it outputs a bitstream on GDO0, which is then oversampled and demodulated in software. A custom MicroPython decoder searches for the M20 sync pattern, reconstructs frames with the correct length, checks CRC-16/X.25 and only accepts a frequency as “valid M20” after several consecutive frames with a good CRC (similar philosophy to `m20mod` and `radiosonde_auto_rx`).

A built-in **Web UI** served by the ESP32 provides live monitoring and control:

* modes: **AUTO SCAN** and **FIXED frequency**
* current RF frequency (Hz and MHz)
* raw and filtered RSSI, estimated noise floor, signal/no-signal flag
* last decoded frame: timestamp, latitude, longitude, altitude, vertical and horizontal speed, temperature, humidity, battery voltage

All configuration and decoding runs entirely on the ESP32; no external computer is required during operation.

#### Main features

* ESP32-C3 + CC1101 based M20 receiver
* CC1101 in async 2-FSK mode (≈9.6 kbit/s, deviation ≈6 kHz, BW ≈100 kHz)
* Software oversampling and bit-timing recovery on the GDO0 bitstream
* M20 frame detection with sync search, proper frame length window and CRC-16/X.25 check
* Strict frequency validation: several valid CRC frames required before entering tracking mode
* Automatic scan over 404–406 MHz with re-scan if the signal is lost
* Fixed-frequency mode for manual tracking or testing
* Lightweight Web UI (HTML + JS) for configuration and live telemetry display

Project status: **experimental but working**. The core architecture (RF, demodulator, decoder, Web UI, state machine) is in place; further work will focus on improving decoding robustness, logging, and optional integrations with external tools (e.g. SondeHub).
