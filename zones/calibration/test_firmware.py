import unittest
from unittest.mock import patch
import firmware

RADIOS = [dict(mac='AA:00:00:00:00:01', name='Pool Radio 1', point_id=1, firmware='pool-3.0.0', last_seen=''),
          dict(mac='AA:00:00:00:00:03', name='Pool Radio 3', point_id=3, firmware='pool-3.0.0', last_seen=''),
          dict(mac='AA:00:00:00:00:04', name='Pool Radio 3', point_id=3, firmware='pool-3.0.0', last_seen='')]


class RadioIdChecks(unittest.TestCase):
    def test_conflicts_ignore_the_board_being_edited(self):
        # Re-assigning a board to the id it already has is not a clash with itself.
        self.assertEqual(firmware.radio_id_conflicts('AA:00:00:00:00:01', 1, RADIOS), [])
        self.assertEqual(firmware.radio_id_conflicts('aa:00:00:00:00:01', 1, RADIOS), [])
        # Two other boards already sit on 3.
        self.assertEqual(len(firmware.radio_id_conflicts('AA:00:00:00:00:09', 3, RADIOS)), 2)
        # And one of that pair still clashes with the other.
        self.assertEqual(len(firmware.radio_id_conflicts('AA:00:00:00:00:03', 3, RADIOS)), 1)

    def test_suggestion_is_the_lowest_free_id(self):
        self.assertEqual(firmware.suggest_radio_id('AA:00:00:00:00:09', RADIOS), 2)
        # A board keeps its own id if nothing else uses it.
        self.assertEqual(firmware.suggest_radio_id('AA:00:00:00:00:01', RADIOS), 1)
        full = [dict(mac=f'BB:00:00:00:00:0{p}', name='', point_id=p, firmware='', last_seen='')
                for p in firmware.POOL_POINTS]
        self.assertIsNone(firmware.suggest_radio_id('AA:00:00:00:00:09', full))

    def test_out_of_range_ids_are_refused_before_anything_is_written(self):
        for bad in (0, 7, -1, 'x'):
            with self.assertRaises(RuntimeError):
                firmware.assign_radio_id('fake', bad, lambda *_: None)

    def test_reassigning_the_same_id_is_a_no_op(self):
        report = dict(firmware='pool-3.0.0', zone_type=3, mac='AA:00:00:00:00:01', point_id=4, name='Pool Radio 4')
        with patch.object(firmware, 'ports', return_value=[dict(port='fake', candidate=True, key='k')]), \
             patch.object(firmware, 'PortLock'), \
             patch.object(firmware, 'snapshot', return_value=(report, None)), \
             patch.object(firmware, 'FlashRunner'), \
             patch.object(firmware.zone_build, 'parse_partitions',
                          return_value={n: dict(offset=0, size=0x1000) for n in ('nvs', 'zcfg', 'zdb_a', 'zdb_b')}):
            result = firmware.assign_radio_id('fake', 4, lambda *_: None)
        self.assertTrue(result['skipped'])

    def test_a_clash_refuses_to_write_unless_overridden(self):
        report = dict(firmware='pool-3.0.0', zone_type=3, mac='AA:00:00:00:00:09', point_id=5, name='Pool Radio 5')
        parts = {n: dict(offset=0, size=0x1000) for n in ('nvs', 'zcfg', 'zdb_a', 'zdb_b')}
        with patch.object(firmware, 'ports', return_value=[dict(port='fake', candidate=True, key='k')]), \
             patch.object(firmware, 'PortLock'), \
             patch.object(firmware, 'snapshot', return_value=(report, None)), \
             patch.object(firmware, 'FlashRunner'), \
             patch.object(firmware, 'pool_radios', return_value=RADIOS), \
             patch.object(firmware.zone_build, 'parse_partitions', return_value=parts):
            with self.assertRaises(RuntimeError) as caught:
                firmware.assign_radio_id('fake', 3, lambda *_: None)
        # The message must name the board in the way, or the operator cannot act on it.
        self.assertIn('AA:00:00:00:00:03', str(caught.exception))

    def test_written_image_keeps_the_parameters_and_sets_the_new_identity(self):
        # The zcfg sector carries the legacy calibration endpoints alongside the identity;
        # rewriting the id must not discard them.
        z = firmware.zonedb
        image = z.zcfg_image(3, 4, 'Pool Radio 4', [3830, 430], rx_gain=38)
        self.assertEqual(z.parse_params(image), [3830, 430])
        rewritten = z.zcfg_image(3, 5, 'Pool Radio 5', z.parse_params(image), z.parse_config(image)['rx_gain'])
        self.assertEqual(z.parse_config(rewritten), dict(zone_type=3, point_id=5, name='Pool Radio 5', rx_gain=38))
        self.assertEqual(z.parse_params(rewritten), [3830, 430])


