"""O lado do app do filtro de microfone: o anel (apo/anel.h) com o micfx.dll, nos dois sentidos.

    python injeta.py estado                         a memoria existe? o alvo e os filtros vivos
    python injeta.py toca arquivo.wav "IN 2"         toca um WAV no microfone (o nome como o Windows da), no tempo certo

O filtro fica em todos os microfones e so age no alvo: alvo(hash_microfone(guid)) com o GUID do microfone
escolhido ("{a1b2c3d4-...}", o nome da chave dele no registro). Ali ele soma o que o app escreve (escreve, no ritmo
de na_fila) e devolve a voz crua do microfone (voz). O anel so existe com algum microfone com o filtro em uso (o
proprio app abrindo o microfone conta); sem ele, Microfone() levanta SemFiltro. O efeito de voz que o filtro roda vai
pelo preset (microfone/preset.py, escrito com seqlock); a resposta do filtro sai em preset_estado e a voz com efeito
volta em voz_fx. A voz convertida fora do filtro (por um processo que le a voz crua e devolve outra) entra pela
pista da voz: pista_liga, pista_escreve e pista_pulso; o filtro poe ela no lugar da voz do microfone enquanto o
escritor bate.
"""
import contextlib
import ctypes
import os
import struct
import sys
import time
from ctypes import wintypes

import numpy as np

MAPA = os.environ.get("MICFX_MAPA", "Global\\RitmelliMicFx5")
MAGIA, VERSAO, TAXA, CANAIS, QUADROS, LEITORES, BATIDA_MS = 0x58464D52, 5, 48000, 2, 32768, 8, 500
VOZ_QUADROS = 16384
PRESET_BYTES = 65536
PISTA_QUADROS, PISTA_MS = 16384, 1000
clock = time.monotonic

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
                ("taxa", ctypes.c_uint32), ("ep", ctypes.c_uint32), ("reservado", ctypes.c_uint32)]


class Anel(ctypes.Structure):
    _fields_ = [("magia", ctypes.c_uint32), ("versao", ctypes.c_uint32), ("taxa", ctypes.c_uint32),
                ("canais", ctypes.c_uint32), ("quadros", ctypes.c_uint32), ("leitores", ctypes.c_uint32),
                ("escrito", ctypes.c_int64), ("ganho", ctypes.c_float), ("sem_voz", ctypes.c_uint32),
                ("batida_app", ctypes.c_int64), ("alvo", ctypes.c_uint32), ("voz_taxa", ctypes.c_uint32),
                ("voz_escrito", ctypes.c_int64), ("leitor", Leitor * LEITORES),
                ("dados", ctypes.c_float * (QUADROS * CANAIS)), ("voz", ctypes.c_float * VOZ_QUADROS),
                ("fx_escrito", ctypes.c_int64), ("preset_seq", ctypes.c_uint32), ("preset_n", ctypes.c_uint32),
                ("preset_feito", ctypes.c_uint32), ("preset_erro", ctypes.c_uint32),
                ("voz_fx", ctypes.c_float * VOZ_QUADROS), ("preset", ctypes.c_uint8 * PRESET_BYTES),
                ("voz_dono", ctypes.c_uint32), ("fx_dono", ctypes.c_uint32), ("voz_batida", ctypes.c_int64),
                ("fx_batida", ctypes.c_int64),
                ("pista_ligada", ctypes.c_uint32), ("pista_ligou_ms", ctypes.c_uint32),
                ("pista_escrito", ctypes.c_int64), ("pista_batida", ctypes.c_int64), ("pista_inicio", ctypes.c_int64),
                ("pista_lido", ctypes.c_int64 * LEITORES), ("pista", ctypes.c_float * (PISTA_QUADROS * CANAIS))]


