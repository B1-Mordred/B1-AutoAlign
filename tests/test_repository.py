import hashlib
import re
import struct
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "firmware" / "B1-AutoAlign" / "B1-AutoAlign.ino"
AUTOPA_MODELS = ROOT / "hardware" / "openastroexplorer-autopa"

AUTOPA_SHA256 = {
    "51111_adapter_left.STL": "3f7ab6a4f5b4d00b8bdc284c205b184dabfe4e272300800cc1c7271b32d61700",
    "51111_adapter_right.STL": "8daf4fd858b594acc730d9ffbdc72142cbed567c054f1864004cc27176df19cd",
    "ALT_Knob.STL": "cf38ee6fbfc799c1d9897c8796b8c7e7c5f0c3eee478b53df8bd51f67d5acb6a",
    "ALT_slider.STL": "14326072f24c298dfc9e934ba29abdcc795acf80bac210eddfbb4f1667d3e9a9",
    "AZ_connector.STL": "6dc44f54981ce814eb465973783c5e8de427a705809f2d7fbeed1ba832a8bc64",
    "AZ_coupler.STL": "a7ae1a363c2ecd4673c48d8dffc6424e183f383c2e15aa21740573602e6b3a8d",
    "AZ_slider.STL": "f9aed700750bbd600af850b63f38625402dd2ba4531822e2bb0bbd0431c13f92",
    "ESP_lid.STL": "dfd285bf2fbc20bf669fe2e787333d58015c772673ca945562a0f953fbf4a8e4",
    "MGN9C_adapter.STL": "de57d76931e9f9abac01821bf7717d621e70dc4cc3895499289c537c1b53ed2e",
    "driver_lid.STL": "887e66ecb2b9308b8e723cbef9e8fbfcd89f0aa9639661a440f02d412960110e",
}


class FirmwareContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = SOURCE.read_text(encoding="utf-8")

    def test_product_identity(self):
        self.assertIn('Serial.print("B1-AutoAlign#")', self.source)
        self.assertIn('Serial.print("B1-AutoAlign V0.3.0#")', self.source)

    def test_oae_v1_pin_contract(self):
        expected = {
            "ALT_STEP_PIN": 13,
            "ALT_DIR_PIN": 23,
            "ALT_EN_PIN": 4,
            "AZ_STEP_PIN": 18,
            "AZ_DIR_PIN": 19,
            "AZ_EN_PIN": 32,
            "SENSOR1_PIN": 39,
            "SENSOR2_PIN": 36,
        }
        for name, pin in expected.items():
            self.assertRegex(self.source, rf"constexpr uint8_t {name}\s*=\s*{pin};")

    def test_altitude_positive_direction_is_inverted_for_assembled_base(self):
        self.assertRegex(self.source, r"constexpr bool DEFAULT_ALT_DIR_INVERT\s*=\s*true;")
        self.assertRegex(self.source, r"constexpr bool DEFAULT_AZ_DIR_INVERT\s*=\s*false;")
        self.assertIn('strncmp(body, "PDI", 3) == 0', self.source)
        self.assertIn('preferences.putBool("altInv", altDirInvert)', self.source)
        self.assertIn('preferences.putBool("azInv", azDirInvert)', self.source)

    def test_lx200_raw_ack_handshake(self):
        self.assertIn("static_cast<uint8_t>(incoming) == 0x06", self.source)
        self.assertIn("Serial.print('P')", self.source)

    def test_altitude_lower_limit_and_safe_stop(self):
        self.assertRegex(self.source, r"DEFAULT_ALT_MIN\s*=\s*0;")
        self.assertIn('strcmp(body, "Q") == 0', self.source)
        self.assertIn("altitude.stopNow(nowMs);", self.source)
        self.assertIn("azimuth.stopNow(nowMs);", self.source)

    def test_v02_motion_safety_contract(self):
        header = (SOURCE.parent / "MotionAxis.h").read_text(encoding="utf-8")
        self.assertIn('strcmp(body, "PZB") == 0', self.source)
        self.assertIn('strcmp(body, "PZT") == 0', self.source)
        self.assertIn('strncmp(body, "PAC", 3) == 0', self.source)
        self.assertIn("startAtomicRelativeMove", self.source)
        self.assertIn("MAX_ALT_COMMAND_ARCMIN", self.source)
        self.assertIn("MAX_AZ_COMMAND_ARCMIN", self.source)
        self.assertIn("CONFIG_SCHEMA_VERSION = 4", self.source)
        self.assertIn("ServiceResult::TimedOut", header)
        self.assertIn("HoldMode::Always", header)
        self.assertIn('strcmp(body, "PAU") == 0', self.source)
        self.assertIn("MotionCompleted", self.source)

    def test_motion_timing_is_independent_of_serial_polling(self):
        header = (SOURCE.parent / "MotionAxis.h").read_text(encoding="utf-8")
        loop_body = self.source.split("void loop()", 1)[1]
        self.assertIn("ESP_TIMER_TASK", self.source)
        self.assertIn("esp_timer_restart(motionTimer, nextServiceUs)", self.source)
        self.assertIn("Serial.setTxBufferSize(Config::SERIAL_TX_BUFFER_BYTES)", self.source)
        self.assertIn("microsecondsUntilStep", header)
        self.assertIn("AxisLockGuard", header)
        self.assertNotIn("altitude.service(", loop_body)
        self.assertNotIn("azimuth.service(", loop_body)

    def test_project_namespace(self):
        self.assertIn('preferences.begin("b1autoalign", false)', self.source)

    def test_physical_endstop_safety_contract(self):
        endstop_header = (SOURCE.parent / "EndstopInput.h").read_text(encoding="utf-8")
        motion_header = (SOURCE.parent / "MotionAxis.h").read_text(encoding="utf-8")
        self.assertIn("ENDSTOP_DEBOUNCE_MS", self.source)
        self.assertIn("MotionAltEndstop", self.source)
        self.assertIn("MotionAzEndstop", self.source)
        self.assertIn('strncmp(body, "PES", 3) == 0', self.source)
        self.assertIn('strcmp(body, "PHEA") == 0', self.source)
        self.assertIn('strcmp(body, "PHEZ") == 0', self.source)
        self.assertIn("endstopBlocksDirection", endstop_header)
        self.assertIn("startHomingMove", motion_header)
        self.assertNotIn("NO_ENDSW", self.source)


