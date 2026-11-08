# Serial protocol

The USB serial interface runs at 19200 baud and uses colon-prefixed, hash-terminated Meade-style commands.

## Identity and compatibility

| Request | Response or behavior |
|---|---|
| raw byte `0x06` | `P` (polar alignment mode) |
| `:GVP#` | `B1-AutoAlign#` |
| `:GVN#` | `V0.3.0#` |
| `:GVF#` | `B1-AutoAlign V0.3.0#` |
| `:GR#` | fixed safe RA value |
| `:GD#` | fixed safe DEC value |
| `:GX#` | OpenAstroTech-compatible motion status |
| `:XGAA#` | `AZ_STEPS|ALT_STEPS#` |
| `:XGA#` | ALT steps per degree |
| `:XGZ#` | AZ steps per degree |

The fixed telescope replies exist only so the inherited telescope-class INDI driver can remain connected. They do not represent a controlled equatorial mount.

## Motion

| Command | Meaning | Reply |
|---|---|---|
| `:MALn#` | relative ALT movement in arcminutes | none |
| `:MAZn#` | relative AZ movement in arcminutes | none |
| `:MXln#` | relative ALT movement in raw steps | `1` accepted, `0` rejected |
| `:MXzn#` | relative AZ movement in raw steps | `1` accepted, `0` rejected |
| `:MAA#` / `:MAAH#` | move both axes to logical zero | `1` or `0` |
| `:hZ#` | set both logical positions to zero without moving | `1` or `0` |
| `:Q#` | immediately stop both axes | none |

`MAL` and `MAZ` are deliberately silent for compatibility with the patched INDI driver. Query `:PGL#` to inspect the last fault.

Firmware rejects zero or oversized commands. The maximum magnitudes are 140 ALT arcminutes, 320 AZ arcminutes and 100,000 raw steps. Every accepted move has a 180-second timeout. When either axis times out during a combined move, both axes stop.

STOP follows the configured holding policy: the default v0.2 behavior stops pulses while retaining motor torque. It does not necessarily de-energize the drivers.

## B1-AutoAlign extensions

| Command | Meaning |
|---|---|
| `:PAB#` | mark current ALT position as bottom/zero |
| `:PAT#` | mark current positive ALT position as upper limit |
| `:PAU#` | set current logical ALT position to its stored upper limit without motion |
| `:PCT#` | clear the ALT upper limit |
| `:PZB#` | mark current AZ position as west limit/zero |
| `:PZT#` | mark current positive AZ position as east limit |
| `:PZC#` | clear both AZ limits |
| `:PGL#` | report positions, targets, limits, calibration, holding, drivers, state and last fault |
| `:PCAl100.0#` | set ALT steps per arcminute |
| `:PCAz11.0#` | set AZ steps per arcminute |
| `:PHM0#` | release drivers after motion |
| `:PHM1#` | use timed holding |
| `:PHM2#` | hold continuously after motion (v0.2 default) |
| `:PHD5000#` | set timed-hold delay in milliseconds, 0–600000 |
| `:PDR#` | explicitly release both idle drivers |
| `:PDI1,0#` | store ALT,AZ direction inversion (`1` = reversed, `0` = normal) |
| `:PAC0.25,-0.10#` | atomic AZ/ALT correction in degrees |
| `:PES1,0,2,0#` | assign ALT to SENSOR1/bottom and AZ to SENSOR2/west |
| `:PHEA#` | start bounded ALT homing toward its configured endstop |
| `:PHEZ#` | start bounded AZ homing toward its configured endstop |

`PDI` is rejected while either axis is moving. If a setting changes, firmware
assumes that axis is at its physical lower safe boundary, sets its logical
position to zero and clears the affected upper limit(s). Applying the already
stored settings does not alter positions or limits.

`PAC` follows the upstream INDI sign convention expected by the integration layer: positive AZ is east, negative AZ west, positive ALT north/up and negative ALT south/down. Actual direction remains subject to physical direction verification. The command is rejected unless both axes are idle and both ALT/AZ travel ranges have been recorded.

The two-axis correction is preflighted atomically. A `1#` reply means both legal targets were committed; `0#` means neither target was started.

`PES` accepts four integers: ALT source, ALT side, AZ source and AZ side.
Source `0` disables an axis, `1` selects SENSOR1/GPIO39 and `2` selects
SENSOR2/GPIO36. Side `0` is ALT bottom or AZ west (protocol minimum/zero), and
side `1` is ALT top or AZ east (protocol maximum). One nonzero source cannot be
assigned to both axes. The setting is persistent and is rejected while either
axis moves.

`PHEA` and `PHEZ` acknowledge that homing was accepted; completion is reported
through `STATE` and `FAULT`. The search is limited to 100,000 steps and retains
the 180-second motion timeout. `:Q#` aborts it. A minimum hit establishes zero.
A maximum hit restores the stored upper coordinate, so maximum-side homing is
rejected until that upper soft reference exists.

During any normal or homing move, an assigned active endstop blocks motion into
its configured side. A newly triggered assigned input stops both axes. Motion
away from an active switch remains available.

## Status response

Firmware v0.3.0 returns an expanded comma-separated `PGL` response:

```text
AZ=0,ALT=0,AZMIN=0,AZMAX=5000,ALTMIN=0,ALTMAX=8000,
AZTARGET=0,ALTTARGET=0,ACAL=100.0000,ZCAL=11.0000,
STATE=IDLE,FAULT=NONE,HOLD=2,HOLDMS=5000,AZEN=0,ALTEN=0,
ALTINV=1,AZINV=0,ES1=0,ES2=0,ALTES=1,ALTESIDE=0,
AZES=2,AZESIDE=0,LIMITS=1,SCHEMA=4#
```

`NA` represents an unset limit. `LIMITS=1` is the firmware interlock required by `PAC`. `AZEN` and `ALTEN` report the electrical driver-enable state, not whether an axis is moving. `ALTINV` and `AZINV` are the persisted electrical-direction settings.

`ES1` and `ES2` are the debounced active-high physical input states.
`ALTES`/`AZES` identify the assigned source and `ALTESIDE`/`AZESIDE` identify
minimum (`0`) or maximum (`1`). During homing, `STATE` is `HOME_ALT` or
`HOME_AZ`. Completion faults are `ALT_HOMED` or `AZ_HOMED`; an exhausted search
reports `ALT_HOME_NOT_FOUND` or `AZ_HOME_NOT_FOUND`.

Example:

```bash
python3 tools/b1_autoalign_cli.py ':PGL#'
```
