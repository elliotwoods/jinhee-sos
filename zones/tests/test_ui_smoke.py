"""Construct the real Tk windows (Zone Database Manager, pairing app, zone flasher) against temporary databases."""
import base64
import sys
import importlib.util
import tempfile
import tkinter as tk
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

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
manager_app = load('manager_app', ROOT / 'dbmanager/app.py')

STATION = dict(zones=1, channel=2, mac='3C:0F:02:AD:83:24')


class UiSmokeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = tk.Tk()
        self.root.withdraw()

    def tearDown(self):
        self.root.destroy()
        self.tmp.cleanup()

    def test_pairing_app_launches_manager(self):
        app = pairing_app.App(self.root, Path(self.tmp.name) / 'devices.sqlite3', api_port=0)
        try:
            self.assertFalse(hasattr(app, 'zones'))
            with patch.object(pairing_app.subprocess, 'Popen') as popen:
                app.open_zones()
            args = popen.call_args[0][0]
            self.assertTrue(args[1].endswith('zones/dbmanager/app.py'))
            self.assertEqual(args[2:], ['--database', str(app.db.path)])
        finally:
            app.closing = True
            app.transport.close()
            app.db.close()

    def status(self, version, crc, name='Preshow 1', count=32):
        return zonedb.STATUS.pack(b'NZ', 1, zonedb.ZONE_STATUS, 0, 1, 1, name.encode().ljust(16, b'\0'),
                                  b'preshow-2.0.0'.ljust(16, b'\0'), version, count, crc, 0, 0, 0, 5, 1, 1, 0, 0, 2, 1, 0).hex()

    def test_zone_database_manager(self):
        dongle_port = dict(port='/dev/cu.dongle', key='d', description='USB JTAG', candidate=True, serial='AA:BB:CC:00:11:22')
        with patch.object(manager_app.dongle, 'ports', return_value=[dongle_port]), \
                patch.object(manager_app, 'WebStatus', MagicMock()):
            app = manager_app.App(self.root, Path(self.tmp.name) / 'devices.sqlite3')
        try:
            store = app.zones.store
            records = store.records()
            p = zonedb.Publication(3, records)
            store.cache(dict(version=3, hash=zonedb.content_hash(records), count=p.count, crc=p.crc,
                             records_b64=base64.b64encode(p.body).decode(), published_at='now', published_by='laptop'))
            self.assertEqual(app.selected_port()['port'], '/dev/cu.dongle')
            sent = []
            app.zones.send = sent.append
            app.send = sent.append
            app.transport.port = MagicMock()
            app.opened_at = app.last_rx = manager_app.time.monotonic()
            # Wrong firmware: hello without zone support is not a usable dongle.
            app.transport.inbox.put(dict(event='hello', protocol=1, channel=2, radio_ok=True, mac='AA:BB:CC:00:11:22',
                                         firmware='nct-pairing-1.5'))
            app.poll()
            self.assertFalse(app.connected)
            self.assertIn('no zone relay', app.radio_status['text'])
            app.transport.inbox.put(dict(event='hello', protocol=1, channel=2, radio_ok=True, zones=1, mac='AA:BB:CC:00:11:22',
                                         firmware='nct-pairing-1.6-zones', nfc_ok=False))
            app.poll()
            self.assertTrue(app.connected)
            self.assertTrue(any(m.get('cmd') == 'zone_send' and bytes.fromhex(m['hex'])[3] == zonedb.ZONE_QUERY for m in sent))
            zone, current = '14:63:93:C0:EC:14', '14:63:93:C0:EC:15'
            app.transport.inbox.put(dict(event='zone_frame', mac=zone, hex=self.status(2, 0x1234)))
            app.transport.inbox.put(dict(event='zone_frame', mac=current, hex=self.status(3, p.crc, 'Desert 1', p.count)))
            app.poll()
            app.render(force=True)
            self.assertEqual(set(app.tree.get_children()), {zone, current})
            self.assertIn('out of date', app.tree.item(zone, 'values')[5])
            self.assertIn('1 out of date', app.summary['text'])
            self.assertIn('Published v3', app.published_label['text'])
            app.tree.selection_set(current)
            with patch.object(manager_app.messagebox, 'showerror') as error:
                app.update_button.invoke()
            self.assertIn('already has database v3', error.call_args[0][1])
            app.tree.selection_set(zone)
            app.update_button.invoke()
            self.assertEqual(app.zones.publish_target, zone)
            app.poll()
            announce = next(m for m in sent if m.get('cmd') == 'zone_send' and bytes.fromhex(m['hex'])[3] == zonedb.DB_ANNOUNCE)
            self.assertEqual(announce['mac'], zone)
            app.transport.inbox.put(dict(event='zone_frame', mac=zone, hex=self.status(3, p.crc, count=p.count)))
            for _ in range(8):  # announce + 3 chunks, one relay in flight at a time
                for m in [m for m in sent if m.get('cmd') == 'zone_send']:
                    app.transport.inbox.put(dict(event='zone_sent', id=m['id'], status='delivered'))
                app.poll()
            self.assertIsNone(app.zones.publication)
            self.assertIn('confirmed', app.status.get())
            # Walkaround needs a published database and turns auto-refresh on.
            app.auto_var.set(False); app.toggle_auto()
            app.walk_var.set(True); app.walk_check.invoke(); app.walk_check.invoke()
            self.assertTrue(app.zones.walkaround and app.zones.auto_refresh and app.auto_var.get())
            app.stop_button.invoke()
            self.assertFalse(app.zones.walkaround or app.walk_var.get())
        finally:
            app.closing = True
            app.transport.port = None
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
                # Identifying a legacy board reboots it: the port vanishes and comes back. It must not be identified again.
                legacy = dict(port='/dev/cu.legacy', key='3C:0F:02:AF:61:C0', description='USB JTAG', candidate=True, serial='3C:0F:02:AF:61:C0')
                with patch.object(flasher_app, 'ports', return_value=[station, zone, legacy]):
                    window.scan_ports()
                    self.assertEqual(window.pending_detect, {'/dev/cu.legacy'})
                with patch.object(flasher_app, 'ports', return_value=[station, zone]):   # rebooting while being identified
                    window.scan_ports()
                    window.handle('detected', ('/dev/cu.legacy', dict(kind='legacy_zone', label='Legacy PreshowZone plate', mac=legacy['serial'], profile='preshow')))
                    window.scan_ports()
                    self.assertNotIn('/dev/cu.legacy', window.detections)
                with patch.object(flasher_app, 'ports', return_value=[station, zone, legacy]):  # back on USB
                    window.pending_detect.clear()
                    window.scan_ports()
                    self.assertEqual(window.detections['/dev/cu.legacy']['label'], 'Legacy PreshowZone plate')
                    self.assertEqual(window.pending_detect, set())
                    self.assertIn('FLASH', window.port_tree.item('/dev/cu.legacy', 'values')[6])
                    window.port_tree.selection_set('/dev/cu.legacy')
                    window.detect_selected()      # "Detect again" does identify again
                    self.assertEqual(window.pending_detect, {'/dev/cu.legacy'})
                    window.pending_detect.clear()
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
