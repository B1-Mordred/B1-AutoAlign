# Hardware mapping

## Printable AutoPA mechanism

The repository includes the ten official OpenAstroExplorer AutoPA/ALTAZ STL
files under [hardware/openastroexplorer-autopa](../hardware/openastroexplorer-autopa/README.md),
together with pinned source provenance, print quantities, SHA-256 checksums and
the separate CC BY-NC 4.0 license.

Only the polar-alignment mechanism is included; unrelated RA/DEC, tracker,
tripod and counterweight models are excluded. The imported geometry is not a
validated 25 kg design. Treat the load rating, material choice, fasteners,
bearings, motor sizing, balance and physical safety factor as separate
engineering work.

## Controller

B1-AutoAlign currently targets an ESP32 using the OpenAstroExplorer board v1 pinout.

| Axis | STEP | DIR | ENABLE |
|---|---:|---:|---:|
| ALT | GPIO13 | GPIO23 | GPIO4 |
| AZ | GPIO18 | GPIO19 | GPIO32 |

ENABLE is assumed to be active-low, as with common A4988-compatible stepper interfaces.

## Physical endstop inputs

The official board's two three-pin sensor connectors are available to firmware
v0.3.0 as active-high inputs:

| Connector | Schematic pin 1 | Pin 2 | Pin 3 |
|---|---|---|---|
| SENSOR1 | 5 V | GPIO39 | GND |
| SENSOR2 | 5 V | GPIO36 | GND |

GPIO36 and GPIO39 are 3.3 V input-only pins without internal pull resistors.
Never connect the connector's 5 V pin directly to the GPIO signal. For the
tested normally-closed mechanical switch and only 10 kΩ resistors, wire each
connector as follows:

```text
5 V ── 10 kΩ ── GPIO / switch NC
                   |
                 10 kΩ
                   |
                 10 kΩ
                   |
GND ───────────────┴── switch C
```

The two lower resistors are in series. They form a 10 kΩ/20 kΩ divider that
produces approximately 3.33 V when the NC contact opens. With the switch
released, NC-C holds the input low. `NO` remains unconnected. Identify 5 V and
GND electrically rather than assuming a left-to-right connector orientation.

Firmware always reports both debounced input states. Their axis and physical
minimum/maximum roles are disabled by default and must be stored from the
desktop app or `PES` command after the switches are securely mounted.

## Direction

A positive ALT command must move the base upward and away from its lower
mechanical stop. Firmware stores independent ALT/AZ inversion settings in NVS;
they can be changed with `:PDI<alt>,<az>#` or from the desktop app. Compile-time
defaults are `DEFAULT_ALT_DIR_INVERT` and `DEFAULT_AZ_DIR_INVERT`.

The assembled base was observed to move upward only for negative ALT values with
the original setting. Firmware v0.2.1 therefore defaults ALT to reversed and AZ
to normal. The intended result is positive ALT = upward and negative ALT =
downward. Confirm this with a tiny positive move and no unsupported telescope
load after flashing.

An ALT top limit recorded under the old polarity is invalid. At the physical
bottom, clear the old ALT top limit and mark the current position as ALT
bottom/zero before testing upward travel. Schema migration and the runtime
direction command perform that reset for a changed ALT polarity, but the
physical bottom still has to be confirmed by the operator. Do not reuse the old
top limit.

## Calibration

The migration defaults are:

- ALT: 100 driver steps per arcminute
- AZ: 11 driver steps per arcminute

These reproduce the observed command-to-counter conversion of the previous firmware. They are not a verified measurement of real base rotation. Belt ratio, lead screw pitch, microstepping and mechanical compliance all affect the final value.

## Position model

Both axes are open-loop. The firmware cannot detect a stalled motor, lost steps, a slipping coupling or manual motion while powered off. The saved counter is therefore not a substitute for mechanical stops, limit switches or a reference procedure.

Firmware v0.2.2 schedules STEP pulses from the ESP32's high-priority
microsecond timer task. Serial status responses, desktop polling and INDI
traffic therefore no longer determine the interval between motor steps. Axis
state access is synchronized between the timer and command tasks. The serial
port also uses a transmit buffer large enough for the expanded status packet.

The 25 kg total system mass is a mechanical design and motor/driver requirement; compiling or operating this firmware does not validate that load capacity.

## Holding policy

Firmware v0.2.0 defaults to **always hold after the first movement**. A STOP ends step generation but retains motor torque. This reduces back-driving risk, but it can increase driver and motor temperature. The desktop app can select:

- release immediately after motion;
- hold for a configurable delay;
- hold continuously until an explicit release or power-off.

The default is a software precaution, not proof that the axes can safely hold 25 kg. Validate current limits and temperatures under a mechanically supported load. The explicit driver-release command must never be used unless the load cannot move when torque is removed.

## Limit model

ALT always has a logical lower limit at zero and supports a recorded upper limit. AZ v0.2.0 supports a recorded lower/zero reference and upper limit. Automatic correction commands remain locked until all four logical boundaries are present.

Firmware v0.3.0 adds one physical endstop per axis while retaining the bilateral
soft limits. An active assigned endstop blocks motion farther into its configured
side, but permits motion away from it. If an assigned switch triggers during
motion, firmware stops both axes. Reaching a minimum endstop establishes zero;
reaching a maximum endstop restores the previously recorded upper coordinate.

Endstops reduce travel-overrun risk but do not detect stalls, missed steps,
coupler slip or unsafe motion in the opposite direction. One switch per axis is
not bilateral physical protection, and it does not make unattended operation safe.
