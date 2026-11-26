import json
import sys
import tempfile
import threading
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import server

WRITERS = 24


class WatchedCfg(dict):
    def __init__(self, lock, *args):
        super().__init__(*args)
        self.lock = lock
        self.updates_held = []

    def update(self, *args, **kwargs):
        self.updates_held.append(self.lock.locked())
        super().update(*args, **kwargs)


class GravaCfg(unittest.TestCase):
    def setUp(self):
        self.real_save = server.save_json
        self.addCleanup(setattr, server, "save_json", self.real_save)

    def app(self, folder):
        lock = threading.Lock()
        return types.SimpleNamespace(cfg=WatchedCfg(lock, {"mic": "default"}), cfg_lock=lock,
                                     cfg_path=Path(folder) / "config.json")

    def test_the_change_and_the_save_both_hold_the_lock(self):
        with tempfile.TemporaryDirectory() as folder:
            app = self.app(folder)
            held = []

            def save(path, data):
                held.append(app.cfg_lock.locked())
                self.real_save(path, data)

            server.save_json = save
            server.App.grava_cfg(app, vol=0.5)
            self.assertEqual(held, [True])
            self.assertEqual(app.cfg.updates_held, [True])

    def test_writers_from_many_threads_all_land_in_the_file(self):
        with tempfile.TemporaryDirectory() as folder:
            app = self.app(folder)
            start = threading.Barrier(WRITERS)

            def write(i):
                start.wait()
                server.App.grava_cfg(app, **{f"key{i}": i})

            threads = [threading.Thread(target=write, args=(i,)) for i in range(WRITERS)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
            expected = {"mic": "default", **{f"key{i}": i for i in range(WRITERS)}}
            self.assertEqual(app.cfg, expected)
            self.assertEqual(json.loads(app.cfg_path.read_text(encoding="utf-8")), expected)


if __name__ == "__main__":
    unittest.main()
