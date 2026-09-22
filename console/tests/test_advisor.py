import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import paths  # noqa: E402,F401
import advisor  # noqa: E402
from tests import fixtures as fx  # noqa: E402
from tests.fixtures import (CUBE_MAC, CUBE_NUMBER, CUBE_UID, NOW, PLATE_MAC, POOL_MAC, STATION_MAC, inventory_row,  # noqa: E402
                            sections, station_section, tap, usb_device, with_registry, zone_report, zone_row, zone_session)


def ids(suggestions):
    return [s['id'] for s in suggestions]


def by_rule(suggestions, rule):
    return [s for s in suggestions if s['rule'] == rule]


def actions(s):
    return {a['id']: a for a in s['actions']}


def run(sec, now=NOW, dismissed=()):
    return advisor.evaluate(sec, now, set(dismissed))


class UnknownTagTests(unittest.TestCase):
    def test_f1_known_tag_zone_behind(self):
        out = run(fx.f1_sections())
        tags = by_rule(out, 'tag.known_zone_behind')
        self.assertEqual(len(tags), 1)
        s = tags[0]
        self.assertEqual(s['id'], f'tag.known_zone_behind:zone:{PLATE_MAC}:{CUBE_UID}')
        self.assertEqual(s['severity'], 'warn')
        self.assertIn('#44', s['title'])
        self.assertIn('v31', s['know'])
        self.assertIn('v32', s['know'])
        self.assertIn('2026-09-21', s['know'])
        self.assertIn('studio-mac', s['know'])
        a = actions(s)
        self.assertEqual(a['usb']['command'], 'zone.update_db_usb')
        self.assertEqual(a['usb']['args'], dict(device=PLATE_MAC))
        self.assertEqual(a['usb']['kind'], 'hardware')
        self.assertFalse(a['usb']['needs_confirm'])
        self.assertEqual(a['air']['command'], 'zones.update')
        self.assertEqual(a['air']['args'], dict(mac=PLATE_MAC))
        self.assertFalse(by_rule(out, 'zone.db_behind'), 'zone.db_behind is superseded by the tag card')
        self.assertEqual(s['device'], PLATE_MAC)

    def test_f1_without_station_has_only_usb_action(self):
        sec = fx.f1_sections(station=dict(present=False), registry=dict(present=False))
        out = run(sec)
        s = by_rule(out, 'tag.known_zone_behind')[0]
        self.assertEqual(list(actions(s)), ['usb'])
        self.assertIn('Over-the-air', s['check'])

    def test_f2_pending_registration(self):
        sec = fx.f1_sections()
        sec['inventory']['rows'] = [inventory_row(uid=None, pending_uid=CUBE_UID, status='unconfirmed',
                                                  detail='No matching acknowledgment after three attempts')]
        sec['inventory']['published_records'] = []
        out = run(sec)
        s = by_rule(out, 'tag.pending_registration')
        self.assertEqual(len(s), 1)
        s = s[0]
        self.assertEqual(s['severity'], 'warn')
        self.assertIn('No matching acknowledgment', s['know'])
        self.assertIn('not acknowledgment', s['why'])
        a = actions(s)
        self.assertEqual(a['transmit']['command'], 'pairing.transmit')
        self.assertEqual(a['transmit']['args'], dict(macs=[CUBE_MAC]))
        self.assertEqual(a['transmit']['kind'], 'hardware')
        self.assertFalse(by_rule(out, 'tag.known_zone_behind'))
        self.assertFalse(by_rule(out, 'tag.known_unpublished'))
        self.assertFalse(any(x['command'].startswith('zone.update') for x in s['actions']))

    def test_pending_paused_offers_retry(self):
        sec = fx.f1_sections(station=station_section(phase='paused'))
        sec['inventory']['rows'] = [inventory_row(uid=None, pending_uid=CUBE_UID, status='unconfirmed')]
        s = by_rule(run(sec), 'tag.pending_registration')[0]
        self.assertIn('retry', actions(s))

    def test_known_but_unpublished(self):
        sec = fx.f1_sections()
        sec['inventory']['published_records'] = []
        sec['inventory']['local_differs'] = True
        out = run(sec)
        s = by_rule(out, 'tag.known_unpublished')
        self.assertEqual(len(s), 1)
        self.assertEqual(actions(s[0])['sync']['command'], 'sync.run')
        self.assertFalse(by_rule(out, 'tag.known_zone_behind'))
        self.assertFalse(by_rule(out, 'zone.local_differs'), 'the tag card carries the same Sync action')

    def test_device_without_number(self):
        sec = fx.f1_sections()
        sec['inventory']['rows'] = [inventory_row(cube_id=None, status='needs_number', detail='Previous number 44 cleared')]
        s = by_rule(run(sec), 'tag.device_without_number')
        self.assertEqual(len(s), 1)
        self.assertEqual(actions(s[0])['rename']['args'], dict(mac=CUBE_MAC, number=45))

    def test_unknown_everywhere(self):
        sec = fx.f1_sections()
        sec['inventory']['rows'] = []
        sec['inventory']['published_records'] = []
        s = by_rule(run(sec), 'tag.unknown_everywhere')
        self.assertEqual(len(s), 1)
        a = actions(s[0])
        self.assertEqual(a['sync']['command'], 'sync.run')
        self.assertEqual(a['register']['command'], 'pairing.start_pair')
        self.assertIn('not a station scan', s[0]['why'])

    def test_inconsistent_when_plate_current(self):
        sec = fx.f1_sections()
        report = zone_report(db_version=32, db_crc=fx.PUBLISHED['crc'])
        sec['sessions'] = {PLATE_MAC: zone_session(report=report, history=[tap(CUBE_UID)])}
        with_registry(sec, [zone_row(db_version=32, db_crc=fx.PUBLISHED['crc'], state='current')])
        out = run(sec)
        self.assertEqual(len(by_rule(out, 'tag.inconsistent')), 1)
        self.assertFalse(by_rule(out, 'tag.known_zone_behind'))

    def test_window_expiry(self):
        sec = fx.f1_sections()
        sec['sessions'][PLATE_MAC]['history'] = [tap(CUBE_UID, at=NOW - 14 * 60)]
        self.assertTrue(by_rule(run(sec), 'tag.known_zone_behind'))
        sec['sessions'][PLATE_MAC]['history'] = [tap(CUBE_UID, at=NOW - 16 * 60)]
        self.assertFalse(by_rule(run(sec), 'tag.known_zone_behind'))
        self.assertTrue(by_rule(run(sec), 'zone.db_behind'), 'the zone card returns once the tag card expired')

    def test_repeated_taps_one_card(self):
        sec = fx.f1_sections()
        sec['sessions'][PLATE_MAC]['history'] = [tap(CUBE_UID, at=NOW - 5), tap(CUBE_UID, at=NOW - 60)]
        self.assertEqual(len(by_rule(run(sec), 'tag.known_zone_behind')), 1)


