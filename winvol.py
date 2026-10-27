"""Nivel do microfone no Windows (o mesmo numero das configuracoes de som), por
IAudioEndpointVolume. A "Voz" da interface le e grava aqui: o
soundboard nao tem ganho proprio de voz. Tambem a lista de dispositivos do seletor, lida
de novo a cada vez (a do PortAudio para no dia em que o servidor subiu). COM so pelo
comtypes, sem pycaw."""
import ctypes
import sys
from ctypes import HRESULT, POINTER, c_float, c_uint, c_void_p, c_wchar_p
from ctypes.wintypes import DWORD

sys.coinit_flags = getattr(sys, "coinit_flags", 0)  # MTA: o engine importa na thread dona do COM
import comtypes  # noqa: E402
from comtypes import COMMETHOD, GUID, IUnknown  # noqa: E402

E_RENDER = 0
E_CAPTURE = 1
E_MULTIMEDIA = 1  # o papel que o PortAudio le como padrao
DEVICE_STATE_ACTIVE = 1
STGM_READ = 0
CLSCTX_ALL = 23
VT_LPWSTR = 31


class PROPERTYKEY(ctypes.Structure):
    _fields_ = [("fmtid", GUID), ("pid", DWORD)]


class PROPVARIANT(ctypes.Structure):
    # so o caso texto (VT_LPWSTR); 24 bytes no 64 bits, como o do Windows
    _fields_ = [("vt", ctypes.c_ushort), ("r1", ctypes.c_ushort), ("r2", ctypes.c_ushort),
                ("r3", ctypes.c_ushort), ("val", c_void_p), ("pad", c_void_p)]


PKEY_FRIENDLY_NAME = PROPERTYKEY(GUID("{A45C254E-DF1C-4EFD-8020-67D146A850E0}"), 14)


class IAudioEndpointVolume(IUnknown):
    _iid_ = GUID("{5CDF2C82-841E-4546-9722-0CF74078229A}")
    _methods_ = [
        COMMETHOD([], HRESULT, "RegisterControlChangeNotify", (["in"], c_void_p, "p")),
        COMMETHOD([], HRESULT, "UnregisterControlChangeNotify", (["in"], c_void_p, "p")),
        COMMETHOD([], HRESULT, "GetChannelCount", (["out"], POINTER(c_uint), "n")),
        COMMETHOD([], HRESULT, "SetMasterVolumeLevel", (["in"], c_float, "db"),
                  (["in"], POINTER(GUID), "ctx")),
        COMMETHOD([], HRESULT, "SetMasterVolumeLevelScalar", (["in"], c_float, "v"),
                  (["in"], POINTER(GUID), "ctx")),
        COMMETHOD([], HRESULT, "GetMasterVolumeLevel", (["out"], POINTER(c_float), "db")),
        COMMETHOD([], HRESULT, "GetMasterVolumeLevelScalar", (["out"], POINTER(c_float), "v")),
    ]


class IPropertyStore(IUnknown):
    _iid_ = GUID("{886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99}")
    _methods_ = [
        COMMETHOD([], HRESULT, "GetCount", (["out"], POINTER(DWORD), "n")),
        COMMETHOD([], HRESULT, "GetAt", (["in"], DWORD, "i"), (["out"], POINTER(PROPERTYKEY), "k")),
        COMMETHOD([], HRESULT, "GetValue", (["in"], POINTER(PROPERTYKEY), "k"),
                  (["in"], POINTER(PROPVARIANT), "v")),
    ]


class IMMDevice(IUnknown):
    _iid_ = GUID("{D666063F-1587-4E43-81F1-B948E807363F}")
    _methods_ = [
        COMMETHOD([], HRESULT, "Activate", (["in"], POINTER(GUID), "iid"), (["in"], DWORD, "ctx"),
                  (["in"], c_void_p, "params"), (["out"], POINTER(POINTER(IUnknown)), "obj")),
        COMMETHOD([], HRESULT, "OpenPropertyStore", (["in"], DWORD, "mode"),
                  (["out"], POINTER(POINTER(IPropertyStore)), "ps")),
        COMMETHOD([], HRESULT, "GetId", (["out"], POINTER(c_wchar_p), "id")),
    ]


