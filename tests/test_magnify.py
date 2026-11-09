import math
import unittest

from linux_magnify import magnify
from linux_magnify.magnify import Params


class MagnifyTest(unittest.TestCase):
    p = Params(icon_size=48, magnification=2.0, spread=3.0, spacing=8)

    def test_peak_and_falloff(self):
        self.assertAlmostEqual(magnify.scale_for_distance(0, self.p), 2.0)
        radius = 3 * (48 + 8)
        self.assertEqual(magnify.scale_for_distance(radius, self.p), 1.0)
        self.assertEqual(magnify.scale_for_distance(radius * 2, self.p), 1.0)
        self.assertAlmostEqual(magnify.scale_for_distance(radius / 2, self.p), 1.5)

    def test_symmetric_and_monotonic(self):
        prev = math.inf
        for d in range(0, 200, 5):
            s = magnify.scale_for_distance(d, self.p)
            self.assertAlmostEqual(s, magnify.scale_for_distance(-d, self.p))
            self.assertLessEqual(s, prev)
            prev = s

    def test_no_magnification(self):
        p = Params(magnification=1.0)
        self.assertEqual(magnify.scale_for_distance(0, p), 1.0)

    def test_rest_layout_without_cursor(self):
        n = 5
        scales = magnify.target_scales(n, self.p, 100, None)
        rects = magnify.layout(scales, self.p, 100, 0.5)
        self.assertEqual(rects[0], (100, 48))
        self.assertAlmostEqual(rects[-1][0] + rects[-1][1] - 100, magnify.rest_length(n, self.p))

    def test_point_under_cursor_is_anchored(self):
        n, start = 8, 0.0
        for cursor in (30.0, 200.0, 400.0):
            frac = magnify.anchor_fraction(n, self.p, start, cursor)
            rects = magnify.layout(magnify.target_scales(n, self.p, start, cursor), self.p, start, frac)
            grown = rects[-1][0] + rects[-1][1] - rects[0][0]
            self.assertAlmostEqual(rects[0][0], start - (grown - magnify.rest_length(n, self.p)) * frac)

    def test_overflow_bounds_layout(self):
        n = 10
        bound = magnify.max_overflow(n, self.p)
        total = magnify.rest_length(n, self.p)
        for i in range(0, 101):
            cursor = total * i / 100
            frac = magnify.anchor_fraction(n, self.p, 0, cursor)
            rects = magnify.layout(magnify.target_scales(n, self.p, 0, cursor), self.p, 0, frac)
            self.assertGreaterEqual(rects[0][0], -bound - 1e-6)
            self.assertLessEqual(rects[-1][0] + rects[-1][1], total + bound + 1e-6)


if __name__ == "__main__":
    unittest.main()