class NackTests(unittest.TestCase):
    def sec(self, mac_on_plate=CUBE_MAC, status='acknowledged', discovered=None):
        sec = fx.f1_sections(station=station_section(discovered=discovered or {}))
        sec['inventory']['rows'] = [inventory_row(status=status)]
        sec['sessions'][PLATE_MAC]['history'] = [tap(CUBE_UID, cube_id=CUBE_NUMBER, mac=mac_on_plate, state='not acknowledged')]
        return sec

    def test_offline(self):
        s = by_rule(run(self.sec()), 'cube.nack_offline')
        self.assertEqual(len(s), 1)
        self.assertIn('not heard', s[0]['know'])
        self.assertEqual(actions(s[0])['discover']['command'], 'pairing.discover')

    def test_mac_mismatch(self):
        s = by_rule(run(self.sec(mac_on_plate='34:85:18:00:00:12')), 'cube.nack_mac_mismatch')
        self.assertEqual(len(s), 1)
        self.assertIn('34:85:18:00:00:12', s[0]['know'])
        self.assertIn('usb', actions(s[0]))

    def test_unregistered(self):
        s = by_rule(run(self.sec(status='not_transmitted')), 'cube.nack_unregistered')
        self.assertEqual(len(s), 1)
        self.assertEqual(actions(s[0])['transmit']['args'], dict(macs=[CUBE_MAC]))


