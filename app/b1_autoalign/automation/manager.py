"""Backend selection and capture-and-solve orchestration."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from .ekos import EkosClient
from .indi_camera import IndiCameraClient
from .models import AutomationReport, PlateSolution
from .solver import AstrometrySolver


class AutomationManager:
    def __init__(
        self,
        host: str = "localhost",
        port: int = 7624,
        *,
        ekos: EkosClient | None = None,
        camera: IndiCameraClient | None = None,
        solver: AstrometrySolver | None = None,
    ) -> None:
        self.host = host
        self.port = port
        self.ekos = ekos or EkosClient()
        self.camera = camera or IndiCameraClient(host, port)
        self.solver = solver or AstrometrySolver()

    def detect(self, requested_backend: str = "auto") -> AutomationReport:
        if requested_backend not in {"auto", "ekos", "standalone"}:
            raise ValueError(f"Unknown automation backend: {requested_backend}")
        ekos = self.ekos.detect()
        cameras = self.camera.discover()
        solver = self.solver.detect()
        pac_devices = self.camera.discover_pac_devices()
        standalone_ready = bool(cameras) and solver.ready

        selected = "none"
        ready = False
        if requested_backend == "ekos":
            selected, ready = "ekos", ekos.ready
        elif requested_backend == "standalone":
            selected, ready = "standalone", standalone_ready
        elif ekos.ready:
            selected, ready = "ekos", True
        elif standalone_ready:
            selected, ready = "standalone", True

        warnings = [
            "Automatic motor correction remains locked until camera, solve, axis direction and limits are validated.",
        ]
        if ekos.running and not ekos.capture_solve_available:
            warnings.append("This KStars version does not expose Ekos capture-and-solve over D-Bus.")
        if not cameras:
            warnings.append(f"No INDI camera is visible on {self.host}:{self.port}.")
        if not pac_devices:
            warnings.append("No INDI PAC correction interface is available; this is expected on INDI 1.9.9.")

        if ready and selected == "ekos":
            detail = f"Ready: Ekos/KStars with {ekos.camera}"
        elif ready:
            detail = f"Ready: standalone INDI camera {cameras[0].name} with Astrometry.net"
        elif requested_backend == "ekos":
            detail = ekos.detail
        elif requested_backend == "standalone":
            detail = "Standalone backend needs an INDI camera and local Astrometry.net indexes"
        else:
            detail = "No complete capture-and-solve backend is currently ready"
        return AutomationReport(
            requested_backend=requested_backend,
            selected_backend=selected,
            ekos=ekos,
            cameras=cameras,
            solver=solver,
            pac_devices=pac_devices,
            ready=ready,
            detail=detail,
            warnings=tuple(warnings),
        )

    def capture_and_solve(
        self,
        requested_backend: str,
        *,
        camera: str = "",
        exposure: float = 2.0,
        scale_low: float | None = None,
        scale_high: float | None = None,
        center_ra_deg: float | None = None,
        center_dec_deg: float | None = None,
        search_radius_deg: float = 15.0,
        downsample: int = 2,
        output_dir: Path | None = None,
    ) -> PlateSolution:
        report = self.detect(requested_backend)
        if not report.ready:
            raise RuntimeError(report.detail)
        if report.selected_backend == "ekos":
            return self.ekos.capture_and_solve()

        selected_camera = camera or report.cameras[0].name
        if selected_camera not in {item.name for item in report.cameras}:
            raise RuntimeError(f"INDI camera is not available: {selected_camera}")
        target_dir = (output_dir or (Path.home() / "Pictures" / "B1-AutoAlign")).expanduser()
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        image = self.camera.capture(selected_camera, exposure, target_dir / f"capture-{timestamp}.fits")
        return self.solver.solve(
            image,
            scale_low=scale_low,
            scale_high=scale_high,
            center_ra_deg=center_ra_deg,
            center_dec_deg=center_dec_deg,
            search_radius_deg=search_radius_deg,
            downsample=downsample,
        )
