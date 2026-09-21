"""The universal Sync widget with a fake sync engine (real Tk; needs a desktop session)."""
from pathlib import Path
import sys
import tempfile
import time
import tkinter as tk
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import sync_widget  # noqa: E402
from sync_widget import SyncWidget, describe  # noqa: E402
import web_client  # noqa: E402
from web_client import Unauthorized  # noqa: E402

OK = dict(state='ok', up=0, down=0, conflicts=0, inventory_up=0, inventory_down=0, zone_publish=False,
          zone_pull=False, waiting=0, web_version=14, local_version=14)


class DescribeTests(unittest.TestCase):
    def test_texts(self):
        self.assertEqual(describe(OK)[:2], ('✓ Synced', 'ok'))
        text, color, detail = describe(dict(OK, up=3, down=2, inventory_up=2, zone_publish=True, inventory_down=1,
                                            zone_pull=True, web_version=15))
        self.assertEqual((text, color), ('⟳ Sync  ↑3 ↓2', 'pending'))
        self.assertIn('2 inventory changes + new zone mappings to publish', detail)
        self.assertIn('1 web change + zone database v15', detail)
        self.assertEqual(describe(dict(OK, up=1, inventory_up=1))[0], '⟳ Sync  ↑1')
        self.assertIn('conflict', describe(dict(OK, conflicts=2))[0])
        self.assertEqual(describe(dict(state='offline'))[0], 'Sync · offline')
        self.assertIn('sign in', describe(dict(state='signin'))[0])
        self.assertEqual(describe(dict(state='unauthorized'))[1], 'error')


class WidgetTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.password = patch.object(web_client, 'PASSWORD_FILE', Path(self.tmp.name) / 'web_password')
        self.password.start()
        self.root = tk.Tk()
        self.root.withdraw()
        self.status = dict(OK, up=1, inventory_up=1)
        self.synced = []
        self.status_patch = patch.object(sync_widget.sync_all, 'status', side_effect=lambda *_: dict(self.status))
        self.status_patch.start()

    def tearDown(self):
        self.status_patch.stop()
        self.password.stop()
        self.root.destroy()
        self.tmp.cleanup()

    def pump(self, until, seconds=5):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            self.root.update()
            if until():
                return True
            time.sleep(0.02)
        return False

    def widget(self, **kw):
        w = SyncWidget(self.root, Path(self.tmp.name) / 'devices.sqlite3', 'Test app', start=False,
                       on_synced=self.synced.append, **kw)
        w.pack()
        return w

    def test_sign_in_stores_password_then_sync_and_status(self):
        w = self.widget(held=('.lock',), can_apply=lambda: False)
        w.events.put(('status', w.check()))
        self.assertTrue(self.pump(lambda: w.button['text'] == '⟳ Sync  ↑1'))
        result = dict(sync=dict(upload=[]), zone=None, blocked=None)
        with patch.object(sync_widget.simpledialog, 'askstring', return_value='s3cret'), \
                patch.object(w.client, 'head', return_value={}), \
                patch.object(sync_widget.sync_all, 'sync', return_value=result) as run:
            self.status = OK
            w.click()
            self.assertEqual(w.button['text'], 'Syncing…')
            self.assertTrue(self.pump(lambda: self.synced and w.button['text'] == '✓ Synced'))
        self.assertEqual(web_client.load_password(), 's3cret')
        self.assertEqual(run.call_args.kwargs, dict(held=('.lock',), apply_ok=False))
        self.assertIn('last synced', w.detail['text'])

    def test_rejected_password_is_forgotten(self):
        web_client.save_password('old')
        w = self.widget()
        self.assertEqual(w.client.password, 'old')
        with patch.object(sync_widget.sync_all, 'sync', side_effect=Unauthorized('Wrong inventory password')), \
                patch.object(sync_widget.messagebox, 'showerror') as error:
            w.click()
            self.assertTrue(self.pump(lambda: error.called))
        self.assertIsNone(web_client.load_password())
        self.assertIsNone(w.client.password)

    def test_conflicts_open_web_sync_instead_of_syncing(self):
        self.status = dict(OK, conflicts=1)
        w = self.widget()
        w.events.put(('status', w.check()))
        self.assertTrue(self.pump(lambda: 'conflict' in w.button['text']))
        with patch.object(sync_widget.messagebox, 'askyesno', return_value=True), \
                patch.object(sync_widget, 'open_web_sync') as opened, \
                patch.object(sync_widget.sync_all, 'sync') as run:
            w.click()
        opened.assert_called_once()
        run.assert_not_called()


if __name__ == '__main__':
    unittest.main()