class RefusedBoardTests(unittest.TestCase):
    def detection(self, mac='B8:D6:1A:00:11:22', kind='cube'):
        return dict(kind=kind, label='Neocube #17 (database)', mac=mac, profile=None, source='database')

    def test_f3_force_path(self):
        d = usb_device(port='/dev/cu.usbmodem2201', role='cube', mac='B8:D6:1A:00:11:22', state='idle', detection=self.detection())
        out = run(sections(devices=[d]))
        s = by_rule(out, 'flash.refused')
        self.assertEqual(len(s), 1)
        s = s[0]
        self.assertEqual(s['severity'], 'warn')
        a = actions(s)
        self.assertEqual(list(a), ['force'])
        self.assertEqual(a['force']['command'], 'zone.flash_force')
        self.assertEqual(a['force']['kind'], 'destructive')
        self.assertTrue(a['force']['needs_confirm'])
        self.assertIn('unregisters', s['know'])

    def test_f3_protected_station_has_no_force(self):
        d = usb_device(port='/dev/cu.usbmodem2201', role='workstation', mac='3C:0F:02:AD:83:24', state='idle',
                       detection=self.detection(mac='3C:0F:02:AD:83:24', kind='station'))
        s = by_rule(run(sections(devices=[d])), 'flash.refused')[0]
        self.assertEqual(s['severity'], 'bad')
        self.assertEqual(s['actions'], [])

    def test_f3_broken_esptool_strips_flash_actions(self):
        d = usb_device(port='/dev/cu.usbmodem2201', role='cube', mac='B8:D6:1A:00:11:22', state='idle', detection=self.detection())
        sec = sections(devices=[d])
        sec['builds']['tools']['esptool_ok'] = False
        out = run(sec)
        self.assertTrue(by_rule(out, 'tools.esptool'))
        s = by_rule(out, 'flash.refused')[0]
        self.assertEqual(s['actions'], [])
        self.assertIn('flashing tool', s['check'])

    def test_refused_job_outcome(self):
        d = usb_device(port='/dev/cu.usbmodem2201', role='cube', mac='B8:D6:1A:00:11:22', state='idle')
        job = dict(id='j1', kind='zone.flash', state='failed', error='B8:D6:1A:00:11:22 is registered as neocube #17; refusing to overwrite it with zone firmware',
                   result=None, outcome=None, device=d['id'], target=d['key'], finished_at=NOW - 30, title='Flash zone')
        s = by_rule(run(sections(devices=[d], jobs=[job])), 'flash.refused')
        self.assertEqual(len(s), 1)
        self.assertEqual(actions(s[0])['force']['kind'], 'destructive')


