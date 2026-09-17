"""Construct the real Tk windows (pairing app Zones window, zone flasher) against temporary databases."""
import sys
import importlib.util
import tempfile
import tkinter as tk
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'flasher'))
sys.path.insert(0, str(ROOT.parent / 'pairing_station'))
sys.path.insert(0, str(ROOT / 'tools'))
import zonedb  # noqa: E402


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


pairing_app = load('pairing_app', ROOT.parent / 'pairing_station/app.py')
flasher_app = load('flasher_app', ROOT / 'flasher/app.py')

STATION = dict(zones=1, channel=2, mac='3C:0F:02:AD:83:24')


class UiSmokeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = tk.Tk()
        self.root.withdraw()

    def tearDown(self):
        self.root.destroy()
        self.tmp.cleanup()

    def test_pairing_app_zones_window(self):
        app = pairing_app.App(self.root, Path(self.tmp.name) / 'devices.sqlite3', api_port=0)
        try:
            sent = []
            app.zones.send = sent.append
            app.controller.connected = True
            app.controller.station = STATION
            app.open_zones()
            status = zonedb.STATUS.pack(b'NZ', 1, zonedb.ZONE_STATUS, 0, 1, 1, b'Preshow 1'.ljust(16, b'\0'),
                                        b'preshow-2.0.0'.ljust(16, b'\0'), 0, 0, 0, 0, 0, 0, 5, 1, 1, 0, 3, 2, 1, 0)
            self.assertTrue(app.zones.event(dict(event='zone_frame', mac='14:63:93:C0:EC:14', hex=status.hex())))
            window = app.zones_window
            window.render()
            self.assertEqual(window.tree.get_children(), ('14:63:93:C0:EC:14',))
            self.assertIn('NFC reader not found', window.tree.item('14:63:93:C0:EC:14', 'values'))
            window.tree.selection_set('14:63:93:C0:EC:14')
            window.render()
            self.assertIn('Show log', window.detail.get('1.0', 'end'))
            buttons = {b['text']: b for b in window.window.winfo_children()[0].winfo_children()[2].winfo_children()}
            buttons['Publish database'].invoke()
            self.assertEqual(app.zones.publication.version, 1)
            buttons['Identify (10 s)'].invoke()
            self.assertEqual(bytes.fromhex(sent[-1]['hex'])[3], zonedb.ZONE_IDENTIFY)
            app.zones.tick(True, STATION)
            self.assertTrue(any(bytes.fromhex(m['hex'])[3] == zonedb.DB_ANNOUNCE for m in sent))
            window.close()
            self.assertIsNone(app.zones_window)
        finally:
            app.closing = True
            app.transport.close()
            app.db.close()

    def test_zone_flasher_window(self):
        station = dict(port='/dev/cu.station', key='s', description='USB JTAG', candidate=False, serial='3C:0F:02:AD:83:24')
        zone = dict(port='/dev/cu.zone', key='z', description='USB JTAG', candidate=True, serial='14:63:93:C0:EC:14')
        with patch.object(flasher_app, 'ports', return_value=[station, zone]):
            window = flasher_app.App(self.root, Path(self.tmp.name) / 'devices.sqlite3')
            try:
                self.assertEqual(window.name.get(), 'Preshow 1')
                window.scan_ports()
                self.assertEqual(window.pending_detect, {'/dev/cu.station', '/dev/cu.zone'})
                window.pending_detect.clear()
                window.handle('detected', ('/dev/cu.station', dict(kind='station', label='Pairing station (protected)', mac=station['serial'], profile=None)))
                window.handle('detected', ('/dev/cu.zone', dict(kind='nctzone', label='NctZone firmware', mac=zone['serial'], firmware='pool-2.0.0',
                              profile='pool', configured=True, point=4, name='Pool Radio 4', zone_type=3, params=[3830, 435],
                              db_version=1, db_count=32, db_crc=5)))
                window.scan_ports()
                # The detected identity fills the form, including calibration parameters.
                self.assertEqual((window.profile_key(), window.point.get(), window.name.get()), ('pool', 4, 'Pool Radio 4'))
                self.assertEqual([v.get() for v in window.param_vars], ['383.0', '43.5'])
                self.assertEqual(window.form()['params'], [3830, 435])
                rows = {iid: window.port_tree.item(iid, 'values') for iid in window.port_tree.get_children()}
                self.assertIn('REFUSE', rows['/dev/cu.station'][6])
                self.assertIn('FLASH', rows['/dev/cu.zone'][6])
                self.assertEqual(list(window.monitor_ports['values']), ['/dev/cu.zone'])
                # Switching zone type relabels the form and hides parameters.
                window.profile_label.set(zone_build_labels['desert'])
                window.profile_changed()
                self.assertEqual((window.name.get(), window.form()['params']), ('Desert 4', []))
                # The monitor connects to a detected zone by itself, but not after a manual disconnect.
                connected = []
                window.monitor.connect = connected.append
                window.auto_connect_monitor(100.0)
                self.assertEqual(connected, ['/dev/cu.zone'])
                window.monitor.port = '/dev/cu.zone'
                window.monitor.disconnect = lambda: setattr(window.monitor, 'port', None)
                window.toggle_monitor()
                window.auto_connect_monitor(200.0)
                self.assertEqual(connected, ['/dev/cu.zone'])
                # Cube monitor: a tap, its acknowledgment, and an action on it.
                sent = []
                window.monitor.port = '/dev/cu.zone'
                window.monitor.send = sent.append
                for line in ['EVT TAG uid=04:60:35:4A:B6:21:91 cube=1 mac=AC:27:6E:80:37:BC zone=1', 'EVT SENT cube=1 type=6 value=1 ok=1']:
                    window.handle('zone_line', line)
                self.assertEqual(window.cube_title.get(), 'Neocube #1 on the plate')
                self.assertIn('acknowledged by the cube', window.status.get())
                self.assertEqual(window.tabs.index(window.tabs.select()), 1)
                self.assertIn('preshow → delivered', window.cube_detail.get('1.0', 'end'))
                self.assertIn('#1 ·', window.cube_detail.get('1.0', 'end'))
                window.cube_buttons[0].invoke()
                window.cube_buttons[1].invoke()
                self.assertEqual(sent, ['flash 1 5', 'clear 1'])
                window.handle('zone_line', 'EVT LEAVE uid=04:60:35:4A:B6:21:91 cube=1 held_ms=1200')
                self.assertEqual(window.cube_title.get(), 'No neocube on the plate')
                row = window.history_tree.get_children()[0]
                self.assertEqual(window.history_tree.item(row, 'values')[1], '#1')
                window.history_tree.selection_set(row)
                window.render_monitor()
                window.cube_buttons[4].invoke()
                self.assertEqual(sent[-1], 'zone 1 3')
            finally:
                window.closing = True
                window.monitor.port = None


zone_build_labels = {key: p['label'] for key, p in flasher_app.zone_build.PROFILES.items()}
