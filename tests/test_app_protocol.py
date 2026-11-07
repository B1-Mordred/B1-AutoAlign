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
            ":GVN#": [b"V0.1.0#"],
            ":PGL#": [b"AZ=11,ALT=100,ALTMIN=0,ALTMAX=NA,ACAL=100.0,ZCAL=11.0,FAULT=NONE#"],
            ":GX#": [b"Parked,------,0,0#"],
            ":MXl10#": [b"1"],
        })
        identity = client.connect("fake")
        self.assertTrue(identity.full_control)
        snapshot = client.snapshot()
        self.assertEqual((snapshot.az_steps, snapshot.alt_steps), (11, 100))
        self.assertIsNone(snapshot.alt_max)
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

    def test_rejected_limit_command_raises(self):
        client, _fake = client_with({
            ":GVP#": [b"B1-AutoAlign#"],
            ":GVN#": [b"V0.1.0#"],
            ":PAT#": [b"0#"],
        })
        client.connect("fake")
        with self.assertRaises(ProtocolError):
            client.mark_alt_top()


if __name__ == "__main__":
    unittest.main()
