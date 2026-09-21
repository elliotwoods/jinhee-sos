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
from sync_widget import SyncWidget, describe, summary  # noqa: E402
import web_client  # noqa: E402
from web_client import Unauthorized, Unreachable  # noqa: E402
from web_sync import SyncBusy  # noqa: E402

OK = dict(state='ok', up=0, down=0, conflicts=0, lost=0, inventory_up=0, inventory_down=0, zone_publish=False,
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
        self.assertIn('1 device(s) here give way', describe(dict(OK, down=1, inventory_down=1, lost=1))[2])
        problem = describe(dict(state='error', message='The web could not answer (500)'))
        self.assertEqual(problem[:2], ('⚠ Sync · problem', 'error')); self.assertIn('500', problem[2])
        self.assertEqual(summary(dict(sync=dict(upload=[]), zone=None, blocked=None)), '')  # older result shape
        text = summary(dict(sync=dict(lost=[dict(mac='m', text='#57 (m) loses number 57')], applied=False),
                            zone_error='404: not found'))
        self.assertIn('• #57 (m) loses number 57', text); self.assertIn('once the apps are idle', text)
        self.assertIn('zone database was not published: 404', text)
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
        self.assertEqual(run.call_args.kwargs['held'], ('.lock',))
        self.assertIs(run.call_args.kwargs['apply_ok'](), False)  # asked again just before writing
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

    def test_failures_are_explained_and_the_button_keeps_working(self):
        web_client.save_password('kept')
        w = self.widget()
        interrupted = Unreachable('timed out'); interrupted.after_push = True
        for error, box, words in ((SyncBusy('busy'), 'showinfo', 'Another app'),
                                  (interrupted, 'showwarning', 'next Sync checks'),
                                  (Unreachable('no route'), 'showwarning', 'nothing changed'),
                                  (ValueError('odd'), 'showerror', 'Sync stopped: odd')):
            with patch.object(sync_widget.sync_all, 'sync', side_effect=error), \
                    patch.object(sync_widget.messagebox, box) as shown:
                w.click()
                self.assertTrue(self.pump(lambda: shown.called and not w.busy))
            self.assertIn(words, shown.call_args.args[1])
        self.assertEqual(web_client.load_password(), 'kept')
        # A result the widget cannot digest must not stop the polling loop.
        with patch.object(sync_widget.sync_all, 'sync', return_value=None), \
                patch.object(sync_widget.traceback, 'print_exc') as logged:
            w.click()
            self.assertTrue(self.pump(lambda: not w.busy))
        logged.assert_called_once()
        self.status = dict(state='error', message='The web could not answer (500)')
        w.events.put(('status', w.check()))
        self.assertTrue(self.pump(lambda: 'problem' in w.button['text']))

    def test_lost_numbers_are_announced(self):
        web_client.save_password('kept')
        w = self.widget()
        result = dict(sync=dict(lost=[dict(mac='m', text='#57 (m) loses number 57')], applied=True), zone=None,
                      blocked=None, zone_error=None)
        with patch.object(sync_widget.sync_all, 'sync', return_value=result), \
                patch.object(sync_widget.messagebox, 'showwarning') as shown:
            w.click()
            self.assertTrue(self.pump(lambda: shown.called))
        self.assertIn('loses number 57', shown.call_args.args[1])
        self.assertEqual(self.synced, [result])


if __name__ == '__main__':
    unittest.main()
