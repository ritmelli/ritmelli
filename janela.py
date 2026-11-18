"""A janela da Vitrola (#99): a interface numa janela propria do Windows, pelo WebView2 (o motor do Edge, que ja vem no
Windows 11 e no Windows 10 atualizado), no lugar da aba do navegador. A janela tem icone e nome na barra de tarefas,
e fechar (o X) desliga tudo, como o botao Desligar da interface: o servidor, o motor de audio e a musica no microfone.
Abrir a Vitrola de novo com ela ligada traz esta janela para a frente (o vitrola.py pede pelo /api/janela/foco).

Sem o WebView2 (ou sem o pywebview, rodando pelo codigo), nada muda: o servidor abre a pagina no navegador, como
antes. O tamanho e a posicao da janela ficam em %LOCALAPPDATA%\\Vitrola\\janela.json, e o que a pagina guarda (o
localStorage) na pasta janela\\ ao lado, para nao se perder ao fechar."""
import ctypes
import json
import sys
import threading
from pathlib import Path

import pastas

TITULO = "Ritmelli"
ESTADO = pastas.DADOS / "janela.json"
GUARDA = pastas.DADOS / "janela"  # o que o WebView2 guarda da pagina (localStorage, cookies)
LARGURA, ALTURA = 1280, 820
MINIMO = (720, 540)
FUNDO = "#BDB4A4"  # o aluminio do tema, para nao piscar branco enquanto a pagina carrega
# a barra de titulo na madeira da mesa, no lugar do branco do Windows: o tom das juntas das tabuas, e o titulo no creme
# das plaquetas
BARRA, BARRA_TEXTO = "#4F220E", "#E9E1D2"
# o runtime do WebView2 (estavel, beta, dev e canary), como o pywebview procura: a versao fica no "pv" da chave
WEBVIEW2 = ("{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}", "{2CD8A007-E189-409D-A2C8-9AF4EF3C72AA}",
            "{0D50BFEC-CD6A-4F9A-964C-C7416E3ACB10}", "{65C35B14-6C1D-4122-AC46-7148CC9D6497}")


