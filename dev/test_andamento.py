import math
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import andamento as an

TEMPOS = {"a": {"ini": 120.0, "fim": 120.0}, "b": {"ini": 122.0, "fim": 140.0}, "c": {"ini": 117.0, "fim": 117.0},
          "d": {"ini": 90.0, "fim": 90.0}, "e": None}


def tempo(c):
    return TEMPOS[c]


class Subida(unittest.TestCase):
    def test_climbs_around_the_circle_of_octaves(self):
        self.assertAlmostEqual(an.subida(120.0, 240.0), 0.0)
        self.assertAlmostEqual(an.subida(120.0, 60.0), 0.0)
        self.assertAlmostEqual(an.subida(120.0, 120.0 * 2 ** 0.25), 0.25)
        self.assertAlmostEqual(an.subida(120.0, 120.0 * 2 ** -0.25), 0.75)


class Ordena(unittest.TestCase):
    def test_with_no_cursor_the_mix_order_stays(self):
        self.assertEqual(an.ordena(None, False, ["d", "a", "b"], tempo, 3), ["d", "a", "b"])

    def test_one_a_little_above_comes_before_one_a_little_below(self):
        self.assertEqual(an.ordena(120.0, False, ["c", "b"], tempo, 2)[0], "b")

    def test_one_far_away_comes_after_those_that_match(self):
        self.assertEqual(an.ordena(120.0, False, ["d", "c", "a"], tempo, 3)[-1], "d")

    def test_the_cursor_follows_the_end_of_the_one_that_plays(self):
        far = 140.0 * 2 ** 0.5
        tempos = {"b": {"ini": 122.0, "fim": 140.0}, "x": {"ini": 141.0, "fim": 141.0},
                  "y": {"ini": 124.0, "fim": 124.0}, "z": {"ini": far, "fim": far}}
        self.assertEqual(an.ordena(120.0, False, ["z", "y", "x", "b"], tempos.get, 2), ["b", "x"])

    def test_a_volume_jump_leaves_the_one_that_would_match_for_later(self):
        self.assertEqual(an.ordena(120.0, True, ["a", "e"], tempo, 2), ["e", "a"])

    def test_a_pick_with_no_firm_end_turns_the_next_into_a_volume_jump(self):
        tempos = {"f": {"ini": 120.0, "fim": None}, "m": {"ini": 121.0, "fim": 121.0}, "e": None}
        self.assertEqual(an.ordena(120.0, False, ["f", "m", "e"], tempos.get, 3), ["f", "e", "m"])

    def test_not_measured_yet_waits_behind_one_that_matches(self):
        self.assertEqual(an.ordena(120.0, False, ["e", "a"], tempo, 2), ["a", "e"])

    def test_two_of_the_same_artist_never_in_a_row_while_there_is_another(self):
        autores = {"a": {"X"}, "c": {"X"}, "d": {"Y"}}
        order = an.ordena(120.0, False, ["a", "c", "d"], tempo, 3, autores=lambda c: frozenset(autores[c]))
        self.assertEqual(order, ["a", "d", "c"])

    def test_the_artist_of_the_track_before_counts_too(self):
        autores = {"a": {"X"}, "d": {"Y"}}
        order = an.ordena(120.0, False, ["a", "d"], tempo, 1, autores=lambda c: frozenset(autores[c]),
                          antes=frozenset({"X"}))
        self.assertEqual(order, ["d"])

    def test_only_n_come_back(self):
        self.assertEqual(len(an.ordena(120.0, False, ["a", "b", "c", "d"], tempo, 2)), 2)

    def test_the_reach_is_what_the_passage_aligns(self):
        self.assertTrue(0.0 < an.ALCANCE < 1.0)
        self.assertAlmostEqual(an.ALCANCE, math.log2((1 + an.eng.TEMPO_MAX) * (1 + an.eng.SAI_MAX)))


if __name__ == "__main__":
    unittest.main()
