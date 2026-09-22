import sys
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from usb_identify import native_mac, eligible, identify, STATION_MAC, firmware_result

class UsbIdentityTests(unittest.TestCase):
    def port(self, mac='02:00:00:00:00:01', vid=0x303A):
        return SimpleNamespace(device='/dev/cu.test',serial_number=mac,vid=vid,location='2-2')

    def test_native_identity_does_not_open_or_reset_serial(self):
        port=self.port()
        with patch('usb_identify.serial.Serial') as serial:
            self.assertEqual(identify(port,threading.Event())[0],port.serial_number)
            serial.assert_not_called()

    def test_station_and_owned_ports_excluded_before_open(self):
        self.assertFalse(eligible(self.port(STATION_MAC),{STATION_MAC},set()))
        self.assertFalse(eligible(self.port(),set(),{'/dev/cu.test'}))
        self.assertTrue(eligible(self.port(),{STATION_MAC},set()))
        self.assertIsNone(native_mac(self.port('adapter serial',vid=0x10C4)))
        self.assertIsNone(native_mac(self.port('FF:FF:FF:FF:FF:FF')))

    def test_windows_port_names(self):
        port=SimpleNamespace(device='COM7',serial_number='02:00:00:00:00:01',vid=0x303A,location=None)
        self.assertTrue(eligible(port,{STATION_MAC},set()))
        self.assertFalse(eligible(port,set(),{'COM7'}))
        with patch('usb_identify.serial.Serial') as serial:
            self.assertEqual(identify(port,threading.Event())[0],port.serial_number)
            serial.assert_not_called()

class FirmwareTests(unittest.TestCase):
    def test_version_requires_matching_mac_and_ready(self):
        mac='02:00:00:00:00:01'
        text=f'FW: v1.4.1-USB.2\nCube MAC: {mac}\nCube READY\n'
        self.assertEqual(firmware_result(text,mac,'v1.4.1-USB.2')['status'],'current')
        self.assertEqual(firmware_result(text,mac,'v1.4.1-USB.3')['status'],'different')
        self.assertEqual(firmware_result(text,mac,None)['status'],'unknown')
        self.assertIsNone(firmware_result(text,'02:00:00:00:00:02','v1.4.1-USB.2'))
        self.assertIsNone(firmware_result(text.replace('Cube READY',''),mac,'v1.4.1-USB.2'))
