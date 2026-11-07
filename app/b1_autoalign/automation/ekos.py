"""KStars/Ekos integration through its public session D-Bus API."""

from __future__ import annotations

import re
import shutil
import subprocess
import time
from collections.abc import Callable

from .models import EkosReport, PlateSolution


Runner = Callable[[list[str], float], subprocess.CompletedProcess[str]]


def _default_runner(command: list[str], timeout: float) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, text=True, capture_output=True, timeout=timeout, check=False)


def _variant_string(output: str) -> str:
    match = re.search(r"<(['\"])(.*?)\1>", output, re.DOTALL)
    return match.group(2).replace("\\'", "'") if match else ""


def _variant_int(output: str) -> int | None:
    match = re.search(r"<(?:(?:u?int(?:16|32|64))\s+)?(-?\d+)>", output)
    return int(match.group(1)) if match else None


def _boolean(output: str) -> bool:
    return bool(re.search(r"\btrue\b", output, re.IGNORECASE))


def _numbers(output: str) -> list[float]:
    return [float(value) for value in re.findall(r"(?<![A-Za-z])[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?", output)]


class EkosClient:
    """Small, dependency-free adapter around the KStars D-Bus interface."""

    service = "org.kde.kstars"
    ekos_path = "/KStars/Ekos"
    align_path = "/KStars/Ekos/Align"
    ekos_interface = "org.kde.kstars.Ekos"
    align_interface = "org.kde.kstars.Ekos.Align"

    def __init__(self, runner: Runner = _default_runner, sleeper: Callable[[float], None] = time.sleep) -> None:
        self._runner = runner
        self._sleep = sleeper

    def _run(self, command: list[str], timeout: float = 5) -> subprocess.CompletedProcess[str]:
        return self._runner(command, timeout)

    def _introspect(self, path: str) -> subprocess.CompletedProcess[str]:
        return self._run([
            "gdbus", "introspect", "--session", "--dest", self.service, "--object-path", path,
        ])

    def _property(self, path: str, interface: str, name: str) -> str:
        result = self._run([
            "gdbus", "call", "--session", "--dest", self.service, "--object-path", path,
            "--method", "org.freedesktop.DBus.Properties.Get", interface, name,
        ])
        return result.stdout if result.returncode == 0 else ""

    def _call(self, path: str, method: str, *arguments: str, timeout: float = 10) -> subprocess.CompletedProcess[str]:
        return self._run([
            "gdbus", "call", "--session", "--dest", self.service, "--object-path", path,
            "--method", method, *arguments,
        ], timeout)

    def detect(self) -> EkosReport:
        if not shutil.which("gdbus"):
            return EkosReport(detail="gdbus is not installed")

        root = self._introspect(self.ekos_path)
        if root.returncode != 0:
            return EkosReport(detail="KStars/Ekos is not available on the session D-Bus")

        version_result = self._run(["kstars", "--version"], 3) if shutil.which("kstars") else None
        version = version_result.stdout.strip() if version_result and version_result.returncode == 0 else ""
        align = self._introspect(self.align_path)
        align_text = align.stdout if align.returncode == 0 else ""
        capture_available = "captureAndSolve" in align_text and "getSolutionResult" in align_text
        camera = _variant_string(self._property(self.align_path, self.align_interface, "camera"))
        train = _variant_string(self._property(self.align_path, self.align_interface, "opticalTrain"))
        indi_status = _variant_int(self._property(self.ekos_path, self.ekos_interface, "indiStatus"))
        ekos_status = _variant_int(self._property(self.ekos_path, self.ekos_interface, "ekosStatus"))

        if not capture_available:
            detail = "Ekos Align is present but does not expose captureAndSolve"
        elif not camera:
            detail = "Ekos Align is available, but no camera is selected"
        else:
            detail = f"Ekos capture-and-solve ready with {camera}"
        return EkosReport(
            running=True,
            version=version,
            align_available=align.returncode == 0,
            capture_solve_available=capture_available,
            indi_status=indi_status,
            ekos_status=ekos_status,
            camera=camera,
            optical_train=train,
            detail=detail,
        )

    def capture_and_solve(self, timeout: float = 120) -> PlateSolution:
        """Capture and solve without syncing or slewing the mount."""

        report = self.detect()
        if not report.ready:
            raise RuntimeError(report.detail)

        action = self._call(self.align_path, f"{self.align_interface}.setSolverAction", "2")
        if action.returncode != 0:
            raise RuntimeError(action.stderr.strip() or "Could not select the solve-only Ekos action")
        started = self._call(self.align_path, f"{self.align_interface}.captureAndSolve", "true")
        if started.returncode != 0 or not _boolean(started.stdout):
            raise RuntimeError(started.stderr.strip() or "Ekos rejected captureAndSolve")

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            state = _variant_int(self._property(self.align_path, self.align_interface, "status"))
            if state == 1:  # ALIGN_COMPLETE
                result = self._call(self.align_path, f"{self.align_interface}.getSolutionResult")
                values = _numbers(result.stdout)
                if result.returncode != 0 or len(values) < 2 or values[0] <= -999_000:
                    raise RuntimeError("Ekos completed without a valid plate solution")
                return PlateSolution(
                    backend="Ekos/KStars",
                    ra_deg=values[0],
                    dec_deg=values[1],
                    orientation_deg=values[2] if len(values) > 2 else None,
                )
            if state in (2, 3):  # ALIGN_FAILED / ALIGN_ABORTED
                raise RuntimeError("Ekos plate solving failed or was aborted")
            self._sleep(0.5)
        raise TimeoutError(f"Ekos capture-and-solve did not finish within {timeout:.0f} seconds")
