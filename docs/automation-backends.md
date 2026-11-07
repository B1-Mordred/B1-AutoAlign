# Camera and plate-solver backends

The desktop app is prepared for two image-acquisition paths. Both stop at a verified sky-coordinate solution; neither path sends an ALT/AZ movement.

## Backend selection

| Requested mode | Selection rule |
| --- | --- |
| Automatic | Prefer ready Ekos; otherwise use a ready standalone path |
| Ekos / KStars | Require KStars D-Bus Align API and an Ekos-selected camera |
| Standalone INDI | Require a visible INDI camera, `solve-field`, `wcsinfo`, and index files |

The readiness probe displays KStars/Ekos, cameras, local solver/indexes, the future INDI PAC interface and the selected path separately. A backend must be complete before the capture-and-solve button is enabled.

## Ekos/KStars path

The adapter uses `gdbus`; it does not depend on a Python D-Bus package. It checks:

```text
org.kde.kstars
/KStars/Ekos
/KStars/Ekos/Align
org.kde.kstars.Ekos.Align.captureAndSolve
org.kde.kstars.Ekos.Align.getSolutionResult
```

Before capture it selects solver action `2` (nothing after solve), avoiding mount sync and slew. It treats `ALIGN_COMPLETE` as success, rejects failed/aborted states and uses a bounded timeout.

## Standalone INDI path

The fallback can use a camera from any local or remote INDI server that implements the standard CCD properties. Configure the host and port in the Automation tab. The app:

1. discovers `*.CCD_EXPOSURE.CCD_EXPOSURE_VALUE`;
2. starts a bounded monitor for `<camera>.CCD1.CCD1`;
3. sends the requested exposure with `indi_setprop`;
4. saves the FITS BLOB under `~/Pictures/B1-AutoAlign/`;
5. runs `solve-field --no-plots` with a CPU limit and optional scale/RA/Dec/radius hints;
6. extracts RA, Dec, orientation, pixel scale and field size with `wcsinfo`;
7. preserves the resulting WCS beside the captured image.

All subprocesses use argument arrays rather than a shell. Camera names and paths are therefore not evaluated as commands.

## Development-PC snapshot (2026-11-07)

The live probe found:

- KStars 3.6.2 running with the public Align capture/solve methods;
- no camera selected in the Ekos Align module;
- the configured Canon DSLR unavailable because it was not connected/powered;
- INDI 1.9.9 on `localhost:7624`, currently exposing only the telescope device;
- Astrometry.net 0.98 with `solve-field`, `wcsinfo`, and 13 index files;
- no `PAC_MANUAL_ADJUSTMENT` property on the installed INDI stack.

Accordingly, the software side is ready but neither capture path is complete until a camera is connected and exposed by Ekos/INDI.

## Remaining route to real automatic polar alignment

1. Validate one capture and one solve with the actual camera and optics.
2. Record camera scale/FOV and use them as solve hints.
3. Implement and validate the three solved-frame polar-axis measurement with controlled RA rotation.
4. Verify the computed ALT/AZ correction signs against tiny supervised physical movements.
5. Expose the controller through the upstream INDI PAC interface on a compatible KStars/INDI stack, or keep corrections inside the desktop app.
6. Add correction magnitude, soft-limit, timeout, no-improvement and abort guards.
7. Only then unlock closed-loop motor correction.

This sequencing is deliberate: a successful plate solve is not proof that motor direction, mechanical clearance, backlash or loaded stopping is safe.
