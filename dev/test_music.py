import ast
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import music

VIDEO = {"youtube_id": "aaaaaaaaaaa", "title": "Ed Sheeran - Shape of You (Official Video)", "channel": "Ed Sheeran",
         "duration": 263}


def track(vid, title="Shape of You", artist="Ed Sheeran", duration=234):
    return {"videoId": vid, "title": title, "artists": [{"name": artist}, {"name": ""}],
            "duration_seconds": duration}


class FindTrack(unittest.TestCase):
    def test_first_valid_same_track(self):
        queries = []
        results = [track("bad id"), track("bbbbbbbbbbb", title="Perfect"), track("ccccccccccc"),
                   track("ddddddddddd")]

        def search(q):
            queries.append(q)
            return results
        self.assertEqual(music.find_track(VIDEO, search)["videoId"], "ccccccccccc")
        self.assertEqual(queries, [music.busca_de(VIDEO)])

    def test_none_without_the_same_track(self):
        self.assertIsNone(music.find_track(VIDEO, lambda q: [track("bbbbbbbbbbb", title="Perfect"), track(None)]))
        self.assertIsNone(music.find_track(VIDEO, lambda q: []))

    def test_track_artists(self):
        self.assertEqual(music.track_artists({"artists": [{"name": "A"}, {}, {"name": "B"}]}), "A, B")
        self.assertEqual(music.track_artists({"artists": None}), "")

    def test_only_music_matches_tracks(self):
        callers = []
        for f in sorted(ROOT.glob("*.py")):
            if f.name == "music.py":
                continue
            for node in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
                if isinstance(node, ast.Call):
                    name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
                    if name == "mesma_faixa":
                        callers.append(f"{f.name}:{node.lineno}")
        self.assertEqual(callers, [], "the track lookup goes through music.find_track")


if __name__ == "__main__":
    unittest.main()
