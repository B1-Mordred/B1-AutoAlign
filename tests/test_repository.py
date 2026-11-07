import re
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "firmware" / "B1-AutoAlign" / "B1-AutoAlign.ino"


class FirmwareContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = SOURCE.read_text(encoding="utf-8")

    def test_product_identity(self):
        self.assertIn('Serial.print("B1-AutoAlign#")', self.source)
        self.assertIn('Serial.print("B1-AutoAlign V0.2.0#")', self.source)

    def test_oae_v1_pin_contract(self):
        expected = {
            "ALT_STEP_PIN": 13,
            "ALT_DIR_PIN": 23,
            "ALT_EN_PIN": 4,
            "AZ_STEP_PIN": 18,
            "AZ_DIR_PIN": 19,
            "AZ_EN_PIN": 32,
        }
        for name, pin in expected.items():
            self.assertRegex(self.source, rf"constexpr uint8_t {name}\s*=\s*{pin};")

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
        self.assertIn("CONFIG_SCHEMA_VERSION = 2", self.source)
        self.assertIn("ServiceResult::TimedOut", header)
        self.assertIn("HoldMode::Always", header)

    def test_project_namespace(self):
        self.assertIn('preferences.begin("b1autoalign", false)', self.source)


class RepositoryTests(unittest.TestCase):
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
