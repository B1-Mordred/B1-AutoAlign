# Hardware mapping

## Controller

B1-AutoAlign currently targets an ESP32 using the OpenAstroExplorer board v1 pinout.

| Axis | STEP | DIR | ENABLE |
|---|---:|---:|---:|
| ALT | GPIO13 | GPIO23 | GPIO4 |
| AZ | GPIO18 | GPIO19 | GPIO32 |

ENABLE is assumed to be active-low, as with common A4988-compatible stepper interfaces.

## Direction

A positive ALT command must move the base upward and away from its lower mechanical stop. Direction inversion is controlled by `ALT_DIR_INVERT` and `AZ_DIR_INVERT` near the top of the sketch.

The current values have not yet been physically verified with B1-AutoAlign. Test with a tiny positive move and no unsupported telescope load before changing them.

## Calibration

The migration defaults are:

- ALT: 100 driver steps per arcminute
- AZ: 11 driver steps per arcminute

These reproduce the observed command-to-counter conversion of the previous firmware. They are not a verified measurement of real base rotation. Belt ratio, lead screw pitch, microstepping and mechanical compliance all affect the final value.

## Position model

Both axes are open-loop. The firmware cannot detect a stalled motor, lost steps, a slipping coupling or manual motion while powered off. The saved counter is therefore not a substitute for mechanical stops, limit switches or a reference procedure.

The 25 kg total system mass is a mechanical design and motor/driver requirement; compiling or operating this firmware does not validate that load capacity.

## Holding policy

Firmware v0.2.0 defaults to **always hold after the first movement**. A STOP ends step generation but retains motor torque. This reduces back-driving risk, but it can increase driver and motor temperature. The desktop app can select:

- release immediately after motion;
- hold for a configurable delay;
- hold continuously until an explicit release or power-off.

The default is a software precaution, not proof that the axes can safely hold 25 kg. Validate current limits and temperatures under a mechanically supported load. The explicit driver-release command must never be used unless the load cannot move when torque is removed.

## Limit model

ALT always has a logical lower limit at zero and supports a recorded upper limit. AZ v0.2.0 supports a recorded lower/zero reference and upper limit. Automatic correction commands remain locked until all four logical boundaries are present.

These are open-loop soft limits. Physical limit switches or absolute encoders remain strongly recommended for eventual unattended operation.