class StationTests(unittest.TestCase):
    def test_f4_status_5(self):
        sec = sections(station=station_section(reader_ok=False, nfc_ok=False, nfc_i2c_status=5,
                                               feedback=dict(kind='error', title='NFC READER NOT RESPONDING',
                                                             detail='The station radio is connected, but live communication with the PN532 has failed. No tag has been registered.')))
        s = by_rule(run(sec), 'station.nfc_down')
        self.assertEqual(len(s), 1)
        self.assertEqual(s[0]['severity'], 'bad')
        self.assertIn('status 5 = bus timeout', s[0]['know'])
        a = actions(s[0])
        self.assertEqual(a['recover']['command'], 'station.nfc_recover')
        self.assertEqual(a['recover']['kind'], 'hardware')
        self.assertEqual(a['status']['command'], 'station.nfc_status')
        self.assertEqual(a['docs']['args']['path'], 'pairing_station/I2C_DEBUG.md')

    def test_f4_status_2(self):
        s = by_rule(run(sections(station=station_section(reader_ok=False, nfc_ok=False, nfc_i2c_status=2))), 'station.nfc_down')[0]
        self.assertIn('status 2 = address NACK', s[0] if isinstance(s, list) else s['know'])

    def test_f4_busy_station_no_recover(self):
        s = by_rule(run(sections(station=station_section(reader_ok=False, nfc_ok=False, nfc_i2c_status=5, mode='pair'))), 'station.nfc_down')[0]
        self.assertNotIn('recover', actions(s))
        self.assertIn('Stop the current operation', s['check'])

    def test_f4_healthy_station_silent(self):
        self.assertFalse(by_rule(run(sections(station=station_section())), 'station.nfc_down'))

    def test_dongle_ignores_nfc(self):
        self.assertFalse(by_rule(run(sections(station=station_section(nfc_ok=False, dongle=True, reader_ok=False))), 'station.nfc_down'))

    def test_disconnected_supersedes_and_strips_air(self):
        sec = fx.f1_sections(station=station_section(connected=False, last_disconnect='Station stopped responding', nfc_ok=False, reader_ok=False))
        out = run(sec)
        self.assertTrue(by_rule(out, 'station.disconnected'))
        self.assertFalse(by_rule(out, 'station.nfc_down'))
        s = by_rule(out, 'tag.known_zone_behind')[0]
        self.assertNotIn('air', actions(s))

    def test_wrong_channel_and_no_zone_support(self):
        out = run(sections(station=station_section(channel=6, zones=0)))
        self.assertTrue(by_rule(out, 'station.wrong_channel'))
        self.assertFalse(by_rule(out, 'station.no_zone_support'), 'superseded by wrong channel')
        out = run(sections(station=station_section(zones=0)))
        self.assertTrue(by_rule(out, 'station.no_zone_support'))

    def test_old_dongle(self):
        s = by_rule(run(sections(station=station_section(firmware='nct-pairing-1.6-zones'))), 'dongle.old')
        self.assertEqual(len(s), 1)
        self.assertEqual(actions(s[0])['flash']['args'], dict(device=STATION_MAC, firmware='workstation'))
        # An older Workstation build is out of date within its family; a legacy General Radio is superseded, never "old".
        s = by_rule(run(sections(station=station_section(firmware='workstation-0.9.0'))), 'dongle.old')
        self.assertEqual(len(s), 1)
        self.assertIn('workstation-1.0.0', s[0]['title'])
        for current in ('workstation-1.0.0', 'general-radio-1.0.0', 'general-radio-1.2.0'):
            self.assertFalse(by_rule(run(sections(station=station_section(firmware=current))), 'dongle.old'), current)