class FirmwareChecks(unittest.TestCase):
    def test_database_sync_uses_inactive_slot_and_preserves_active(self):
        z=firmware.zonedb
        records=[(1,b'\x01',bytes.fromhex('021122334455'))]
        old=z.slot_image(records,1,5)
        backup=bytearray(b'\xff'*0x400000)
        backup[0x211000:0x211000+len(old)]=old
        pub=z.Publication(2,records+[(2,b'\x02',bytes.fromhex('021122334466'))])
        offset,image=firmware.database_plan(backup,pub)
        self.assertEqual(offset,0x219000)
        parsed=z.parse_slot(image)
        self.assertEqual((parsed['version'],parsed['generation'],parsed['count']),(2,6,2))
        self.assertEqual(bytes(backup[0x211000:0x211000+len(old)]),old)
        backup[offset:offset+0x8000]=image
        self.assertIsNone(firmware.database_plan(backup,pub))
        with self.assertRaises(RuntimeError): firmware.database_plan(backup,z.Publication(1,records))
        # When B is newest, the next database must target A.
        self.assertEqual(firmware.database_plan(backup,z.Publication(3,records))[0],0x211000)
        # Staged header is invalid until the commit-sector write.
        self.assertIsNone(z.parse_slot(b'\xff'*24+image[24:]))

    def test_database_status_compares_crc_not_just_version(self):
        p=firmware.zonedb.Publication(2,[])
        report=dict(db_version=2,db_count=0,db_crc=p.crc)
        self.assertEqual(firmware.database_status(report,p)[0],'current')
        self.assertEqual(firmware.database_status(dict(report,db_crc=12),p)[0],'update')
        self.assertEqual(firmware.database_status(dict(report,db_version=3),p)[0],'ahead')
    def test_legacy_snapshot_allows_missing_calibration_only_before_update(self):
        report=dict(firmware='pool-2.2.0',zone_type=3,mac='02:11:22:33:44:55')
        with patch.object(firmware.serial,'Serial') as serial_open, patch.object(firmware,'parse_report',return_value=report), patch.object(firmware.time,'monotonic',side_effect=[0,0,5]):
            serial_open.return_value.__enter__.return_value.readline.return_value=b'READY\n'
            self.assertEqual(firmware.snapshot('fake',require_calibration=False),(report,None))
        with patch.object(firmware.serial,'Serial') as serial_open, patch.object(firmware,'parse_report',return_value=report), patch.object(firmware.time,'monotonic',side_effect=[0,0,5]):
            serial_open.return_value.__enter__.return_value.readline.return_value=b'READY\n'
            with self.assertRaises(RuntimeError): firmware.snapshot('fake')

    def test_legacy_snapshot_still_requires_identification(self):
        with patch.object(firmware.serial,'Serial') as serial_open, patch.object(firmware,'parse_report',return_value=None), patch.object(firmware.time,'monotonic',side_effect=[0,0,5]):
            serial_open.return_value.__enter__.return_value.readline.return_value=b'READY\n'
            with self.assertRaises(RuntimeError): firmware.snapshot('fake',require_calibration=False)

    def test_calibration_comparison_skipped_only_when_old_response_missing(self):
        after=dict(ticks=[20]*23,anchors=4194305)
        firmware.verify_calibration(None,after)
        firmware.verify_calibration(after,after)
        with self.assertRaises(RuntimeError): firmware.verify_calibration(dict(after,anchors=0),after)

    def test_cached_build_is_reused(self):
        manifest={'version':'pool-test'}
        with patch.object(firmware.zone_build,'load_manifest',return_value=manifest), patch.object(firmware.zone_build,'build') as build:
            self.assertEqual(firmware.ensure_build(None,lambda *_:None),manifest)
            build.assert_not_called()
    def test_stale_build_compiles_once(self):
        manifest={'version':'pool-test'}
        with patch.object(firmware.zone_build,'load_manifest',side_effect=[ValueError('Source changed'),manifest]), patch.object(firmware.zone_build,'build') as build:
            self.assertEqual(firmware.ensure_build(None,lambda *_:None),manifest)
            build.assert_called_once_with('PoolZone',None)
    def test_terminal_codes_are_removed(self):
        self.assertEqual(firmware.clean_output('\x1b[31mError: failed\x1b[0m\r'), 'Error: failed')
        self.assertEqual(firmware.clean_output('Progress \x00 50%'), 'Progress  50%')
    def test_database_only_reports_the_running_firmware_not_the_build(self):
        # A database-only update leaves the application alone, so the result must not
        # claim the newly built version was installed.
        import inspect
        source = inspect.getsource(firmware.flash)
        self.assertIn("before['firmware'] if database_only else manifest['version']", source)

    def test_database_only_does_not_demand_calibration_from_legacy_firmware(self):
        # After a database-only update the board still runs its original firmware; a
        # legacy board never answers CAL GET, and that must not fail a successful update.
        import inspect
        source = inspect.getsource(firmware.flash)
        self.assertIn('require_calibration=True if not database_only else calibration is not None', source)

    def test_record_zone_status_writes_the_shared_registry(self):
        import sqlite3, tempfile
        from pathlib import Path
        report = dict(mac='02:11:22:33:44:55', name='Pool Radio 4', zone_type=3, point_id=4,
                      firmware='pool-2.8.0', db_version=2, db_count=32, db_crc=7, channel=2)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'devices.sqlite3'
            with patch.object(firmware, 'DEFAULT_DATABASE', path):
                db = firmware.Database(path, recover_pending=False)
                try:
                    self.assertEqual(firmware.record_zone_status(report, detail='tuning saved: exit=0.45'),
                                     report['mac'])
                finally:
                    db.close()
                with sqlite3.connect(path) as check:
                    rows = check.execute('SELECT mac, firmware, source, detail FROM zones').fetchall()
                check.close()
        self.assertEqual(rows[0][0], report['mac'])
        self.assertEqual(rows[0][1], 'pool-2.8.0')
        self.assertEqual(rows[0][2], 'poolzone-calibration')
        self.assertIn('exit=0.45', rows[0][3])

    def test_record_zone_status_refuses_a_report_without_a_mac(self):
        with self.assertRaises(RuntimeError): firmware.record_zone_status(dict(firmware='pool-2.8.0'))

    def test_identity_refuses_non_pool_and_swapped_board(self):
        report=dict(firmware='pool-2.7.0',zone_type=3,mac='02:11:22:33:44:55')
        firmware.check_identity(report,report['mac'])
        with self.assertRaises(RuntimeError): firmware.check_identity(report,'02:11:22:33:44:66')
        with self.assertRaises(RuntimeError): firmware.check_identity(dict(report,zone_type=1),report['mac'])
        with self.assertRaises(RuntimeError): firmware.check_identity(dict(report,firmware='neocube-1'),report['mac'])
    def test_layout_refuses_truncated_or_changed_partitions(self):
        backup=bytearray(0x400000); backup[0x8000:0x8003]=b'ABC'
        firmware.check_layout(backup,b'ABC')
        with self.assertRaises(RuntimeError): firmware.check_layout(backup,b'ABD')
        with self.assertRaises(RuntimeError): firmware.check_layout(backup[:-1],b'ABC')
    @patch.object(firmware.zone_build,'source_hash',return_value='abc')
    @patch.object(firmware.zone_build,'firmware_version',return_value='pool-2.7.0')
    def test_status_requires_version_and_exact_source_fingerprint(self,*_):
        report=dict(firmware='pool-2.7.0',zone_type=3)
        self.assertEqual(firmware.status(report,dict(build_id='habc'))[0],'current')
        self.assertEqual(firmware.status(report,dict(build_id='hdef'))[0],'update')
        self.assertEqual(firmware.status(report,{})[0],'update')
        self.assertEqual(firmware.status(dict(report,firmware='pool-2.6.0'),dict(build_id='habc'))[0],'update')
        self.assertEqual(firmware.status(dict(report,zone_type=1),{})[0],'unsupported')
        self.assertEqual(firmware.status(None,{})[0],'unknown')


