# Vitrola

Um toca-discos em pixel art que toca música e efeitos no microfone do jogo ou da chamada de
voz, misturados com a sua voz, enquanto só a música toca no seu fone. A interface abre no
navegador do PC ou do celular no mesmo Wi-Fi. Nasceu para o VRChat e serve para qualquer
programa que deixe escolher o microfone.

## O que faz

- Toca do YouTube (busca, stream na hora e download por trás) ou de arquivos baixados.
- Fila com passagem de DJ: emenda no tempo, alinha as batidas e acerta o andamento de uma
  música para a outra sem mudar o tom.
- Automático: mantém a fila cheia com músicas parecidas, ordenadas pelo andamento.
- Sons rápidos que tocam por cima da música.
- Efeitos de voz: rádio de polícia, megafone, locutor de FM, eco, robô, voz grossa e outros.

## Requisitos

- Windows 10 ou 11 (o áudio sai por WASAPI e o volume do microfone vem do Core Audio).
- Python 3.12 ou mais novo.
- [VB-Audio Virtual Cable](https://vb-audio.com/Cable/): o cabo que leva o som para o
  microfone do jogo.
- ffmpeg (com o ffprobe) no PATH, ou numa pasta `bin/` ao lado do código.
- Node ou Deno: o yt-dlp precisa de um runtime de JavaScript para o YouTube entregar todos os
  formatos. O Deno também vale na `bin/`.

## Instalação

```powershell
python -m pip install -r requirements.txt
```

O modelo de batida (`modelos/compasso.onnx`, ~83 MB) já vem no repositório. Ele sai do
`dev/exporta_compasso.py`; sem ele tudo funciona, mas a passagem no tempo acerta menos (só
com o detector em numpy).

## Uso

```powershell
.\soundboard.ps1 start    # liga e abre a galeria
.\soundboard.ps1 status
.\soundboard.ps1 stop     # a voz para de passar pelo cabo
```

- No jogo, o microfone precisa ser **CABLE Output (VB-Audio Virtual Cable)**. Desligou o
  servidor, volte o microfone do jogo para o microfone de verdade.
- "Escutar este dispositivo" no CABLE Output precisa ficar desligado, senão a própria voz
  volta no fone.
- Microfone e fone seguem o padrão do Windows, inclusive quando ele muda com o servidor
  ligado. A escolha feita na interface fica gravada em
  `%LOCALAPPDATA%\Vitrola\library\config.json`.
- Os dados de quem usa (áudio baixado, biblioteca, escolhas) moram em
  `%LOCALAPPDATA%\Vitrola\library`, e os logs do servidor em
  `%LOCALAPPDATA%\Vitrola\logs`.
- Sem o `soundboard.ps1`: `python vitrola.py` (aceita os mesmos argumentos do `server.py`).
- A versão: `python vitrola.py --version`.
- **No celular**, no mesmo Wi-Fi: no PC, o botão Celular da interface mostra um QR. Aponte a
  câmera do celular para ele, ou abra o endereço que aparece ao lado e digite o código. O
  celular fica conectado até ser desconectado na mesma tela do PC. Sem esse pareamento, outro
  aparelho do Wi-Fi abre a página, mas não mexe em nada. A conversa entre o celular e o PC
  não é criptografada (HTTP): use na rede de casa, não em Wi-Fi aberta de café ou hotel.
  `server.py --so-local` atende só o PC.
- Para mexer na interface sem som: `python server.py --mock --port 8801 --data-dir <pasta>`.

## Executável

O `vitrola.spec` gera o `vitrola.exe` pelo PyInstaller, num ambiente só com as dependências
do app:

```powershell
python -m venv .venv-build
.venv-build\Scripts\python -m pip install -r requirements.txt pyinstaller
.venv-build\Scripts\pyinstaller --noconfirm vitrola.spec
```

Sai em `dist\vitrola\` (o `vitrola.exe` e a `_internal\`). O ffmpeg, o ffprobe e o Deno não
vão junto: copie para `dist\vitrola\bin\` (cada build apaga a pasta). Sem console, os logs
ficam em `%LOCALAPPDATA%\Vitrola\logs`, e o `soundboard.ps1 stop` desliga o exe também.

## Estrutura

| Arquivo | O que é |
| --- | --- |
| `vitrola.py` | o ponto de entrada (o mesmo do executável): o servidor e os processos auxiliares |
| `vitrola.spec` | a receita do executável (PyInstaller) |
| `server.py` | servidor aiohttp: API, eventos (SSE), fila, Automático, busca e download |
| `engine.py` | motor de áudio: mistura, dois decks, passagem de DJ |
| `batida.py`, `compasso.py`, `andamento.py` | andamento, grade de batidas e o 1 do compasso |
| `fx.py` | efeitos de voz |
| `versao.py` | a versão do app |
| `pastas.py` | onde moram os dados de quem usa, e onde o app acha o ffmpeg, o ffprobe e o Deno |
| `pareamento.py` | o código e o QR do celular, e os celulares conectados |
| `yt_fora.py` | YouTube (yt-dlp e ytmusicapi) num processo à parte |
| `winvol.py` | volume do microfone no Windows |
| `themes/vitrola/` | a interface |
| `gallery.html` | a página inicial, que lista os temas |
| `dev/` | ferramentas de desenvolvimento: prints, medição no celular, geração do pixel art |

O funcionamento de cada peça está em [docs/ARQUITETURA.md](docs/ARQUITETURA.md), e o contrato
entre o servidor e a interface em [API.md](API.md).

## Licença

[GPLv3](LICENSE). As fontes da interface são SIL OFL 1.1 (`themes/vitrola/fonts/`).
