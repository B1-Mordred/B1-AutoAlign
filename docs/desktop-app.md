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
- clear the upper ALT limit;
- store ALT and AZ steps-per-arcminute calibration;
- detect and prefer an available Ekos/KStars capture-and-solve backend;
- fall back to a standard INDI camera plus local Astrometry.net;
- perform an explicit single capture-and-solve test without moving either PA axis;
- maintain a timestamped command and activity log.

## Firmware safety gate

Full controls are enabled only when `:GVP#` returns `B1-AutoAlign`. An older controller such as `OpenAstroMount V1.13.16` can be connected for position/status inspection, but the application keeps all movement controls—including STOP—disabled.

This is intentional: the legacy V1.13.16 controller previously crashed when sent the generic `:Q#` stop command. B1-AutoAlign implements a safe `:Q#` path.

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