class ZoneDatabaseTests(unittest.TestCase):
    def test_unpublished_global(self):
        sec = sections()
        sec['inventory']['published'] = dict(version=0, hash='', count=0, crc=0)
        sec['inventory']['published_error'] = 'No zone database published yet; publish one in the Zone Database Manager'
        sec['inventory']['local_differs'] = True
        out = run(sec)
        self.assertTrue(by_rule(out, 'zone.unpublished'))
        self.assertFalse(by_rule(out, 'zone.local_differs'))

    def test_local_differs(self):
        sec = sections()
        sec['inventory']['local_differs'] = True
        s = by_rule(run(sec), 'zone.local_differs')
        self.assertEqual(len(s), 1)
        self.assertIn('v32', s[0]['know'])

    def test_behind_from_registry_without_station(self):
        sec = sections()
        with_registry(sec, [zone_row(db_version=31, state='behind', in_range=True)])
        out = run(sec)
        s = by_rule(out, 'zone.db_behind')
        self.assertEqual(len(s), 1)
        self.assertIn('v31', s[0]['title'])
        self.assertEqual(s[0]['actions'], [])

    def test_behind_out_of_range_is_one_summary_card(self):
        sec = sections()
        with_registry(sec, [zone_row(db_version=31, state='behind', in_range=False),
                            zone_row(mac='30:ED:A0:5B:0C:E8', name='Desert 15', db_version=32, state='behind', in_range=False)])
        out = run(sec)
        self.assertEqual(by_rule(out, 'zone.db_behind'), [])
        many = by_rule(out, 'zone.db_behind_many')
        self.assertEqual(len(many), 1)
        self.assertIn('2 known zone', many[0]['title'])

    def test_ahead(self):
        sec = sections()
        with_registry(sec, [zone_row(db_version=40, state='ahead')])
        s = by_rule(run(sec), 'zone.db_ahead')
        self.assertEqual(len(s), 1)
        self.assertEqual(actions(s[0])['sync']['command'], 'sync.run')

    def test_publish_timeout(self):
        sec = sections(devices=[usb_device()], sessions={PLATE_MAC: zone_session()})
        with_registry(sec, [zone_row(state='behind')])
        sec['registry']['message'] = f'Publishing v32 timed out; not confirmed: {PLATE_MAC}'
        s = by_rule(run(sec), 'zone.publish_timeout')
        self.assertEqual(len(s), 1)
        self.assertIn('usb', actions(s[0]))

    def test_error_code_8_offers_usb(self):
        sec = sections(devices=[usb_device()], sessions={PLATE_MAC: zone_session(report=zone_report(last_error=8))})
        s = by_rule(run(sec), 'zone.error')
        self.assertEqual(len(s), 1)
        self.assertEqual(s[0]['id'], f'zone.error:zone:{PLATE_MAC}:8')
        self.assertEqual(actions(s[0])['usb']['command'], 'zone.update_db_usb')

    def test_config_invalid(self):
        sec = sections(devices=[usb_device()], sessions={PLATE_MAC: zone_session(report=zone_report(config_valid=False))})
        s = by_rule(run(sec), 'zone.config_invalid')
        self.assertEqual(len(s), 1)
        self.assertEqual(actions(s[0])['flash']['command'], 'zone.flash')

    def test_partitions_missing_supersedes(self):
        sec = sections(devices=[usb_device()], sessions={PLATE_MAC: zone_session(report=zone_report(config_valid=False), tags=[
            dict(tag='zone.partitions_missing', level='bad', fields={}, text='PARTITIONS MISSING: flash with the zone flasher', t=NOW)])})
        out = run(sec)
        self.assertTrue(by_rule(out, 'zone.partitions_missing'))
        self.assertFalse(by_rule(out, 'zone.config_invalid'))

    def test_nfc_down_plate(self):
        nfc = dict(ok=False, polls=0, found=0, last_ms=0, fast_fail=0, recoveries=3, sda='1', scl='0', pins='4/3')
        sec = sections(devices=[usb_device()], sessions={PLATE_MAC: zone_session(nfc=nfc)})
        s = by_rule(run(sec), 'zone.nfc_down')
        self.assertEqual(len(s), 1)
        self.assertIn('SCL=0', s[0]['know'])
        self.assertIn('power-cycle reader and board together', s[0]['check'])
        self.assertEqual(actions(s[0])['recover']['command'], 'zone.nfc_recover')

    def test_preshow_legacy_mode(self):
        sec = sections(devices=[usb_device()], sessions={PLATE_MAC: zone_session(host=dict(mode='legacy', armed=False))})
        self.assertEqual(len(by_rule(run(sec), 'preshow.legacy_mode')), 1)

    def test_rx_gain_not_applied(self):
        sec = sections(devices=[usb_device()], sessions={PLATE_MAC: zone_session(report=zone_report(rx_gain_applied=None))})
        self.assertEqual(len(by_rule(run(sec), 'zone.rx_gain_unconfirmed')), 1)


class PoolTests(unittest.TestCase):
    def test_radio_id_clash(self):
        sec = sections()
        sec['inventory']['zones'] = [zone_row(mac=POOL_MAC, name='Pool Radio 3', zone_type=3, point_id=3, firmware='pool-3.2.0'),
                                     zone_row(mac='14:63:93:C0:EC:34', name='Pool Radio 3b', zone_type=3, point_id=3, firmware='pool-3.2.0')]
        sec['devices'] = [usb_device(port='/dev/cu.usbmodem3', role='zone', mac=POOL_MAC, session_kind='pool')]
        s = by_rule(run(sec), 'pool.radio_id_clash')
        self.assertEqual(len(s), 1)
        a = actions(s[0])
        self.assertEqual(len(a), 1)
        act = list(a.values())[0]
        self.assertEqual(act['command'], 'pool.assign_radio_id')
        self.assertEqual(act['args']['new_id'], 1)

    def test_central_not_seeing(self):
        sec = sections(devices=[usb_device(port='/dev/cu.usbmodem3', role='zone', mac=POOL_MAC, session_kind='pool')],
                       sessions={POOL_MAC: zone_session(mac=POOL_MAC, kind='pool', report=zone_report(mac=POOL_MAC, zone_type=3, firmware='pool-3.2.0', db_version=32, db_crc=fx.PUBLISHED['crc']),
                                                        interaction=dict(radio=True, central_sees_me=False, central_seen_ms=0, central_mac=None))})
        sec['inventory']['zones'] = [zone_row(mac=POOL_MAC, zone_type=3, point_id=3, db_version=32, db_crc=fx.PUBLISHED['crc'])]
        self.assertEqual(len(by_rule(run(sec), 'pool.central_not_seeing')), 1)

    def test_tune_unsupported(self):
        sec = sections(devices=[usb_device(port='/dev/cu.usbmodem3', role='zone', mac=POOL_MAC, session_kind='pool')],
                       sessions={POOL_MAC: zone_session(mac=POOL_MAC, kind='pool', report=zone_report(mac=POOL_MAC, zone_type=3, firmware='pool-2.7.0', db_version=32, db_crc=fx.PUBLISHED['crc']), tune_supported=False)})
        sec['inventory']['zones'] = [zone_row(mac=POOL_MAC, zone_type=3, point_id=3, db_version=32, db_crc=fx.PUBLISHED['crc'])]
        self.assertEqual(actions(by_rule(run(sec), 'pool.fw_update')[0])['flash']['command'], 'pool.flash_firmware')


