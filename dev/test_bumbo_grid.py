import ast
import types
import unittest
from pathlib import Path

SOURCE = Path(__file__).with_name("bumbo.py")


def grid_assignment():
    for node in ast.walk(ast.parse(SOURCE.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Assign) and [getattr(t, "id", None) for t in node.targets] == ["gr"]:
            return compile(ast.Module(body=[node], type_ignores=[]), str(SOURCE), "exec")
    raise AssertionError("dev/bumbo.py no longer assigns gr")


def run_with(eng):
    names = {"eng": eng, "xb": "the stretch"}
    exec(grid_assignment(), names)
    return names["gr"]


class NetworkGridFallback(unittest.TestCase):
    def test_engine_after_the_move(self):
        calls = []
        batida = types.SimpleNamespace(network_beat_grid=lambda x, sr: calls.append((x, sr)) or "grid")
        self.assertEqual(run_with(types.SimpleNamespace(SR=48000, batida=batida)), "grid")
        self.assertEqual(calls, [("the stretch", 48000)])

    def test_engine_before_the_move(self):
        calls = []
        eng = types.SimpleNamespace(SR=48000, batida=types.SimpleNamespace(),
                                    _grade_rede=lambda x: calls.append(x) or "old grid")
        self.assertEqual(run_with(eng), "old grid")
        self.assertEqual(calls, ["the stretch"])


if __name__ == "__main__":
    unittest.main()