assert ctypes.sizeof(Leitor) == 32 and Anel.escrito.offset == 24 and Anel.batida_app.offset == 40
assert Anel.alvo.offset == 48 and Anel.voz_escrito.offset == 56 and Anel.leitor.offset == 64
assert Anel.dados.offset == 320 and Anel.voz.offset == 320 + QUADROS * CANAIS * 4
assert Anel.fx_escrito.offset == 328000 and Anel.preset_seq.offset == 328008 and Anel.voz_fx.offset == 328024
assert Anel.preset.offset == 328024 + VOZ_QUADROS * 4
assert Anel.voz_dono.offset == 459096 and Anel.fx_dono.offset == 459100
assert Anel.voz_batida.offset == 459104 and Anel.fx_batida.offset == 459112
assert Anel.pista_ligada.offset == 459120 and Anel.pista_escrito.offset == 459128 and Anel.pista_batida.offset == 459136
assert Anel.pista_inicio.offset == 459144 and Anel.pista_lido.offset == 459152 and Anel.pista.offset == 459216
assert ctypes.sizeof(Anel) == 459216 + PISTA_QUADROS * CANAIS * 4


def hash_microfone(guid):
    """O MicFxHash do anel.h: FNV-1a de 32 bits do GUID do microfone em minusculo; nunca 0."""
    h = 2166136261
    for c in guid.lower():
        h = ((h ^ (ord(c) & 0xFF)) * 16777619) & 0xFFFFFFFF
    return h or 1


class SemFiltro(RuntimeError):
    pass