class CubeTests(unittest.TestCase):
    def cube(self, **kw):
        return usb_device(port='/dev/cu.usbmodem9', role='cube', mac=CUBE_MAC, session_kind='cube', firmware='v1.4.0', **kw)

    def test_fw_different(self):
        d = self.cube(fw_status=dict(version='v1.4.0', expected='v1.4.1-USB.2', status='different', detail='Use USB Flash Station to update'))
        s = by_rule(run(sections(devices=[d])), 'cube.fw_different')
        self.assertEqual(len(s), 1)
        self.assertIn('v1.4.0', s[0]['title'])
        self.assertIn('not a hash verification', s[0]['why'])
        self.assertEqual(actions(s[0])['flash']['args'], dict(device=CUBE_MAC))

    def test_fw_unverified(self):
        d = self.cube(fw_status=dict(version=None, expected='v1.4.1-USB.2', status='unknown', detail='no answer'))
        s = by_rule(run(sections(devices=[d])), 'cube.fw_unverified')
        self.assertEqual(len(s), 1)
        self.assertEqual(s[0]['severity'], 'info')

    def test_unregistered_flag(self):
        d = self.cube(fw_status=dict(version='v1.4.1-USB.2', expected='v1.4.1-USB.2', status='current'))
        session = dict(kind='cube', device=CUBE_MAC, port=d['port'], flags=dict(unregistered=dict(at=NOW - 10)), fw_status=d['fw_status'], tags=[])
        s = by_rule(run(sections(devices=[d], sessions={CUBE_MAC: session}, station=station_section())), 'cube.unregistered')
        self.assertEqual(len(s), 1)
        self.assertEqual(actions(s[0])['transmit']['args'], dict(macs=[CUBE_MAC]))

    def test_show_start_ignored(self):
        d = self.cube(fw_status=dict(version='v1.4.1-USB.2', expected='v1.4.1-USB.2', status='current'))
        session = dict(kind='cube', device=CUBE_MAC, port=d['port'], flags=dict(show_start_ignored=dict(at=NOW - 10, zone='1')), tags=[])
        sec = sections(devices=[d], sessions={CUBE_MAC: session}, show=dict(present=True, usable=True, device='X', problem=None))
        s = by_rule(run(sec), 'cube.show_start_ignored')
        self.assertEqual(len(s), 1)
        self.assertEqual(actions(s[0])['ready']['command'], 'mainshow.ready')
        sec['sessions'][CUBE_MAC]['flags']['show_start_ignored']['at'] = NOW - 6 * 60
        self.assertFalse(by_rule(run(sec), 'cube.show_start_ignored'))


