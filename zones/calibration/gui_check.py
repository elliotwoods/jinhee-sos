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
        # The status detail is only shown while connected, so connect before checking it.
        self.app.connection=object()
        try:
            self.app.monitor.zone=dict(firmware='pool-old',zone_type=3)
            self.app.update_firmware_status()
            self.assertEqual(self.app.firmware_state,'update')
            self.assertIn('Update available',self.app.flash_status.cget('text'))
            self.app.dirty=True
            self.app.start_flash()
            self.assertFalse(self.app.flashing)
            self.assertIn('draft',self.app.flash_status.cget('text'))
        finally: self.app.connection=None

    def test_legacy_board_without_calibration_can_still_be_updated(self):
        # A board on pre-calibration firmware never becomes ready, but must stay flashable.
        self.app.connection=object()
        try:
            self.app.monitor.zone=dict(firmware='pool-old',zone_type=3)
            self.app.ready=False
            self.app.update_firmware_status()
            self.assertEqual(self.app.firmware_state,'update')
            self.assertIn('Update available',self.app.flash_status.cget('text'))
            self.assertIn('legacy update supported',self.app.flash_status.cget('text'))
            self.assertEqual(str(self.app.flash_button['state']),'normal')
            # A newer database on the board still blocks the update.
            self.app.database_state='ahead'
            self.app.draw()
            self.assertEqual(str(self.app.flash_button['state']),'disabled')
        finally: self.app.connection=None

    def test_database_and_registry_controls_are_visible(self):
        self.app.connection=object()
        try:
            self.app.monitor.zone=dict(firmware='pool-2.8.0',zone_type=3,mac='02:11:22:33:44:55',
                                       name='Pool Radio 4',point_id=4,db_version=1,db_count=32,db_crc=123)
            self.app.ready=True
            self.app.update_firmware_status()
            self.assertIn('Board', self.app.database_detail.cget('text'))
            self.assertIn('Pool Radio 4', self.app.registry_label.cget('text'))
            # A separate database control exists and is not the firmware button.
            self.assertIsNot(self.app.database_button, self.app.flash_button)
            self.app.database_state='current'
            self.app.draw()
            self.assertEqual(str(self.app.database_button['state']),'disabled')
            self.app.database_state='update'
            self.app.draw()
            self.assertEqual(str(self.app.database_button['state']),'normal')
            self.assertEqual(str(self.app.registry_button['state']),'normal')
        finally: self.app.connection=None

    def test_tuning_absorbed_from_device_and_shown_live(self):
        import recording as rec
        payload=dict(device='PoolZoneCalibration',type='tuning',saved=True,valid=True,
                     defaults={n:rec.DEFAULTS[k] for k,n in rec.JSON_KEYS.items()},
                     **{n:rec.DEFAULTS[k] for k,n in rec.JSON_KEYS.items()})
        payload['min_cutoff_hz']=0.25
        self.app.handle(json.dumps(payload))
        self.assertIsNotNone(self.app.tuning)
        self.assertAlmostEqual(self.app.tuning['mincutoff'],0.25)
        self.assertIn('saved to flash',self.app.tune_state.cget('text'))
        self.app.handle(json.dumps(dict(device='PoolZoneCalibration',type='sample',sensor=True,
                                        distance=129.25,raw_distance=140,index=12)))
        # The label must reflect the board's live parameters, not a hardcoded constant.
        self.assertIn('0.25',self.app.filter_label.cget('text'))

    def test_tuning_apply_queues_verified_commands(self):
        import recording as rec
        self.app.tuning=dict(rec.DEFAULTS)
        self.app.send_tuning(dict(rec.DEFAULTS,exit=0.6,release=200),save=True)
        self.assertEqual(list(self.app.queue),['TUNE SET exit 0.6','TUNE SET release 200','TUNE SAVE'])
        self.app.queue.clear()
        # An invalid set is refused before anything reaches the device.
        self.app.send_tuning(dict(rec.DEFAULTS,budget=5),save=False)
        self.assertEqual(list(self.app.queue),[])

    def test_guided_recording_schedule_and_analysis(self):
        import recording as rec
        self.app.ready=True
        self.app.connection=object()
        sent=[]
        self.app.send=lambda cmd: sent.append(cmd) or True
        try:
            self.app.stride_var.set('4'); self.app.settle_var.set('0.05'); self.app.hold_var.set('0.05')
            self.app.start_recording()
            self.assertIn('RAW ON',sent)
            self.assertEqual([s['tick'] for s in self.app.record_steps],[1,5,9,13,17,21,23])
            ticks=[383-(383-43)*i/22 for i in range(23)]
            now=time.monotonic(); stamp=0
            guard=0
            while self.app.record_state is not None and guard<200:
                guard+=1
                step=self.app.record_steps[self.app.record_step]
                for _ in range(12):
                    stamp+=20
                    self.app.handle(json.dumps(dict(device='PoolZoneCalibration',type='raw',
                                                    t=stamp,mm=round(ticks[step['tick']-1],2),st=0)))
                now+=0.06
                self.app.advance_recording(now)
            self.assertIn('RAW OFF',sent)
            self.assertIsNotNone(self.app.analysis)
            self.assertIsNotNone(self.app.proposal)
            self.assertEqual(len(self.app.result_table.get_children()),7)
            # The proposal must be something the firmware will actually accept.
            self.assertIsNone(rec.valid(self.app.proposal['tuning']))
            self.app.apply_recording_calibration()
            self.assertTrue(self.app.dirty)
            self.assertEqual(len(self.app.ticks),23)
        finally:
            self.app.connection=None

    def test_legacy_board_can_still_update_its_database(self):
        # A legacy board never answers CAL GET, so `ready` stays False; the cube
        # database update must not be gated on calibration readiness.
        self.app.connection=object()
        try:
            self.app.ready=False
            self.app.firmware_state='update'
            self.app.database_state='update'
            self.app.draw()
            self.assertEqual(str(self.app.database_button['state']),'normal')
            started=[]
            self.app.start_flash=lambda database_only=False: started.append(database_only)
            self.app.start_database()
            self.assertEqual(started,[True])
        finally: self.app.connection=None

    def test_firmware_without_tune_support_is_reported_once(self):
        # Firmware before pool-2.8.0 answers CAL GET but has no TUNE command.
        self.app.connection=object()
        try:
            self.app.ready=True
            sent=[]
            self.app.send=lambda cmd: sent.append(cmd) or True
            for _ in range(8):
                self.app.last_query=0
                self.app.poll_tune_probe()
            self.assertLessEqual(sent.count('TUNE GET'),3)
            self.assertIs(self.app.tune_supported,False)
            self.assertIn('not supported',self.app.tune_state.cget('text'))
            self.app.draw()
            self.assertEqual(str(self.app.record_button['state']),'disabled')
        finally: self.app.connection=None

    def test_output_stability_counts_index_changes(self):
        now=time.monotonic()
        for i,index in enumerate([12,-1,12,-1,12]):
            self.app.note_index(index,now-1+i*0.1)
        self.assertIn('4 index changes',self.app.stability_text(now))
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
