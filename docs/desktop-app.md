# Desktop application

The B1-AutoAlign Control Center is a native PyQt6 application for Linux. It keeps serial I/O on a worker thread so controller timeouts do not freeze the interface.

## Capabilities

- discover USB serial devices and remember the selected port;
- identify product and firmware version before enabling motion;
- display live ALT/AZ counters, motion state, calibration, limits and last fault;
- jog ALT and AZ in arcminutes or commissioning-only raw steps;
- send an immediate safe stop to B1-AutoAlign firmware;
- set both logical coordinates to zero;
- mark the physical ALT bottom and upper soft limit;
- restore the logical ALT position to an already stored upper reference without
  sending motor pulses;
- clear the upper ALT limit;
- mark and clear the AZ west/east soft limits;
- show live SENSOR1/GPIO39 and SENSOR2/GPIO36 OK/triggered states;
- assign one physical endstop to each axis and choose ALT bottom/top or AZ
  west/east explicitly;
- start bounded, guarded ALT or AZ endstop homing;
- display and persist independent ALT/AZ motor-direction inversion;
- configure release, timed and continuous motor holding;
- show correction-limit readiness and live driver-enable state;
- store ALT and AZ steps-per-arcminute calibration;
- detect and prefer an available Ekos/KStars capture-and-solve backend;
- fall back to a standard INDI camera plus local Astrometry.net;
- perform an explicit single capture-and-solve test without moving either PA axis;
- maintain a timestamped command and activity log.

The protocol client also resynchronizes once after an interrupted previous
connection leaves a status response in flight. When a move completes between
the separate position and motion-state queries, it refreshes once so the UI
shows the settled final coordinate rather than the last moving sample.

## Firmware safety gate

Full controls are enabled only when `:GVP#` returns `B1-AutoAlign`. An older controller such as `OpenAstroMount V1.13.16` can be connected for position/status inspection, but the application keeps all movement controls—including STOP—disabled.

This is intentional: the legacy V1.13.16 controller previously crashed when sent the generic `:Q#` stop command. B1-AutoAlign implements a safe `:Q#` path.

Firmware v0.2.0 keeps motor torque according to the configured holding policy after STOP. The explicit **Release idle drivers** operation requires confirmation because releasing torque may permit a heavy load to back-drive the mechanism.

Direction changes are commissioning operations. The app requires confirmation
that every changed axis is at its physical lower safe boundary. Firmware then
zeros that changed axis and clears its now-invalid upper limit(s); the safe
range must be recorded again before automatic correction can become ready.

Physical endstop inputs are disabled after the v0.3.0 migration until explicitly
assigned. The app prevents assigning one connector to both axes. Homing uses the
stored configuration—not an uncommitted dropdown edit—and requires confirmation.
It searches at most 100,000 steps, retains the normal 180-second timeout and can
be aborted with **STOP BOTH AXES**. A maximum-side switch can only home after its
upper soft reference has been recorded.

The commissioned coordinate convention is **ALT bottom = minimum/zero**, **ALT
top = maximum**, **AZ west = minimum/zero**, and **AZ east = maximum**. These
physical names are shown throughout the interface; minimum/maximum remain only
the protocol-level representation. A non-triggered sensor is displayed as
**OK**, while an actuated or open NC switch is displayed as **TRIGGERED**.

## Run from the checkout

Check/install Python dependencies and run the application:

```bash
./scripts/setup-app.sh
./scripts/run-app.sh
```

The runner automatically uses `.venv/bin/python` when that environment exists.
If PyQt6 and pyserial are already installed system-wide, `setup-app.sh` keeps using them and does not create an unnecessary environment. On Debian/Ubuntu, creating a new environment may first require the `python3-venv` package.

## Desktop launcher

Install a user-local application launcher and SVG icon:

```bash
./scripts/install-desktop.sh
```

Remove only those installed launcher files with:

```bash
./scripts/uninstall-desktop.sh
```

No root privileges are used. The launcher remains tied to the current repository location.

## Ekos serial-port ownership

Only one application can own the serial device at a time. Disconnect the B1-AutoAlign device in Ekos/INDI before connecting the desktop app. A port-busy error is shown when another process owns it.

## Automation tab

The Automation tab probes both supported acquisition paths in a worker thread:

1. **Ekos/KStars:** uses the public session D-Bus Align interface. The app forces solver action `2` (solve only), calls `captureAndSolve(true)`, waits for the terminal status and reads the RA/Dec/orientation result. It does not sync or slew the mount.
2. **Standalone:** discovers cameras through the standard INDI `CCD_EXPOSURE` property, receives the next `CCD1` FITS BLOB and solves it with local `solve-field`/`wcsinfo`.

Automatic mode prefers a fully ready Ekos path and otherwise selects the standalone path. See [Automation backends](automation-backends.md) for setup and the live compatibility boundary.

## Automatic polar-alignment boundary

The app can now acquire and plate-solve a test frame, but it does not yet run the three-frame polar-error measurement or send a computed correction to the motors. The interface shows **AUTOMATIC CORRECTION LOCKED**, and the automation code has no motor-client reference. This keeps camera/solver qualification separate from physical motion qualification.
