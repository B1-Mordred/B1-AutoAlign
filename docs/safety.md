# Safety and first-motion procedure

The polar-alignment base carries a mechanically significant telescope assembly. Treat every new firmware upload as an unverified motion controller.

## Before uploading

1. Stop KStars/Ekos and INDI so the serial port is free.
2. Back up the current ESP32 flash.
3. Confirm the controller is the OpenAstroExplorer-derived ALT/AZ base.
4. Put the ALT mechanism at the known physical lower stop without driving into it.
5. Remove the telescope load or support it independently.
6. Make motor power quickly disconnectable.

## First controlled test

1. Upload B1-AutoAlign and confirm there is no startup motion.
2. Query `:GVP#`; it must return `B1-AutoAlign#`.
3. Query `:PGL#`; ALT must be zero at the lower reference.
4. Send `:MXl10#`. Positive ALT must move upward, away from the bottom.
5. If it moves down, stop immediately with `:Q#`, remove motor power and correct `ALT_DIR_INVERT`.
6. Send `:MXl-10#` and confirm ALT returns to zero.
7. At zero, attempt another negative move. It must return `0` and remain still.
8. Repeat a small reversible raw-step test for AZ.
9. Move AZ to its physical lower safe travel boundary and record it as AZ lower/zero.
10. Traverse the safe AZ range under supervision and record the upper AZ limit.
11. Measure real angular motion before changing the steps-per-arcminute values.
12. Record an upper ALT soft limit only after the full safe travel is established.
13. Confirm that status reports `LIMITS=1` before testing an atomic correction.

## Motor holding

Version 0.2.0 defaults to continuous holding after motion and after STOP. This is intended to reduce sudden back-driving, but holding current can overheat a motor or driver. Support the telescope independently while testing temperature and current limits.

`PDR` explicitly de-energizes both idle drivers. Do not use it with an unsupported load. A hardware power disconnect remains necessary for an electrical or driver fault.

## Boundaries

Soft limits depend on the saved open-loop position. They are invalid after lost steps, a slipped coupling, manual movement or a restored flash image with different coordinates. Use mechanical protection appropriate to the load.

The firmware rejects oversized commands and stops both axes if either exceeds the 180-second motion timeout. These guards do not detect a stalled motor or prove that the mechanism actually moved.

Do not treat a successful compile, serial response or unloaded motor turn as proof that the 25 kg system is safe under load.
