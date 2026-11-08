# B1-AutoAlign

[![CI](https://github.com/B1-Mordred/B1-AutoAlign/actions/workflows/ci.yml/badge.svg)](https://github.com/B1-Mordred/B1-AutoAlign/actions/workflows/ci.yml)

B1-AutoAlign is minimal ESP32 firmware for the motorized altitude/azimuth polar-alignment base derived from the OpenAstroExplorer hardware layout. It controls only the two polar-alignment axes and deliberately excludes RA/DEC tracking, GoTo, guiding, focuser, GPS, display and Wi-Fi features.

The repository also includes a native PyQt6 desktop control center for connection management, live position/status monitoring, safe ALT/AZ jogging, reference and limit management, calibration, and camera/plate-solver backend preparation.

The firmware identifies itself as `B1-AutoAlign` over the LX200-compatible serial protocol and is intended to work with the patched INDI `LX200 OpenAstroTech` driver used by Ekos.

> **Development status:** firmware v0.3.0 is flashed and communicating with the
> connected controller. Schema migration preserved the commissioned positions,
> limits and motor settings; live endstop reporting and no-motion configuration
> interlocks are validated. Timer-driven ALT motion under intensive status polling,
> logical reference recovery, persistence across reset, direction polarity and
> the commissioned soft-limit ranges have been validated. Real angular
> calibration, physical stop-during-motion, homing, thermal/holding behavior and
> unattended operation under the full telescope load remain unverified.

## Features

- ESP32 control of two STEP/DIR/ENABLE stepper axes
- OpenAstroExplorer v1 pin assignment
- acceleration and conservative default step rates
- microsecond timer-driven STEP scheduling independent of serial polling
- persistent positions, calibration, ALT/AZ limits, motor directions and holding policy in ESP32 NVS
- bilateral soft-limit support with an automatic-correction readiness interlock
- debounced SENSOR1/GPIO39 and SENSOR2/GPIO36 physical endstops with configurable ALT/AZ and min/max assignment
- motion-into-limit rejection, two-axis emergency stop, escape motion and bounded endstop homing
- atomic two-axis correction command with bounded magnitude
- 180-second motion timeout and safe, non-crashing `:Q#` stop command
- configurable release, timed-hold and always-hold motor policies
- boot-time configuration validation and schema migration
- LX200 handshake and fixed compatibility replies for Ekos/INDI
- PA-specific status, limit, calibration and motor-direction commands
- guarded no-motion recovery to an already stored ALT upper reference
- no automatic movement at startup
- native Linux desktop app with strict legacy-firmware read-only mode
- Ekos/KStars capture-and-solve integration over D-Bus, with solve-only action
- automatic fallback to a standard INDI camera and local Astrometry.net solver
- explicit correction lock: the new automation backend cannot move ALT or AZ

## Repository layout

```text
firmware/B1-AutoAlign/   Arduino sketch
app/b1_autoalign/        PyQt6 desktop application and protocol client
assets/                  desktop icon
docs/                    build, hardware, protocol, safety and validation notes
packaging/               desktop launcher templates
scripts/                 build, check, flash and flash-backup helpers
tools/                   serial diagnostic client
tests/                   repository, protocol, endstop and executable motion-policy tests
integrations/indi-1.9.9/ legacy INDI OpenAstroTech PA-control patch
hardware/                 imported AutoPA printable parts and provenance
.github/workflows/       continuous-integration build
```

## Quick start

Requirements: Arduino CLI, ESP32 Arduino core 3.3.12, Python 3, PyQt6 and `pyserial`.

```bash
./scripts/setup-app.sh  # checks existing modules or creates .venv when needed
./scripts/check.sh
```

This compiles the sketch for `esp32:esp32:esp32`, validates the Python tool and runs the repository tests. It does not access or flash a connected controller.

Run or install the desktop app:

```bash
./scripts/run-app.sh
./scripts/install-desktop.sh
```

Before any future upload, read [Safety](docs/safety.md), make a flash backup, support or remove the telescope load, and verify the physical bottom position.

## Documentation

- [Changelog](CHANGELOG.md)
- [Build and installation](docs/build.md)
- [Hardware mapping](docs/hardware.md)
- [OpenAstroExplorer AutoPA printable parts](hardware/openastroexplorer-autopa/README.md)
- [Serial protocol](docs/protocol.md)
- [Desktop application](docs/desktop-app.md)
- [Automation backends](docs/automation-backends.md)
- [Ekos/INDI integration](docs/ekos-indi.md)
- [Safety and first-motion procedure](docs/safety.md)
- [Validation status](docs/validation.md)

## License and attribution

B1-AutoAlign source code is released under the [MIT License](LICENSE). The imported OpenAstroExplorer AutoPA STL files are separately licensed under CC BY-NC 4.0; see their [model license](hardware/openastroexplorer-autopa/LICENSE.md) and [third-party notices](THIRD_PARTY_NOTICES.md).
