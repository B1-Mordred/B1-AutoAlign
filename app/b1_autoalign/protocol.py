"""Thread-agnostic serial protocol client for B1-AutoAlign."""

from __future__ import annotations

from dataclasses import dataclass
import math
import time
from typing import Callable, Optional

import serial


BAUD_RATE = 19200
SUPPORTED_PRODUCT = "B1-AutoAlign"


class ProtocolError(RuntimeError):
    """The controller returned an invalid or unsuccessful response."""


class UnsupportedFirmwareError(ProtocolError):
    """A motion command was attempted against non-B1 firmware."""


@dataclass(frozen=True)
class Identity:
    product: str
    version: str
    full_control: bool


@dataclass(frozen=True)
class Snapshot:
    az_steps: int
    alt_steps: int
    az_min: Optional[int]
    az_max: Optional[int]
    alt_min: Optional[int]
    alt_max: Optional[int]
    alt_calibration: Optional[float]
    az_calibration: Optional[float]
    fault: str
    moving_az: bool
    moving_alt: bool
    state: str
    az_target: Optional[int]
    alt_target: Optional[int]
    hold_mode: Optional[int]
    hold_delay_ms: Optional[int]
    az_driver_enabled: Optional[bool]
    alt_driver_enabled: Optional[bool]
    alt_direction_inverted: Optional[bool]
    az_direction_inverted: Optional[bool]
    limits_ready: Optional[bool]
    schema: Optional[int]


def parse_pgl(response: str) -> dict[str, str]:
    """Parse the comma-separated `:PGL#` response."""
    fields: dict[str, str] = {}
    for item in response.split(","):
        if "=" not in item:
            raise ProtocolError(f"Malformed PGL field: {item!r}")
        key, value = item.split("=", 1)
        fields[key] = value
    required = {"AZ", "ALT", "ALTMIN", "ALTMAX", "ACAL", "ZCAL", "FAULT"}
    missing = required.difference(fields)
    if missing:
        raise ProtocolError(f"PGL response is missing: {', '.join(sorted(missing))}")
    return fields


def parse_motion(response: str) -> tuple[bool, bool]:
    """Return AZ/ALT moving flags from the OpenAstroTech `:GX#` reply."""
    parts = response.split(",")
    if len(parts) < 2 or len(parts[1]) < 5:
        raise ProtocolError(f"Malformed GX response: {response!r}")
    motors = parts[1]
    return motors[3] != "-", motors[4] != "-"


