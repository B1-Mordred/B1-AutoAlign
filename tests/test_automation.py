import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

from b1_autoalign.automation.ekos import EkosClient  # noqa: E402
from b1_autoalign.automation.indi_camera import IndiCameraClient  # noqa: E402
from b1_autoalign.automation.manager import AutomationManager  # noqa: E402
from b1_autoalign.automation.models import CameraDevice, EkosReport, SolverReport  # noqa: E402
from b1_autoalign.automation.solver import AstrometrySolver  # noqa: E402


def completed(command, stdout="", stderr="", returncode=0):
    return subprocess.CompletedProcess(command, returncode, stdout, stderr)


class EkosTests(unittest.TestCase):
    def test_detects_public_capture_and_solve_api(self):
        def runner(command, _timeout):
            joined = " ".join(command)
            if command[:2] == ["kstars", "--version"]:
                return completed(command, "kstars 3.6.2 Stable\n")
            if "introspect" in command and command[-1] == "/KStars/Ekos":
                return completed(command, "interface org.kde.kstars.Ekos")
            if "introspect" in command and command[-1] == "/KStars/Ekos/Align":
                return completed(command, "method captureAndSolve; method getSolutionResult;")
            if joined.endswith(" camera"):
                return completed(command, "(<'Guide Camera'>,)\n")
            if joined.endswith(" opticalTrain"):
                return completed(command, "(<'Primary'>,)\n")
            if joined.endswith(" indiStatus"):
                return completed(command, "(<2>,)\n")
            if joined.endswith(" ekosStatus"):
                return completed(command, "(<3>,)\n")
            raise AssertionError(command)

        with patch("b1_autoalign.automation.ekos.shutil.which", return_value="/usr/bin/tool"):
            report = EkosClient(runner=runner).detect()
        self.assertTrue(report.ready)
        self.assertEqual(report.camera, "Guide Camera")
        self.assertEqual(report.indi_status, 2)

    def test_capture_uses_solve_only_action_and_returns_solution(self):
        commands = []

        class ReadyEkos(EkosClient):
            def detect(self):
                return EkosReport(
                    running=True, align_available=True, capture_solve_available=True,
                    camera="CCD", detail="ready",
                )

        def runner(command, _timeout):
            commands.append(command)
            joined = " ".join(command)
            if "setSolverAction" in joined:
                return completed(command, "()")
            if "captureAndSolve" in joined:
                return completed(command, "(true,)")
            if joined.endswith(" status"):
                return completed(command, "(<1>,)")
            if "getSolutionResult" in joined:
                return completed(command, "([123.4, -22.5, 44.0],)")
            raise AssertionError(command)

        solution = ReadyEkos(runner=runner, sleeper=lambda _seconds: None).capture_and_solve()
        self.assertEqual((solution.ra_deg, solution.dec_deg), (123.4, -22.5))
        self.assertTrue(any(command[-1] == "2" and "setSolverAction" in command[-2] for command in commands))


class IndiCameraTests(unittest.TestCase):
    def test_discovers_standard_ccd_exposure_properties(self):
        output = (
            "Main CCD.CCD_EXPOSURE.CCD_EXPOSURE_VALUE=1\n"
            "Guide CCD.CCD_EXPOSURE.CCD_EXPOSURE_VALUE=0\n"
        )
        runner = lambda command, _timeout: completed(command, output)
        with patch("b1_autoalign.automation.indi_camera.shutil.which", return_value="/usr/bin/indi_getprop"):
            cameras = IndiCameraClient(runner=runner).discover()
        self.assertEqual([camera.name for camera in cameras], ["Guide CCD", "Main CCD"])

    def test_discovers_future_pac_property(self):
        output = "B1-AutoAlign.PAC_MANUAL_ADJUSTMENT.MANUAL_AZ_STEP=0\n"
        runner = lambda command, _timeout: completed(command, output)
        with patch("b1_autoalign.automation.indi_camera.shutil.which", return_value="/usr/bin/indi_getprop"):
            devices = IndiCameraClient(runner=runner).discover_pac_devices()
        self.assertEqual(devices, ("B1-AutoAlign",))


class SolverTests(unittest.TestCase):
    def test_parses_wcsinfo(self):
        parsed = AstrometrySolver.parse_wcsinfo(
            "ra_center 12.345\ndec_center -45.6\norientation 89.5\npixscale 1.25\n"
        )
        self.assertEqual(parsed["dec_center"], -45.6)
        self.assertEqual(parsed["pixscale"], 1.25)

    def test_solves_with_bounded_subprocess_and_preserves_wcs(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "index-4100.fits").write_bytes(b"index")
            image = root / "frame.fits"
            image.write_bytes(b"fits")
            commands = []

            def runner(command, _timeout):
                commands.append(command)
                if command[0] == "/usr/bin/solve-field":
                    output = Path(command[command.index("--dir") + 1])
                    (output / "solution.solved").write_bytes(b"1")
                    (output / "solution.wcs").write_bytes(b"wcs")
                    return completed(command)
                return completed(command, "ra_center 10\ndec_center 20\norientation 30\npixscale 2\n")

            def which(name):
                return f"/usr/bin/{name}"

            with patch("b1_autoalign.automation.solver.shutil.which", side_effect=which):
                solution = AstrometrySolver(runner=runner, index_roots=[root]).solve(
                    image, scale_low=1.0, scale_high=3.0, center_ra_deg=10.0,
                    center_dec_deg=20.0, search_radius_deg=5.0, downsample=2,
                )
            self.assertEqual(solution.ra_deg, 10)
            self.assertTrue(solution.wcs_path.is_file())
            solve_command = commands[0]
            self.assertIn("--no-plots", solve_command)
            self.assertIn("--scale-low", solve_command)
            self.assertIn("--ra", solve_command)


class ManagerTests(unittest.TestCase):
    class FakeCamera:
        def __init__(self, cameras=(), pac=()):
            self._cameras = cameras
            self._pac = pac

        def discover(self):
            return tuple(CameraDevice(name) for name in self._cameras)

        def discover_pac_devices(self):
            return tuple(self._pac)

    class FakeSolver:
        def __init__(self, ready=True):
            self.report = SolverReport(
                available=ready, solve_field="solve-field", wcsinfo="wcsinfo",
                index_count=1 if ready else 0, detail="ready" if ready else "missing",
            )

        def detect(self):
            return self.report

    class FakeEkos:
        def __init__(self, ready=False):
            self.report = EkosReport(
                running=True, align_available=True, capture_solve_available=True,
                camera="Ekos CCD" if ready else "", detail="ready" if ready else "no camera",
            )

        def detect(self):
            return self.report

    def test_auto_prefers_ready_ekos(self):
        manager = AutomationManager(
            ekos=self.FakeEkos(True), camera=self.FakeCamera(["INDI CCD"]), solver=self.FakeSolver(),
        )
        self.assertEqual(manager.detect().selected_backend, "ekos")

    def test_auto_falls_back_to_standalone(self):
        manager = AutomationManager(
            ekos=self.FakeEkos(False), camera=self.FakeCamera(["INDI CCD"]), solver=self.FakeSolver(),
        )
        report = manager.detect()
        self.assertTrue(report.ready)
        self.assertEqual(report.selected_backend, "standalone")


if __name__ == "__main__":
    unittest.main()
