# Serial protocol

The USB serial interface runs at 19200 baud and uses colon-prefixed, hash-terminated Meade-style commands.

## Identity and compatibility

| Request | Response or behavior |
|---|---|
| raw byte `0x06` | `P` (polar alignment mode) |
| `:GVP#` | `B1-AutoAlign#` |
| `:GVN#` | `V0.2.0#` |
| `:GVF#` | `B1-AutoAlign V0.2.0#` |
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
| `:PCT#` | clear the ALT upper limit |
| `:PZB#` | mark current AZ position as lower limit/zero |
| `:PZT#` | mark current positive AZ position as upper limit |
| `:PZC#` | clear both AZ limits |
| `:PGL#` | report positions, targets, limits, calibration, holding, drivers, state and last fault |
| `:PCAl100.0#` | set ALT steps per arcminute |
| `:PCAz11.0#` | set AZ steps per arcminute |
| `:PHM0#` | release drivers after motion |
| `:PHM1#` | use timed holding |
| `:PHM2#` | hold continuously after motion (v0.2 default) |
| `:PHD5000#` | set timed-hold delay in milliseconds, 0–600000 |
| `:PDR#` | explicitly release both idle drivers |
| `:PAC0.25,-0.10#` | atomic AZ/ALT correction in degrees |

`PAC` follows the upstream INDI sign convention expected by the integration layer: positive AZ is east, negative AZ west, positive ALT north/up and negative ALT south/down. Actual direction remains subject to physical direction verification. The command is rejected unless both axes are idle and both ALT/AZ travel ranges have been recorded.

The two-axis correction is preflighted atomically. A `1#` reply means both legal targets were committed; `0#` means neither target was started.

## Status response

Firmware v0.2.0 returns an expanded comma-separated `PGL` response:

```text
AZ=0,ALT=0,AZMIN=0,AZMAX=5000,ALTMIN=0,ALTMAX=8000,
AZTARGET=0,ALTTARGET=0,ACAL=100.0000,ZCAL=11.0000,
STATE=IDLE,FAULT=NONE,HOLD=2,HOLDMS=5000,AZEN=0,ALTEN=0,LIMITS=1,SCHEMA=2#
```

`NA` represents an unset limit. `LIMITS=1` is the firmware interlock required by `PAC`. `AZEN` and `ALTEN` report the electrical driver-enable state, not whether an axis is moving.

Example:

```bash
python3 tools/b1_autoalign_cli.py ':PGL#'
```
