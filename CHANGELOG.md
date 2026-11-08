# Changelog

All notable changes to B1-AutoAlign will be documented here.

## 0.2.1 - 2026-11-08

- Added the ten official OpenAstroExplorer AutoPA/ALTAZ STL files.
- Added pinned upstream provenance, CC BY-NC 4.0 licensing, print quantities,
  checksums, and automated binary STL integrity checks.
- Added persistent, independently configurable ALT/AZ electrical direction
  inversion in firmware and the desktop app.
- Defaulted ALT to reversed so positive logical ALT moves upward on the
  assembled base; AZ remains normal.
- Added safe direction-change handling that resets the changed lower reference,
  invalidates obsolete limits and locks automatic correction until requalified.

## 0.2.0 - 2026-11-07

- Added ALT/AZ soft-limit readiness for automatic corrections.
- Added bounded, atomic two-axis correction commands in degrees.
- Added a wrap-safe 180-second motion timeout that stops both axes.
- Added release, timed and continuous motor-holding policies.
- Kept holding torque after STOP by default.
- Added explicit idle-driver release with desktop confirmation.
- Added NVS schema migration and boot-time configuration repair.
- Expanded status with targets, AZ limits, holding, driver state and readiness.
- Added executable host tests for the shared motion implementation.
- Extended the desktop app with AZ-limit and holding controls.

## 0.1.0 - 2026-11-07

- Initial PA-only ESP32 firmware.
- Added OAE v1 ALT/AZ pin mapping and accelerated STEP/DIR motion.
- Added persistent position, calibration and ALT-limit storage.
- Added LX200/INDI compatibility and `B1-AutoAlign` identification.
- Added safe stop, diagnostic protocol, build scripts, tests and CI.
- Added the PyQt6 B1-AutoAlign Control Center with live status, safe motion controls, calibration and limit management.
- Added strict read-only handling for legacy OpenAstroMount firmware.
- Added user-local desktop launcher installation and an offscreen UI smoke test.
- Added Ekos and standalone INDI/Astrometry.net capture-and-solve backends.