class Microfone:
    def __init__(self):
        self._h = self._p = None
        self._pista_ligou = False
        h = k32.OpenFileMappingW(FILE_MAP_READ | FILE_MAP_WRITE, False, MAPA)
        if not h:
            raise SemFiltro(f"the ring {MAPA} doesn't exist (no microphone with the filter in use; error "
                            f"{ctypes.get_last_error()})")
        self._h = h
        try:
            self._p = k32.MapViewOfFile(h, FILE_MAP_READ | FILE_MAP_WRITE, 0, 0, ctypes.sizeof(Anel))
            if not self._p:
                raise SemFiltro(f"MapViewOfFile failed ({ctypes.get_last_error()})")
            self.a = Anel.from_address(self._p)
            if self.a.magia != MAGIA or self.a.versao != VERSAO:
                raise SemFiltro(f"ring with unexpected magic/version ({self.a.magia:#x}/{self.a.versao})")
            self.dados = np.ctypeslib.as_array(self.a.dados).reshape(QUADROS, CANAIS)
            self._voz = np.ctypeslib.as_array(self.a.voz)
            self._voz_fx = np.ctypeslib.as_array(self.a.voz_fx)
            self._pista = np.ctypeslib.as_array(self.a.pista).reshape(PISTA_QUADROS, CANAIS)
        except BaseException:
            with contextlib.suppress(Exception):  # o erro que sobe e o de abrir, e nao o de fechar
                self.fecha()  # o handle e a vista abertos aqui nao ficam para tras com o erro
            raise
        self.voz_pos = None  # ate onde o app leu a voz crua (comeca no que chegar depois de abrir)
        self.fx_pos = None   # e a voz com efeito
        self.pista_pos = None  # e a voz da pista (o app le o que o processo da voz escreveu, para o fone)

    def alvo(self, h):
        """O microfone em que o filtro age (hash_microfone do GUID dele; 0 = nenhum)."""
        self.a.alvo = h

    def vivos(self):
        """Os filtros do alvo lendo agora (o de um microfone sem hash conta: ele age como o alvo)."""
        agora, alvo = k32.GetTickCount64(), self.a.alvo
        return [l for l in self.a.leitor if l.dono and agora - l.batida <= BATIDA_MS and l.ep in (alvo, 0)]

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

    def voz(self):
        """A voz crua do alvo que chegou desde a ultima leitura: (amostras float32 mono, taxa do microfone). Ficou
        para tras mais que o anel da voz (o app parou): pula para o mais novo."""
        fim = self.a.voz_escrito
        if self.voz_pos is None or fim - self.voz_pos > VOZ_QUADROS or fim < self.voz_pos:
            self.voz_pos = fim
        n = fim - self.voz_pos
        if n <= 0:
            return np.zeros(0, np.float32), self.a.voz_taxa
        idx = np.arange(self.voz_pos, fim) % VOZ_QUADROS
        x = self._voz[idx].astype(np.float32)
        self.voz_pos = fim
        return x, self.a.voz_taxa

    def voz_fx(self):
        """A voz com efeito que o filtro devolveu desde a ultima leitura (amostras float32 mono, taxa do microfone), como
        a voz()."""
        fim = self.a.fx_escrito
        if self.fx_pos is None or fim - self.fx_pos > VOZ_QUADROS or fim < self.fx_pos:
            self.fx_pos = fim
        n = fim - self.fx_pos
        if n <= 0:
            return np.zeros(0, np.float32), self.a.voz_taxa
        x = self._voz_fx[np.arange(self.fx_pos, fim) % VOZ_QUADROS].astype(np.float32)
        self.fx_pos = fim
        return x, self.a.voz_taxa

    def preset(self, dados):
        """Escreve o preset do efeito (bytes; vazio = sem efeito no filtro) e devolve o seq dele, que o filtro do alvo
        devolve em preset_feito quando ler. Seqlock: impar enquanto escreve, o filtro so le com o seq par e igual antes e
        depois da copia."""
        dados = bytes(dados or b"")
        if len(dados) > PRESET_BYTES:
            raise ValueError(f"preset of {len(dados)} bytes, the ring takes {PRESET_BYTES}")
        a = self.a
        seq = a.preset_seq
        if seq & 1:  # um escritor que caiu no meio
            seq += 1
        a.preset_seq = (seq + 1) & 0xFFFFFFFF
        ctypes.memmove(ctypes.addressof(a) + Anel.preset.offset, dados, len(dados))
        a.preset_n = len(dados)
        a.preset_seq = seq = (seq + 2) & 0xFFFFFFFE or 2  # nunca 0: o filtro comeca esperando 1
        return seq

    def preset_estado(self):
        """(o seq que o filtro do alvo leu por ultimo, o erro dele: 0 = montou; ver voz.h)."""
        return self.a.preset_feito, self.a.preset_erro

    def pulso(self, sem_voz=False):
        """O app esta vivo: o filtro so corta a voz (sem_voz) ate MICFX_APP_MS depois do ultimo pulso, entao o app
        que cai com a voz cortada nao deixa o microfone mudo. Chamar a cada escrita (ou mais)."""
        self.a.batida_app = k32.GetTickCount64()
        self.a.sem_voz = 1 if sem_voz else 0

    def pista_liga(self, ligada=True):
        """A pista da voz: ligada, o filtro do alvo tira a voz do microfone e poe o que vier por pista_escreve (a voz
        convertida fora do filtro), enquanto o escritor bate; sem bater por PISTA_MS, a voz do microfone volta.
        Desligada, a voz do microfone volta na hora. A leitura comeca do que for escrito a partir daqui: quem quer
        folga escreve um pouco de silencio logo depois de ligar, antes da voz."""
        new = ligada and not self._pista_ligou
        self.a.pista_batida = k32.GetTickCount64()
        if ligada and not self.a.pista_ligada:
            self.a.pista_inicio = self.a.pista_escrito  # antes de ligar: o filtro so le a marca com a pista ligada
        self._pista_ligou = ligada
        self.a.pista_ligada = 1 if ligada else 0
        if new:
            self.a.pista_ligou_ms = 1 + round(clock() * 1000) % (2**32 - 1)

    def pista_ligou(self):
        return self.a.pista_ligou_ms

    def pista_pulso(self):
        """O escritor da pista esta vivo (chamar a cada volta, mesmo sem ter o que escrever)."""
        self.a.pista_batida = k32.GetTickCount64()

    def pista_escreve(self, x):
        """Escreve x inteiro (float32 mono, ou quadros x 2, a 48 kHz) na pista da voz e devolve quantos quadros foram.
        Nao espera leitor: voz e ao vivo, e o filtro que ficar para tras pula para o mais novo."""
        x = np.ascontiguousarray(x, dtype=np.float32)
        if x.ndim == 1:
            x = np.repeat(x[:, None], 2, axis=1)
        x = x[-PISTA_QUADROS:]
        n = len(x)
        if n:
            ini = self.a.pista_escrito % PISTA_QUADROS
            a = min(n, PISTA_QUADROS - ini)
            self._pista[ini:ini + a] = x[:a]
            if n > a:
                self._pista[:n - a] = x[a:]
        self.a.pista_batida = k32.GetTickCount64()
        self.a.pista_escrito += n  # depois dos dados: o filtro so le ate aqui
        return n

    def pista_viva(self):
        """A pista da voz esta no comando: ligada e com o escritor batendo (o filtro poe a voz dela no lugar da do
        microfone)."""
        return bool(self.a.pista_ligada) and k32.GetTickCount64() - self.a.pista_batida < PISTA_MS

    def pista_le(self):
        """A voz da pista escrita desde a ultima leitura (float32 mono, 48 kHz): o que o jogo ouve no lugar da voz do
        microfone, para o fone e o medidor do app. Ficou para tras mais que a pista: pula para o mais novo."""
        fim = self.a.pista_escrito
        if self.pista_pos is None or fim - self.pista_pos > PISTA_QUADROS or fim < self.pista_pos:
            self.pista_pos = fim
        n = fim - self.pista_pos
        if n <= 0:
            return np.zeros(0, np.float32)
        x = self._pista[np.arange(self.pista_pos, fim) % PISTA_QUADROS].mean(axis=1).astype(np.float32)
        self.pista_pos = fim
        return x

    def pista_na_fila(self):
        """Quadros da pista que o filtro mais atrasado do alvo ainda nao leu (0 sem leitor vivo): a folga da voz."""
        agora, alvo = k32.GetTickCount64(), self.a.alvo
        lidos = [self.a.pista_lido[i] for i, l in enumerate(self.a.leitor)
                 if l.dono and agora - l.batida <= BATIDA_MS and l.ep in (alvo, 0) and self.a.pista_lido[i] >= 0]
        return max(0, self.a.pista_escrito - min(lidos)) if lidos else 0

    def toca(self, x, folga_ms=30, parar=None, cauda_ms=10):
        """Toca o clipe x no ritmo do microfone alvo, mantendo ~folga_ms escritos a frente do leitor mais atrasado.
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
        """Solta a vista e o handle, cada um uma vez (chamar de novo nao faz nada); o handle fecha mesmo se soltar a
        vista falhar."""
        p, self._p = self._p, None
        h, self._h = self._h, None
        try:
            if p:
                k32.UnmapViewOfFile(p)
        finally:
            if h:
                k32.CloseHandle(h)


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
        print(f"ring ok: written {m.a.escrito}, target {m.a.alvo:#010x}, no_voice {m.a.sem_voz}, voice {m.a.voz_escrito} "
              f"at {m.a.voz_taxa} Hz, voice track {'on' if m.a.pista_ligada else 'off'} "
              f"({m.a.pista_escrito} written, heartbeat {k32.GetTickCount64() - m.a.pista_batida} ms ago)")
        for i, l in enumerate(m.a.leitor):
            if l.dono:
                print(f"  slot {i}: owner {l.dono:#x}, microphone {l.ep:#010x}, rate {l.taxa}, read {l.lido}, heartbeat "
                      f"{k32.GetTickCount64() - l.batida} ms ago")
    elif sys.argv[1] == "toca":
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from microfone import microfone as filtro
        m = Microfone()
        m.alvo(hash_microfone(filtro.acha(sys.argv[3])[0]))
        m.toca(le_wav(sys.argv[2]))
