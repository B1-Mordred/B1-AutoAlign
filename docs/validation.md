# Validation status

## Verified

- Firmware compiles for `esp32:esp32:esp32` with ESP32 core 3.3.12.
- No external Arduino libraries are required.
- The build currently uses approximately 22% of flash and 6% of RAM.
- The Python diagnostic tool parses and imports successfully.
- Repository contract tests check the product identity, OAE v1 pins, raw LX200 handshake, lower-limit configuration, safe-stop command and local documentation links.
- The release archive from the precursor prototype passed ZIP integrity checking.

## Derived from the connected system

- USB serial speed: 19200 baud.
- Previous controller identity: OpenAstroMount V1.13.16.
- Observed conversion: ALT 100 and AZ 11 counter steps per commanded arcminute.
- The physical lower ALT position was deliberately established as logical zero.

## Not yet verified

- Upload and boot of B1-AutoAlign on the connected controller.
- Physical ALT and AZ direction with this firmware.
- Motor enable polarity on the assembled controller.
- Real angular calibration and repeatability.
- Loaded holding, stopping, clearance and thermal behavior.
- Ekos GUI operation against B1-AutoAlign after flashing.
- Operation with the complete 25 kg telescope assembly.

The existing controller firmware has not been replaced during repository creation.
