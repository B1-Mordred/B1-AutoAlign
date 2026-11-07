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
9. Measure real angular motion before changing the steps-per-arcminute values.
10. Record an upper ALT soft limit only after the full safe travel is established.

## Boundaries

Soft limits depend on the saved open-loop position. They are invalid after lost steps, a slipped coupling, manual movement or a restored flash image with different coordinates. Use mechanical protection appropriate to the load.

Do not treat a successful compile, serial response or unloaded motor turn as proof that the 25 kg system is safe under load.
