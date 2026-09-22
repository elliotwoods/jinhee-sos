import copy
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import showfile  # noqa: E402


class ShowFileTests(unittest.TestCase):
    def setUp(self):
        self.doc = showfile.load()

    def test_default_show_is_the_v141_timeline(self):
        doc = self.doc
        self.assertEqual((doc['length_ms'], len(doc['cues'])), (298000, 21))
        image = showfile.pack(doc)
        self.assertEqual(showfile.unpack(image)['cues'][10]['params'],
                         dict(level_min=12, level_max=50, dur_min_ms=700, dur_max_ms=1500, start_level=20))
        # Spot checks against the old hard-coded segments (the C++ golden test sweeps every millisecond).
        player, rng = showfile.Player(image), showfile.TestRng()
        self.assertEqual(player.render(0, rng), (18, 20, 1))
        self.assertEqual(player.render(33000, rng), (0, 0, 0))
        self.assertEqual(player.render(36499, rng), (20, 20, 20))
        self.assertEqual(player.render(36500, rng), (0, 0, 0))
        self.assertEqual(player.render(64000, rng), (60, 60, 60))
        self.assertEqual(player.render(74120, rng), (81, 100, 23))
        self.assertEqual(player.render(79000 + 1500, rng), (14, 17, 18))  # truncation toward zero
        self.assertEqual(player.render(287000, rng), (100, 100, 100))
        self.assertIsNone(player.render(298000, rng))

    def test_default_header_is_current(self):
        self.assertEqual(showfile.DEFAULT_HEADER.read_text(encoding='utf-8'), showfile.header_text(self.doc),
                         'DefaultShow.h is stale: run python pairing_station/showfile.py --header')

    def test_round_trip_and_stable_json(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'show.json'
            showfile.save(self.doc, path)
            self.assertEqual(showfile.load(path), self.doc)
            raw = path.read_bytes()
            self.assertNotIn(b'\r\n', raw)
            self.assertEqual(raw.decode('utf-8'), showfile.dumps(self.doc))
        self.assertEqual(showfile.pack(showfile.unpack(showfile.pack(self.doc))), showfile.pack(self.doc))

    def test_validation(self):
        def bad(change, message):
            doc = copy.deepcopy(self.doc)
            change(doc)
            with self.assertRaisesRegex(showfile.ShowError, message):
                showfile.validate(doc)
        bad(lambda d: d['cues'][0].update(start_ms=5), 'first cue must start at 0')
        bad(lambda d: d['cues'][2].update(start_ms=d['cues'][1]['start_ms']), 'must start after')
        bad(lambda d: d['cues'][0]['colours'][0].__setitem__(0, 101), 'from 0 to 100')
        bad(lambda d: d['cues'][2]['params'].update(on_ms=5000), 'on_ms cannot exceed')
        bad(lambda d: d['cues'][3]['params'].pop('duration_ms'), 'needs parameters')
        bad(lambda d: d['cues'][3].update(type='sparkle'), 'unknown type')
        bad(lambda d: d['cues'][1].update(colours=[[1, 2, 3]]), 'needs 0 colours')
        bad(lambda d: d['cues'][7].update(colours=[]), '1 to 3 colours')
        bad(lambda d: d['cues'][10]['params'].update(level_min=60), 'level_min cannot exceed')
        bad(lambda d: d.update(length_ms=d['cues'][-1]['start_ms']), 'start_ms must be')
        bad(lambda d: d.update(cues=[]), '1 to 128 cues')
        bad(lambda d: d['cues'][3]['params'].update(duration_ms=True), 'whole number')

    def test_frames(self):
        image = showfile.pack(self.doc)
        announce = showfile.announce(9, image)
        self.assertEqual((len(announce), showfile.frame_type(announce)), (18, showfile.SHOW_ANNOUNCE))
        chunks = showfile.chunks(9, image)
        self.assertEqual(len(chunks), 3)
        self.assertTrue(all(len(c) == 211 and showfile.frame_type(c) == showfile.SHOW_CHUNK for c in chunks))
        self.assertEqual(b''.join(c[11:11 + c[10]] for c in chunks), image)
        for frame in [announce, showfile.query(1), showfile.timecode(1, 2)] + chunks:
            self.assertNotIn(len(frame), (2, 24))
        self.assertEqual(showfile.frame_type(b'NZ\x01\x54' + bytes(20)), 0)  # 24 bytes is always a cube Packet

    def test_summary(self):
        timeline = showfile.summary(self.doc)
        self.assertEqual(timeline[0], (31000, 'Neon hold (entrance)'))
        self.assertEqual(timeline[-1], (298000, 'White fades out'))


if __name__ == '__main__':
    unittest.main()
