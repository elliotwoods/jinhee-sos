import unittest
from unittest.mock import patch
import firmware

class FirmwareChecks(unittest.TestCase):
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

if __name__=='__main__': unittest.main()
