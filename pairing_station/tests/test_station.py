import csv
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from database import Database
from controller import Controller

NEW='02:00:00:00:00:01'
NEW2='02:00:00:00:00:02'
UID='04:01:02:03:04:05:06'

class StationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.path=Path(self.temp.name)/'devices.sqlite3'
        self.db=Database(self.path)
        self.sent=[]
        self.now=100
        self.c=Controller(self.db,self.sent.append,lambda _:None,lambda:self.now)
        self.c.event(dict(event='hello',id=self.c.emit('hello'),radio_ok=True,nfc_ok=True,protocol=1,channel=2))
    def tearDown(self):
        self.db.close()
        self.temp.cleanup()
    def reply(self,ack=True):
        self.c.event(dict(event='registered',id=self.c.request,mac=self.c.active['mac'],cube_id=self.c.active['cube_id'],acknowledged=ack))
    def test_known_physical_numbers_are_reserved_without_fake_devices(self):
        self.db.clear_unseen_numbers()
        with self.db.conn:
            for number in range(33,44):
                if number not in (39,43):
                    self.db.conn.execute('INSERT INTO reserved_numbers VALUES (?,?)',(number,'test occupied'))
        self.assertEqual(self.db.suggested_number(),44)
        self.c.event(dict(event='device',mac=NEW))
        self.db.rename(NEW,39)  # Explicit identification of the real labelled module is allowed.
        self.assertEqual(self.db.get(NEW)['cube_id'],39)
        self.db.close(); self.db=Database(self.path)
        self.assertEqual({2,22,39,43} & {r[0] for r in self.db.conn.execute('SELECT cube_id FROM reserved_numbers')},{2,22,39,43})
        self.assertEqual(self.db.suggested_number(),44)

    def test_suggested_number_is_free_above_32_and_reuses_gaps(self):
        self.db.clear_unseen_numbers()
        self.assertEqual(self.db.suggested_number(),33)
        self.db.reserve(NEW); self.db.rename(NEW,33)
        self.db.reserve(NEW2); self.db.rename(NEW2,35)
        self.assertEqual(self.db.suggested_number(),34)
        self.db.rename(NEW,36)
        self.assertEqual(self.db.suggested_number(),33)

    def test_original_number_remains_visible_without_reserving_it(self):
        from dashboard import inventory
        from types import SimpleNamespace
        original=self.db.rows()[0]
        self.db.clear_unseen_numbers()
        app=SimpleNamespace(controller=self.c, db=self.db)
        row=next(r for r in inventory(app) if r['mac']==original['mac'])
        self.assertEqual(row['original_number'], 1)
        self.assertIsNone(row['cube_id'])
        self.assertFalse(row['nfc_seen'])
        self.db.reserve(NEW)
        self.db.rename(NEW, 1)
        self.db.mark_nfc_seen(original['mac'], original['uid'])
        row=next(r for r in inventory(app) if r['mac']==original['mac'])
        self.assertTrue(row['nfc_seen'])
        self.assertEqual(row['original_number'], 1)
        self.assertIsNone(row['cube_id'])

    def test_clear_numbers_preserves_scans_and_does_not_reassign_on_discovery(self):
        keep, clear = self.db.rows()[:2]
        self.db.mark_nfc_seen(keep['mac'], keep['uid'])
        self.assertEqual(self.db.clear_unseen_numbers(), 31)
        self.assertEqual(self.db.get(keep['mac'])['cube_id'], keep['cube_id'])
        self.assertIsNone(self.db.get(clear['mac'])['cube_id'])
        self.assertEqual(self.db.get(clear['mac'])['uid'], clear['uid'])
        for mac in (clear['mac'], NEW):
            self.c.event(dict(event='device', mac=mac))
            self.assertIsNone(self.db.get(mac)['cube_id'])
        with self.assertRaises(ValueError): self.c.transmit([self.db.get(clear['mac'])])
        self.c.rename(NEW, clear['cube_id'])
        self.assertEqual(self.db.get(NEW)['cube_id'], clear['cube_id'])
        self.db.clear_unseen_numbers(also_clear=[keep['mac']])
        self.assertIsNone(self.db.get(keep['mac'])['cube_id'])

    def test_unregister_releases_number_and_tags_but_keeps_role(self):
        cube = self.db.rows()[0]
        self.db.set_role(cube['mac'], 'led')
        previous = self.db.unregister(cube['mac'], 'repurposed')
        self.assertEqual((previous['cube_id'], previous['uid']), (cube['cube_id'], cube['uid']))
        row = self.db.get(cube['mac'])
        self.assertEqual((row['cube_id'], row['uid'], row['pending_uid'], row['status'], row['detail']),
                         (None, None, None, 'needs_number', 'repurposed'))
        self.assertEqual(self.db.roles()[cube['mac']], 'led')
        self.assertIn('unregistered', [r[0] for r in self.db.conn.execute('SELECT action FROM events WHERE mac=?', (cube['mac'],))])
        self.assertIsNone(self.db.unregister(cube['mac'], 'again'))  # nothing left to release
        self.assertIsNone(self.db.unregister(NEW, 'unknown'))
        self.db.rename(cube['mac'], cube['cube_id'])  # the released number is free again
        with (self.path.parent/'devices.csv').open(encoding='utf-8-sig') as stream:
            self.assertEqual(next(r for r in csv.DictReader(stream) if r['mac']==cube['mac'])['uid'], '')

    def test_rename_unregistered_persists_and_rejects_duplicate_numbers(self):
        self.c.event(dict(event='device', mac=NEW))
        self.c.rename(NEW, 80)
        self.assertEqual(self.db.get(NEW)['cube_id'], 80)
        self.assertEqual(self.db.get(NEW)['status'], 'awaiting_tag')
        for invalid in (0, -1, 2**32, 2.5, True, 1):
            with self.assertRaises(ValueError): self.c.rename(NEW, invalid)
        self.assertEqual(self.db.get(NEW)['cube_id'], 80)
        with (self.path.parent/'devices.csv').open(encoding='utf-8-sig') as stream:
            self.assertEqual(next(r for r in csv.DictReader(stream) if r['mac']==NEW)['cube_id'], '80')

    def test_rename_registered_sends_new_id_and_requires_matching_ack(self):
        row=self.db.rows()[0]
        self.c.rename(row['mac'], 90)
        self.assertEqual(self.sent[-1]['cmd'], 'register')
        self.assertEqual(self.sent[-1]['cube_id'], 90)
        self.assertEqual(self.sent[-1]['uid'], row['uid'])
        self.assertEqual(self.db.get(row['mac'])['status'], 'pending')
        self.c.event(dict(event='registered', id=self.c.request, mac=row['mac'], cube_id=row['cube_id'], acknowledged=True))
        self.assertEqual(self.db.get(row['mac'])['status'], 'pending')
        self.reply()
        self.assertEqual(self.db.get(row['mac'])['status'], 'acknowledged')
        self.assertEqual(self.db.get(row['mac'])['cube_id'], 90)

    def test_rename_waits_for_preview_stop_and_offline_rename_needs_sync(self):
        self.c.event(dict(event='device', mac=NEW))
        self.c.preview(NEW)
        self.c.rename(NEW, 80)
        self.assertEqual(self.db.get(NEW)['cube_id'], 33)
        self.c.event(dict(event='stopped', id=self.c.request))
        self.assertEqual(self.db.get(NEW)['cube_id'], 80)
        row=self.db.rows()[0]
        self.c.connected=False
        self.c.rename(row['mac'], 90)
        self.assertEqual(self.db.get(row['mac'])['status'], 'not_transmitted')
        self.assertEqual(self.db.get(row['mac'])['uid'], row['uid'])

    def test_discovery_assigns_stable_ids_without_registering(self):
        c=self.c
        count=len(self.sent)
        for mac in (NEW, NEW2, NEW):
            c.event(dict(event='device', mac=mac))
        first=self.db.get(NEW)
        self.assertEqual(first['cube_id'], 33)
        self.assertEqual(self.db.get(NEW2)['cube_id'], 34)
        self.assertEqual(first['status'], 'awaiting_tag')
        self.assertIsNone(first['uid'])
        self.assertEqual(len(self.sent), count)
        self.db.close()
        self.db=Database(self.path)
        self.assertEqual(self.db.get(NEW)['cube_id'], 33)

    def test_connection_enables_initialized_reader_and_waits_for_confirmation(self):
        c=self.c
        c.event(dict(event='hello', id=c.emit('hello'), radio_ok=True,
                     nfc_ok=True, nfc_polling=False, protocol=1, channel=2))
        self.assertFalse(c.reader_ok)
        request=self.sent[-1]
        self.assertEqual(request['cmd'], 'nfc_poll')
        self.assertTrue(request['enabled'])
        c.event(dict(event='nfc_poll_result', id=request['id'], enabled=True, ready=True))
        self.assertTrue(c.reader_ok)
        self.assertTrue(c.station['nfc_polling'])
        self.assertIn('Select a device', c.message)

    def test_unsolicited_and_duplicate_hello_do_not_start_or_cancel_work(self):
        c=Controller(self.db,self.sent.append,lambda _:None,lambda:self.now)
        token=c.emit('hello')
        c.event(dict(event='hello',id='',radio_ok=True,nfc_ok=True,protocol=1,channel=2))
        self.assertFalse(c.connected)
        c.event(dict(event='hello',id=token,radio_ok=True,nfc_ok=True,protocol=1,channel=2))
        c.transmit([self.db.rows()[0]])
        c.event(dict(event='hello',id=token,radio_ok=True,nfc_ok=True,protocol=1,channel=2))
        self.assertEqual(c.phase,'registering')
    def test_excluded_devices_are_persistent_and_never_targeted(self):
        self.db.set_role(NEW, 'excluded')
        self.c.start_pair()
        self.c.event(dict(event='device', mac=NEW))
        self.assertIsNone(self.c.active)
        self.assertIsNone(self.db.get(NEW))
        self.c.complete('test')
        with self.assertRaises(ValueError): self.c.repair(NEW)
        with self.assertRaises(ValueError): self.c.flash([dict(mac=NEW)])
        with self.assertRaises(ValueError): self.c.transmit([dict(mac=NEW)])
        self.db.close(); self.db=Database(self.path)
        self.assertTrue(self.db.excluded(NEW))

    def test_selected_unregistered_device_can_pair_and_idle_discovery_refreshes(self):
        self.c.repair(NEW)
        self.assertEqual(self.c.active['mac'], NEW)
        self.assertEqual(self.c.phase, 'identifying')
        self.c.event(dict(event='tag', id=self.c.request, uid=UID))
        self.reply()
        self.assertEqual(self.db.get(NEW)['uid'], UID)
        self.c.complete('test')
        self.now += 10
        self.c.tick()
        self.assertEqual(self.sent[-1]['cmd'], 'discover')

    def test_grid_filters_and_led_commands_do_not_claim_measured_state(self):
        from dashboard import inventory, matches, led_state
        from types import SimpleNamespace
        self.c.event(dict(event='device', mac=NEW))
        app=SimpleNamespace(controller=self.c, db=self.db)
        row=next(r for r in inventory(app) if r['mac']==NEW)
        self.assertTrue(matches(row, 'Unregistered', NEW[-5:]))
        self.assertTrue(matches(row, 'Seen recently', ''))
        self.assertFalse(matches(row, 'Registered (ACK)', ''))
        self.assertEqual(led_state(row, True)[0], 'Unknown LEDs')
        self.c.flash([row])
        row=next(r for r in inventory(app) if r['mac']==NEW)
        self.assertEqual(led_state(row, True)[0], 'Flash command')
        self.assertEqual(led_state(row, False)[0], 'Unknown LEDs')
        self.db.set_role(NEW, 'excluded')
        row=next(r for r in inventory(app) if r['mac']==NEW)
        self.assertFalse(matches(row, 'LED candidates', ''))
        self.assertTrue(matches(row, 'All incl. excluded', ''))

    def test_failed_repair_does_not_leave_a_phantom_active_target(self):
        self.db.reserve(NEW)
        self.db.prepare(NEW,UID)
        self.db.set_role(NEW, 'excluded')
        with self.assertRaises(ValueError): self.c.repair(NEW)
        self.assertIsNone(self.c.active)
        self.assertEqual(self.c.mode,'')
        self.c.disconnected('test')
        self.assertFalse(self.c.reader_ok)

    def test_selection_preview_is_one_second_and_coalesces_fast_changes(self):
        self.assertTrue(self.c.preview(NEW))
        self.assertEqual(self.sent[-1]['duration_ms'], 1000)
        first_request=self.c.request
        self.c.preview(NEW2)
        third='02:00:00:00:00:03'
        self.c.preview(third)
        self.c.event(dict(event='flash_done', id=first_request))
        self.assertEqual(self.c.active['mac'], third)
        self.assertEqual(self.sent[-1]['duration_ms'], 1000)
        self.c.event(dict(event='flash_done', id=self.c.request))
        self.assertEqual(self.c.mode, '')
        self.assertIsNone(self.db.get(NEW))  # Preview must not allocate an ID.

    def test_background_flash_gives_way_to_every_operation(self):
        """The console's tag-read flash: lowest priority, never paused or left holding the Controller."""
        self.db.reserve(NEW); self.db.rename(NEW,50); self.db.prepare(NEW,UID)
        row=self.db.get(NEW)
        self.c.notify('success','REGISTERED','kept')
        banner=self.c.feedback
        self.assertTrue(self.c.background_flash(row))
        self.assertEqual((self.c.mode,self.sent[-1]['cmd'],self.sent[-1]['duration_ms']),('reader_flash','identify',2000))
        self.assertIs(self.c.feedback,banner,'the registration banner is not cleared')
        self.assertFalse(self.c.background_flash(row),'one at a time')
        self.assertFalse(self.c.preview(NEW2))
        old=self.c.request
        # Anything real takes over at once: stop first, then its own command.
        self.c.repair(NEW)
        self.assertEqual([m['cmd'] for m in self.sent[-2:]],['stop','identify'])
        self.assertEqual((self.c.mode,self.c.phase,self.sent[-1]['duration_ms']),('repair','identifying',0))
        for late in (dict(event='flash_done',id=old),dict(event='stopped',id=self.sent[-2]['id']),dict(event='tag',id=old,uid=UID)):
            self.c.event(late)
        self.assertEqual((self.c.mode,self.c.phase),('repair','identifying'),'late replies of the flash are ignored')
        self.c.stop(); self.c.event(dict(event='stopped',id=self.c.request))
        for start in (lambda: self.c.transmit([self.db.get(NEW)]),lambda: self.c.flash([row],sequential=True),
                      lambda: self.db.reserve(NEW2) and self.c.rename(NEW2,78),lambda: self.c.start_pair()):
            self.assertTrue(self.c.background_flash(self.db.get(NEW)))
            since=len(self.sent)
            start()
            self.assertEqual(self.sent[since]['cmd'],'stop','the station is stopped before the next command')
            self.assertNotEqual(self.c.mode,'reader_flash')
            if self.c.mode:
                self.c.stop(); self.c.event(dict(event='stopped',id=self.c.request))
        self.assertEqual(self.c.mode,'')
        # flash_done ends it quietly; an error or a missing flash_done never pauses it or drops the link.
        self.c.notify('success','REGISTERED','kept'); banner=self.c.feedback
        self.assertTrue(self.c.background_flash(row))
        self.c.event(dict(event='flash_done',id=self.c.request))
        self.assertEqual((self.c.mode,self.c.active,self.c.connected),('',None,True))
        self.assertTrue(self.c.background_flash(row))
        self.c.event(dict(event='error',id=self.c.request,detail='Radio busy; stop first'))
        self.assertEqual((self.c.mode,self.c.phase,self.c.connected),('','',True))
        self.assertTrue(self.c.background_flash(row))
        self.now+=11
        self.c.tick()
        self.assertEqual((self.c.mode,self.c.connected,self.sent[-1]['cmd']),('',True,'stop'))
        self.assertIs(self.c.feedback,banner)
        self.db.set_role(NEW2,'excluded')
        self.assertFalse(self.c.background_flash(dict(mac=NEW2,cube_id=None)))
        self.c.disconnected('test')
        self.assertFalse(self.c.background_flash(row))

    def test_preview_does_not_interrupt_operations_and_stop_clears_queue(self):
        self.c.repair(NEW)
        request=self.c.request
        self.assertFalse(self.c.preview(NEW2))
        self.assertEqual(self.c.request, request)
        self.c.complete('test')
        self.db.set_role(NEW2, 'excluded')
        self.assertFalse(self.c.preview(NEW2))
        self.c.preview(NEW)
        self.c.preview(self.db.rows()[0]['mac'])
        self.assertFalse(self.c.preview(NEW2))
        self.assertEqual(self.c.batch, [])
        self.c.preview(self.db.rows()[0]['mac'])
        self.c.stop()
        self.c.event(dict(event='stopped', id=self.c.request))
        self.assertEqual(self.c.mode, '')
        self.assertEqual(self.c.batch, [])
        self.c.disconnected('test')
        self.assertFalse(self.c.preview(NEW))

    def test_guided_registration_takes_over_preview_and_waits_for_ack(self):
        self.c.preview(NEW)
        self.c.preview(NEW2)
        old_request=self.c.request
        self.c.repair(NEW)
        self.assertEqual(self.c.phase,'stopping')
        self.c.event(dict(event='flash_done',id=old_request))
        self.assertEqual(self.c.phase,'stopping')
        self.c.event(dict(event='stopped',id=self.c.request))
        self.assertEqual(self.c.mode,'repair')
        self.assertEqual(self.c.active['mac'],NEW)
        self.assertEqual(self.sent[-1]['duration_ms'],0)
        self.assertEqual(self.c.batch,[])
        self.c.event(dict(event='tag_state',present=False))
        self.assertIn('READY TO SCAN',self.c.feedback['title'])
        self.c.event(dict(event='tag',id=self.c.request,uid=UID))
        self.assertEqual(self.c.feedback['kind'],'sending')
        self.assertIsNone(self.db.get(NEW)['uid'])
        self.reply()
        self.assertEqual(self.c.feedback['kind'],'success')
        self.assertEqual(self.db.get(NEW)['uid'],UID)
        self.assertEqual(self.c.mode,'')

    def test_guided_failure_and_cancel_never_report_success(self):
        self.c.repair(NEW)
        self.c.event(dict(event='tag',id=self.c.request,uid=UID))
        self.reply(ack=False)
        self.assertEqual(self.c.feedback['kind'],'error')
        self.assertEqual(self.c.phase,'paused')
        self.assertIsNone(self.db.get(NEW)['uid'])
        self.c.stop()
        self.assertNotEqual(self.c.feedback['kind'],'success')
        self.c.event(dict(event='stopped',id=self.c.request))
        self.assertEqual(self.c.mode,'')

    def test_cancel_preview_handoff_does_not_start_registration(self):
        self.c.preview(NEW)
        self.c.repair(NEW)
        first_stop=self.c.request
        self.c.stop()
        self.c.event(dict(event='stopped',id=first_stop))
        self.c.event(dict(event='stopped',id=self.c.request))
        self.assertEqual(self.c.mode,'')
        self.assertIsNone(self.db.get(NEW))
        self.assertEqual(self.c.feedback['title'],'REGISTRATION STOPPED')

    def test_live_reader_diagnostic_overrides_cached_ready_flag(self):
        self.c.event(dict(event='nfc_status',firmware_now=0,i2c_status=5))
        self.assertFalse(self.c.reader_ok)
        self.assertEqual(self.c.feedback['kind'],'error')
        with self.assertRaises(ValueError): self.c.repair(NEW)
        self.c.event(dict(event='nfc_status',firmware_now=1,i2c_status=0,nfc_polling=False))
        self.assertFalse(self.c.reader_ok)
        self.c.event(dict(event='nfc_poll_result',ready=True,enabled=True))
        self.assertTrue(self.c.reader_ok)

    def test_originals_match_source_and_import_once(self):
        source=(ROOT.parent/'mainshow_enter/mainshow_enter.ino').read_text(encoding='utf-8')
        expected=[]
        for ident,uid,mac in re.findall(r'\{(\d+),7,\{([^}]+)\},\{([^}]+)\}\}',source):
            fmt=lambda s: ':'.join(f'{int(x,16):02X}' for x in s.split(','))
            expected.append(dict(cube_id=int(ident),uid=fmt(uid),mac=fmt(mac)))
        self.assertEqual(expected,self.db.originals())
        self.assertEqual(len(self.db.rows()),32)
        self.assertTrue(all(r['status']=='not_transmitted' for r in self.db.rows()))
        self.db.close();self.db=Database(self.path)
        self.assertEqual(len(self.db.rows()),32)
    def test_bulk_32_and_offline_continuation(self):
        self.c.transmit(self.db.original_batch())
        for index in range(32):
            self.assertEqual(self.c.active['cube_id'],index+1)
            self.reply(index!=3)
        self.assertEqual(self.c.mode,'')
        self.assertEqual(sum(r['status']=='acknowledged' for r in self.db.rows()),31)
        self.assertEqual(len(self.db.original_batch()),32) # same-UID retries remain safe
        failed=[r for r in self.db.rows() if r['status']=='unconfirmed']
        self.c.transmit(failed);self.reply()
        self.assertEqual(self.db.get(failed[0]['mac'])['status'],'acknowledged')
    def test_pair_stale_scan_and_removal_gate(self):
        self.c.start_pair()
        self.c.event(dict(event='device',mac=self.db.rows()[0]['mac']))
        self.assertEqual(self.c.phase,'waiting')
        self.c.event(dict(event='device',mac=NEW))
        token=self.c.request
        self.assertEqual(self.c.active['cube_id'],33)
        self.c.event(dict(event='device',mac=NEW2))
        self.c.event(dict(event='tag',id='stale',uid=UID))
        self.assertEqual(self.c.phase,'identifying')
        self.c.event(dict(event='tag_state',present=True))
        self.c.event(dict(event='tag',id=token,uid=UID))
        self.assertEqual(self.c.phase,'registering')
        self.reply()
        self.assertEqual(self.c.phase,'removal')
        self.c.event(dict(event='tag_state',present=False))
        self.assertEqual(self.c.active['mac'],NEW2)
    def test_scanned_tag_transfers_from_previous_device(self):
        selected, previous = self.db.rows()[:2]
        self.c.repair(selected['mac'])
        self.c.event(dict(event='tag', id=self.c.request, uid=previous['uid']))
        self.assertEqual(self.c.phase, 'registering')
        self.assertIsNone(self.db.get(previous['mac'])['uid'])
        self.assertEqual(self.db.get(previous['mac'])['status'], 'awaiting_tag')
        self.assertEqual(self.db.get(selected['mac'])['uid'], selected['uid'])
        self.assertIn('transferred from #2', self.c.feedback['detail'])
        self.reply()
        self.assertEqual(self.db.get(selected['mac'])['uid'], previous['uid'])
        self.assertEqual(self.db.get(selected['mac'])['cube_id'], 1)
        with self.assertRaises(ValueError): self.db.original_batch()

    def test_transfer_pending_reservation_survives_failed_registration(self):
        old = self.db.rows()[0]
        self.db.prepare(old['mac'], UID)
        self.db.reserve(NEW)
        self.c.repair(NEW)
        self.c.event(dict(event='tag', id=self.c.request, uid=UID))
        self.assertEqual(self.db.get(old['mac'])['uid'], old['uid'])
        self.assertIsNone(self.db.get(old['mac'])['pending_uid'])
        self.reply(ack=False)
        self.db.close(); self.db=Database(self.path)
        self.assertEqual(self.db.get(NEW)['pending_uid'], UID)
        self.assertEqual(self.db.get(NEW)['status'], 'unconfirmed')
        self.db.reserve(NEW2)
        with self.assertRaises(ValueError): self.db.prepare(NEW2, UID)

    def test_pending_survives_disconnect_restart(self):
        self.db.reserve(NEW)
        self.db.prepare(NEW,UID)
        self.db.close();self.db=Database(self.path)
        row=self.db.get(NEW)
        self.assertEqual(row['status'],'unconfirmed')
        self.assertEqual(row['pending_uid'],UID)
        self.assertEqual(row['cube_id'],33)
        self.db.reserve(NEW2)
        with self.assertRaises(ValueError):self.db.prepare(NEW2,UID)
    def test_wrong_ack_and_stop_late_result(self):
        self.c.transmit([self.db.rows()[0]])
        original_id=self.c.request
        row=self.c.active.copy()
        self.c.event(dict(event='registered',id=original_id,mac=NEW,cube_id=1,acknowledged=True))
        self.assertEqual(self.c.phase,'registering')
        self.c.stop()
        self.c.event(dict(event='registered',id=original_id,mac=row['mac'],cube_id=1,acknowledged=True))
        self.assertEqual(self.db.get(row['mac'])['status'],'unconfirmed')
        self.c.event(dict(event='stopped',id=self.c.request))
        self.assertEqual(self.c.mode,'')
    def test_flashing_sequential_and_busy(self):
        self.c.flash(self.db.rows()[:2],sequential=True)
        with self.assertRaises(ValueError):self.c.start_pair()
        self.assertEqual(self.sent[-1]['duration_ms'],2000)
        self.c.event(dict(event='flash_done',id=self.c.request))
        self.assertEqual(self.c.active['cube_id'],2)
        self.c.event(dict(event='flash_done',id=self.c.request))
        self.assertEqual(self.c.mode,'')
    def test_timeout_and_no_reader(self):
        self.c.transmit([self.db.rows()[0]])
        self.now+=16;self.c.tick()
        self.assertFalse(self.c.connected)
        self.assertEqual(self.db.rows()[0]['status'],'unconfirmed')
        self.c.connected=True;self.c.reader_ok=False
        with self.assertRaises(ValueError):self.c.start_pair()
        self.c.transmit([self.db.rows()[0]]) # bulk doesn't require PN532
    def test_exports_and_unique_ids(self):
        self.db.reserve(NEW);self.db.prepare(NEW,UID)
        self.db.export_header(Path(self.temp.name)/'table.h')
        header=(Path(self.temp.name)/'table.h').read_text(encoding='utf-8')
        self.assertNotIn('{33,',header)
        with (Path(self.temp.name)/'devices.csv').open(encoding='utf-8-sig') as file:
            rows=list(csv.DictReader(file))
        self.assertEqual(len(rows),33)
        self.assertEqual(rows[-1]['pending_uid'],UID)
        self.db.result(NEW,True,'ACK')
        self.db.export_header(Path(self.temp.name)/'table.h')
        self.assertIn('{33,7,',(Path(self.temp.name)/'table.h').read_text(encoding='utf-8'))

if __name__=='__main__': unittest.main()
