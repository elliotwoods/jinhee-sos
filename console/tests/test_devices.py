import json
import unittest

import support  # noqa: F401
from devices import Device, presumed_role


def port(**over):
    base = dict(port='/dev/cu.usbmodem101', key='A4CF12345678', serial='A4:CF:12:34:56:78', description='USB JTAG/serial',
                candidate=True, native_usb=True, location=None)
    base.update(over)
    return base


class DeviceTests(unittest.TestCase):
    def test_native_usb_mac_is_the_identity(self):
        d = Device(port(), clock=lambda: 0.0)
        self.assertEqual((d.usb_mac, d.mac, d.id, d.state), ('A4:CF:12:34:56:78', 'A4:CF:12:34:56:78', 'A4:CF:12:34:56:78', 'present'))
        self.assertTrue(d.wants_probe())

    def test_protected_station_is_never_probed(self):
        d = Device(port(serial='3C:0F:02:AD:83:24', candidate=False), clock=lambda: 0.0)
        self.assertEqual(d.state, 'protected')
        self.assertFalse(d.wants_probe())

    def test_booting_cube_is_retried_then_given_up(self):
        clock = [0.0]
        d = Device(port(), clock=lambda: clock[0])
        for attempt in range(Device.MAX_ATTEMPTS):
            self.assertTrue(d.wants_probe(), attempt)
            d.probe_started()
            d.probe_result('cube', dict(booting=True), ['NCT NEOCORE CUBE'], None)
            clock[0] += Device.RETRY_AFTER + 1
        self.assertEqual(d.state, 'idle')
        self.assertFalse(d.wants_probe())

    def test_foreign_port_backs_off_without_burning_attempts(self):
        clock = [0.0]
        d = Device(port(), clock=lambda: clock[0])
        d.probe_started()
        d.probe_result(None, None, [], 'USB port is owned by another Neocore application')
        self.assertEqual((d.state, d.attempts), ('foreign', 0))

    def test_zone_identity_fills_mac_and_firmware(self):
        d = Device(port(serial=None, native_usb=False, key='loc-1-2'), clock=lambda: 0.0)
        d.probe_started()
        d.probe_result('zone', dict(mac='14:63:93:c0:ec:14', firmware='preshow-3.4.0', zone_type=1), ['...'], None)
        self.assertEqual((d.id, d.firmware, d.zone_type, d.state), ('14:63:93:C0:EC:14', 'preshow-3.4.0', 1, 'idle'))
        json.dumps(d.to_dict())

    def test_presumed_roles(self):
        rows = {'AA:00:00:00:00:01': dict(mac='AA:00:00:00:00:01', cube_id=7, uid=None)}
        roles = {'AA:00:00:00:00:02': 'excluded'}
        zones = {'AA:00:00:00:00:03': dict(name='Pool 1')}
        self.assertEqual(presumed_role('3C:0F:02:AD:83:24', rows, roles, zones, set())['role'], 'workstation')
        self.assertEqual(presumed_role('AA:00:00:00:00:04', rows, roles, zones, {'AA:00:00:00:00:04'})['role'], 'mainshow')
        self.assertEqual(presumed_role('AA:00:00:00:00:03', rows, roles, zones, set())['role'], 'zone')
        self.assertEqual(presumed_role('AA:00:00:00:00:02', rows, roles, zones, set())['role'], 'workstation')
        recorded = presumed_role('AA:00:00:00:00:05', rows, roles, zones, set(), workstations={'AA:00:00:00:00:05'})
        self.assertEqual((recorded['role'], recorded['label']), ('workstation', 'Recorded as a Workstation / General Radio'))
        self.assertEqual(presumed_role('AA:00:00:00:00:01', rows, roles, zones, set())['label'], 'Cube #7')
        self.assertEqual(presumed_role('AA:00:00:00:00:09', rows, roles, zones, set()), {})
        self.assertEqual(presumed_role(None, rows, roles, zones, set()), {})


if __name__ == '__main__':
    unittest.main()