class RepositoryTests(unittest.TestCase):
    def test_release_versions_are_consistent(self):
        project = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        package_init = (ROOT / "app" / "b1_autoalign" / "__init__.py").read_text(encoding="utf-8")
        version = re.search(r'^version\s*=\s*"([^"]+)"', project, re.MULTILINE)
        self.assertIsNotNone(version)
        self.assertEqual(version.group(1), "0.3.0")
        self.assertIn('__version__ = "0.3.0"', package_init)
        self.assertIn('Serial.print("B1-AutoAlign V0.3.0#")', SOURCE.read_text(encoding="utf-8"))

    def test_autopa_model_set_and_checksums(self):
        model_dir = AUTOPA_MODELS / "STL"
        actual_names = {path.name for path in model_dir.glob("*.STL")}
        self.assertEqual(set(AUTOPA_SHA256), actual_names)

        for name, expected_hash in AUTOPA_SHA256.items():
            digest = hashlib.sha256((model_dir / name).read_bytes()).hexdigest()
            self.assertEqual(expected_hash, digest, name)

        checksum_lines = (AUTOPA_MODELS / "SHA256SUMS").read_text(encoding="ascii").splitlines()
        expected_lines = {
            f"{digest}  STL/{name}" for name, digest in AUTOPA_SHA256.items()
        }
        self.assertEqual(expected_lines, set(checksum_lines))

    def test_autopa_models_are_valid_binary_stl_records(self):
        for name in AUTOPA_SHA256:
            path = AUTOPA_MODELS / "STL" / name
            with path.open("rb") as model:
                header = model.read(84)
            self.assertEqual(84, len(header), name)
            triangle_count = struct.unpack("<I", header[80:84])[0]
            self.assertGreater(triangle_count, 0, name)
            self.assertEqual(84 + triangle_count * 50, path.stat().st_size, name)

    def test_autopa_models_have_separate_license(self):
        license_text = (AUTOPA_MODELS / "LICENSE.md").read_text(encoding="utf-8")
        self.assertIn("Attribution-NonCommercial 4.0 International", license_text)
        self.assertIn("a5373d654d3d14ce146800848f2b174f9c0f6e27",
                      (AUTOPA_MODELS / "README.md").read_text(encoding="utf-8"))

    def test_no_precursor_project_name_remains(self):
        old_name = "OpenAstro" + "PA"
        checked_suffixes = {".ino", ".md", ".py", ".sh", ".yml"}
        for path in ROOT.rglob("*"):
            if path.is_file() and path.suffix in checked_suffixes and ".git" not in path.parts:
                self.assertNotIn(old_name, path.read_text(encoding="utf-8"), str(path))

    def test_local_markdown_links_exist(self):
        pattern = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
        for document in ROOT.rglob("*.md"):
            for target in pattern.findall(document.read_text(encoding="utf-8")):
                if target.startswith(("http://", "https://", "mailto:", "#")):
                    continue
                local_target = target.split("#", 1)[0]
                self.assertTrue((document.parent / local_target).resolve().exists(),
                                f"broken link in {document}: {target}")

    def test_shell_scripts_parse(self):
        scripts = sorted((ROOT / "scripts").glob("*.sh"))
        subprocess.run(["bash", "-n", *map(str, scripts)], check=True)


if __name__ == "__main__":
    unittest.main()
