# Ritmelli

O Ritmelli é um aplicativo para Windows 10 e 11 que reproduz músicas e efeitos sonoros no microfone usado no jogo ou
na chamada de voz, junto com a sua voz, enquanto você ouve apenas a música no fone. A interface, um toca-discos em
pixel art, abre em uma janela própria no computador (fechá-la encerra o aplicativo) e, no celular, no navegador, pela
mesma rede Wi-Fi. Funciona com qualquer jogo ou programa de chamada que permita escolher o microfone.

## Recursos

- Reprodução de músicas do YouTube (busca, reprodução imediata por streaming e download em segundo plano) ou de
  arquivos já baixados.
- Fila com transições de DJ: as músicas se emendam no tempo certo, com as batidas alinhadas e o andamento ajustado de
  uma para a outra, sem alterar o tom.
- Tocar parecidas (modo Automático): mantém a fila sempre cheia com músicas parecidas, ordenadas pelo andamento,
  que aparecem na fila marcadas como Automático.
- Sons rápidos: efeitos sonoros curtos que tocam por cima da música.
- Efeitos de voz: rádio de polícia, megafone, locutor de rádio FM, eco, robô, voz grave e outros.

## Requisitos

- Windows 10 ou 11 (o áudio é reproduzido por WASAPI, e o volume do microfone é controlado pelo Core Audio).
- Python 3.12 ou superior.
- O som chega ao jogo pelo filtro de microfone do Ritmelli (`microfone/`), que mistura a música ao microfone real,
  dentro do próprio sistema de áudio do Windows: o jogo e o Discord continuam usando o microfone de sempre. O
  instalador adiciona o filtro a todos os microfones do computador (o som do computador é interrompido por alguns
  segundos) e cria a tarefa do Windows que prepara os microfones conectados depois, sem pedir permissão ao usuário. No
  código-fonte, a DLL do filtro e a do seu motor de efeitos (`voz.dll`, usada para a voz com efeito que sai pelo
  aplicativo) são geradas pelo `microfone\apo\compila.bat` (Visual Studio 2022 com C++), e o filtro é adicionado aos
  microfones com `python microfone\microfone.py instala-todos`, em um terminal de administrador.
- ffmpeg (com o ffprobe) no PATH ou em uma pasta `bin/` ao lado do código.
- Node ou Deno: o yt-dlp precisa de um runtime de JavaScript para que o YouTube disponibilize todos os formatos. O
  Deno também pode ficar na pasta `bin/`.

## Instalação

```powershell
python -m pip install -r requirements.txt
```

O modelo de detecção de batidas (`modelos/compasso.onnx`, cerca de 83 MB) já está incluído no repositório e é gerado
pelo `dev/exporta_compasso.py`. Sem ele, tudo funciona, mas as transições acertam o tempo com menos precisão (apenas
com o detector em numpy).

## Uso

```powershell
.\soundboard.ps1 start    # inicia o servidor e abre a galeria
.\soundboard.ps1 status   # informa se está em execução, o que está tocando e o microfone e o fone em uso
.\soundboard.ps1 stop     # para a música no microfone
```

- No jogo e no Discord, use o mesmo microfone selecionado no Ritmelli, pois o filtro atua apenas nele. A voz original
  volta do filtro para o Ritmelli (para o medidor, para a opção de ouvir a própria voz e para a Mina DJ): sem efeito,
  ela segue diretamente para o microfone; o efeito de voz é aplicado no próprio filtro, sem atraso; com a voz silenciada, o
  Ritmelli envia a voz gerada por ele no lugar; e, se o Ritmelli parar de responder, o filtro restaura a voz original
  automaticamente em 1 segundo. No Discord, use o perfil de entrada **Estúdio** ou desative o Krisp e a
  sensibilidade automática: com qualquer um dos dois ativado, a música chega cortada ou não chega.
- Microfone conectado depois da instalação (por exemplo, um headset USB novo): ao selecioná-lo, o Ritmelli executa a
  tarefa criada pelo instalador, e o som do computador é interrompido por alguns segundos enquanto o Windows o
  prepara.
- O microfone e o fone seguem o padrão do Windows, inclusive quando ele muda com o servidor em execução. A escolha
  feita na interface fica salva em `%LOCALAPPDATA%\Ritmelli\library\config.json`.
- Se o microfone ou o fone selecionado estiver desconectado, o Ritmelli usa o padrão do Windows até que ele volte. Se
  o dispositivo de gravação padrão for um cabo virtual, é usado o primeiro microfone físico.
- Os dados do usuário (áudios baixados, biblioteca e preferências) ficam em `%LOCALAPPDATA%\Ritmelli\library`, e os
  logs do servidor, em `%LOCALAPPDATA%\Ritmelli\logs`. Até a versão 0.4.1, o aplicativo se chamava Vitrola: na
  atualização, os dados de `%LOCALAPPDATA%\Vitrola`, as escolhas e o celular pareado são migrados automaticamente para o
  Ritmelli, sem nenhuma perda (`migra.py`).
