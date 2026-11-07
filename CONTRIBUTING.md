# Contributing

Contributions are welcome through GitHub issues and pull requests.

Before submitting a change:

1. Keep the firmware focused on the ALT/AZ polar-alignment base.
2. Do not add automatic startup motion.
3. Preserve the ALT lower-limit and safe-stop behavior.
4. Run `./scripts/check.sh`.
5. Document whether a result is compile-tested, bench-tested or tested under mechanical load.

Hardware changes must include the board revision, driver type, motor wiring, supply voltage and a safe test procedure.
