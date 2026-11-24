import tempfile
import unittest
from pathlib import Path

from sign_broadcast.__main__ import parser, run
from sign_broadcast.store import connect, ingest


class SeatTapeTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.db = connect(Path(folder.name) / 'seat.sqlite', create=True)
        self.addCleanup(self.db.close)
        self.cue = dict(type='cue', id='intro', rev=1, session='main', start=0, end=10, terms='')
        self.patterns = [dict(type='seat_pattern', id=label, rev=1, cue='intro', cue_rev=1,
                              label=label, pulse=pulse)
                         for label, pulse in [('stop','0'), ('ready','01'), ('turn','011')]]
        ingest(self.db, [self.cue, *self.patterns])

    def command(self, command, *entries):
        return run(self.db, parser().parse_args(['--db', 'ignored', command, 'intro', *entries]))

    def test_frames_are_emitted_and_received_in_order(self):
        sent = self.command('seat-tape', 'stop', 'turn', 'stop', 'ready')
        self.assertEqual(sent['frames'], ['0', '011', '0', '01'])
        self.assertEqual(self.command('seat-read', *sent['frames'])['received'],
                         ['stop', 'turn', 'stop', 'ready'])
        with self.assertRaises(KeyError):
            self.command('seat-read', '0011001')

    def test_revision_changes_which_patterns_can_be_emitted(self):
        ingest(self.db, [dict(self.cue, rev=2)])
        with self.assertRaisesRegex(ValueError, 'no seat patterns'):
            self.command('seat-tape', 'stop')
        ingest(self.db, [dict(self.patterns[0], rev=2, cue_rev=2, pulse='1')])
        self.assertEqual(self.command('seat-tape', 'stop')['frames'], ['1'])
        with self.assertRaises(KeyError):
            self.command('seat-read', '0')
