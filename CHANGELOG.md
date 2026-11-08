# Changelog

All notable changes to B1-AutoAlign will be documented here.

## 0.2.3 - 2026-11-08

- Added a guarded command and desktop action to confirm that the stationary
  ALT mechanism is physically at its already stored upper reference. This
  restores the logical coordinate without generating motor pulses.
- Persist completed motion immediately when both axes are idle, closing the
  previous 1.5-second power-loss window before the final position was saved.
- Refresh a desktop status snapshot once when motion completes between the
  separate position and motion-state queries, avoiding a stale final readout.
- Resynchronize once when reconnecting after a previous process was interrupted
  with a status reply still in flight.

## 0.2.2 - 2026-11-08

- Moved ALT/AZ STEP scheduling from the serial-processing loop to the ESP32's
  dedicated high-priority microsecond timer task.
- Added synchronized axis state so motion timing and serial status polling can
  run concurrently without corrupting positions or targets.
- Added deadline-driven timer periods, avoiding a busy high-frequency polling
  loop while preserving the acceleration profile.
- Added a 512-byte UART transmit buffer so the expanded status response does
  not unnecessarily block command processing at 19200 baud.
- Added fail-safe motion rejection and immediate stopping if the timer service
  cannot be created or rescheduled.
- Added host and repository regression coverage for timer-driven motion.

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
