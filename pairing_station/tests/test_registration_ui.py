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
    def test_disconnected_open_station_rehandshakes_and_explains_disabled_register(self):
        with tempfile.TemporaryDirectory() as directory:
            root=tk.Tk(); root.withdraw()
            app=App(root,Path(directory)/'test.sqlite3',api_port=0)
            try:
                sent=[]; app.controller.send=sent.append
                app.transport.port=object()
                app.last_hello_retry=0
                app.recover_station_connection(10)
                self.assertEqual(sent[-1]['cmd'],'hello')
                app.recover_station_connection(11)
                self.assertEqual(len(sent),1)
                app.dashboard.render(force=True)
                self.assertIn('Connect the NFC station',app.dashboard.registration_hint.get())
                app.controller.event(dict(event='hello',id=sent[-1]['id'],radio_ok=True,nfc_ok=True,protocol=1,channel=2))
                app.recover_station_connection(20)
                self.assertEqual(len(sent),1)
                app.controller.connected=False
                app.transport.port=None
                app.recover_station_connection(30)
                self.assertEqual(len(sent),1)
            finally:
                app.transport.port=None; app.db.close(); root.destroy()

    def test_register_available_with_pending_mapping_and_preserves_until_scan(self):
        with tempfile.TemporaryDirectory() as directory:
            root=tk.Tk(); root.withdraw()
            app=App(root,Path(directory)/'test.sqlite3',api_port=0)
            try:
                c=app.controller; sent=[]; c.send=sent.append
                c.connected=c.reader_ok=True
                row=app.db.rows()[0]
                pending='04:10:20:30'
                replacement='04:10:20:31'
                app.db.prepare(row['mac'],pending)
                app.db.result(row['mac'],False,'Stopped')
                app.dashboard.select(row['mac'])
                self.assertEqual(str(app.dashboard.selected_buttons[0]['state']),'normal')
                with patch('app.messagebox.askokcancel',return_value=True):
                    app.dashboard.selected_buttons[0].invoke()
                c.event(dict(event='stopped',id=c.request))
                self.assertEqual(c.phase,'identifying')
                self.assertEqual(app.db.get(row['mac'])['pending_uid'],pending)
                self.assertEqual(app.db.get(row['mac'])['uid'],row['uid'])
                c.event(dict(event='tag_state',present=False))
                c.event(dict(event='tag',id=c.request,uid=replacement))
                self.assertEqual(sent[-1]['uid'],replacement)
                self.assertEqual(app.db.get(row['mac'])['pending_uid'],replacement)
                c.event(dict(event='registered',id=c.request,mac=row['mac'],cube_id=row['cube_id'],acknowledged=True))
                self.assertEqual(app.db.get(row['mac'])['uid'],replacement)
                self.assertIsNone(app.db.get(row['mac'])['pending_uid'])
            finally:
                app.db.close(); root.destroy()

    def test_usb_pins_selection_across_removal_filters_and_replacement(self):
        with tempfile.TemporaryDirectory() as directory:
            root=tk.Tk(); root.withdraw()
            app=App(root,Path(directory)/'test.sqlite3',api_port=0)
            try:
                app.db.clear_unseen_numbers()
                app.dashboard.auto_flash.set(False)
                app.dashboard.filter.set('Has original number and connected')
                app.dashboard.search.set('nothing matches')
                generation=app.usb_identifier.generation
                mac='02:00:00:00:00:01'
                key=('/dev/test', mac, 'test')
                def detected(target):
                    app.usb_identifier.events.put(dict(kind='identified',mac=target,source='test',key=key,generation=generation))
                detected(mac)
                with patch('app.simpledialog.askinteger', return_value=80): app.poll_usb()
                self.assertEqual(app.db.get(mac)['cube_id'],80)
                self.assertEqual(app.dashboard.rows[0]['mac'],mac)
                self.assertEqual(app.dashboard.selected_mac,mac)
                app.dashboard.select('02:00:00:00:00:02')
                self.assertEqual(app.dashboard.selected_mac,mac)
                app.usb_identifier.events.put(dict(kind='removed', key=key,generation=generation))
                app.poll_usb()
                self.assertEqual(app.usb_locked_mac,mac)
                detected('02:00:00:00:00:02')
                with patch('app.simpledialog.askinteger',return_value=None): app.poll_usb()
                self.assertEqual(app.usb_locked_mac,'02:00:00:00:00:02')
                self.assertIsNone(app.db.get(app.usb_locked_mac)['cube_id'])
                app.unlock_usb()
                self.assertIsNone(app.usb_locked_mac)
                app.dashboard.select(mac)
                self.assertEqual(app.dashboard.selected_mac,mac)
            finally:
                app.usb_identifier.stop(); app.db.close(); root.destroy()

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
                with patch('app.simpledialog.askinteger', return_value=None) as prompt:
                    app.dashboard.selected_buttons[0].invoke()
                    self.assertEqual(prompt.call_args.kwargs['initialvalue'],33)
                    self.assertIn('Press Enter to accept',prompt.call_args.args[1])
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
