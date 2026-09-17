import unittest
from unittest.mock import patch
import firmware

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
