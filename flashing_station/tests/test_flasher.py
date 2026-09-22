import concurrent.futures
import json
import os
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from core import Store, Scheduler, PortLock, load_manifest, ROOT, digest
from backend import validate_partition, Flasher, Runner, tool_command

MAC='02:00:00:00:00:AB'
class DatabaseTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.path=Path(self.temp.name)/'devices.sqlite3';self.db=Store(self.path)
    def tearDown(self):self.db.close();self.temp.cleanup()
    def test_concurrent_allocations_and_mapping_preservation(self):
        self.db.reserve(MAC);self.db.prepare(MAC,'01:02:03:04')
        def allocate(i):
            db=Store(self.path)
            try:return db.reserve(f'02:00:00:01:00:{i:02X}',source='usb_flash')['cube_id']
            finally:db.close()
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:ids=list(pool.map(allocate,range(12)))
        self.assertEqual(len(set(ids)),12)
        self.assertEqual(self.db.get(MAC)['status'],'pending')
        self.assertEqual(self.db.get(MAC)['pending_uid'],'01:02:03:04')
        self.assertIsNone(self.db.get('02:00:00:01:00:00')['uid'])
    def test_flash_status_independent_and_success_dedup(self):
        row=self.db.rows()[0];before=dict(row)
        self.db.start('attempt','port',dict(version='v',build_hash='h'),'log')
        self.db.update_run('attempt',mac=row['mac'],result='success')
        self.assertTrue(self.db.seen(row['mac'],'h'));self.assertFalse(self.db.seen(row['mac'],'other'))
        self.assertEqual(self.db.reserve(row['mac']),before)
        self.assertTrue(self.db.protected('3C:0F:02:AD:83:24'))
        self.db.set_role(MAC,'excluded');self.assertTrue(self.db.protected(MAC))
    def test_interrupted_history_does_not_recover_pairing(self):
        self.db.reserve(MAC);self.db.prepare(MAC,'01:02:03:04')
        self.db.start('attempt','port',dict(version='v',build_hash='h'),'log');self.db.recover()
        self.assertEqual(self.db.history()[0]['result'],'interrupted')
        self.assertEqual(self.db.get(MAC)['status'],'pending')

class PolicyTests(unittest.TestCase):
    def test_dependency_error_cannot_be_mistaken_for_success(self):
        with self.assertRaisesRegex(RuntimeError,'Python dependencies'):
            Runner(lambda *_:None)([sys.executable,'-c',"print('No module named esptool')"])
    def test_tool_entry_loads_without_automatic_site_initialization(self):
        command=tool_command();command.insert(1,'-S')
        output=Runner(lambda *_:None)(command+['version'])
        self.assertIn('5.3.1',output)

    def test_auto_requires_arm_and_connection_rearm(self):
        s=Scheduler();p=dict(port='a',key='usb1',candidate=True)
        s.scan([p]);self.assertIsNone(s.next());s.armed=True;self.assertEqual(s.next(),p)
        s.mark(p);s.scan([dict(p,port='b')]);self.assertIsNone(s.next())
        with patch('core.time.monotonic',return_value=1):s.scan([],busy=True)
        with patch('core.time.monotonic',return_value=2):s.scan([])
        with patch('core.time.monotonic',return_value=5):s.scan([])
        s.scan([p]);self.assertEqual(s.next(),p)
    def test_shared_port_lock(self):
        # One lock per physical port, however it is spelled: macOS lists cu./tty. twins, Windows ignores case.
        port,alias=('COM250','\\\\.\\com250') if os.name=='nt' else ('/dev/cu.test-neocore','/dev/tty.test-neocore')
        with PortLock(port):
            with self.assertRaises(RuntimeError):PortLock(alias)
        with PortLock(port):pass
    def test_partition_preservation_gate(self):
        self.assertEqual(validate_partition(b'\xff'*4096),'Blank flash')
        def table(offset):return struct.pack('<HBBII16sI',0x50aa,1,2,offset,0x5000,b'nvs',0)+b'\xff'*32
        self.assertIn('Compatible',validate_partition(table(0x9000)))
        with self.assertRaises(ValueError):validate_partition(table(0x10000))
        with self.assertRaises(ValueError):validate_partition(b'\0'*4096)
    def test_firmware_has_no_upload_service_and_has_boot_query(self):
        source=(ROOT/'firmware/neocore_usb/neocore_usb.ino').read_text(encoding='utf-8')
        for token in ['ArduinoOTA','WiFi.begin(', 'OTA_PASSWORD','startTemporaryOTA']:self.assertNotIn(token,source)
        self.assertIn('esp_wifi_set_channel(2, WIFI_SECOND_CHAN_NONE)',source)
        self.assertIn("Serial.read() == '?'",source)
        self.assertIn('MSG_RESERVED_5      = 5',source)
    def test_artifacts_valid(self):
        m=load_manifest();self.assertEqual(m['version'],'v1.7.0-USB.1')
        for s in m['segments']:
            self.assertFalse(s['offset'] < 0xe000 and s['offset']+s['size']>0x9000)

