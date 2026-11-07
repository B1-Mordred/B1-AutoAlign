# Serial protocol

The USB serial interface runs at 19200 baud and uses colon-prefixed, hash-terminated Meade-style commands.

## Identity and compatibility

| Request | Response or behavior |
|---|---|
| raw byte `0x06` | `P` (polar alignment mode) |
| `:GVP#` | `B1-AutoAlign#` |
| `:GVN#` | `V0.1.0#` |
| `:GVF#` | `B1-AutoAlign V0.1.0#` |
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

## B1-AutoAlign extensions

| Command | Meaning |
|---|---|
| `:PAB#` | mark current ALT position as bottom/zero |
| `:PAT#` | mark current positive ALT position as upper limit |
| `:PCT#` | clear the ALT upper limit |
| `:PGL#` | report positions, limits, calibration and last fault |
| `:PCAl100.0#` | set ALT steps per arcminute |
| `:PCAz11.0#` | set AZ steps per arcminute |

Example:

```bash
python3 tools/b1_autoalign_cli.py ':PGL#'
```
