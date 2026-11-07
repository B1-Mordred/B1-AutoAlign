"""Local Astrometry.net plate-solver adapter."""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from collections.abc import Callable, Iterable
from pathlib import Path

from .models import PlateSolution, SolverReport


Runner = Callable[[list[str], float], subprocess.CompletedProcess[str]]


def _default_runner(command: list[str], timeout: float) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, text=True, capture_output=True, timeout=timeout, check=False)


class AstrometrySolver:
    def __init__(
        self,
        runner: Runner = _default_runner,
        index_roots: Iterable[Path] | None = None,
    ) -> None:
        self._runner = runner
        self.index_roots = tuple(index_roots or (
            Path("/usr/share/astrometry"),
            Path("/usr/local/share/astrometry"),
            Path.home() / ".local/share/astrometry",
        ))

    def detect(self) -> SolverReport:
        solve_field = shutil.which("solve-field") or ""
        wcsinfo = shutil.which("wcsinfo") or ""
        indexes = {
            path.resolve()
            for root in self.index_roots if root.exists()
            for pattern in ("index-*.fits", "index-*.fit", "index-*.fits.fz")
            for path in root.rglob(pattern)
        }
        if not solve_field or not wcsinfo:
            detail = "solve-field and wcsinfo are required"
        elif not indexes:
            detail = "Astrometry.net is installed, but no index files were found"
        else:
            detail = f"Astrometry.net ready with {len(indexes)} index files"
        return SolverReport(
            available=bool(solve_field and wcsinfo),
            solve_field=solve_field,
            wcsinfo=wcsinfo,
            index_count=len(indexes),
            detail=detail,
        )

    def solve(
        self,
        image_path: Path,
        *,
        scale_low: float | None = None,
        scale_high: float | None = None,
        center_ra_deg: float | None = None,
        center_dec_deg: float | None = None,
        search_radius_deg: float = 15.0,
        downsample: int = 2,
        timeout: float = 120,
    ) -> PlateSolution:
        report = self.detect()
        if not report.ready:
            raise RuntimeError(report.detail)
        image_path = image_path.expanduser().resolve()
        if not image_path.is_file():
            raise FileNotFoundError(image_path)

        with tempfile.TemporaryDirectory(prefix="b1-autoalign-solve-") as temporary:
            output_dir = Path(temporary)
            command = [
                report.solve_field,
                "--overwrite", "--no-plots", "--cpulimit", str(max(1, int(timeout))),
                "--dir", str(output_dir), "--out", "solution",
            ]
            if downsample > 1:
                command.extend(("--downsample", str(downsample)))
            if scale_low is not None and scale_high is not None:
                if scale_low <= 0 or scale_high <= scale_low:
                    raise ValueError("Scale bounds must be positive and high must exceed low")
                command.extend((
                    "--scale-units", "arcsecperpix",
                    "--scale-low", str(scale_low), "--scale-high", str(scale_high),
                ))
            if center_ra_deg is not None and center_dec_deg is not None:
                if not 0 <= center_ra_deg <= 360 or not -90 <= center_dec_deg <= 90:
                    raise ValueError("Pointing hint is outside valid RA/Dec bounds")
                if not 0 < search_radius_deg <= 180:
                    raise ValueError("Search radius must be between 0 and 180 degrees")
                command.extend((
                    "--ra", str(center_ra_deg), "--dec", str(center_dec_deg),
                    "--radius", str(search_radius_deg),
                ))
            command.append(str(image_path))
            try:
                result = self._runner(command, timeout + 10)
            except subprocess.TimeoutExpired as exc:
                raise TimeoutError(f"Astrometry.net exceeded the {timeout:.0f}-second solve limit") from exc
            solved = output_dir / "solution.solved"
            wcs_path = output_dir / "solution.wcs"
            if result.returncode != 0 or not solved.exists() or not wcs_path.exists():
                message = (result.stderr or result.stdout).strip()
                raise RuntimeError(message[-1000:] or "Astrometry.net did not solve the image")

            info = self._runner([report.wcsinfo, str(wcs_path)], 10)
            if info.returncode != 0:
                raise RuntimeError(info.stderr.strip() or "wcsinfo failed")
            values = self.parse_wcsinfo(info.stdout)
            persistent_wcs = image_path.with_suffix(image_path.suffix + ".wcs")
            shutil.copy2(wcs_path, persistent_wcs)
            return PlateSolution(
                backend="Standalone INDI + Astrometry.net",
                ra_deg=values["ra_center"],
                dec_deg=values["dec_center"],
                orientation_deg=values.get("orientation"),
                pixel_scale_arcsec=values.get("pixscale"),
                field_width_deg=values.get("fieldw"),
                field_height_deg=values.get("fieldh"),
                image_path=image_path,
                wcs_path=persistent_wcs,
            )

    @staticmethod
    def parse_wcsinfo(output: str) -> dict[str, float]:
        wanted = {"ra_center", "dec_center", "orientation", "pixscale", "fieldw", "fieldh"}
        values: dict[str, float] = {}
        for line in output.splitlines():
            match = re.match(r"^([A-Za-z_]+)\s+([-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)", line.strip())
            if match and match.group(1) in wanted:
                values[match.group(1)] = float(match.group(2))
        if "ra_center" not in values or "dec_center" not in values:
            raise RuntimeError("wcsinfo did not return a sky position")
        return values
