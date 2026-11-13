"""O lado do app do filtro de microfone: escreve audio no anel (apo/anel.h) que o micfx.dll soma no microfone.

    python injeta.py estado               a memoria existe? quais filtros estao vivos (um por microfone ou stream)
    python injeta.py toca arquivo.wav     toca um WAV no microfone, no tempo certo

Uso no app: m = Microfone(); m.toca(x) com x float32 (quadros, 2) a 48 kHz. O anel so existe com algum microfone
que tem o filtro sendo usado por alguem (jogo, Discord, gravador); sem ele, Microfone() levanta SemFiltro.
"""
import ctypes
import os
import struct
import sys
import time
from ctypes import wintypes

import numpy as np

MAPA = os.environ.get("MICFX_MAPA", "Global\\RitmelliMicFx1")
MAGIA, VERSAO, TAXA, CANAIS, QUADROS, LEITORES, BATIDA_MS = 0x58464D52, 1, 48000, 2, 32768, 8, 500

k32 = ctypes.WinDLL("kernel32", use_last_error=True)
k32.OpenFileMappingW.restype = wintypes.HANDLE
k32.OpenFileMappingW.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR)
k32.MapViewOfFile.restype = ctypes.c_void_p
k32.MapViewOfFile.argtypes = (wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, ctypes.c_size_t)
k32.UnmapViewOfFile.argtypes = (ctypes.c_void_p,)
k32.GetTickCount64.restype = ctypes.c_uint64
k32.CloseHandle.argtypes = (wintypes.HANDLE,)
FILE_MAP_READ, FILE_MAP_WRITE = 0x0004, 0x0002


class Leitor(ctypes.Structure):
    _fields_ = [("lido", ctypes.c_int64), ("batida", ctypes.c_int64), ("dono", ctypes.c_uint32),
                ("taxa", ctypes.c_uint32)]


class Anel(ctypes.Structure):
    _fields_ = [("magia", ctypes.c_uint32), ("versao", ctypes.c_uint32), ("taxa", ctypes.c_uint32),
                ("canais", ctypes.c_uint32), ("quadros", ctypes.c_uint32), ("leitores", ctypes.c_uint32),
                ("escrito", ctypes.c_int64), ("ganho", ctypes.c_float), ("sem_voz", ctypes.c_uint32),
                ("batida_app", ctypes.c_int64), ("reservado", ctypes.c_uint32 * 4),
                ("leitor", Leitor * LEITORES),
                ("dados", ctypes.c_float * (QUADROS * CANAIS))]


assert Anel.escrito.offset == 24 and Anel.batida_app.offset == 40 and Anel.leitor.offset == 64
assert Anel.dados.offset == 256


class SemFiltro(RuntimeError):
    pass


