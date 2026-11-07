# Validation status

## Verified

- Firmware compiles for `esp32:esp32:esp32` with ESP32 core 3.3.12.
- No external Arduino libraries are required.
- The build currently uses approximately 22% of flash and 6% of RAM.
- The Python diagnostic tool parses and imports successfully.
- Repository contract tests check the product identity, OAE v1 pins, raw LX200 handshake, lower-limit configuration, safe-stop command and local documentation links.
- Protocol tests cover status parsing, B1 motion commands, rejected limits and strict legacy-firmware read-only behavior.
- The PyQt6 desktop window passes an offscreen create/show/close smoke test.
- Automation tests cover Ekos D-Bus capability parsing, solve-only capture setup, standard INDI camera/PAC discovery, WCS parsing, bounded local-solver invocation and backend fallback selection.
- The release archive from the precursor prototype passed ZIP integrity checking.

## Derived from the connected system

- USB serial speed: 19200 baud.
- Previous controller identity: OpenAstroMount V1.13.16.
- Observed conversion: ALT 100 and AZ 11 counter steps per commanded arcminute.
- The physical lower ALT position was deliberately established as logical zero.
- KStars 3.6.2 exposes generic Align capture/solve over session D-Bus, but no camera is currently selected.
- INDI 1.9.9 is reachable on `localhost:7624`, but no camera or PAC device is currently exposed.
- Astrometry.net 0.98, `solve-field`, `wcsinfo`, and 13 index files are available.

## Not yet verified

- Upload and boot of B1-AutoAlign on the connected controller.
- Physical ALT and AZ direction with this firmware.
- Motor enable polarity on the assembled controller.
- Real angular calibration and repeatability.
- Loaded holding, stopping, clearance and thermal behavior.
- Ekos GUI operation against B1-AutoAlign after flashing.
- Ekos or standalone capture with an actual connected camera.
- Plate solving an image from the actual telescope/camera optical train.
- Three-frame polar-error calculation and any automatic motor correction.
- Desktop-app communication with flashed B1-AutoAlign hardware.
- Operation with the complete 25 kg telescope assembly.

The existing controller firmware has not been replaced during repository creation.
