import base64
import copy
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from database import Database  # noqa: E402
from show_registry import ShowRegistry, BROADCAST, image_hash  # noqa: E402
from show_sim import FakeShowCube  # noqa: E402
import showfile  # noqa: E402

CUBES = ['1C:DB:D4:F0:A8:30', 'AC:27:6E:80:00:D0', 'AC:27:6E:80:00:D1']


def edited_show(level=30):
    doc = copy.deepcopy(showfile.load())
    doc['cues'][0]['colours'] = [[level, level, 1]]
    return showfile.validate(doc)


def web_doc(version, doc):
    image = showfile.pack(doc)
    return dict(version=version, hash=image_hash(image), crc=showfile.crc32(image), length=len(image),
                image_b64=base64.b64encode(image).decode(), source=doc, published_at='2026-09-23T00:00:00Z',
                published_by='test')


class ShowRegistryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.temp.name) / 'devices.sqlite3')
        self.sent, self.logs = [], []
        self.now, self.wall = 1000.0, 1_700_000_000.0
        self.show = ShowRegistry(self.db, self.sent.append, self.logs.append, lambda: self.now, lambda: self.wall)
        self.cubes = {mac: FakeShowCube(mac, cube_id=i + 17) for i, mac in enumerate(CUBES)}
        self.reachable = set(CUBES)

    def tearDown(self):
        self.db.close()
        self.temp.cleanup()

    def deliver(self):
        """Relay every sent frame: to the addressed cube(s), acknowledge, and feed replies back."""
        pending, self.sent[:] = list(self.sent), []
        for message in pending:
            data = bytes.fromhex(message['hex'])
            targets = [m for m in CUBES if message['mac'] in (BROADCAST, m) and m in self.reachable]
            self.show.event(dict(event='show_sent', id=message['id'], mac=message['mac'],
                                 status='delivered' if message['mac'] == BROADCAST or targets else 'unconfirmed'))
            for mac in targets:
                for reply in self.cubes[mac].receive(data, broadcast=message['mac'] == BROADCAST):
                    self.show.event(dict(event='show_frame', mac=mac, rssi=-50, hex=reply.hex().upper()))

    def run_ticks(self, n, show_running=False, step=0.25):
        for _ in range(n):
            self.show.tick(True, show_running)
            self.deliver()
            self.now += step
            self.wall += step

    def test_discovery_then_update_all(self):
        self.run_ticks(2)
        rows = {c['mac']: c for c in self.show.cube_rows()}
        self.assertEqual(set(rows), set(CUBES))
        self.assertTrue(all(c['state'] == 'unpublished' and c['source'] == 'builtin' for c in rows.values()))
        with self.assertRaisesRegex(ValueError, 'No show published'):
            self.show.publish()
        doc = edited_show()
        self.assertTrue(self.show.store.cache(web_doc(3, doc)))
        self.assertFalse(self.show.store.cache(web_doc(3, doc)), 'already cached')
        self.assertTrue(all(c['state'] == 'behind' for c in self.show.cube_rows()))
        self.show.publish()
        self.run_ticks(40)
        self.assertIsNone(self.show.publication)
        self.assertIn('confirmed on 3 cube(s)', self.show.message)
        image = showfile.pack(doc)
        for cube in self.cubes.values():
            self.assertEqual((cube.version, cube.image, cube.commits), (3, image, 1))
        self.assertTrue(all(c['state'] == 'current' and c['source'] == 'nvs' for c in self.show.cube_rows()))
        self.assertEqual(self.show.store.highest_seen(), 3)

    def test_never_goes_back_and_force_is_single_cube(self):
        self.show.store.cache(web_doc(5, edited_show(40)))
        self.assertFalse(self.show.store.cache(web_doc(4, edited_show(50))))
        with self.assertRaisesRegex(ValueError, 'single cube'):
            self.show.publish(force=True)
        self.run_ticks(2)
        self.show.publish()
        self.run_ticks(40)
        self.assertTrue(all(c.version == 5 for c in self.cubes.values()))

    def test_holds_while_a_show_runs_and_cube_defers_commit(self):
        self.run_ticks(2)
        self.show.store.cache(web_doc(2, edited_show()))
        self.show.publish()
        self.run_ticks(10, show_running=True)
        self.assertEqual(self.sent, [])
        self.assertIn('a show is running', self.show.message)
        self.assertTrue(all(c.version == 0 for c in self.cubes.values()))
        # The controller stopped reporting a show, but one cube is still playing its own copy.
        self.cubes[CUBES[0]].show_running = True
        self.run_ticks(30)
        states = {c['mac']: c['state'] for c in self.show.cube_rows()}
        self.assertEqual(states[CUBES[0]], 'pending')
        self.assertEqual(self.cubes[CUBES[0]].version, 0)
        for reply in self.cubes[CUBES[0]].end_show():
            self.show.event(dict(event='show_frame', mac=CUBES[0], hex=reply.hex()))
        self.run_ticks(20)
        self.assertTrue(all(c.version == 2 for c in self.cubes.values()))
        self.assertIsNone(self.show.publication)

    def test_timeout_names_missing_cube_and_walkaround_retries(self):
        self.run_ticks(2)
        self.show.store.cache(web_doc(2, edited_show()))
        self.reachable.discard(CUBES[2])
        self.show.publish(timeout=20)
        self.run_ticks(100)
        self.assertIn('timed out', self.show.message)
        self.assertIn(CUBES[2], self.show.message)
        # Walk-around: the cube comes back into range and is updated automatically.
        self.show.set_walkaround(True)
        self.reachable.add(CUBES[2])
        self.run_ticks(80)
        self.assertEqual(self.cubes[CUBES[2]].version, 2)

    def test_malformed_and_foreign_events(self):
        self.assertTrue(self.show.event(dict(event='show_frame', mac=CUBES[0], hex='ZZ')))
        self.assertIn('malformed', self.logs[-1])
        self.assertFalse(self.show.event(dict(event='zone_frame', mac=CUBES[0], hex='')))
        self.show.tick(False)
        self.assertEqual(self.sent, [])


if __name__ == '__main__':
    unittest.main()
