import sys
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import compasso

CHUNK, EDGE = 1500, 6
STEP = CHUNK - 2 * EDGE


class Echo:
    def __init__(self):
        self.lengths = []

    def run(self, outputs, feed):
        x = feed["spect"][0]
        self.lengths.append(len(x))
        return x[None, :, 0], x[None, :, 1]


class Tagged(Echo):
    def run(self, outputs, feed):
        b, u = super().run(outputs, feed)
        call = len(self.lengths)
        return b * 0 + call, u * 0 + call


def frames(n):
    idx = np.arange(n, dtype=np.float32)
    return np.stack([idx, -idx], axis=1)


class Logits(unittest.TestCase):
    def setUp(self):
        self.real_open = compasso._abre
        self.addCleanup(setattr, compasso, "_abre", self.real_open)
        self.session = Echo()
        compasso._abre = lambda: self.session

    def check_stitched(self, n, lengths):
        b, u = compasso.logits(frames(n))
        np.testing.assert_array_equal(b, np.arange(n, dtype=np.float32))
        np.testing.assert_array_equal(u, -np.arange(n, dtype=np.float32))
        self.assertEqual(self.session.lengths, lengths)

    def test_a_track_shorter_than_one_chunk(self):
        self.check_stitched(500, [500 + 2 * EDGE])

    def test_a_track_of_several_chunks_with_a_short_last_one(self):
        self.check_stitched(2 * CHUNK + 37, [CHUNK] * 3)

    def test_where_chunks_overlap_the_earlier_chunk_wins(self):
        compasso._abre = lambda: Tagged()
        n = 2 * CHUNK + 37
        b, _ = compasso.logits(frames(n))
        self.assertEqual(b[0], 3.0)
        self.assertEqual(b[STEP - 1], 3.0)
        self.assertEqual(b[STEP], 2.0)
        self.assertEqual(b[n - 1], 1.0)
        last_start = n - CHUNK + 2 * EDGE
        self.assertLess(last_start, 2 * STEP)
        self.assertEqual(b[last_start], 2.0)
        self.assertEqual(b[2 * STEP - 1], 2.0)
        self.assertEqual(b[2 * STEP], 1.0)

    def test_a_track_of_exactly_one_chunk(self):
        self.check_stitched(STEP, [CHUNK])


class Picos(unittest.TestCase):
    def test_peaks_above_zero_and_their_glued_neighbours_merge(self):
        lg = np.full(60, -5.0, np.float32)
        lg[10] = lg[11] = 3.0
        lg[30], lg[31] = 2.0, 1.0
        lg[45] = -0.5
        lg[52] = 0.0
        np.testing.assert_allclose(compasso._picos(lg), [10.5, 30.0])

    def test_only_the_highest_in_seven_frames_counts(self):
        lg = np.full(40, -5.0, np.float32)
        lg[10], lg[13] = 2.0, 3.0
        np.testing.assert_allclose(compasso._picos(lg), [13.0])

    def test_two_equal_peaks_two_frames_apart_stay_two(self):
        lg = np.full(40, -5.0, np.float32)
        lg[10] = lg[12] = 2.0
        np.testing.assert_allclose(compasso._picos(lg), [10.0, 12.0])

    def test_two_peaks_four_frames_apart_both_count_whichever_is_higher(self):
        for left, right in ((2.0, 3.0), (3.0, 2.0)):
            lg = np.full(40, -5.0, np.float32)
            lg[10], lg[14] = left, right
            np.testing.assert_allclose(compasso._picos(lg), [10.0, 14.0])


if __name__ == "__main__":
    unittest.main()