class B1AutoAlignClient:
    """Own one serial connection and expose safe high-level operations."""

    def __init__(
        self,
        serial_factory: Optional[Callable[[str, int, float], object]] = None,
        trace: Optional[Callable[[str], None]] = None,
        startup_delay: float = 0.3,
    ) -> None:
        self._serial_factory = serial_factory or self._open_serial
        self._trace = trace or (lambda _message: None)
        self._startup_delay = startup_delay
        self._link: Optional[object] = None
        self.identity: Optional[Identity] = None

    @staticmethod
    def _open_serial(port: str, baud: int, timeout: float) -> serial.Serial:
        link = serial.Serial(port=None, baudrate=baud, timeout=timeout, write_timeout=timeout)
        link.dtr = False
        link.rts = False
        link.port = port
        link.open()
        return link

    @property
    def connected(self) -> bool:
        return self._link is not None and bool(getattr(self._link, "is_open", True))

    def connect(self, port: str, timeout: float = 1.2) -> Identity:
        self.close()
        try:
            self._link = self._serial_factory(port, BAUD_RATE, timeout)
            if self._startup_delay:
                time.sleep(self._startup_delay)
            self._reset_input()
            product = self._query_hash(":GVP#")
            version = self._query_hash(":GVN#")
            self.identity = Identity(
                product=product,
                version=version,
                full_control=product == SUPPORTED_PRODUCT,
            )
            return self.identity
        except Exception:
            self.close()
            raise

    def close(self) -> None:
        link, self._link = self._link, None
        self.identity = None
        if link is not None:
            try:
                link.close()
            except Exception:
                pass

    def _require_connection(self) -> object:
        if not self.connected:
            raise ProtocolError("Controller is not connected")
        return self._link

    def _require_full_control(self) -> None:
        if self.identity is None or not self.identity.full_control:
            product = self.identity.product if self.identity else "unknown"
            raise UnsupportedFirmwareError(
                f"Motion is disabled for {product!r}; flash B1-AutoAlign first"
            )

    def _reset_input(self) -> None:
        link = self._require_connection()
        link.reset_input_buffer()

    def _write(self, command: str) -> None:
        link = self._require_connection()
        if not command.startswith(":") or not command.endswith("#"):
            raise ValueError("Commands must use colon/hash framing")
        self._reset_input()
        self._trace(f"TX  {command}")
        link.write(command.encode("ascii"))
        link.flush()

    def _query_hash(self, command: str) -> str:
        self._write(command)
        link = self._require_connection()
        raw = link.read_until(b"#", 512)
        if not raw.endswith(b"#"):
            raise ProtocolError(f"Timeout waiting for {command}")
        response = raw[:-1].decode("ascii", errors="replace")
        self._trace(f"RX  {response}#")
        return response

    def _command_char(self, command: str) -> bool:
        self._write(command)
        link = self._require_connection()
        raw = link.read(1)
        if raw not in (b"0", b"1"):
            raise ProtocolError(f"Invalid acknowledgement for {command}: {raw!r}")
        self._trace(f"RX  {raw.decode('ascii')}")
        return raw == b"1"

    def _command_silent(self, command: str) -> None:
        self._write(command)

    def snapshot(self) -> Snapshot:
        return self._snapshot(allow_completion_refresh=True)

    def _snapshot(self, allow_completion_refresh: bool) -> Snapshot:
        identity = self.identity
        if identity is None:
            raise ProtocolError("Controller identity is unavailable")

        if identity.full_control:
            fields = parse_pgl(self._query_hash(":PGL#"))
            alt_max = None if fields["ALTMAX"] == "NA" else int(fields["ALTMAX"])
            az_min = None if fields.get("AZMIN", "NA") == "NA" else int(fields["AZMIN"])
            az_max = None if fields.get("AZMAX", "NA") == "NA" else int(fields["AZMAX"])
            az_steps = int(fields["AZ"])
            alt_steps = int(fields["ALT"])
            alt_min = int(fields["ALTMIN"])
            alt_cal = float(fields["ACAL"])
            az_cal = float(fields["ZCAL"])
            fault = fields["FAULT"]
            state = fields.get("STATE", "UNKNOWN")
            az_target = int(fields["AZTARGET"]) if "AZTARGET" in fields else None
            alt_target = int(fields["ALTTARGET"]) if "ALTTARGET" in fields else None
            hold_mode = int(fields["HOLD"]) if "HOLD" in fields else None
            hold_delay_ms = int(fields["HOLDMS"]) if "HOLDMS" in fields else None
            az_driver_enabled = fields.get("AZEN") == "1" if "AZEN" in fields else None
            alt_driver_enabled = fields.get("ALTEN") == "1" if "ALTEN" in fields else None
            alt_direction_inverted = fields.get("ALTINV") == "1" if "ALTINV" in fields else None
            az_direction_inverted = fields.get("AZINV") == "1" if "AZINV" in fields else None
            limits_ready = fields.get("LIMITS") == "1" if "LIMITS" in fields else None
            schema = int(fields["SCHEMA"]) if "SCHEMA" in fields else None
        else:
            positions = self._query_hash(":XGAA#").split("|")
            if len(positions) != 2:
                raise ProtocolError("Malformed XGAA position response")
            az_steps, alt_steps = map(int, positions)
            az_min = None
            az_max = None
            alt_min = None
            alt_max = None
            alt_cal = None
            az_cal = None
            fault = "LEGACY_READ_ONLY"
            state = "LEGACY"
            az_target = None
            alt_target = None
            hold_mode = None
            hold_delay_ms = None
            az_driver_enabled = None
            alt_driver_enabled = None
            alt_direction_inverted = None
            az_direction_inverted = None
            limits_ready = None
            schema = None

        moving_az, moving_alt = parse_motion(self._query_hash(":GX#"))
        if (
            allow_completion_refresh
            and identity.full_control
            and state != "IDLE"
            and not moving_az
            and not moving_alt
        ):
            # PGL and GX are separate serial queries. A move can finish between
            # them, leaving positions from the last moving instant paired with
            # an idle motion flag. Refresh once to return one settled snapshot.
            return self._snapshot(allow_completion_refresh=False)
        return Snapshot(
            az_steps=az_steps,
            alt_steps=alt_steps,
            az_min=az_min,
            az_max=az_max,
            alt_min=alt_min,
            alt_max=alt_max,
            alt_calibration=alt_cal,
            az_calibration=az_cal,
            fault=fault,
            moving_az=moving_az,
            moving_alt=moving_alt,
            state=state,
            az_target=az_target,
            alt_target=alt_target,
            hold_mode=hold_mode,
            hold_delay_ms=hold_delay_ms,
            az_driver_enabled=az_driver_enabled,
            alt_driver_enabled=alt_driver_enabled,
            alt_direction_inverted=alt_direction_inverted,
            az_direction_inverted=az_direction_inverted,
            limits_ready=limits_ready,
            schema=schema,
        )

    def move_arcminutes(self, axis: str, amount: float) -> None:
        self._require_full_control()
        normalized = axis.upper()
        limits = {"ALT": 140.0, "AZ": 320.0}
        if normalized not in limits:
            raise ValueError("Axis must be ALT or AZ")
        if not math.isfinite(amount) or amount == 0 or abs(amount) > limits[normalized]:
            raise ValueError(f"{normalized} move must be non-zero and within +/-{limits[normalized]:g} arcmin")
        command = "MAL" if normalized == "ALT" else "MAZ"
        self._command_silent(f":{command}{amount:.3f}#")

    def move_steps(self, axis: str, steps: int) -> None:
        self._require_full_control()
        normalized = axis.upper()
        if normalized not in ("ALT", "AZ"):
            raise ValueError("Axis must be ALT or AZ")
        if steps == 0 or abs(steps) > 100_000:
            raise ValueError("Raw move must be non-zero and within +/-100000 steps")
        command = "MXl" if normalized == "ALT" else "MXz"
        if not self._command_char(f":{command}{steps}#"):
            raise ProtocolError(f"{normalized} raw move was rejected")

    def stop(self) -> None:
        self._require_full_control()
        self._command_silent(":Q#")

    def zero_both(self) -> None:
        self._require_full_control()
        if not self._command_char(":hZ#"):
            raise ProtocolError("Zero command was rejected while an axis is moving")

    def mark_alt_bottom(self) -> None:
        self._require_full_control()
        if self._query_hash(":PAB#") != "1":
            raise ProtocolError("ALT bottom command was rejected")

    def mark_alt_top(self) -> None:
        self._require_full_control()
        if self._query_hash(":PAT#") != "1":
            raise ProtocolError("ALT top command was rejected")

    def restore_alt_top_reference(self) -> None:
        self._require_full_control()
        if self._query_hash(":PAU#") != "1":
            raise ProtocolError("Stored ALT top reference is unavailable or the axis is moving")

    def clear_alt_top(self) -> None:
        self._require_full_control()
        if self._query_hash(":PCT#") != "1":
            raise ProtocolError("Clearing the ALT top limit was rejected")

    def mark_az_bottom(self) -> None:
        self._require_full_control()
        if self._query_hash(":PZB#") != "1":
            raise ProtocolError("AZ lower-limit command was rejected")

    def mark_az_top(self) -> None:
        self._require_full_control()
        if self._query_hash(":PZT#") != "1":
            raise ProtocolError("AZ upper-limit command was rejected")

    def clear_az_limits(self) -> None:
        self._require_full_control()
        if self._query_hash(":PZC#") != "1":
            raise ProtocolError("Clearing the AZ limits was rejected")

    def set_hold_mode(self, mode: int) -> None:
        self._require_full_control()
        if mode not in (0, 1, 2):
            raise ValueError("Hold mode must be 0 (release), 1 (timed), or 2 (always)")
        if self._query_hash(f":PHM{mode}#") != "1":
            raise ProtocolError("Hold-mode command was rejected")

    def set_hold_delay(self, milliseconds: int) -> None:
        self._require_full_control()
        if not 0 <= milliseconds <= 600_000:
            raise ValueError("Hold delay must be between 0 and 600000 milliseconds")
        if self._query_hash(f":PHD{milliseconds}#") != "1":
            raise ProtocolError("Hold-delay command was rejected")

    def set_direction_inversion(self, alt_inverted: bool, az_inverted: bool) -> None:
        self._require_full_control()
        alt_value = 1 if alt_inverted else 0
        az_value = 1 if az_inverted else 0
        if self._query_hash(f":PDI{alt_value},{az_value}#") != "1":
            raise ProtocolError("Direction command was rejected; both axes must be idle")

    def release_drivers(self) -> None:
        self._require_full_control()
        if self._query_hash(":PDR#") != "1":
            raise ProtocolError("Drivers cannot be released while an axis is moving")

    def move_correction_degrees(self, az_degrees: float, alt_degrees: float) -> None:
        self._require_full_control()
        if not math.isfinite(az_degrees) or not math.isfinite(alt_degrees):
            raise ValueError("Correction values must be finite")
        if az_degrees == 0 and alt_degrees == 0:
            raise ValueError("At least one correction axis must be non-zero")
        if abs(az_degrees) > 320.0 / 60.0 or abs(alt_degrees) > 140.0 / 60.0:
            raise ValueError("Correction exceeds the firmware safety envelope")
        if self._query_hash(f":PAC{az_degrees:.6f},{alt_degrees:.6f}#") != "1":
            raise ProtocolError("Atomic correction was rejected; inspect limits and fault status")

    def set_calibration(self, axis: str, steps_per_arcminute: float) -> None:
        self._require_full_control()
        normalized = axis.upper()
        if normalized not in ("ALT", "AZ"):
            raise ValueError("Axis must be ALT or AZ")
        if not math.isfinite(steps_per_arcminute) or not 0 < steps_per_arcminute < 100_000:
            raise ValueError("Calibration must be between 0 and 100000 steps/arcmin")
        command = "PCAl" if normalized == "ALT" else "PCAz"
        if self._query_hash(f":{command}{steps_per_arcminute:.4f}#") != "1":
            raise ProtocolError(f"{normalized} calibration was rejected")
