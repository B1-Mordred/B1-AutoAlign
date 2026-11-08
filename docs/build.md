# Build and installation

## Toolchain

The validated toolchain is:

- Arduino CLI 1.2.2
- ESP32 Arduino core 3.3.12
- board target `esp32:esp32:esp32`
- a C++17 compiler for the executable host-side motion and endstop tests
- no third-party Arduino libraries

For Python tooling on a machine with pip available:

```bash
python3 -m pip install -r requirements.txt
```

For an isolated desktop-app environment, use `./scripts/setup-app.sh`; see [Desktop application](desktop-app.md).

Install the ESP32 core:

```bash
arduino-cli core update-index \
  --additional-urls https://espressif.github.io/arduino-esp32/package_esp32_index.json
arduino-cli core install esp32:esp32@3.3.12 \
  --additional-urls https://espressif.github.io/arduino-esp32/package_esp32_index.json
```

Compile and run all checks:

```bash
./scripts/check.sh
```

Compile only:

```bash
./scripts/build.sh
```

## Back up the installed controller

Stop Ekos/INDI so it releases the serial port. Then use the stable by-id device path:

```bash
./scripts/backup-flash.sh /dev/serial/by-id/usb-1a86_USB_Serial-if00-port0
```

The helper defaults to a 4 MiB ESP32 flash image and 460800 baud. It uses a
system `esptool`, its Python module, or the newest copy bundled with the Arduino
ESP32 core. Set `B1_FLASH_SIZE_BYTES` only if the board has a confirmed
different flash size. `B1_ESPTOOL` can select an explicit executable.

## Upload

Uploading replaces the current controller firmware and can reset the board. Do it only after the backup and the procedure in [Safety](safety.md):

```bash
./scripts/flash.sh /dev/serial/by-id/usb-1a86_USB_Serial-if00-port0
```

The normal helper uses the validated 460800 baud upload speed. The connected
OpenAstroExplorer-derived controller does not reliably enter download mode via
DTR/RTS. For an update to an already installed B1-AutoAlign controller:

1. Close the desktop app and Ekos/INDI.
2. Hold **BOOT**, tap **EN/RESET**, then release **BOOT**.
3. Optionally preserve the complete flash while leaving the controller in the
   bootloader:

   ```bash
   B1_ESPTOOL_BEFORE=no-reset B1_ESPTOOL_AFTER=no-reset \
     ./scripts/backup-flash.sh \
     /dev/serial/by-id/usb-1a86_USB_Serial-if00-port0 \
     backups/pre-update.bin
   ```

4. Upload only the application partition without toggling the reset lines:

   ```bash
   ./scripts/flash-manual.sh \
     /dev/serial/by-id/usb-1a86_USB_Serial-if00-port0
   ```

5. Tap **EN/RESET** without holding BOOT, then confirm `:GVP#`, `:GVN#` and
   `:PGL#` before allowing motion.

`flash-manual.sh` is for updates after the standard ESP32 partition table and
bootloader are already installed; it intentionally preserves NVS references,
limits and calibration.

Neither `build.sh` nor `check.sh` accesses the serial port.
