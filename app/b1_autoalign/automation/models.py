"""Shared data models for capture and plate-solving backends."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class CameraDevice:
    name: str


@dataclass(frozen=True)
class PlateSolution:
    backend: str
    ra_deg: float
    dec_deg: float
    orientation_deg: float | None = None
    pixel_scale_arcsec: float | None = None
    field_width_deg: float | None = None
    field_height_deg: float | None = None
    image_path: Path | None = None
    wcs_path: Path | None = None


@dataclass(frozen=True)
class EkosReport:
    running: bool = False
    version: str = ""
    align_available: bool = False
    capture_solve_available: bool = False
    indi_status: int | None = None
    ekos_status: int | None = None
    camera: str = ""
    optical_train: str = ""
    detail: str = "KStars is not running"

    @property
    def ready(self) -> bool:
        return self.running and self.capture_solve_available and bool(self.camera)


@dataclass(frozen=True)
class SolverReport:
    available: bool = False
    solve_field: str = ""
    wcsinfo: str = ""
    index_count: int = 0
    detail: str = "Astrometry.net was not found"

    @property
    def ready(self) -> bool:
        return self.available and self.index_count > 0


@dataclass(frozen=True)
class AutomationReport:
    requested_backend: str
    selected_backend: str
    ekos: EkosReport
    cameras: tuple[CameraDevice, ...]
    solver: SolverReport
    pac_devices: tuple[str, ...] = ()
    ready: bool = False
    detail: str = ""
    warnings: tuple[str, ...] = field(default_factory=tuple)
