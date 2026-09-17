import unittest
from app import from_points, validate, capture_distance

class CalibrationTests(unittest.TestCase):
    def test_noisy_capture(self):
        self.assertEqual(capture_distance([(1.0,100),(1.1,109),(1.2,104)],1.25),104)
        self.assertEqual(capture_distance([(1.0,500),(1.1,101),(1.2,102),(1.3,103)],1.35),103)
        with self.assertRaises(ValueError): capture_distance([(1,100),(1.1,102),(1.2,103)],2)
        self.assertEqual(capture_distance([(1.1,102)],1.2),102)

    def test_piecewise(self):
        ticks=from_points({1:383,12:220,23:43})
        self.assertEqual(ticks[0],383)
        self.assertEqual(ticks[11],220)
        self.assertEqual(ticks[-1],43)
        self.assertAlmostEqual(ticks[5],308.91)
        self.assertAlmostEqual(ticks[17],123.45)
        validate(ticks)
    def test_partial(self):
        ticks=from_points({5:50,10:100})
        self.assertEqual(ticks[:4],[0]*4)
        self.assertEqual(ticks[4:10],[50,60,70,80,90,100])
        with self.assertRaises(ValueError): validate(ticks)
    def test_invalid(self):
        for points in ({1:100,12:200,23:150},{1:100,23:110},{1:float('nan')},{0:20}):
            with self.assertRaises(ValueError): from_points(points)
    def test_ascending(self):
        self.assertEqual(from_points({1:10,23:230}),list(range(10,231,10)))

if __name__=='__main__': unittest.main()