class Microfone:
    def __init__(self):
        h = k32.OpenFileMappingW(FILE_MAP_READ | FILE_MAP_WRITE, False, MAPA)
        if not h:
            raise SemFiltro(f"o anel {MAPA} nao existe (nenhum microfone com o filtro em uso; erro "
                            f"{ctypes.get_last_error()})")
        self._h = h
        self._p = k32.MapViewOfFile(h, FILE_MAP_READ | FILE_MAP_WRITE, 0, 0, ctypes.sizeof(Anel))
        if not self._p:
            raise SemFiltro(f"MapViewOfFile falhou ({ctypes.get_last_error()})")
        self.a = Anel.from_address(self._p)
        if self.a.magia != MAGIA or self.a.versao != VERSAO:
            raise SemFiltro(f"anel com magia/versao inesperada ({self.a.magia:#x}/{self.a.versao})")
        self.dados = np.ctypeslib.as_array(self.a.dados).reshape(QUADROS, CANAIS)

    def vivos(self):
        agora = k32.GetTickCount64()
        return [l for l in self.a.leitor if l.dono and agora - l.batida <= BATIDA_MS]

    def na_fila(self):
        """Quadros escritos que o leitor mais atrasado ainda nao leu (0 sem leitor vivo)."""
        v = self.vivos()
        return max(0, self.a.escrito - min(l.lido for l in v)) if v else 0

    def escreve(self, x):
        """Escreve o que couber de x (float32, quadros x 2) e devolve quantos quadros foram."""
        n = min(len(x), QUADROS - self.na_fila())
        if n <= 0:
            return 0
        ini = self.a.escrito % QUADROS
        a = min(n, QUADROS - ini)
        self.dados[ini:ini + a] = x[:a]
        if n > a:
            self.dados[:n - a] = x[a:n]
        self.a.escrito += n  # depois dos dados: o filtro so le ate aqui
        return n

    def pulso(self, sem_voz=False):
        """O app esta vivo: o filtro so corta a voz (sem_voz) ate MICFX_APP_MS depois do ultimo pulso, entao o app
        que cai com a voz cortada nao deixa o microfone mudo. Chamar a cada escrita (ou mais)."""
        self.a.batida_app = k32.GetTickCount64()
        self.a.sem_voz = 1 if sem_voz else 0

    def toca(self, x, folga_ms=30, parar=None, cauda_ms=10):
        """Toca o clipe x no ritmo do microfone, mantendo ~folga_ms escritos a frente do leitor mais atrasado.
        Fecha com cauda_ms de silencio: o filtro de um microfone que nao roda a 48 kHz so solta a ultima amostra
        quando tem meia janela do reamostrador depois dela (ate 8 ms num microfone de 8 kHz). Pra emendar pedacos
        de um fluxo continuo, cauda_ms=0."""
        x = np.ascontiguousarray(x, dtype=np.float32)
        if x.ndim == 1:
            x = np.repeat(x[:, None], 2, axis=1)
        if cauda_ms:
            x = np.concatenate([x, np.zeros((int(TAXA * cauda_ms / 1000), 2), np.float32)])
        folga = int(TAXA * folga_ms / 1000)
        winmm = ctypes.WinDLL("winmm")
        winmm.timeBeginPeriod(1)
        try:
            i = 0
            while i < len(x) and not (parar and parar.is_set()):
                falta = folga - self.na_fila() if self.vivos() else 0
                self.pulso(self.a.sem_voz)
                if falta > 0:
                    i += self.escreve(x[i:i + falta])
                time.sleep(0.002)
        finally:
            winmm.timeEndPeriod(1)

    def fecha(self):
        if self._p:
            k32.UnmapViewOfFile(self._p)
            self._p = None
        if self._h:
            k32.CloseHandle(self._h)
            self._h = None


def le_wav(caminho):
    """WAV int16, int32 ou float32 (formato 3, que o modulo wave nao le) -> float32 (quadros, 2) a 48 kHz."""
    b = open(caminho, "rb").read()
    i, fmt, dados = 12, None, None
    while i + 8 <= len(b):
        cid, tam = b[i:i + 4], struct.unpack_from("<I", b, i + 4)[0]
        if cid == b"fmt ":
            fmt = struct.unpack_from("<HHIIHH", b, i + 8)
        elif cid == b"data":
            dados = b[i + 8:i + 8 + tam]
        i += 8 + tam + (tam & 1)
    tipo, ch, sr, _, _, bits = fmt
    if tipo == 3:
        x = np.frombuffer(dados, "<f4").reshape(-1, ch).astype(np.float32)
    else:
        x = np.frombuffer(dados, {16: "<i2", 32: "<i4"}[bits]).reshape(-1, ch)
        x = x.astype(np.float32) / (32768.0 if bits == 16 else 2147483648.0)
    if ch == 1:
        x = np.repeat(x, 2, axis=1)
    if sr != TAXA:
        n = int(round(len(x) * TAXA / sr))
        t = np.linspace(0, len(x) - 1, n)
        x = np.stack([np.interp(t, np.arange(len(x)), x[:, c]) for c in range(2)], axis=1).astype(np.float32)
    return x[:, :2]


if __name__ == "__main__":
    if sys.argv[1] == "estado":
        m = Microfone()
        print(f"anel ok: escrito {m.a.escrito}, ganho {m.a.ganho}, sem_voz {m.a.sem_voz}")
        for i, l in enumerate(m.a.leitor):
            if l.dono:
                print(f"  vaga {i}: dono {l.dono:#x}, taxa {l.taxa}, lido {l.lido}, batida ha "
                      f"{k32.GetTickCount64() - l.batida} ms")
    elif sys.argv[1] == "toca":
        Microfone().toca(le_wav(sys.argv[2]))