class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.path=self.root/'db.sqlite3'
        self.port=dict(port='fake',key='fake');self.events=[];self.fail_write=False;self.mac=MAC;self.size='4MB';self.calls=[];self.native=False
        (self.root/'build').mkdir();(self.root/'build/app.bin').write_bytes(b'firmware')
        self.manifest=dict(version='v1.4.1-USB',build_hash='h',segments=[dict(offset=0x10000,file='app.bin',sha256=digest(self.root/'build/app.bin'))])
    def tearDown(self):self.tmp.cleanup()
    def run_fake(self,args,timeout=90):
        args=list(map(str,args));self.calls.append(args)
        if args[-1]=='version':return 'esptool v5.3.1'
        if 'flash-id' in args:return f'MAC: {self.mac}\nDetected flash size: {self.size}'+('\nUSB mode: USB-Serial/JTAG' if self.native else '')
        if 'read-flash' in args:
            Path(args[-1]).write_bytes(b'\xff'*4096+b'N'*0x5000 if args[-3]=='0x8000' else b'N'*0x5000)
        if 'write-flash' in args and self.fail_write:raise RuntimeError('Disconnected while writing')
        return 'verified'
    def execute(self,boot=True,manual=False):
        with patch('backend.ROOT',self.root),patch('backend.Runner.__call__',side_effect=self.run_fake),patch.object(Flasher,'boot',return_value=boot),patch('backend.ports',return_value=[self.port]):
            return Flasher(self.path,lambda *e:self.events.append(e)).execute(self.port,self.manifest,manual)
    def test_success_boot_and_duplicate_skip(self):
        result=self.execute();self.assertEqual(result['ui_result'],'success')
        self.assertEqual(len(self.calls),5)
        self.assertTrue(all(c[1]=='-u' and c[2].endswith('esptool_entry.py') for c in self.calls))
        self.assertEqual(self.calls[-1][self.calls[-1].index('--after')+1],'hard-reset')
        self.assertEqual(self.calls[2][self.calls[2].index('--before')+1],'no-reset')
        result=self.execute();self.assertEqual(result['ui_result'],'skipped')
        self.assertEqual(sum('write-flash' in c for c in self.calls),1)
        self.execute(manual=True);self.assertEqual(sum('write-flash' in c for c in self.calls),2)
    def test_native_boot_query_keeps_control_lines_released(self):
        port=dict(self.port,native_usb=True)
        conn=MagicMock();conn.__enter__.return_value=conn
        conn.read.return_value=f'FW: v1.4.1-USB\nCube MAC: {MAC}\nESP-NOW CHANNEL: 2\nCube READY\n'.encode()
        opened=[];conn.open.side_effect=lambda:opened.append((conn.dtr,conn.rts))
        with patch('backend.ports',return_value=[port]),patch('backend.serial.Serial',return_value=conn):
            result=Flasher(self.path,lambda *_:None).boot(port,MAC,'v1.4.1-USB',MagicMock())
        self.assertTrue(result);self.assertEqual(opened,[(False,False)])
        conn.write.assert_called_with(b'?')
    def test_native_usb_uses_watchdog_reset(self):
        self.native=True
        self.assertEqual(self.execute()['ui_result'],'success')
        self.assertEqual(self.calls[-1][self.calls[-1].index('--after')+1],'watchdog-reset')
    def test_boot_unconfirmed_is_not_success(self):
        self.assertEqual(self.execute(False)['ui_result'],'boot_unconfirmed')
        db=Store(self.path);self.assertFalse(db.seen(MAC,'h'));db.close()
    def test_disconnect_never_reports_success(self):
        self.fail_write=True;self.assertEqual(self.execute()['ui_result'],'failed')
    def test_reused_port_with_station_identity_blocks_tool(self):
        station=dict(self.port,serial='3C:0F:02:AD:83:24')
        with patch('backend.ROOT',self.root),patch('backend.ports',return_value=[station]),patch('backend.Runner.__call__') as command:
            command.return_value='esptool v5.3.1'
            result=Flasher(self.path,lambda *_:None).execute(self.port,self.manifest)
        self.assertEqual(result['ui_result'],'failed')
        self.assertEqual(command.call_count,1)
        self.assertEqual(command.call_args.args[0][-1],'version')
    def test_station_boot_check_is_blocked_before_port_enumeration(self):
        with patch('backend.ports') as scan:
            with self.assertRaisesRegex(RuntimeError,'Protected registration station'):
                Flasher(self.path,lambda *_:None).boot(dict(self.port,serial='3C:0F:02:AD:83:24'),MAC,'v',None)
            scan.assert_not_called()
    def test_failed_tool_preflight_never_accesses_hardware(self):
        with patch('backend.ROOT',self.root),patch('backend.Runner.__call__',return_value='No module named esptool') as command:
            result=Flasher(self.path,lambda *_:None).execute(self.port,self.manifest)
        self.assertEqual(result['ui_result'],'failed')
        self.assertIn('tool did not start',result['detail'])
        self.assertEqual(command.call_count,1)
        self.assertEqual(command.call_args.args[0][-1],'version')
    def test_checksum_failure_blocks_all_serial_commands(self):
        self.manifest['segments'][0]['sha256']='corrupt'
        self.assertEqual(self.execute()['ui_result'],'failed')
        self.assertEqual(self.calls,[])
    def test_station_usb_identity_never_opens_or_resets_port(self):
        self.port['serial']='3C:0F:02:AD:83:24'
        with patch('backend.PortLock') as lock:
            result=self.execute(manual=True)
        self.assertEqual(result['ui_result'],'failed')
        lock.assert_not_called()
        self.assertEqual(self.calls,[])
    def test_protected_station_and_wrong_flash_never_written(self):
        self.mac='3C:0F:02:AD:83:24';self.assertEqual(self.execute()['ui_result'],'failed')
        self.mac=MAC;self.size='8MB';self.assertEqual(self.execute()['ui_result'],'failed')
        self.assertFalse(any('write-flash' in c for c in self.calls))

