"""Tk integration checks; run on a graphical session (separately from headless unit tests)."""
import json
import time
import tkinter as tk
import unittest
from unittest.mock import patch
from app import App

class InterfaceTests(unittest.TestCase):
    def setUp(self):
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

    def test_stale_snapshot_and_disarm(self):
        self.feed(override=True,tag=False,output=12)
        self.app.last_interaction=time.monotonic()-2
        self.app.draw()
        self.assertEqual(str(self.app.arm_button['state']),'disabled')
        self.assertIn('unavailable',self.app.output_label.cget('text'))

if __name__=='__main__': unittest.main()
