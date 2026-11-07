#!/usr/bin/env python3
"""Small diagnostic client for the B1-AutoAlign serial protocol."""

import argparse
import sys
import time

import serial


DEFAULT_PORT = "/dev/serial/by-id/usb-1a86_USB_Serial-if00-port0"


def transact(port: str, baud: int, command: str, timeout: float) -> str:
    if not command.startswith(":") or not command.endswith("#"):
        raise ValueError("command must start with ':' and end with '#'")
    with serial.Serial(port, baud, timeout=timeout, write_timeout=timeout) as link:
        link.dtr = False
        link.rts = False
        time.sleep(0.3)
        link.reset_input_buffer()
        link.write(command.encode("ascii"))
        link.flush()
        return link.read_until(b"#", 512).decode("ascii", errors="replace")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", help="for example :PGL# or :GVP#")
    parser.add_argument("--port", default=DEFAULT_PORT)
    parser.add_argument("--baud", type=int, default=19200)
    parser.add_argument("--timeout", type=float, default=2.0)
    args = parser.parse_args()
    try:
        response = transact(args.port, args.baud, args.command, args.timeout)
    except (ValueError, serial.SerialException) as exc:
        print(exc, file=sys.stderr)
        return 2
    print(response)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
