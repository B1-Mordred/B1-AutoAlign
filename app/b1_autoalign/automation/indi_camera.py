"""Standalone INDI camera capture using the standard command-line clients."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import time
from collections.abc import Callable
from pathlib import Path

from .models import CameraDevice


Runner = Callable[[list[str], float], subprocess.CompletedProcess[str]]


def _default_runner(command: list[str], timeout: float) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, text=True, capture_output=True, timeout=timeout, check=False)


class IndiCameraClient:
    exposure_suffix = ".CCD_EXPOSURE.CCD_EXPOSURE_VALUE"

    def __init__(self, host: str = "localhost", port: int = 7624, runner: Runner = _default_runner) -> None:
        self.host = host
        self.port = port
        self._runner = runner

    def _base(self, executable: str) -> list[str]:
        return [executable, "-h", self.host, "-p", str(self.port), "-t", "3"]

    def discover(self) -> tuple[CameraDevice, ...]:
        getprop = shutil.which("indi_getprop")
        if not getprop:
            return ()
        result = self._runner(
            self._base(getprop) + [f"*{self.exposure_suffix}"],
            5,
        )
        devices = set()
        for line in result.stdout.splitlines():
            qualified = line.split("=", 1)[0].strip()
            if qualified.endswith(self.exposure_suffix):
                devices.add(qualified[: -len(self.exposure_suffix)])
        return tuple(CameraDevice(name) for name in sorted(devices))

    def discover_pac_devices(self) -> tuple[str, ...]:
        getprop = shutil.which("indi_getprop")
        if not getprop:
            return ()
        suffix = ".PAC_MANUAL_ADJUSTMENT.MANUAL_AZ_STEP"
        result = self._runner(self._base(getprop) + [f"*{suffix}"], 5)
        devices = {
            line.split("=", 1)[0].strip()[: -len(suffix)]
            for line in result.stdout.splitlines()
            if line.split("=", 1)[0].strip().endswith(suffix)
        }
        return tuple(sorted(devices))

    def capture(self, camera: str, exposure: float, output_path: Path, timeout: float = 90) -> Path:
        """Trigger a standard CCD exposure and save the next CCD1 FITS BLOB."""

        if camera not in {item.name for item in self.discover()}:
            raise RuntimeError(f"INDI camera is not available: {camera}")
        if exposure <= 0:
            raise ValueError("Exposure must be positive")
        getprop = shutil.which("indi_getprop")
        setprop = shutil.which("indi_setprop")
        if not getprop or not setprop:
            raise RuntimeError("indi_getprop and indi_setprop are required")

        output_path = output_path.expanduser().resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="b1-autoalign-capture-") as temporary:
            capture_dir = Path(temporary)
            monitor = subprocess.Popen(
                self._base(getprop) + ["-m", f"{camera}.CCD1.CCD1"],
                cwd=capture_dir,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            try:
                time.sleep(0.25)
                trigger = self._runner(
                    self._base(setprop) + ["-n", f"{camera}{self.exposure_suffix}={exposure:.3f}"],
                    5,
                )
                if trigger.returncode != 0:
                    raise RuntimeError(trigger.stderr.strip() or "INDI rejected the exposure")
                deadline = time.monotonic() + max(timeout, exposure + 15)
                while time.monotonic() < deadline:
                    candidates = sorted(
                        (path for path in capture_dir.iterdir() if ".fit" in path.name.lower()),
                        key=lambda path: path.stat().st_mtime,
                    )
                    if candidates:
                        source = candidates[-1]
                        lowered = source.name.lower()
                        extension = ".fits.z" if lowered.endswith(".fits.z") else (
                            ".fits.fz" if lowered.endswith(".fits.fz") else (
                                ".fit" if lowered.endswith(".fit") else ".fits"
                            )
                        )
                        destination = Path(str(output_path.with_suffix("")) + extension)
                        shutil.move(source, destination)
                        return destination
                    if monitor.poll() is not None:
                        error = monitor.stderr.read().strip() if monitor.stderr else ""
                        raise RuntimeError(error or "INDI BLOB monitor stopped before an image arrived")
                    time.sleep(0.1)
                raise TimeoutError("No INDI CCD1 image arrived before the capture timeout")
            finally:
                if monitor.poll() is None:
                    monitor.terminate()
                    try:
                        monitor.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        monitor.kill()
                        monitor.wait(timeout=2)
