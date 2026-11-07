# Build and installation

## Toolchain

The validated toolchain is:

- Arduino CLI 1.2.2
- ESP32 Arduino core 3.3.12
- board target `esp32:esp32:esp32`
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

The helper defaults to a 4 MiB ESP32 flash image. Set `B1_FLASH_SIZE_BYTES` only if the board has a confirmed different flash size.

## Upload

Uploading replaces the current controller firmware and can reset the board. Do it only after the backup and the procedure in [Safety](safety.md):

```bash
./scripts/flash.sh /dev/serial/by-id/usb-1a86_USB_Serial-if00-port0
```

Neither `build.sh` nor `check.sh` accesses the serial port.