class ShowPipelineTests(unittest.TestCase):
    """The show stage: the published show written into the cube's NVS over USB, everything else kept."""
    def setUp(self):
        import zlib
        import nvs
        self.nvs,self.zlib=nvs,zlib
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.path=self.root/'db.sqlite3'
        self.port=dict(port='fake',key='fake');self.calls=[];self.boots=[];self.corrupt_readback=False;self.fail_show_write=False
        (self.root/'build').mkdir();(self.root/'build/app.bin').write_bytes(b'firmware')
        self.manifest=dict(version='v1.7.0-USB.1',build_hash='h',segments=[dict(offset=0x10000,file='app.bin',sha256=digest(self.root/'build/app.bin'))])
        self.image=bytes((i*13+5)%256 for i in range(600))
        self.show=dict(version=7,crc=zlib.crc32(self.image),image=self.image)
        self.flash=self.registered()
    def tearDown(self):self.tmp.cleanup()
    def registered(self,show=None):
        E=self.nvs.Entry
        entries=[E('phy','cal_data',self.nvs.BLOB,bytes(range(256))*7),E('cube','cubeID',self.nvs.U32,34),E('cube','uidLen',self.nvs.U8,7),
                 E('cube','uid',self.nvs.BLOB,bytes.fromhex('04776655443324'))]
        if show:
            version,img=show
            entries+=[E('show','img',self.nvs.BLOB,img),E('show','crc',self.nvs.U32,self.zlib.crc32(img)),E('show','ver',self.nvs.U32,version)]
        return self.nvs.build(['phy','cube']+(['show'] if show else []),entries)
    def run_fake(self,args,timeout=90):
        args=list(map(str,args));self.calls.append(args)
        if args[-1]=='version':return 'esptool v5.3.1'
        if 'flash-id' in args:return f'MAC: {MAC}\nDetected flash size: 4MB'
        if 'read-flash' in args:
            data=self.flash
            if self.corrupt_readback and any('nvs-show.bin' in a for c in self.calls for a in c):data=data[:-1]+b'\x00'
            Path(args[-1]).write_bytes(b'\xff'*4096+data if args[-3]=='0x8000' else data)
        if 'write-flash' in args and '0x9000' in args:
            if self.fail_show_write:raise RuntimeError('Disconnected while writing')
            self.flash=Path(args[args.index('0x9000')+1]).read_bytes()
        return 'verified'
    def boot(self,port,mac,version,runner,show=None):
        self.boots.append(show);return True
    def execute(self,manual=False,show='default',show_only=None):
        show=self.show if show=='default' else show
        with patch('backend.ROOT',self.root),patch('backend.Runner.__call__',side_effect=self.run_fake),patch.object(Flasher,'boot',self.boot),patch('backend.ports',return_value=[self.port]):
            return Flasher(self.path,lambda *e:None).execute(self.port,self.manifest,manual,show=show,show_only=show_only)
    def shows_written(self):return sum('write-flash' in c and '0x9000' in c for c in self.calls)
    def test_new_cube_gets_firmware_and_show(self):
        before=self.flash
        result=self.execute()
        self.assertEqual((result['ui_result'],result['show_result'],result['show_version']),('success','written',7))
        self.assertEqual(self.nvs.show_of(self.flash),dict(version=7,crc=self.show['crc'],length=600,valid=True))
        self.assertTrue(self.nvs.same_except_show(before,self.flash))
        self.assertEqual(self.boots,[self.show],'the boot check requires the cube to report the show from NVS')
        self.assertEqual(self.calls[-1][self.calls[-1].index('--after')+1],'hard-reset')
        db=Store(self.path);row=db.history()[0];db.close()
        self.assertEqual((row['show_result'],row['show_version']),('written',7))
    def test_matching_firmware_still_gets_the_show(self):
        self.execute(show=None)
        self.assertEqual(self.shows_written(),0)
        result=self.execute()
        self.assertEqual((result['ui_result'],result['show_result']),('skipped','written'))
        self.assertEqual(sum('write-flash' in c for c in self.calls),2,'one firmware write, then the show only')
        self.assertEqual(self.nvs.show_of(self.flash)['version'],7)
        self.assertEqual(self.boots[-1],self.show)
    def test_current_show_is_not_rewritten(self):
        self.flash=self.registered((7,self.image))
        result=self.execute()
        self.assertEqual(result['show_result'],'current');self.assertEqual(self.shows_written(),0)
        self.assertEqual(self.boots,[None])
        self.flash=self.registered((9,self.image))
        self.assertEqual(self.execute()['show_result'],'newer');self.assertEqual(self.shows_written(),0)
    def test_damaged_or_older_show_is_replaced(self):
        self.flash=self.registered((3,b'old show'))
        self.assertEqual(self.execute()['show_result'],'written')
        namespaces,entries=self.nvs.parse(self.registered((7,self.image)))
        self.flash=self.nvs.build(namespaces,[e._replace(value=e.value+1) if e.key=='crc' else e for e in entries])
        self.assertEqual(self.execute(manual=True)['show_result'],'written')
        self.assertTrue(self.nvs.show_of(self.flash)['valid'])
    def test_unreadable_storage_is_never_written(self):
        self.flash=b'N'*0x5000
        result=self.execute(manual=True)
        self.assertEqual(result['ui_result'],'attention','firmware was written before the show check')
        self.assertIn('could not be read',result['detail']);self.assertEqual(self.shows_written(),0)
    def test_readback_mismatch_needs_attention_and_keeps_backup(self):
        self.execute(show=None)
        self.corrupt_readback=True
        result=self.execute()
        self.assertEqual(result['ui_result'],'attention')
        self.assertIn('nvs-show-before.bin',result['detail'])
        self.assertTrue(Path(result['detail'].rsplit(' ',1)[-1]).exists())
    def test_interrupted_show_write_needs_attention(self):
        self.execute(show=None)
        self.fail_show_write=True
        self.assertEqual(self.execute()['ui_result'],'attention')
    def test_show_only_never_writes_firmware(self):
        result=self.execute(manual=True,show_only='v1.6.0-USB.1')
        self.assertEqual((result['ui_result'],result['show_result']),('skipped','written'))
        self.assertEqual(sum('write-flash' in c for c in self.calls),1)
        self.assertEqual(self.shows_written(),1)
        self.assertEqual(self.execute(manual=True,show_only='v1.4.1-USB.2')['show_result'],'current')
        self.flash=self.registered()
        self.assertEqual(self.execute(manual=True,show_only='v1.4.1-USB.2')['show_result'],'unsupported')
        self.assertEqual(self.shows_written(),1)
    def test_old_firmware_never_gets_a_show(self):
        self.manifest['version']='v1.4.1-USB.2'
        result=self.execute()
        self.assertEqual(result['show_result'],'unsupported');self.assertEqual(self.shows_written(),0)
    def test_boot_check_requires_the_nvs_show_line(self):
        from backend import show_line
        conn=MagicMock();conn.__enter__.return_value=conn
        reply=f'FW: v1.7.0-USB.1\nCube MAC: {MAC}\nESP-NOW CHANNEL: 2\nSHOW: v=0 crc=00000000 src=builtin\nCube READY\n'
        conn.read.return_value=reply.encode()
        with patch('backend.ports',return_value=[self.port]),patch('backend.serial.Serial',return_value=conn),patch('backend.time.monotonic',side_effect=[0]+[0]*20+[99]*5):
            self.assertFalse(Flasher(self.path,lambda *_:None).boot(self.port,MAC,'v1.7.0-USB.1',MagicMock(),show=self.show))
        conn.read.return_value=reply.replace('SHOW: v=0 crc=00000000 src=builtin',show_line(7,self.show['crc'])).encode()
        with patch('backend.ports',return_value=[self.port]),patch('backend.serial.Serial',return_value=conn):
            self.assertTrue(Flasher(self.path,lambda *_:None).boot(self.port,MAC,'v1.7.0-USB.1',MagicMock(),show=self.show))

if __name__=='__main__':unittest.main()
