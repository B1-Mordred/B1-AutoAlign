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
