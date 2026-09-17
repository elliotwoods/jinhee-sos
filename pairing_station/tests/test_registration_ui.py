"""Exercise the real Tk Register button with an isolated DB and fake radio."""
import tempfile
import unittest
from unittest.mock import patch
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import tkinter as tk
from app import App

class RegistrationUITest(unittest.TestCase):
    def test_unnumbered_register_prompts_then_waits_for_fresh_scan(self):
        with tempfile.TemporaryDirectory() as directory:
            root=tk.Tk(); root.withdraw()
            app=App(root,Path(directory)/'test.sqlite3',api_port=0)
            try:
                c=app.controller; sent=[]; c.send=sent.append
                c.connected=c.reader_ok=True
                keep=app.db.rows()[0]
                app.db.mark_nfc_seen(keep['mac'], keep['uid'])
                app.db.clear_unseen_numbers()
                mac=app.db.rows()[0]['mac']  # An imported device with its number cleared.
                app.dashboard.select(mac)
                self.assertEqual(str(app.dashboard.selected_buttons[0]['state']), 'normal')
                with patch('app.simpledialog.askinteger', return_value=None):
                    app.dashboard.selected_buttons[0].invoke()
                self.assertIsNone(app.db.get(mac)['cube_id'])
                with patch('app.simpledialog.askinteger', side_effect=[keep['cube_id'], 80]), patch('app.messagebox.showerror') as error:
                    app.dashboard.selected_buttons[0].invoke()
                    error.assert_called_once()
                self.assertEqual(c.phase, 'stopping')
                c.event(dict(event='stopped', id=c.request))
                self.assertEqual(app.db.get(mac)['cube_id'], 80)
                self.assertEqual(c.phase, 'identifying')
                self.assertFalse(any(e['cmd']=='register' for e in sent))
                c.event(dict(event='tag_state', present=False))
                c.event(dict(event='tag', id=c.request, uid='04:01:02:03'))
                self.assertEqual(sent[-1]['cmd'], 'register')
                self.assertEqual(sent[-1]['cube_id'], 80)
                self.assertEqual(sent[-1]['uid'], '04:01:02:03')
            finally:
                app.db.close(); root.destroy()

    def test_register_button_takes_preview_through_visible_scan_and_success(self):
        with tempfile.TemporaryDirectory() as directory:
            root=tk.Tk();root.withdraw()
            app=App(root,Path(directory)/'test.sqlite3',api_port=0)
            try:
                c=app.controller
                sent=[];c.send=sent.append
                c.connected=c.reader_ok=True
                mac='02:00:00:00:00:01'
                c.event(dict(event='device',mac=mac))
                app.dashboard.select(mac)
                self.assertEqual(c.mode,'preview')
                self.assertEqual(str(app.dashboard.selected_buttons[0]['state']),'normal')
                app.dashboard.selected_buttons[0].invoke()
                self.assertEqual(c.phase,'stopping')
                c.event(dict(event='stopped',id=c.request))
                self.assertEqual(sent[-1]['duration_ms'],0)
                c.event(dict(event='tag_state',present=False))
                app.dashboard.render(force=True)
                self.assertIn('READY TO SCAN',app.status.get())
                c.event(dict(event='tag',id=c.request,uid='04:01:02:03'))
                app.dashboard.render(force=True)
                self.assertIn('TAG DETECTED',app.status.get())
                self.assertNotEqual(app.dashboard.banner['bg'],'#174c39')
                c.event(dict(event='registered',id=c.request,mac=mac,cube_id=33,acknowledged=True))
                app.dashboard.render(force=True)
                self.assertIn('NEOCORE #33 REGISTERED',app.status.get())
                self.assertEqual(app.dashboard.banner['bg'],'#174c39')
                self.assertEqual(app.db.get(mac)['uid'],'04:01:02:03')
            finally:
                app.db.close();root.destroy()

if __name__=='__main__':unittest.main()
