"""O motor de efeitos do filtro (microfone/apo/voz.h) fora do audiodg, pelo voz.dll: a mesma conta que o micfx.dll faz
na voz. O app usa quando a voz com efeito sai dele (o filtro recusou o efeito, ou o microfone nao tem o filtro e o
efeito so vale no fone), e os testes conferem e medem por aqui (dev/testa_voz.py). O compila.bat gera a DLL e o
instalador leva (ritmelli.spec); sem ela o app sobe igual e so o filtro roda o efeito.

    c = Cadeia(preset.compila(fx.criar("eco"), 48000), 48000)
    y = c(x)  # x float32 mono, em blocos (como o filtro recebe)
"""
import ctypes
import os
import sys

import numpy as np

ERROS = {1: "invalid preset", 2: "out of memory", 3: "rate differs from the preset's"}
_P = ctypes.POINTER(ctypes.c_float)
_dll = None


def caminho():
    if getattr(sys, "frozen", False):
        return os.path.join(sys._MEIPASS, "microfone", "voz.dll")
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "apo", "saida", "voz.dll")


def dll():
    """O voz.dll carregado; OSError se ele nao esta la (instalacao sem ele, ou o compila.bat nao rodou)."""
    global _dll
    if _dll is None:
        d = ctypes.CDLL(caminho())
        d.voz_cria.restype = ctypes.c_void_p
        d.voz_cria.argtypes = (ctypes.c_char_p, ctypes.c_uint32, ctypes.c_double, ctypes.POINTER(ctypes.c_uint32))
        d.voz_processa.argtypes = (ctypes.c_void_p, _P, ctypes.c_uint32)
        d.voz_usado.restype = ctypes.c_ulonglong
        d.voz_usado.argtypes = (ctypes.c_void_p,)
        d.voz_arena.restype = ctypes.c_ulonglong
        d.voz_arena.argtypes = (ctypes.c_double,)
        d.voz_destroi.argtypes = (ctypes.c_void_p,)
        _dll = d
    return _dll


def disponivel():
    """O voz.dll carrega: sem ele, a voz com efeito pelo app segue crua."""
    try:
        dll()
    except OSError:
        return False
    return True


class Cadeia:
    """Uma cadeia do voz.h montada do preset; chamar com um bloco devolve o bloco com efeito."""

    def __init__(self, preset, taxa):
        erro = ctypes.c_uint32(0)
        self.h = dll().voz_cria(preset, len(preset), float(taxa), ctypes.byref(erro))
        if not self.h:
            raise ValueError(f"the filter refused the preset: {ERROS.get(erro.value, erro.value)}")
        self.finito = True

    def __call__(self, x):
        y = np.array(x, np.float32, copy=True)
        self.finito = bool(dll().voz_processa(self.h, y.ctypes.data_as(_P), len(y))) and self.finito
        return y

    @property
    def usado(self):
        return int(dll().voz_usado(self.h))

    def __del__(self):
        if getattr(self, "h", None) and _dll is not None:
            _dll.voz_destroi(self.h)
            self.h = None


def arena(taxa):
    """A memoria que o filtro separa para a cadeia nessa taxa (bytes)."""
    return int(dll().voz_arena(float(taxa)))
