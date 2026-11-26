import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import winvol


class Endpoint:
    def __init__(self, level=0.25):
        self.level = level
        self.set_calls = []

    def GetMasterVolumeLevelScalar(self):
        return self.level

    def SetMasterVolumeLevelScalar(self, value, context):
        self.set_calls.append((value, context))


class Activated:
    def __init__(self, endpoint):
        self.endpoint = endpoint

    def QueryInterface(self, interface):
        return self.endpoint if interface is winvol.IAudioEndpointVolume else None


class Device:
    def __init__(self, endpoint):
        self.endpoint = endpoint
        self.activations = 0

    def Activate(self, iid, context, params):
        self.activations += 1
        return Activated(self.endpoint)


class Patched(unittest.TestCase):
    def patch(self, name, value):
        self.addCleanup(setattr, winvol, name, getattr(winvol, name))
        setattr(winvol, name, value)


class VolumeDo(Patched):
    def setUp(self):
        self.quest, self.usb = Endpoint(), Endpoint()
        self.devices = [("Microfone (Quest 3)", Device(self.quest)), ("USB Mic", Device(self.usb))]
        self.patch("microfones", lambda: self.devices)

    def test_finds_the_input_by_its_friendly_name_in_any_case(self):
        self.assertIs(winvol.volume_do("USB MIC"), self.usb)
        self.assertEqual([d.activations for _, d in self.devices], [0, 1])

    def test_no_input_with_that_name_is_none(self):
        self.assertIsNone(winvol.volume_do("Headset"))
        self.assertIsNone(winvol.volume_do(None))


class LerGravar(unittest.TestCase):
    def test_reads_the_level_as_a_float(self):
        self.assertEqual(winvol.ler(Endpoint(level=1)), 1.0)
        self.assertEqual(winvol.ler(Endpoint(level=0.25)), 0.25)
        self.assertIsInstance(winvol.ler(Endpoint(level=1)), float)

    def test_writes_a_level_held_between_zero_and_one(self):
        ep = Endpoint()
        for v in (-0.2, 0.5, "0.75", 1.7):
            winvol.gravar(ep, v)
        self.assertEqual(ep.set_calls, [(0.0, None), (0.5, None), (0.75, None), (1.0, None)])


class Dispositivos(Patched):
    def test_inputs_outputs_and_defaults_in_the_format_of_list_devices(self):
        names = {winvol.E_CAPTURE: [("Mic A", None), ("Mic B", None)], winvol.E_RENDER: [("Fone", None)]}
        defaults = {winvol.E_CAPTURE: "Mic B", winvol.E_RENDER: None}
        self.patch("_ativos", names.get)
        self.patch("_padrao", defaults.get)
        self.assertEqual(winvol.dispositivos(), {"inputs": ["Mic A", "Mic B"], "outputs": ["Fone"],
                                                 "default_input": "Mic B", "default_output": None})


if __name__ == "__main__":
    unittest.main()
