# B1-AutoAlign

[![CI](https://github.com/B1-Mordred/B1-AutoAlign/actions/workflows/ci.yml/badge.svg)](https://github.com/B1-Mordred/B1-AutoAlign/actions/workflows/ci.yml)

B1-AutoAlign is minimal ESP32 firmware for the motorized altitude/azimuth polar-alignment base derived from the OpenAstroExplorer hardware layout. It controls only the two polar-alignment axes and deliberately excludes RA/DEC tracking, GoTo, guiding, focuser, GPS, display and Wi-Fi features.

The firmware identifies itself as `B1-AutoAlign` over the LX200-compatible serial protocol and is intended to work with the patched INDI `LX200 OpenAstroTech` driver used by Ekos.

> **Development status:** source and host-side tooling are build-validated, but this firmware has not been flashed to the connected controller. Direction, angular calibration, holding behavior and motion under the full telescope load remain physically unverified.

## Features

- ESP32 control of two STEP/DIR/ENABLE stepper axes
- OpenAstroExplorer v1 pin assignment
- acceleration and conservative default step rates
- persistent positions, calibration and upper ALT limit in ESP32 NVS
- persistent ALT lower soft limit at zero
- optional ALT upper soft limit
- safe, non-crashing `:Q#` stop command
- LX200 handshake and fixed compatibility replies for Ekos/INDI
- PA-specific status, limit and calibration commands
- no automatic movement at startup

## Repository layout

```text
firmware/B1-AutoAlign/   Arduino sketch
docs/                    build, hardware, protocol, safety and validation notes
scripts/                 build, check, flash and flash-backup helpers
tools/                   serial diagnostic client
tests/                   repository and firmware-contract tests
integrations/indi-1.9.9/ legacy INDI OpenAstroTech PA-control patch
.github/workflows/       continuous-integration build
```

## Quick start

Requirements: Arduino CLI, ESP32 Arduino core 3.3.12, and Python 3 with `pyserial` for the optional diagnostic client.

```bash
./scripts/check.sh
```

This compiles the sketch for `esp32:esp32:esp32`, validates the Python tool and runs the repository tests. It does not access or flash a connected controller.

Before any future upload, read [Safety](docs/safety.md), make a flash backup, support or remove the telescope load, and verify the physical bottom position.

## Documentation

- [Build and installation](docs/build.md)
- [Hardware mapping](docs/hardware.md)
- [Serial protocol](docs/protocol.md)
- [Ekos/INDI integration](docs/ekos-indi.md)
- [Safety and first-motion procedure](docs/safety.md)
- [Validation status](docs/validation.md)

## License and attribution

B1-AutoAlign is released under the [MIT License](LICENSE). The hardware pin mapping and protocol behavior were derived from the MIT-licensed OpenAstroTech project; see [third-party notices](THIRD_PARTY_NOTICES.md).
