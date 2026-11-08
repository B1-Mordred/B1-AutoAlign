import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

from b1_autoalign.protocol import (  # noqa: E402
    B1AutoAlignClient,
    ProtocolError,
    UnsupportedFirmwareError,
    parse_motion,
    parse_pgl,
)


class FakeSerial:
    def __init__(self, responses):
        self.responses = {key: list(value) for key, value in responses.items()}
        self.commands = []
        self.current = None
        self.is_open = True

    def reset_input_buffer(self):
        pass

    def write(self, payload):
        self.current = payload.decode("ascii")
        self.commands.append(self.current)

    def flush(self):
        pass

    def _response(self):
        values = self.responses.get(self.current, [])
        return values.pop(0) if values else b""

    def read_until(self, _terminator, _size):
        return self._response()

    def read(self, _size):
        return self._response()

    def close(self):
        self.is_open = False


def client_with(responses):
    fake = FakeSerial(responses)
    client = B1AutoAlignClient(
        serial_factory=lambda _port, _baud, _timeout: fake,
        startup_delay=0,
    )
    return client, fake


class ParserTests(unittest.TestCase):
    def test_pgl_and_motion_parsing(self):
        fields = parse_pgl("AZ=11,ALT=100,ALTMIN=0,ALTMAX=5000,ACAL=100.0,ZCAL=11.0,FAULT=NONE")
        self.assertEqual(fields["ALTMAX"], "5000")
        self.assertEqual(parse_motion("Parked,---za-,0,0#"), (True, True))

    def test_malformed_pgl_is_rejected(self):
        with self.assertRaises(ProtocolError):
            parse_pgl("AZ=0,ALT=0")


class ClientTests(unittest.TestCase):
    def test_full_identity_snapshot_and_motion_commands(self):
        client, fake = client_with({
            ":GVP#": [b"B1-AutoAlign#"],
            ":GVN#": [b"V0.2.1#"],
            ":PGL#": [
                b"AZ=11,ALT=100,AZMIN=0,AZMAX=500,ALTMIN=0,ALTMAX=1000,"
                b"AZTARGET=11,ALTTARGET=100,ACAL=100.0,ZCAL=11.0,STATE=IDLE,FAULT=NONE,"
                b"HOLD=2,HOLDMS=5000,AZEN=1,ALTEN=1,ALTINV=1,AZINV=0,LIMITS=1,SCHEMA=3#"
            ],
            ":GX#": [b"Parked,------,0,0#"],
            ":MXl10#": [b"1"],
        })
        identity = client.connect("fake")
        self.assertTrue(identity.full_control)
        snapshot = client.snapshot()
        self.assertEqual((snapshot.az_steps, snapshot.alt_steps), (11, 100))
        self.assertEqual(snapshot.alt_max, 1000)
        self.assertEqual((snapshot.az_min, snapshot.az_max), (0, 500))
        self.assertTrue(snapshot.limits_ready)
        self.assertEqual(snapshot.hold_mode, 2)
        self.assertTrue(snapshot.alt_direction_inverted)
        self.assertFalse(snapshot.az_direction_inverted)
        client.move_arcminutes("ALT", 1.25)
        client.move_steps("ALT", 10)
        self.assertIn(":MAL1.250#", fake.commands)
        self.assertIn(":MXl10#", fake.commands)

    def test_legacy_firmware_is_strictly_read_only(self):
        client, _fake = client_with({
            ":GVP#": [b"OpenAstroMount#"],
            ":GVN#": [b"V1.13.16#"],
            ":XGAA#": [b"0|0#"],
            ":GX#": [b"Parked,------,0,0#"],
        })
        identity = client.connect("fake")
        self.assertFalse(identity.full_control)
        self.assertEqual(client.snapshot().fault, "LEGACY_READ_ONLY")
        with self.assertRaises(UnsupportedFirmwareError):
            client.move_arcminutes("ALT", 1)
        with self.assertRaises(UnsupportedFirmwareError):
            client.stop()

    def test_snapshot_refreshes_if_move_finishes_between_queries(self):
        moving = (
            b"AZ=0,ALT=61002,AZMIN=NA,AZMAX=NA,ALTMIN=0,ALTMAX=62000,"
            b"AZTARGET=0,ALTTARGET=61000,ACAL=100.0,ZCAL=11.0,STATE=ALT,FAULT=NONE#"
        )
        settled = (
            b"AZ=0,ALT=61000,AZMIN=NA,AZMAX=NA,ALTMIN=0,ALTMAX=62000,"
            b"AZTARGET=0,ALTTARGET=61000,ACAL=100.0,ZCAL=11.0,STATE=IDLE,FAULT=NONE#"
        )
        client, fake = client_with({
            ":GVP#": [b"B1-AutoAlign#"],
            ":GVN#": [b"V0.2.3#"],
            ":PGL#": [moving, settled],
            ":GX#": [b"Parked,------,0,0#", b"Parked,------,0,0#"],
        })
        client.connect("fake")
        snapshot = client.snapshot()
        self.assertEqual(snapshot.alt_steps, 61000)
        self.assertEqual(snapshot.state, "IDLE")
        self.assertEqual(fake.commands.count(":PGL#"), 2)

    def test_rejected_limit_command_raises(self):
        client, _fake = client_with({
            ":GVP#": [b"B1-AutoAlign#"],
            ":GVN#": [b"V0.1.0#"],
            ":PAT#": [b"0#"],
        })
        client.connect("fake")
        with self.assertRaises(ProtocolError):
            client.mark_alt_top()

    def test_v02_limit_hold_and_atomic_correction_commands(self):
        client, fake = client_with({
            ":GVP#": [b"B1-AutoAlign#"],
            ":GVN#": [b"V0.2.0#"],
            ":PZB#": [b"1#"],
            ":PZT#": [b"1#"],
            ":PHM2#": [b"1#"],
            ":PHD5000#": [b"1#"],
            ":PDI1,0#": [b"1#"],
            ":PAU#": [b"1#"],
            ":PAC0.250000,-0.125000#": [b"1#"],
        })
        client.connect("fake")
        client.mark_az_bottom()
        client.mark_az_top()
        client.set_hold_mode(2)
        client.set_hold_delay(5000)
        client.set_direction_inversion(True, False)
        client.restore_alt_top_reference()
        client.move_correction_degrees(0.25, -0.125)
        self.assertIn(":PZB#", fake.commands)
        self.assertIn(":PZT#", fake.commands)
        self.assertIn(":PDI1,0#", fake.commands)
        self.assertIn(":PAU#", fake.commands)
        self.assertIn(":PAC0.250000,-0.125000#", fake.commands)


if __name__ == "__main__":
    unittest.main()