def tem_webview2():
    """O runtime do WebView2 instalado (para a maquina ou so para quem usa). Sem ele, o pywebview cairia no motor do
    Internet Explorer, que nao roda a pagina: ai fica o navegador."""
    if sys.platform != "win32":
        return False
    import winreg
    for raiz, sub in ((winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients"),
                      (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\EdgeUpdate\Clients"),
                      (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\EdgeUpdate\Clients")):
        for guid in WEBVIEW2:
            try:
                with winreg.OpenKey(raiz, rf"{sub}\{guid}") as k:
                    pv = str(winreg.QueryValueEx(k, "pv")[0])
            except OSError:
                continue
            if pv and pv.strip("0.") != "":
                return True
    return False


def _icone():
    """O .ico do app: no executavel, o pywebview ja pega o icone do vitrola.exe; pelo codigo, sem isto, sairia o do
    Python."""
    for p in (pastas.APP / "_internal" / "icone" / "vitrola.ico", Path(__file__).resolve().parent / "icone" / "vitrola.ico"):
        if p.is_file():
            return str(p)
    return None


def _cabe_na_tela(x, y, largura, altura):
    """Algum pedaco da barra de titulo (os 40 px de cima, no meio) cai num monitor ligado: o monitor de onde a janela
    estava pode ter saido."""
    if sys.platform != "win32":
        return True

    class PONTO(ctypes.Structure):
        _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

    u32 = ctypes.windll.user32
    u32.MonitorFromPoint.restype = ctypes.c_void_p
    return bool(u32.MonitorFromPoint(PONTO(int(x + largura / 2), int(y + 20)), 0))  # MONITOR_DEFAULTTONULL


def _colorref(cor):
    """'#RRGGBB' no COLORREF do Windows (0x00BBGGRR)."""
    r, g, b = int(cor[1:3], 16), int(cor[3:5], 16), int(cor[5:7], 16)
    return r | g << 8 | b << 16


def pinta_barra(hwnd):
    """A barra de titulo na cor da mesa (DWMWA_CAPTION_COLOR e DWMWA_TEXT_COLOR, do Windows 11 em diante; no 10 o
    Windows recusa e ela fica escura so pelo modo escuro). O modo escuro e o que deixa claros os botoes de minimizar,
    maximizar e fechar em cima da cor escura."""
    if sys.platform != "win32" or not hwnd:
        return
    dwm = ctypes.windll.dwmapi
    dwm.DwmSetWindowAttribute.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p, ctypes.c_uint]

    def poe(atributo, valor):
        v = ctypes.c_int(valor)
        return dwm.DwmSetWindowAttribute(hwnd, atributo, ctypes.byref(v), ctypes.sizeof(v))

    if poe(20, 1) != 0:  # DWMWA_USE_IMMERSIVE_DARK_MODE; o Windows 10 antes do 20H1 conhece pelo 19
        poe(19, 1)
    poe(35, _colorref(BARRA))  # DWMWA_CAPTION_COLOR
    poe(36, _colorref(BARRA_TEXTO))  # DWMWA_TEXT_COLOR


def _le_estado():
    try:
        e = json.loads(ESTADO.read_text(encoding="utf-8"))
        if not isinstance(e, dict):
            return {}
    except (OSError, ValueError):
        return {}
    out = {}
    try:
        largura, altura = max(int(e["largura"]), MINIMO[0]), max(int(e["altura"]), MINIMO[1])
        out.update(largura=largura, altura=altura)
        if e.get("x") is not None and _cabe_na_tela(int(e["x"]), int(e["y"]), largura, altura):
            out.update(x=int(e["x"]), y=int(e["y"]))
    except (KeyError, TypeError, ValueError):
        pass
    out["maximizada"] = e.get("maximizada") is True
    return out


class Janela:
    """A janela da pagina. abre() roda o laco da janela e so volta quando ela fecha: tem de ser na thread principal
    (o servidor vai para outra). fecha() e foco() podem vir de qualquer thread."""

    def __init__(self, url):
        self.url = url
        self.w = None
        self.maximizada = False
        self.pronta = threading.Event()

    def abre(self, ao_fechar):
        import webview
        e = _le_estado()
        # a primeira vez, maximizada: a mesa de DJ (as duas pickups numa tela so) so monta com a pagina a partir de
        # 1400 px de largura (o mqUnica do tema); nos 1280 de antes ela caia no layout estreito, o de navegador pequeno
        self.maximizada = e.get("maximizada", True)
        self.w = webview.create_window(TITULO, self.url, width=e.get("largura", LARGURA), height=e.get("altura", ALTURA),
                                       x=e.get("x"), y=e.get("y"), min_size=MINIMO, maximized=self.maximizada,
                                       background_color=FUNDO, text_select=True, zoomable=True)
        self.w.events.maximized += lambda *_: setattr(self, "maximizada", True)
        self.w.events.restored += lambda *_: setattr(self, "maximizada", False)
        self.w.events.closing += lambda *_: self._guarda()
        self.w.events.closed += lambda *_: ao_fechar()
        self.w.events.shown += lambda *_: self.pronta.set()
        self.w.events.before_show += lambda *_: self._pinta()  # na thread da janela, antes de ela aparecer branca
        GUARDA.mkdir(parents=True, exist_ok=True)
        webview.start(gui="edgechromium", private_mode=False, storage_path=str(GUARDA), icon=_icone())

    def _hwnd(self):
        try:
            return int(self.w.native.Handle.ToInt64())
        except Exception:  # noqa: BLE001 - sem a janela nativa, a barra fica a do Windows
            return None

    def _pinta(self):
        pinta_barra(self._hwnd())
        # o pywebview poe o modo escuro da barra igual ao do Windows quando o tema dele muda (e os botoes da barra
        # ficariam pretos na madeira): a barra pinta de novo depois dele, que assinou antes
        try:
            from Microsoft.Win32 import SystemEvents
            SystemEvents.UserPreferenceChanged += lambda *_: pinta_barra(self._hwnd())
        except Exception as ex:  # noqa: BLE001 - so o tema trocado com a janela aberta perde a cor
            print(f"window: title bar ({ex})", flush=True)

    def _guarda(self):
        """O tamanho e a posicao, para a proxima vez. Maximizada, guarda so isso: o tamanho seria o da tela."""
        w = self.w
        try:
            e = _le_estado() if self.maximizada else {"largura": w.width, "altura": w.height, "x": w.x, "y": w.y}
            e["maximizada"] = self.maximizada
            ESTADO.parent.mkdir(parents=True, exist_ok=True)
            pastas.save_json(ESTADO, e)
        except (OSError, TypeError, ValueError, AttributeError) as ex:
            print(f"window: couldn't save the size ({ex})", flush=True)

    def fecha(self):
        """O servidor parou sozinho (o Desligar da pagina, a atualizacao): a janela vai junto."""
        if self.w is not None:
            try:
                self.w.destroy()
            except Exception as ex:  # noqa: BLE001 - a janela que ja fechou nao impede o resto de sair
                print(f"window: {ex}", flush=True)

    def foco(self):
        """A Vitrola foi aberta de novo: esta janela vem para a frente, restaurada se estava minimizada. Quem abriu
        chamou o AllowSetForegroundWindow antes (vitrola.py): sem isso, o Windows so pisca o botao na barra."""
        if self.w is None:
            return False
        try:
            self.w.restore()
            self.w.show()
            if sys.platform == "win32" and self.w.native is not None:
                hwnd = int(self.w.native.Handle.ToInt64())
                ctypes.windll.user32.SetForegroundWindow(ctypes.c_void_p(hwnd))
        except Exception as ex:  # noqa: BLE001 - trazer para a frente e conforto, nao pode derrubar o pedido
            print(f"window: focus ({ex})", flush=True)
            return False
        return True


def se_der(url):
    """A Janela, se o WebView2 e o pywebview estao aqui; senao None (o servidor abre o navegador)."""
    if not tem_webview2():
        print("window: no WebView2 runtime; opening the browser", flush=True)
        return None
    try:
        import webview  # noqa: F401
    except ImportError as ex:
        print(f"window: no pywebview ({ex}); opening the browser", flush=True)
        return None
    return Janela(url)
