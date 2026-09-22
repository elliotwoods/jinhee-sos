import copy
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))
from fake_web_inventory import FakeWebInventory  # noqa: E402
from database import Database  # noqa: E402
from show_registry import ShowStore  # noqa: E402
import show_publish  # noqa: E402
import showfile  # noqa: E402
import web_client  # noqa: E402


class ShowPublishTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'devices.sqlite3'
        Database(self.path).close()
        self.server = FakeWebInventory()
        self.client = web_client.WebClient(self.server.url, password=self.server.password)

    def tearDown(self):
        self.server.close()
        self.temp.cleanup()

    def published(self):
        db = Database(self.path)
        try:
            return ShowStore(db).published()
        finally:
            db.close()

    def test_publish_pull_and_versions(self):
        self.assertEqual(show_publish.pull(self.path, self.client)[1], 'none')
        self.assertEqual(self.client.show_head()['version'], 0)
        doc = showfile.load()
        first = show_publish.publish(self.path, self.client, 'laptop A', doc)
        self.assertEqual((first['published']['version'], first['changed']), (1, True))
        again = show_publish.publish(self.path, self.client, 'laptop A', doc)
        self.assertEqual((again['published']['version'], again['changed']), (1, False))
        # A version already running on a cube lifts the next one above it.
        edited = copy.deepcopy(doc)
        edited['cues'][0]['colours'] = [[30, 30, 1]]
        second = show_publish.publish(self.path, self.client, 'laptop A', edited, seen_versions=[6])
        self.assertEqual(second['published']['version'], 7)
        self.assertEqual(self.client.show_head()['version'], 7)
        # A second computer pulls it.
        other = Path(self.temp.name) / 'other.sqlite3'
        Database(other).close()
        published, status = show_publish.pull(other, self.client)
        self.assertEqual((published['version'], status), (7, 'updated'))
        self.assertEqual(show_publish.pull(other, self.client)[1], 'current')
        db = Database(other)
        try:
            current = ShowStore(db).current()
            self.assertEqual(current.image, showfile.pack(edited))
            self.assertEqual(current.doc['cues'][0]['label'], 'Neon hold (entrance)')
        finally:
            db.close()

    def test_invalid_show_never_reaches_the_web(self):
        doc = copy.deepcopy(showfile.load())
        doc['cues'][0]['start_ms'] = 9
        with self.assertRaises(showfile.ShowError):
            show_publish.publish(self.path, self.client, 'laptop A', doc)
        self.assertEqual(self.client.show_head()['version'], 0)


if __name__ == '__main__':
    unittest.main()
