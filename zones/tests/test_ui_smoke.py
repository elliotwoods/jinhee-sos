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
preshow_test_app = load('preshow_test_app', ROOT / 'preshow_test/app.py')

STATION = dict(zones=1, channel=2, mac='3C:0F:02:AD:83:24')


def publish(db, version):
    """Cache a web publication of the database's committed mappings (versions come from the web, never locally)."""
    store = flasher_app.ZoneStore(db)
    records = store.records()
    p = zonedb.Publication(version, records)
    store.cache(dict(version=version, hash=zonedb.content_hash(records), count=p.count, crc=p.crc,
                     records_b64=base64.b64encode(p.body).decode(), published_at='now', published_by='laptop'))


class UiSmokeTests(unittest.TestCase):
    def setUp(self):
        # The Sync widget's background status check must not reach the real web from tests.
        self.offline = patch('sync_widget.sync_all.status', return_value=dict(state='offline'))
        self.offline.start()
        self.addCleanup(self.offline.stop)
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
        with patch.object(manager_app.dongle, 'ports', return_value=[dongle_port]):
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
            app.transport.inbox.put(dict(event='zone_frame', mac=zone, hex=self.status(2, 0x1234), rssi=-62))
            app.transport.inbox.put(dict(event='zone_frame', mac=current, hex=self.status(3, p.crc, 'Desert 1', p.count)))
            app.poll()
            app.render(force=True)
            self.assertEqual(set(app.tree.get_children()), {zone, current})
            column = lambda mac, key: app.tree.item(mac, 'values')[[c[0] for c in manager_app.COLUMNS].index(key)]
            self.assertIn('out of date', column(zone, 'state'))
            self.assertEqual(column(zone, 'signal'), '▂▄▆ -62 dBm')
            self.assertEqual(column(current, 'signal'), '—')  # no rssi reported (dongle firmware 1.6)
            self.assertEqual(manager_app.signal_text(-75), '▂▄· -75 dBm')
            self.assertEqual(manager_app.signal_text(-88), '▂·· -88 dBm')
            self.assertIn('Flash dongle', app.radio_status['text'])  # 1.6 dongle: hint to update (signal bars, RX gain)
            # A general radio is a current relay too: connected, no reflash hint.
            app.transport.inbox.put(dict(event='hello', protocol=1, channel=2, radio_ok=True, zones=1, mac='AA:BB:CC:00:11:22',
                                         firmware='general-radio-1.0.0', nfc_ok=False))
            app.poll()
            self.assertTrue(app.connected)
            self.assertIn('general radio', app.radio_status['text'])
            self.assertNotIn('Flash dongle', app.radio_status['text'])
            app.transport.inbox.put(dict(event='hello', protocol=1, channel=2, radio_ok=True, zones=1, mac='AA:BB:CC:00:11:22',
                                         firmware='nct-pairing-1.6-zones', nfc_ok=False))  # back to the 1.6 dongle for the rest
            app.poll()
            self.assertIn('1 out of date', app.summary['text'])
            self.assertIn('Published v3', app.published_label['text'])
            app.render(force=True)
            self.assertEqual(app.selected_label['text'], 'Selected: —')
            self.assertTrue(app.identify_button.instate(['disabled']))  # nothing selected
            app.tree.selection_set(current)
            app.render(force=True)
            self.assertEqual(app.selected_label['text'], 'Selected: Desert 1')
            self.assertTrue(app.update_button.instate(['disabled']))  # already current
            self.assertFalse(app.identify_button.instate(['disabled']))
            # RX gain: unknown until the zone reports it; set through a 1.8 dongle, settled only by the zone's report.
            self.assertEqual(column(current, 'rx_gain'), '—')
            settings = lambda gain, applied, result, nonce=0: zonedb.SETTINGS.pack(
                b'NZ', 1, zonedb.ZONE_SETTINGS, nonce, gain, applied, result).hex()
            app.transport.inbox.put(dict(event='zone_frame', mac=current, hex=settings(48, 48, 0, 9)))
            app.poll()
            app.render(force=True)
            self.assertEqual(column(current, 'rx_gain'), '48 dB')
            self.assertFalse(app.gain_button.instate(['disabled']))
            gain_frames = lambda: [m for m in sent if m.get('cmd') == 'zone_send'
                                   and bytes.fromhex(m['hex'])[3] == zonedb.ZONE_SET_CONFIG]
            with patch.object(manager_app, 'GainDialog') as dialog_class, \
                    patch.object(manager_app.messagebox, 'showerror') as error:
                dialog_class.return_value.result = 33
                app.gain_button.invoke()  # the 1.6 dongle would reject the frame: refused here with the reason
                error.assert_called_once()
                self.assertIn('Flash dongle', error.call_args[0][1])
                self.assertEqual(gain_frames(), [])
                app.station['firmware'] = manager_app.dongle.FIRMWARE
                app.gain_button.invoke()
            [request] = gain_frames()
            self.assertEqual((request['mac'], bytes.fromhex(request['hex'])), (current, zonedb.set_config_frame(33)))
            app.render(force=True)
            self.assertEqual(column(current, 'rx_gain'), '→ 33 dB …')
            self.assertTrue(app.gain_button.instate(['disabled']))
            app.transport.inbox.put(dict(event='zone_frame', mac=current, hex=settings(48, 48, 0, 77)))  # routine query
            app.poll()
            self.assertEqual(app.zones.gain_requests[current][0], 33)
            app.transport.inbox.put(dict(event='zone_frame', mac=current, hex=settings(33, 33, zonedb.SET_OK)))
            app.poll()
            app.render(force=True)
            self.assertEqual(column(current, 'rx_gain'), '33 dB')
            self.assertNotIn(current, app.zones.gain_requests)
            self.assertIn('RX gain 33 dB — ok', app.logbox.get('1.0', 'end'))
            self.assertIn('RX gain 33 dB stored · reader 33 dB · last change: ok', app.detail.get('1.0', 'end'))
            app.transport.inbox.put(dict(event='zone_frame', mac=current, hex=settings(33, 0, zonedb.SET_NOT_APPLIED)))
            app.poll()
            app.render(force=True)
            self.assertEqual(column(current, 'rx_gain'), '33 dB (not applied)')
            app.tree.selection_set(zone)
            app.render(force=True)
            self.assertFalse(app.update_button.instate(['disabled']))
            app.update_button.invoke()
            self.assertEqual(app.zones.publish_target, zone)
            # The run opens the modal progress window listing the zone being updated.
            dialog = app.update_dialog
            self.assertIsNotNone(dialog)
            self.assertEqual(dialog.macs, [zone])
            self.assertFalse(dialog.finished)
            self.assertTrue(dialog.close_button.instate(['disabled']))
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
            app.render(force=True)
            self.assertTrue(dialog.finished)
            self.assertEqual(dialog.tree.item(zone)['values'][3], 'confirmed ✓')
            self.assertTrue(dialog.stop_button.instate(['disabled']))
            dialog.close_button.invoke()
            app.render(force=True)
            self.assertIsNone(app.update_dialog)
            self.assertTrue(app.update_all_button.instate(['disabled']))  # nothing out of date in range
            # Walkaround needs a published database and turns auto-refresh on.
            app.auto_var.set(False); app.toggle_auto()
            app.walk_var.set(True); app.walk_check.invoke(); app.walk_check.invoke()
            self.assertTrue(app.zones.walkaround and app.zones.auto_refresh and app.auto_var.get())
            app.stop_button.invoke()
            self.assertFalse(app.zones.walkaround or app.walk_var.get())
            # USB drop-out during a walkaround update: the update stops, walkaround stays armed, and the
            # same dongle is reopened automatically when it reappears (a failed send is not an error).
            app.walk_var.set(True); app.toggle_walkaround()
            app.transport.inbox.put(dict(event='zone_frame', mac=zone, hex=self.status(2, 0x1234)))
            app.poll()
            self.assertTrue(app.zones.walk_run)
            app.render(force=True)
            self.assertTrue(app.update_dialog.auto)
            app.transport.send = MagicMock(side_effect=ValueError('Serial port is disconnected'))
            app.send = manager_app.App.send.__get__(app)
            app.zones.send = app.send
            app.zones.queue.insert(0, 0); app.zones.inflight = None
            app.poll()  # the send fails: recorded, not raised
            self.assertIsNotNone(app.link_lost)
            app.poll()  # next poll handles the drop-out
            self.assertIsNone(app.zones.publication)
            self.assertIsNone(app.transport.port)
            self.assertTrue(app.walk_var.get() and app.zones.walkaround)
            self.assertIn('reconnecting automatically', app.radio_status['text'])
            reopened = []
            with patch.object(manager_app.dongle, 'ports', return_value=[dongle_port]), \
                    patch.object(app.transport, 'open', side_effect=lambda port: (reopened.append(port),
                                                                             setattr(app.transport, 'port', MagicMock()))):
                app.last_reconnect_scan = 0
                app.poll()
            self.assertEqual(reopened, ['/dev/cu.dongle'])
        finally:
            app.closing = True
            app.transport.port = None
            app.db.close()

    def test_preshow_link_test_window(self):
        # Never opens a port: with no --port and more than one candidate it waits to be told.
        with patch.object(preshow_test_app, 'list_ports') as ports:
            ports.comports.return_value = [MagicMock(device='/dev/cu.a', vid=0x303a),
                                           MagicMock(device='/dev/cu.b', vid=0x303a)]
            window = preshow_test_app.App(self.root)
        self.assertIsNone(window.serial)
        # Disarmed: the cue buttons do nothing at all, so a stray click cannot reach the show.
        for button in window.buttons.values():
            self.assertEqual(str(button['state']), 'disabled')
        window.toggle(1)

        # Telemetry from the plate drives the panel, including which point is lit.
        window.handle('{"device":"PreshowZone","type":"host","armed":true,"state":"ON","point":3,'
                      '"configured_point":1,"mode":"legacy","firmware":"preshow-3.2.0","seq":4,'
                      '"acked":false,"ack_ms":0,"bridge_sees_me":false,"bridge_seen_ms":0,"sent":9,'
                      '"legacy_sent":9,"retries":2,"acks":0,"failed":0,"errors":0,"nfc":false,'
                      '"radio":true,"bridge_mac":""}')
        self.assertTrue(window.armed)
        self.assertEqual(window.held(), 3)
        self.assertEqual(str(window.buttons[3]['text']), 'ON')
        self.assertEqual(str(window.buttons[1]['text']), 'OFF')
        self.assertIn('LEGACY MODE', window.detail.cget('text'))
        self.assertIn('preshow-3.2.0', window.state.cget('text'))
        # A cue that cannot be acknowledged must not be reported as acknowledged.
        self.assertIn('n/a', window.link.cget('text'))

        # Switching points is OFF then ON, spaced, because the firmware refuses an implicit
        # switch — each edge has to get its own burst and retry window.
        sent = []
        window.send = lambda command: sent.append(command) or True
        window.toggle(2)
        self.assertEqual(sent, ['HOST OFF'])
        self.assertEqual(window.pending_on, 2)
        window.flush_pending()
        self.assertEqual(sent, ['HOST OFF', 'HOST ON 2'])
        # Pressing the lit point again is a plain release.
        sent.clear()
        window.toggle(3)
        self.assertEqual(sent, ['HOST OFF'])

        # Modern mode reports the real acknowledgement instead.
        window.handle('{"device":"PreshowZone","type":"host","armed":true,"state":"OFF","point":1,'
                      '"configured_point":1,"mode":"modern","firmware":"preshow-3.2.0","seq":5,'
                      '"acked":true,"ack_ms":31,"bridge_sees_me":true,"bridge_seen_ms":120,"sent":12,'
                      '"legacy_sent":9,"retries":2,"acks":1,"failed":0,"errors":0,"nfc":false,'
                      '"radio":true,"bridge_mac":"E8:3D:C1:94:6C:9C"}')
        self.assertIn('MODERN MODE', window.detail.cget('text'))
        self.assertIn('31 ms', window.link.cget('text'))
        self.assertIn('E8:3D:C1:94:6C:9C', window.bridge.cget('text'))
        self.assertIsNone(window.held())

    def test_zone_flasher_window(self):
        station = dict(port='/dev/cu.station', key='s', description='USB JTAG', candidate=False, serial='3C:0F:02:AD:83:24')
        zone = dict(port='/dev/cu.zone', key='z', description='USB JTAG', candidate=True, serial='14:63:93:C0:EC:14')
        with patch.object(flasher_app, 'ports', return_value=[station, zone]):
            window = flasher_app.App(self.root, Path(self.tmp.name) / 'devices.sqlite3')
            try:
                self.assertEqual(window.name.get(), 'Preshow 1')
                PLAN = [c[0] for c in flasher_app.PORT_COLUMNS].index('plan')
                GAIN = [c[0] for c in flasher_app.PORT_COLUMNS].index('rx_gain')
                self.assertEqual(window.form()['rx_gain'], 48)
                window.scan_ports()
                self.assertEqual(window.pending_detect, {'/dev/cu.station', '/dev/cu.zone'})
                window.pending_detect.clear()
                window.handle('detected', ('/dev/cu.station', dict(kind='station', label='Pairing station (protected)', mac=station['serial'], profile=None)))
                window.handle('detected', ('/dev/cu.zone', dict(kind='nctzone', label='NctZone firmware', mac=zone['serial'], firmware='pool-2.0.0',
                              profile='pool', configured=True, point=4, name='Pool Radio 4', zone_type=3, params=[3830, 435],
                              db_version=1, db_count=32, db_crc=5, source='serial report', rx_gain=38, rx_gain_applied=None)))
                window.scan_ports()
                # The detected identity fills the form, including calibration parameters.
                self.assertEqual((window.profile_key(), window.point.get(), window.name.get()), ('pool', 4, 'Pool Radio 4'))
                self.assertEqual([v.get() for v in window.param_vars], ['383.0', '43.5'])
                self.assertEqual(window.form()['params'], [3830, 435])
                self.assertEqual(window.form()['rx_gain'], 38)  # the board's gain, kept when reflashing
                rows = {iid: window.port_tree.item(iid, 'values') for iid in window.port_tree.get_children()}
                self.assertEqual(rows['/dev/cu.zone'][GAIN], '38 dB (not applied)')
                self.assertEqual(rows['/dev/cu.station'][GAIN], '—')
                self.assertEqual(window.plan_for('/dev/cu.zone', auto=False)['rx_gain'], 38)
                window.rx_gain.set('23')
                self.assertEqual(window.plan_for('/dev/cu.zone', auto=False)['rx_gain'], 23)
                self.assertEqual(window.plan_for('/dev/cu.zone', auto=True)['rx_gain'], 38)  # auto-flash keeps the board's
                self.assertIn('REFUSE', rows['/dev/cu.station'][PLAN])
                self.assertIn('FLASH', rows['/dev/cu.zone'][PLAN])  # nothing published yet: no database plan
                self.assertEqual(list(window.monitor_ports['values']), ['/dev/cu.zone'])
                # Automatic database update (on by default): a zone behind the published database is updated once per
                # publication; one ahead of it never is; an unticked box stops it; a manual update is always offered.
                self.assertTrue(window.auto_db.get())
                self.assertIn('Update database', [b['text'] for b in window.buttons])
                updates = []
                window.update_database = lambda port, auto=False: updates.append((port, auto)) or True
                db = flasher_app.Database(Path(self.tmp.name) / 'devices.sqlite3')
                publish(db, 3)
                db.close()
                window.refresh_info()
                self.assertIsNone(window.db_ready)
                window.render_ports()
                self.assertEqual(window.port_tree.item('/dev/cu.zone', 'values')[PLAN], 'DATABASE · Update database v1 → v3')
                window.auto_step()
                self.assertEqual(updates, [('/dev/cu.zone', True)])
                window.auto_step()
                self.assertEqual(len(updates), 1)                   # attempted: not again while it stays plugged in
                db = flasher_app.Database(Path(self.tmp.name) / 'devices.sqlite3')
                publish(db, 4)                                       # a new publication is tried again
                db.close()
                window.auto_step()
                self.assertEqual(len(updates), 2)
                window.handle('detected', ('/dev/cu.zone', dict(window.detections['/dev/cu.zone'], db_version=9)))
                window.db_scheduler.attempted.clear()
                window.render_ports()
                self.assertIn('ASK · Database v9 is ahead', window.port_tree.item('/dev/cu.zone', 'values')[PLAN])
                window.auto_step()
                self.assertEqual(len(updates), 2)                    # ahead: left alone automatically
                window.handle('detected', ('/dev/cu.zone', dict(window.detections['/dev/cu.zone'], db_version=1)))
                window.auto_db.set(False)
                window.auto_db_changed()
                window.auto_step()
                self.assertEqual(len(updates), 2)                    # unticked
                self.assertIn('FLASH', window.port_tree.item('/dev/cu.zone', 'values')[PLAN])
                window.port_tree.selection_set('/dev/cu.zone')
                with patch.object(flasher_app.messagebox, 'askokcancel', return_value=True) as ask:
                    window.update_selected()
                self.assertEqual(updates[-1], ('/dev/cu.zone', False))
                self.assertIn('v4', ask.call_args[0][1])
                window.port_tree.selection_set('/dev/cu.station')
                with patch.object(flasher_app.messagebox, 'showerror') as error:
                    window.update_selected()
                self.assertIn('pairing station', error.call_args[0][1])
                self.assertEqual(len(updates), 3)
                window.auto_db.set(True)
                window.auto_db_changed()
                window.port_tree.selection_set('/dev/cu.zone')
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
                    self.assertIn('FLASH', window.port_tree.item('/dev/cu.legacy', 'values')[PLAN])
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