class DatabaseUpdaterFlow(unittest.TestCase):
    def test_database_only_update_keeps_app_nvs_identity_and_old_slot(self):
        import contextlib
        import tempfile
        from pathlib import Path
        from unittest.mock import MagicMock
        z=firmware.zonedb
        rows=[(1,b'\x01',bytes.fromhex('021122334455'))]
        target=z.Publication(2,rows+[(2,b'\x02',bytes.fromhex('021122334466'))])
        memory=bytearray(b'\xff'*0x400000)
        old=z.slot_image(rows,1,3)
        memory[0x211000:0x211000+len(old)]=old
        table=b'example compatible table'
        memory[0x8000:0x8000+len(table)]=table
        app=b'existing application'; memory[0x10000:0x10000+len(app)]=app
        original=bytes(memory); writes=[]
        report=dict(firmware='pool-test',mac='02:11:22:33:44:55',channel=2,zone_type=3,point_id=1,name='Pool 1',db_version=1,db_count=1,db_crc=z.crc32(z.pack_records(rows)))
        cal=dict(build_id='habc',ticks=list(range(23)),anchors=4194305)
        device=dict(port='/mock',key='same',candidate=True,native_usb=True)
        class FakeRunner:
            def __init__(self,*args): pass
            def line(self,*args): pass
            def __call__(self,args,timeout=0):
                for command in ('read-mac','read-flash','write-flash','verify-flash'):
                    if command in args: break
                index=args.index(command)
                parts=args[index+1:]
                if command=='read-mac': return 'MAC: '+report['mac']
                offset=int(parts[0],0)
                if command=='read-flash': Path(parts[2]).write_bytes(memory[offset:offset+int(parts[1],0)])
                else:
                    data=Path(parts[1]).read_bytes()
                    if command=='write-flash':
                        writes.append(offset); memory[offset:offset+len(data)]=data
                    else: assert bytes(memory[offset:offset+len(data)])==data
                return ''
        with tempfile.TemporaryDirectory() as tmp, contextlib.ExitStack() as stack:
            folder=Path(tmp)
            (folder/'PoolZone.ino.bin').write_bytes(app)
            (folder/'PoolZone.ino.partitions.bin').write_bytes(table)
            segments=[dict(file=name,offset=offset,size=len(data),sha256=firmware.zone_build.digest(folder/name)) for name,offset,data in [('PoolZone.ino.bin',0x10000,app),('PoolZone.ino.partitions.bin',0x8000,table)]]
            manifest=dict(version='pool-test',source_hash='abc',segments=segments)
            overrides=dict(__file__=str(folder/'firmware.py'),FlashRunner=FakeRunner,ports=lambda:[device],PortLock=lambda _:contextlib.nullcontext(),snapshot=MagicMock(return_value=(report,cal)),status=lambda *_:('current','current'),local_database=lambda **_:target,ensure_build=lambda *_:manifest,Database=MagicMock(),ZoneStore=MagicMock())
            for name,value in overrides.items(): stack.enter_context(patch.object(firmware,name,value))
            stack.enter_context(patch.object(firmware.zone_build,'build_dir',return_value=folder))
            stack.enter_context(patch.object(firmware.ZoneFlasher,'boot_report',return_value=dict(report,db_version=2,db_count=target.count,db_crc=target.crc)))
            result=firmware.flash('/mock',lambda *_:None)
            self.assertEqual(result['db_version'],2)
            self.assertEqual(writes,[0x219000,0x219000])
            self.assertEqual(bytes(memory[:0x219000]),original[:0x219000])
            self.assertEqual(z.parse_slot(memory[0x219000:0x221000])['records'],target.records)

if __name__=='__main__': unittest.main()
