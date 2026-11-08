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
3. At the physical ALT bottom, send `:PCT#` to clear any top limit recorded with
   the old motor polarity, then `:PAB#` to mark the current position as bottom/zero.
4. Query `:PGL#`; ALT must be zero and `ALTMAX` must be `NA`.
5. Send `:MXl10#`. Positive ALT must move upward, away from the bottom.
6. If it moves down, stop immediately with `:Q#`, remove motor power and change
   the stored ALT direction from the desktop app or with `:PDI<alt>,<az>#`.
7. Send `:MXl-10#` and confirm ALT returns to zero.
8. At zero, attempt another negative move. It must return `0` and remain still.
9. Repeat a small reversible raw-step test for AZ.
10. Move AZ to its physical lower safe travel boundary and record it as AZ lower/zero.
11. Traverse the safe AZ range under supervision and record the upper AZ limit.
12. Measure real angular motion before changing the steps-per-arcminute values.
13. Record a new upper ALT soft limit only after the full safe travel is established.
14. Confirm that status reports `LIMITS=1` before testing an atomic correction.

## Physical endstop commissioning

1. Leave both endstop assignments disabled while mounting the switches.
2. In the desktop status panel, press each switch by hand and verify that only
   its expected SENSOR1/GPIO39 or SENSOR2/GPIO36 indicator becomes `TRIGGERED`.
3. Verify the signal is approximately 0 V released and no more than about
   3.3 V triggered. A logic-state test alone cannot detect an unsafe 5 V input.
4. Mount each switch so it opens before the mechanism reaches a damaging hard stop.
5. Store the correct axis, connector and minimum/maximum side assignment while
   both axes are stationary.
6. With the load independently supported, trigger the switch by hand and send a
   tiny command farther into the configured side. It must be rejected without a step.
7. Confirm a tiny command away from the switch is allowed, then release it.
8. Start homing only with the mechanism in view and a hardware power disconnect
   within reach. Use STOP immediately if the configured direction is wrong.

The normally-closed wiring is fail-safe for an open switch cable: the input
appears triggered. Firmware deliberately permits escape motion away from the
configured boundary even while the input remains active.

## Motor holding

Version 0.2.0 defaults to continuous holding after motion and after STOP. This is intended to reduce sudden back-driving, but holding current can overheat a motor or driver. Support the telescope independently while testing temperature and current limits.

`PDR` explicitly de-energizes both idle drivers. Do not use it with an unsupported load. A hardware power disconnect remains necessary for an electrical or driver fault.

## Boundaries

Soft limits depend on the saved open-loop position. They are invalid after lost steps, a slipped coupling, manual movement or a restored flash image with different coordinates. A single endstop per axis re-establishes one coordinate but does not protect the opposite physical boundary. Use mechanical protection appropriate to the load.

The firmware rejects oversized commands and stops both axes if either exceeds the 180-second motion timeout. These guards do not detect a stalled motor or prove that the mechanism actually moved.

Do not treat a successful compile, serial response or unloaded motor turn as proof that the 25 kg system is safe under load.
