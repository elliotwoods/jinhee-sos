"""Tk integration checks; run on a graphical session (separately from headless unit tests)."""
import json
import time
import tkinter as tk
import unittest
from unittest.mock import patch
from app import App
import firmware

class InterfaceTests(unittest.TestCase):
    def setUp(self):
        publication=patch.object(firmware,'local_database',return_value=firmware.zonedb.Publication(1,[]))
        publication.start()
        self.addCleanup(publication.stop)
        self.root=tk.Tk(); self.root.withdraw()
        self.app=App(self.root)
        self.sent=[]
        self.app.send=lambda command: self.sent.append(command) or True
        self.app.handle(json.dumps(dict(device='PoolZoneCalibration',type='calibration',ticks=[20+10*i for i in range(23)],anchors=4194305,saved=True)))
    def tearDown(self): self.app.close()
    def feed(self, **state):
        self.app.handle(json.dumps(dict(device='PoolZoneCalibration',type='interaction',**state)))
    def test_arm_and_neocube_snapshot(self):
        self.feed(override=False,tag=False,output=0)
        self.assertEqual(self.sent,[])
        self.app.toggle_arm(); self.assertEqual(self.sent,['HOST ARM'])
        self.feed(override=True,tag=False,output=12)
        self.app.toggle_arm(); self.assertEqual(self.sent[-1],'HOST DISARM')
        self.feed(override=False,tag=True,cube=7,uid='04:AA',mac='02:11:22:33:44:55',delivery=1,output=12)
        self.assertIn('#7',self.app.cube_label.cget('text'))
        self.assertIn('acknowledged',self.app.delivery_label.cget('text'))
        self.feed(override=False,tag=True,cube=0,uid='04:BB',output=12)
        self.assertIn('Unknown',self.app.cube_label.cget('text'))
    def test_capture_uses_displayed_filter_output(self):
        self.app.handle(json.dumps(dict(device='PoolZoneCalibration', type='sample', sensor=True, distance=129.25, raw_distance=140, index=12)))
        self.app.table.selection_set('12')
        self.app.capture()
        self.assertEqual(self.app.points[12],129.25)
        self.assertEqual(self.app.distance,129.25)
        self.assertEqual(self.app.raw_distance,140)

    def test_firmware_status_and_unsaved_draft_guard(self):
        self.app.monitor.zone=dict(firmware='pool-old',zone_type=3)
        self.app.ready=False
        self.app.connection=object()
        self.app.update_firmware_status()
        self.assertEqual(self.app.firmware_state,'update')
        self.assertIn('Update available',self.app.flash_status.cget('text'))
        self.assertIn('legacy update supported',self.app.flash_status.cget('text'))
        self.assertEqual(str(self.app.flash_button['state']),'normal')
        self.app.database_state='ahead'
        self.app.draw()
        self.assertEqual(str(self.app.flash_button['state']),'disabled')
        self.app.database_state='update'
        self.app.ready=True
        self.app.connection=object()
        self.app.dirty=True
        try:
            self.app.start_flash()
            self.assertFalse(self.app.flashing)
            self.assertIn('draft',self.app.flash_status.cget('text'))
        finally: self.app.connection=None

    def test_legacy_report_keeps_connection_alive_without_enabling_calibration(self):
        self.app.ready=False
        self.app.connection=object()
        self.app.last_rx=0
        try:
            with patch.object(self.app.monitor,'feed',return_value=True):
                self.app.monitor.zone=dict(firmware='pool-2.2.0',zone_type=3)
                self.app.handle('READY')
            self.assertGreater(self.app.last_rx,0)
            self.assertEqual(str(self.app.flash_button['state']),'normal')
            self.assertEqual(str(self.app.apply_button['state']),'disabled')
            self.assertFalse(self.app.ready)
        finally: self.app.connection=None

    def test_disconnect_clears_stale_firmware_offer(self):
        self.app.flash_status.configure(text='Update available · installed pool-old')
        self.app.firmware_state='update'
        self.app.disconnect('No calibration telemetry')
        self.assertEqual(self.app.firmware_state,'unknown')
        self.assertIn('Connect to a configured PoolZone',self.app.flash_status.cget('text'))

    def test_stale_snapshot_and_disarm(self):
        self.feed(override=True,tag=False,output=12)
        self.app.last_interaction=time.monotonic()-2
        self.app.draw()
        self.assertEqual(str(self.app.arm_button['state']),'disabled')
        self.assertIn('unavailable',self.app.output_label.cget('text'))

if __name__=='__main__': unittest.main()
