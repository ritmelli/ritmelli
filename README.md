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
- ffmpeg no PATH.
- Node ou Deno: o yt-dlp precisa de um runtime de JavaScript para o YouTube entregar todos os
  formatos.

## Instalação

```powershell
python -m pip install -r requirements.txt
```

O modelo de batida (`modelos/compasso.onnx`, ~83 MB) fica fora do git: baixe da release
`modelo-compasso-v1` e ponha em `modelos/`. Sem ele tudo funciona, mas a passagem no tempo
acerta menos (só com o detector em numpy).

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
  ligado. A escolha feita na interface fica gravada em `library/config.json`.
- **No celular**, no mesmo Wi-Fi: o `start` e o `status` mostram o endereço
  (`http://<ip do PC>:8799/`). Qualquer aparelho do Wi-Fi alcança, sem senha;
  `server.py --so-local` atende só o PC.
- Para mexer na interface sem som: `python server.py --mock --port 8801 --data-dir <pasta>`.

## Estrutura

| Arquivo | O que é |
| --- | --- |
| `server.py` | servidor aiohttp: API, eventos (SSE), fila, Automático, busca e download |
| `engine.py` | motor de áudio: mistura, dois decks, passagem de DJ |
| `batida.py`, `compasso.py`, `andamento.py` | andamento, grade de batidas e o 1 do compasso |
| `fx.py` | efeitos de voz |
| `yt_fora.py` | YouTube (yt-dlp e ytmusicapi) num processo à parte |
| `winvol.py` | volume do microfone no Windows |
| `themes/vitrola/` | a interface |
| `gallery.html` | a página inicial, que lista os temas |
| `dev/` | ferramentas de desenvolvimento: prints, medição no celular, geração do pixel art |

O funcionamento de cada peça está em [docs/ARQUITETURA.md](docs/ARQUITETURA.md), e o contrato
entre o servidor e a interface em [API.md](API.md).

## Licença

[GPLv3](LICENSE). As fontes da interface são SIL OFL 1.1 (`themes/vitrola/fonts/`).