class SyncAndRegistrationTests(unittest.TestCase):
    def test_signin(self):
        sec = sections()
        sec['sync']['status']['state'] = 'signin'
        sec['sync']['password_known'] = False
        s = by_rule(run(sec), 'sync.signin')
        self.assertEqual(actions(s[0])['signin']['command'], 'sync.signin')

    def test_publish_pending(self):
        sec = sections()
        sec['sync']['status'].update(zone_publish=True, inventory_up=2, up=3)
        s = by_rule(run(sec), 'sync.publish_pending')
        self.assertEqual(len(s), 1)
        self.assertIn('2 inventory change', s[0]['know'])

    def test_lost(self):
        sec = sections()
        sec['sync']['last_result'] = dict(sync=dict(lost=[dict(mac=CUBE_MAC, text='#44 (A4:…) loses number 44 and tag …: now needs number')]))
        sec['inventory']['rows'] = [inventory_row(cube_id=None, uid=None, status='needs_number')]
        s = by_rule(run(sec), 'sync.lost')
        self.assertEqual(len(s), 1)
        self.assertIn('rename', actions(s[0]))

    def test_waiting_names_holder(self):
        sec = sections()
        sec['sync']['status']['waiting'] = 2
        sec['locks']['.lock'] = True
        s = by_rule(run(sec), 'sync.waiting')[0]
        self.assertIn('Pairing station app', s['know'])
        self.assertTrue(by_rule(run(sec), 'apps.legacy_open'))

    def test_registration_unconfirmed_feedback(self):
        sec = sections(station=station_section(phase='paused', active=dict(mac=CUBE_MAC, cube_id=44),
                                               feedback=dict(kind='error', title='NEOCORE #44 NOT CONFIRMED',
                                                             detail='The tag was read, but the device did not acknowledge.')))
        s = by_rule(run(sec), 'reg.unconfirmed')
        self.assertEqual(len(s), 1)
        self.assertEqual(s[0]['scope'], f'mac:{CUBE_MAC}')
        self.assertEqual(actions(s[0])['retry']['kind'], 'hardware')

    def test_unconfirmed_rows_and_needs_number(self):
        sec = sections(station=station_section())
        live = inventory_row(mac='34:85:18:00:00:12', cube_id=None, uid=None, status='needs_number')
        live['recent'] = True
        sec['inventory']['rows'] = [inventory_row(status='unconfirmed'), live,
                                    inventory_row(mac='34:85:18:00:00:13', cube_id=None, uid=None, status='needs_number')]
        out = run(sec)
        self.assertEqual(actions(by_rule(out, 'reg.unconfirmed_rows')[0])['retry']['command'], 'pairing.retry_unconfirmed')
        self.assertEqual(len(by_rule(out, 'number.needs_number')), 1)          # only the one answering discovery
        self.assertEqual(len(by_rule(out, 'number.needs_number_many')), 1)     # the rest, summarised


class OutcomeTests(unittest.TestCase):
    def test_boot_unconfirmed(self):
        d = usb_device(port='/dev/cu.usbmodem9', role='cube', mac=CUBE_MAC, session_kind='cube',
                       fw_status=dict(version='v1.4.1-USB.2', expected='v1.4.1-USB.2', status='current'))
        job = dict(id='j2', kind='cube.flash', state='done', error=None, device=CUBE_MAC, target=CUBE_MAC, finished_at=NOW - 5, title='Flash cube',
                   result=dict(ui_result='boot_unconfirmed', ui_detail='Firmware verified; boot not confirmed. Use Check boot, without reflashing.'),
                   outcome=dict(level='delivered', text='x'))
        s = by_rule(run(sections(devices=[d], jobs=[job])), 'flash.boot_unconfirmed')
        self.assertEqual(len(s), 1)
        self.assertEqual(actions(s[0])['check']['command'], 'cube.check_boot')
        self.assertIn('Do not reflash', s[0]['check'])

    def test_running_job_suspends_actions(self):
        sec = fx.f1_sections()
        sec['jobs'] = [dict(id='j3', kind='zone.db_usb', state='running', device=PLATE_MAC, target=PLATE_MAC, finished_at=None, title='Update')]
        s = by_rule(run(sec), 'tag.known_zone_behind')[0]
        self.assertEqual(s['actions'], [])
        self.assertIn('job is running', s['check'])

    def test_silent_board(self):
        d = usb_device(port='/dev/cu.usbmodem5', role='unknown', mac=None, state='idle', attempts=3)
        s = by_rule(run(sections(devices=[d])), 'zone.silent')
        self.assertEqual(len(s), 1)
        self.assertEqual(actions(s[0])['detect']['kind'], 'hardware')

    def test_foreign_port(self):
        d = usb_device(port='/dev/cu.usbmodem5', role=None, mac=None, state='foreign', error='USB port is owned by another Neocore application')
        sec = sections(devices=[d])
        sec['locks']['.zonedb.lock'] = True
        s = by_rule(run(sec), 'port.owned')[0]
        self.assertIn('Zone Database Manager', s['know'])


