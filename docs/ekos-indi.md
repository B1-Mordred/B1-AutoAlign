# Ekos and INDI integration

B1-AutoAlign implements the serial subset used by the `LX200 OpenAstroTech` telescope driver. In the tested Ekos configuration, the device uses:

- driver: `LX200 OpenAstroTech`
- connection: serial
- port: `/dev/serial/by-id/usb-1a86_USB_Serial-if00-port0`
- baud rate: 19200
- controls: **Polar Align Alt** and **Polar Align Azimuth**

## INDI 1.9.9 compatibility patch

Ubuntu's older INDI 1.9.9 OpenAstroTech driver required a small backport so its normal number properties send `MAL` and `MAZ` commands correctly. The patch is included at [integrations/indi-1.9.9/lx200_OpenAstroTech.patch](../integrations/indi-1.9.9/lx200_OpenAstroTech.patch).

It changes four behaviors:

1. accepts the vector property names `POLAR_ALT` and `POLAR_AZ`;
2. labels values as arcminutes;
3. uses practical ALT/AZ command ranges with one-arcminute steps;
4. treats the silent relative-move command as complete after a successful serial write.

On the development PC, the patched driver is installed as a user-local override:

```text
~/.local/lib/indi-oat-patch/indi_lx200generic_patched
~/.local/bin/indi_lx200_OpenAstroTech
```

The system package was not overwritten. Removing the user-local symlink restores the packaged driver.

The patch is for INDI 1.9.9 source and may not apply cleanly to newer INDI releases. Check the current upstream driver before using it elsewhere.

## Camera and solver integration

The desktop app independently uses the KStars session D-Bus interface at `/KStars/Ekos/Align` when it exposes `captureAndSolve` and a camera is selected. It requests the solve-only action before every test, so the test does not sync or slew the equatorial mount.

When Ekos is unavailable or incomplete, the fallback uses only standard INDI camera properties:

```text
CCD_EXPOSURE.CCD_EXPOSURE_VALUE
CCD1.CCD1
```

No Python INDI binding is required; the implementation uses `indi_getprop` and `indi_setprop`, then runs the local Astrometry.net tools. Details are in [Automation backends](automation-backends.md).

## Future native polar-correction interface

Current upstream INDI defines a dedicated Polar Alignment Correction interface (`PAC_INTERFACE`). Its core commands are:

```text
PAC_MANUAL_ADJUSTMENT.MANUAL_AZ_STEP
PAC_MANUAL_ADJUSTMENT.MANUAL_ALT_STEP
PAC_ABORT_MOTION.ABORT
```

The upstream sign convention is positive AZ = east, negative AZ = west, positive ALT = north/up and negative ALT = south/down. Current upstream KStars can use this interface from its Polar Alignment Assistant. The installed INDI 1.9.9/KStars 3.6.2 stack predates that capability, so B1-AutoAlign only detects and reports a future PAC device for now. It does not emulate support that the installed stack does not have.

Firmware v0.2.0 provides a bounded, atomic serial correction primitive in the same axis order and units:

```text
:PAC<azimuth-degrees>,<altitude-degrees>#
```

It accepts the move only when both axes are idle, all ALT/AZ soft limits are recorded, both target positions are legal and the requested magnitude is inside the firmware envelope. The reply is `1#` when both targets were committed or `0#` when neither was started. A future INDI PAC driver can map `PAC_MANUAL_ADJUSTMENT` to this command without issuing two non-atomic moves.
