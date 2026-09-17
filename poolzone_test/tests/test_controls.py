import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import toggle_member

class ControlsTest(unittest.TestCase):
    def test_release_keeps_other_radio_assignments(self):
        self.assertEqual(toggle_member([1,5,23,0,0,0],5),[1,0,23,0,0,0])
    def test_reuses_free_slot(self):
        self.assertEqual(toggle_member([1,0,23,0,0,0],16),[1,16,23,0,0,0])
    def test_protocol_capacity(self):
        with self.assertRaises(ValueError): toggle_member([1,2,3,4,5,6],7)
        self.assertEqual(toggle_member([1,2,3,4,5,6],6),[1,2,3,4,5,0])

if __name__ == '__main__': unittest.main()