class IMMDeviceCollection(IUnknown):
    _iid_ = GUID("{0BD7A1BE-7A1A-44DB-8397-CC5392387B5E}")
    _methods_ = [
        COMMETHOD([], HRESULT, "GetCount", (["out"], POINTER(c_uint), "n")),
        COMMETHOD([], HRESULT, "Item", (["in"], c_uint, "i"), (["out"], POINTER(POINTER(IMMDevice)), "d")),
    ]


class IMMDeviceEnumerator(IUnknown):
    _iid_ = GUID("{A95664D2-9614-4F35-A746-DE8DB63617E6}")
    _methods_ = [
        COMMETHOD([], HRESULT, "EnumAudioEndpoints", (["in"], c_uint, "flow"), (["in"], DWORD, "state"),
                  (["out"], POINTER(POINTER(IMMDeviceCollection)), "c")),
        COMMETHOD([], HRESULT, "GetDefaultAudioEndpoint", (["in"], c_uint, "flow"), (["in"], c_uint, "role"),
                  (["out"], POINTER(POINTER(IMMDevice)), "d")),
    ]


CLSID_ENUMERATOR = GUID("{BCDE0395-E52F-467C-8E3D-C4579291692E}")


def _nome(dev):
    pv = PROPVARIANT()
    dev.OpenPropertyStore(STGM_READ).GetValue(ctypes.byref(PKEY_FRIENDLY_NAME), ctypes.byref(pv))
    try:
        return ctypes.wstring_at(pv.val) if pv.vt == VT_LPWSTR and pv.val else ""
    finally:
        ctypes.windll.ole32.PropVariantClear(ctypes.byref(pv))


def _ativos(flow):
    en = comtypes.CoCreateInstance(CLSID_ENUMERATOR, IMMDeviceEnumerator, CLSCTX_ALL)
    col = en.EnumAudioEndpoints(flow, DEVICE_STATE_ACTIVE)
    return [(_nome(d), d) for d in (col.Item(i) for i in range(col.GetCount()))]


def microfones():
    """[(nome, IMMDevice)] das entradas ativas. Chamar numa thread com COM iniciado."""
    return _ativos(E_CAPTURE)


def _padrao(flow):
    en = comtypes.CoCreateInstance(CLSID_ENUMERATOR, IMMDeviceEnumerator, CLSCTX_ALL)
    try:
        return _nome(en.GetDefaultAudioEndpoint(flow, E_MULTIMEDIA))
    except comtypes.COMError:  # nenhum dispositivo desse lado
        return None


def dispositivos():
    """Entradas, saidas e padroes do Windows nesta hora, no formato do engine.list_devices
    (o nome amigavel e o mesmo do sounddevice no WASAPI). Chamar numa thread com COM iniciado."""
    return {"inputs": [n for n, _ in _ativos(E_CAPTURE)], "outputs": [n for n, _ in _ativos(E_RENDER)],
            "default_input": _padrao(E_CAPTURE), "default_output": _padrao(E_RENDER)}


def volume_do(nome):
    """IAudioEndpointVolume da entrada com esse nome (o do sounddevice no WASAPI e o
    nome amigavel do Windows); None se nao achou."""
    alvo = (nome or "").lower()
    for n, d in microfones():
        if n.lower() == alvo:
            u = d.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
            return u.QueryInterface(IAudioEndpointVolume)
    return None


def ler(ep):
    return float(ep.GetMasterVolumeLevelScalar())


def gravar(ep, v):
    ep.SetMasterVolumeLevelScalar(max(0.0, min(1.0, float(v))), None)
