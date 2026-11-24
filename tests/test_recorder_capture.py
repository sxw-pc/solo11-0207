import json
import unittest
from pathlib import Path

from sign_broadcast.recorder_capture import decode
from sign_broadcast.recorder_uptime import assess


class RecorderCaptureTest(unittest.TestCase):
    def setUp(self):
        fixture = Path(__file__).resolve().parents[1] / 'fixtures' / 'recorder-health.json'
        self.packet = json.loads(fixture.read_text(encoding='utf-8'))

    def test_count_observed_service(self):
        session = {'id': 'main', 'start': 100, 'end': 140}
        report = assess(self.packet, session)
        self.assertEqual(report['seconds'], {'up': 30, 'down': 7, 'unknown': 3})
        self.assertEqual(report['raw'], self.packet)
        self.assertEqual(report['timeline'][2], {'start': 119, 'end': 126, 'state': 'down'})

    def test_reordered_samples_are_rejected(self):
        self.packet['samples'].reverse()
        with self.assertRaisesRegex(ValueError, 'reordered'):
            decode(self.packet)