- Sem o `soundboard.ps1`: `python ritmelli.py` (aceita os mesmos argumentos do `server.py`).
- Para ver a versão: `python ritmelli.py --version`.
- **No celular**, na mesma rede Wi-Fi: no computador, o botão Celular da interface exibe um QR code. Aponte a câmera
  do celular para ele ou abra o endereço exibido ao lado e digite o código. O celular permanece conectado até ser
  desconectado na mesma tela do computador. Sem esse pareamento, outro aparelho da rede consegue abrir a página, mas
  não consegue alterar nada. A comunicação entre o celular e o computador não é criptografada (HTTP): use-a na rede
  de casa, e não em redes Wi-Fi públicas, como as de cafés ou hotéis. Com `server.py --so-local`, o servidor atende
  apenas o próprio computador.
- Para trabalhar na interface sem áudio: `python server.py --mock --port 8801 --data-dir <pasta>`.

## Executável

O `ritmelli.spec` gera o `ritmelli.exe` com o PyInstaller, em um ambiente que contém apenas as dependências do
aplicativo:

```powershell
python -m venv .venv-build
.venv-build\Scripts\python -m pip install -r requirements.txt pyinstaller
.venv-build\Scripts\pyinstaller --noconfirm ritmelli.spec
```

O resultado fica em `dist\ritmelli\` (o `ritmelli.exe` e a pasta `_internal\`). O ffmpeg, o ffprobe e o Deno não são
incluídos: copie-os para `dist\ritmelli\bin\` (cada build apaga a pasta). Sem console, os logs ficam em
`%LOCALAPPDATA%\Ritmelli\logs`, e o `soundboard.ps1 stop` também encerra o executável.

## Como montar o instalador

O instalador disponibilizado nas versões publicadas é gerado pelo `instalador\monta.ps1`: o script empacota o
aplicativo pelo `ritmelli.spec`, adiciona o ffmpeg, o ffprobe e o Deno e compila o `instalador\ritmelli.iss` com o Inno
Setup. São necessários Windows, Python 3.12 e Inno Setup 6.

```powershell
instalador\monta.ps1                              # gera instalador\saida\Ritmelli-<versão>-setup.exe
instalador\monta.ps1 -Anterior <manifest.json>    # gera também a atualização parcial a partir daquela versão
```

- As versões das bibliotecas ficam fixadas em `instalador\travas.txt` (exceto o yt-dlp, que é sempre incluído na
  versão mais recente, porque as mudanças do YouTube costumam quebrar as versões antigas).
- O ffmpeg somente de áudio (`instalador\ffmpeg\`) e o bootloader do PyInstaller (`instalador\bootloader\`) são
  compilados pela equipe: os scripts ficam ao lado dos executáveis, e o `FONTE.txt` de cada um informa a origem do
  código-fonte e como ele foi compilado.
- A atualização parcial (apenas o que mudou) é gerada pelo `instalador\atualizacao\parcial.py`, e o manifesto que o
  aplicativo consulta, pelo `publica.py` da mesma pasta.
- O instalador cria a tarefa "Ritmelli Atualiza" do Windows (`atualizador.py`), que é executada como SYSTEM no logon e
  a cada 4 horas e instala a nova versão em segundo plano, sem pedido de permissão, quando o Ritmelli está fechado. Se
  ele estiver aberto, a nova versão fica baixada e é instalada quando ele for fechado.
- O pipeline `.github/workflows/monta.yml` faz o mesmo em uma máquina Windows do GitHub e testa o instalador, a
  atualização parcial e a atualização automática em uma máquina limpa.

## Versões e código-fonte

As versões publicadas ficam nas Releases do
[ritmelli/ritmelli-releases](https://github.com/ritmelli/ritmelli-releases), de onde o aplicativo instalado baixa as
atualizações. Cada versão tem neste repositório uma tag com o seu número (por exemplo, `v0.3.6`), com o código do
aplicativo e do instalador daquela versão.

## Code signing policy

Free code signing provided by [SignPath.io](https://about.signpath.io/), certificate by
[SignPath Foundation](https://signpath.org/).

Política de assinatura de código do Ritmelli. Até que a SignPath Foundation aprove o projeto, as versões são
publicadas sem assinatura.

- **Desenvolvimento e revisão:** os [membros da organização](https://github.com/orgs/ritmelli/people). Contribuições
  de pessoas de fora da equipe só são incorporadas após a revisão de um membro.
- **Aprovação de cada assinatura:** os
  [proprietários da organização](https://github.com/orgs/ritmelli/people?query=role%3Aowner).
- **O que é assinado:** o `ritmelli.exe`, o instalador e a atualização parcial, gerados pelo pipeline deste
  repositório (`.github/workflows/monta.yml`) em uma máquina do GitHub, a partir deste código. O ffmpeg, o ffprobe e
  o Deno são incluídos no instalador exatamente como são distribuídos pelos respectivos projetos, sem a nossa
  assinatura.

Committers and reviewers: [members](https://github.com/orgs/ritmelli/people). Approvers:
[owners](https://github.com/orgs/ritmelli/people?query=role%3Aowner).

## Privacidade

A busca, a reprodução e o download de músicas acessam o YouTube e o YouTube Music, a seu pedido. Ao ser aberto, o
Ritmelli verifica no GitHub se há uma nova versão (baixando apenas o manifesto público das versões, sem enviar nenhum
dado seu). O celular pareado se comunica diretamente com o computador, na sua rede. Se você permitir, o Ritmelli
envia dados anônimos de uso e relatórios de erro (`metricas.py`), sem nome, músicas, buscas ou voz. O que é enviado,
para onde e como desativar o envio estão descritos na [política de privacidade](PRIVACIDADE.md), que também é exibida
durante a instalação.

Privacy policy: [PRIVACIDADE.md](PRIVACIDADE.md#ritmelli-privacy-policy). It is shown during installation and describes
the anonymous usage data and error reports, which can be turned off in the installer and in the app.

## Estrutura

| Arquivo | Descrição |
| --- | --- |
| `ritmelli.py` | o ponto de entrada (o mesmo do executável): o servidor e os processos auxiliares |
| `janela.py` | a janela própria do aplicativo no computador, pelo WebView2 (sem ele, o navegador) |
| `ritmelli.spec` | a configuração do executável (PyInstaller) |
| `server.py` | servidor aiohttp: API, eventos (SSE), fila, modo Automático, busca e download |
| `engine.py` | motor de áudio: mixagem, os dois decks e as transições de DJ |
| `batida.py`, `compasso.py`, `andamento.py` | andamento, grade de batidas e o primeiro tempo do compasso |
| `fx.py` | efeitos de voz |
| `versao.py` | a versão do aplicativo |
| `atualizacao.py`, `atualizador.py` | as novas versões: o que a interface exibe e a tarefa do Windows que baixa e instala as atualizações |
| `metricas.py` | os dados anônimos de uso (PostHog) e os relatórios de erro (Sentry), enviados somente com a permissão do usuário: a lista do que é enviado e a política estão no [PRIVACIDADE.md](PRIVACIDADE.md) |
| `i18n.py` | os textos da interface em cada idioma: lê os `.properties` do tema e os aplica à página, além das mensagens que o servidor envia para a interface traduzir |
| `pastas.py` | onde ficam os dados do usuário e onde o aplicativo localiza o ffmpeg, o ffprobe e o Deno |
| `pareamento.py` | o código e o QR code do celular e a lista de celulares conectados |
| `yt_fora.py` | YouTube (yt-dlp e ytmusicapi) em um processo separado |
| `winvol.py` | volume do microfone no Windows |
| `microfone/` | o filtro de microfone: a DLL que o Windows carrega (`apo/`), o canal de comunicação com ela nos dois sentidos (`injeta.py`: a música vai, a voz original volta) e o programa que adiciona e remove o filtro (`microfone.py`, executado pelo instalador) |
| `migra.py` | a troca de nome de Vitrola para Ritmelli no computador de quem já tinha o aplicativo: o registro, as tarefas do Windows e a pasta de instalação de antes |
| `themes/vitrola/` | a interface: o tema Vitrola, um aparelho de som dos anos 70 |
| `gallery/` | a página inicial, que lista os temas (`index.html`), com os textos nos dois idiomas (`i18n/`) |
| `icone/` | o ícone do aplicativo (executável, instalador, aba do navegador e celular), gerado pelo `dev/icone.py` |
| `dev/` | ferramentas de desenvolvimento: capturas de tela, medições no celular e geração do pixel art |
| `instalador/` | o instalador: `monta.ps1`, `ritmelli.iss`, ffmpeg, bootloader, a atualização parcial e os textos de licença |
| `.github/workflows/monta.yml` | o pipeline que monta e testa o instalador |

O funcionamento de cada componente está descrito em [docs/ARQUITETURA.md](docs/ARQUITETURA.md), e o contrato entre o
servidor e a interface, em [API.md](API.md).

## Licença

[GPLv3](LICENSE). As fontes da interface estão sob a licença SIL OFL 1.1 (`themes/vitrola/fonts/`), e o modelo de
detecção de batidas (`modelos/compasso.onnx`, exportado do beat_this) está sob a licença MIT
(`modelos/LICENSE-beat_this.txt`).