class EngineTests(unittest.TestCase):
    def test_pure_and_deterministic(self):
        sec = fx.f1_sections()
        frozen = copy.deepcopy(sec)
        a = run(sec)
        b = run(sec)
        self.assertEqual(a, b)
        self.assertEqual(sec, frozen, 'evaluate must not mutate its input')
        self.assertEqual(run(sec, now=NOW + 1), a)

    def test_ranking(self):
        sec = fx.f1_sections()
        sec['builds']['tools']['esptool_ok'] = False
        out = run(sec)
        severities = [advisor.SEVERITY_RANK[s['severity']] for s in out]
        self.assertEqual(severities, sorted(severities))
        self.assertEqual(out[0]['rule'], 'tools.esptool')

    def test_dismissal_forms(self):
        sec = fx.f1_sections()
        sid = by_rule(run(sec), 'tag.known_zone_behind')[0]['id']
        self.assertFalse(by_rule(run(sec, dismissed=[sid]), 'tag.known_zone_behind'))
        self.assertFalse(by_rule(run(sec, dismissed=[f'tag.known_zone_behind@zone:{PLATE_MAC}']), 'tag.known_zone_behind'))
        self.assertFalse(by_rule(run(sec, dismissed=['tag.known_zone_behind@*']), 'tag.known_zone_behind'))
        self.assertTrue(by_rule(run(sec, dismissed=['tag.known_zone_behind@zone:other']), 'tag.known_zone_behind'))

    def test_section_shape(self):
        out = run(fx.f1_sections())
        sec = advisor.section(out)
        self.assertEqual(set(sec), {'suggestions', 'by_scope', 'counts'})
        self.assertIn(f'zone:{PLATE_MAC}', sec['by_scope'])
        self.assertIn(f'device:{PLATE_MAC}', sec['by_scope'])
        self.assertEqual(sum(sec['counts'].values()), len(out))

    def test_empty_sections(self):
        self.assertEqual(run({}), [])
        self.assertEqual(run(dict(devices=None, inventory=None)), [])

    def test_json_serialisable(self):
        import json
        json.dumps(run(fx.f1_sections()))

    def test_every_action_command_is_registered(self):
        import commands
        rank = dict(safe=0, hardware=1, destructive=2)
        fixtures = [fx.f1_sections(), sections(), sections(station=station_section(reader_ok=False, nfc_ok=False, nfc_i2c_status=5)),
                    sections(station=station_section(channel=6, zones=0, firmware='nct-pairing-1.6-zones'))]
        sec = fx.f1_sections()
        sec['builds']['tools'] = dict(esptool_ok=False, arduino_cli=None, core_ok=False)
        sec['builds']['cube']['error'] = 'Firmware source changed; rebuild before flashing'
        sec['builds']['zones'] = {'PreshowZone': dict(error='No firmware build yet; choose Build firmware')}
        sec['builds']['workstation']['state'] = 'stale'
        fixtures.append(sec)
        seen = set()
        for fixture in fixtures:
            for s in run(fixture):
                for a in s['actions']:
                    seen.add(a['command'])
                    self.assertIn(a['command'], commands.COMMANDS, f'{s["id"]} names unknown command {a["command"]}')
                    self.assertGreaterEqual(rank[a['kind']], rank[commands.COMMANDS[a['command']]['kind']],
                                            f'{s["id"]}#{a["id"]} is weaker than the registry kind')
                    self.assertEqual(a['needs_confirm'], a['kind'] == 'destructive')
        for name in advisor.ALL_COMMANDS:
            self.assertIn(name, commands.COMMANDS, name)


if __name__ == '__main__':
    unittest.main()
