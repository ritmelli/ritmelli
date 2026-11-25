# Política de privacidade do Ritmelli

[English below](#ritmelli-privacy-policy)

O Ritmelli é executado no seu computador. Ele acessa a internet em quatro situações: quando você busca, ouve ou baixa
músicas do YouTube e do YouTube Music; quando ele procura e mostra as capas dos discos (para cada disco da prateleira,
ele busca a mesma faixa no YouTube Music pelo título, com o nome do canal na frente quando o título não o traz, e as
capas vêm dos servidores de imagens do YouTube e do YouTube Music); quando ele consulta no GitHub o manifesto público
das versões e, se houver uma nova versão, baixa a atualização, sem enviar nenhum dado seu; e, se você permitir, quando
ele envia **dados anônimos de uso e relatórios de erro**, conforme descrito abaixo. O YouTube e o YouTube Music são
serviços do Google, sujeitos à [política de privacidade do Google](https://policies.google.com/privacy?hl=pt-BR). Além
disso, o instalador baixa do GitHub as vozes do pedal de troca de voz (do
[ritmelli-voices](https://github.com/ritmelli/ritmelli-voices)), também sem enviar nenhum dado seu. O GitHub é um serviço
da Microsoft, sujeito à
[declaração de privacidade do GitHub](https://docs.github.com/pt/site-policy/privacy-policies/github-general-privacy-statement).

A troca de voz é feita no seu computador: a sua voz é convertida ali mesmo, pela placa de vídeo, e só vai para onde o
seu microfone já vai (o jogo ou a chamada). O ONNX Runtime, a biblioteca da Microsoft que executa os modelos, vem com a
telemetria da Microsoft ligada no Windows, e o Ritmelli a desliga. A DirectML, o componente da Microsoft que leva essa
conta para a placa de vídeo, segue os termos de licença da Microsoft (no arquivo `TERCEIROS.txt`, na pasta do Ritmelli),
que preveem a coleta de dados de uso pela Microsoft.

## Dados de uso e relatórios de erro

**Finalidade:** saber quantas pessoas usam o Ritmelli, se as novas versões estão chegando a elas, quais erros ocorrem e
quais recursos são de fato utilizados (cada efeito de voz, a reprodução de músicas), para decidir o que corrigir,
melhorar ou remover.

**O que é enviado**, sempre acompanhado de um código aleatório desta instalação (que não está vinculado a você e é
substituído por outro em caso de reinstalação), das versões do Ritmelli e do Windows e do idioma do Windows:

- um registro por dia em que o Ritmelli é utilizado;
- a versão anterior, na primeira vez que uma nova versão é aberta;
- o efeito de voz ativado, sempre que um efeito é ativado;
- a cada meia hora de uso e ao fechar o aplicativo: por quantos segundos a música tocou, por quantos a voz ficou com
  efeito e por quantos cada efeito ficou ativo;
- no mesmo momento, a saúde do som que vai para o jogo naquela meia hora (o evento `audio`): quantas vezes o som
  falhou porque o microfone ficou sem música para ler (`secas`), quantas dessas foram numa passagem entre músicas
  (`secas_passagem`) e quantas durante um ajuste de andamento (`secas_esticamento`), a menor folga de som à frente do
  microfone (`folga_min_ms`) e a maior demora entre dois envios (`volta_max_ms`), quantas passagens foram preparadas
  (`passagens`), quantos ajustes de andamento começaram (`esticamentos`) e por quanto tempo algum estava em curso
  (`esticamento_ms`), quantas vezes e por quantos segundos o microfone deixou de receber a música
  (`leitor_perdido`, `leitor_perdido_s`), por quantos segundos o efeito de voz rodou no filtro do microfone
  (`fx_no_filtro_s`) e a voz veio do microfone de reserva, aberto pelo Ritmelli (`mic_reserva_s`), e a taxa de
  amostragem do microfone (`voz_taxa`, como 48000);
- os erros: o tipo do erro, o ponto do código em que ocorreu (arquivo, função e linha) e a mensagem do erro, sem
  nenhum trecho entre aspas, sem endereços e sem caminhos de pastas.

**O que nunca é enviado:** nome, conta, e-mail, nomes de músicas, buscas, links, áudio, a sua voz, o nome dos seus
dispositivos (microfone e fone) ou os seus arquivos. O endereço IP não é armazenado.

**Para onde vão os dados:** os dados de uso, para o [PostHog](https://posthog.com/privacy), e os relatórios de erro,
para o [Sentry](https://sentry.io/privacy/), ambos com armazenamento na União Europeia. Os dados de uso são mantidos por
até 1 ano, e os relatórios de erro, por até 90 dias. Somente a equipe do Ritmelli tem acesso a eles, e os dados não são
vendidos nem usados para publicidade.

**Como ativar ou desativar:** durante a instalação, na página "Dados de uso e erros", e depois, no Ritmelli, em
**Microfone e fone**. Com o envio desativado, nada é enviado, e o que ainda não havia sido enviado é descartado. Quem
atualizar a partir de uma versão que não enviava esses dados verá um aviso no Ritmelli, e nada será enviado antes da sua escolha.
Quando o que é enviado aumenta, quem tinha ativado o envio vê o aviso de novo, com o texto atual, e o que é novo
(como a saúde do som) só é enviado depois de ativar com esse texto; até lá, continua sendo enviado só o que o texto
anterior descrevia.

**Base legal:** o legítimo interesse em melhorar o Ritmelli e corrigir os erros do aplicativo (LGPD, art. 7º, IX), com os dados
reduzidos ao mínimo necessário, sem identificação de ninguém e com a opção de desativar o envio a qualquer momento.

**O código responsável pelo envio** é aberto: [`metricas.py`](metricas.py), com a lista completa do que pode ser
enviado, e o teste que verifica essa lista, [`dev/testa_metricas.py`](dev/testa_metricas.py).

## Controlador dos dados

Behling Informática Ltda., que publica o Ritmelli. Para tirar dúvidas sobre os seus dados ou solicitar a exclusão dos dados de uma
instalação (informando o código dela, que está no arquivo `%LOCALAPPDATA%\Ritmelli\metricas.json`),
[abra uma issue](https://github.com/ritmelli/ritmelli/issues) sem incluir dados pessoais; a resposta será dada na própria issue.

---

# Ritmelli privacy policy

Ritmelli runs on your computer. It connects to the internet in four situations: when you search for, listen to, or
download music from YouTube and YouTube Music; when it finds and shows record covers (for each record on the shelf, it
looks up the same track on YouTube Music by its title, with the channel name in front when the title doesn't include it,
and the covers come from the image servers of YouTube and YouTube Music); when it checks the public release manifest on
GitHub and, if there is a new version, downloads the update, without sending any of your data; and, if you allow it,
when it sends **anonymous usage data and error reports**, as described below. YouTube and YouTube Music are Google
services, covered by [Google's privacy policy](https://policies.google.com/privacy). In addition, the installer
downloads the voices for the voice changer pedal from GitHub (from
[ritmelli-voices](https://github.com/ritmelli/ritmelli-voices)), also without sending any of your data. GitHub is a
Microsoft service, covered by the
[GitHub General Privacy Statement](https://docs.github.com/en/site-policy/privacy-policies/github-general-privacy-statement).

The voice changer works on your computer: your voice is converted right there, on the graphics card, and only goes
where your microphone already goes (the game or the call). ONNX Runtime, the Microsoft library that runs the models,
comes with Microsoft telemetry turned on in Windows, and Ritmelli turns it off. DirectML, the Microsoft component that
runs those calculations on the graphics card, follows Microsoft's license terms (in the `TERCEIROS.txt` file, in the
Ritmelli folder), which provide for Microsoft collecting usage data.

## Usage data and error reports

**Purpose:** to learn how many people use Ritmelli, whether new versions are reaching them, which errors occur, and
which features are actually used (each voice effect, music playback), so we can decide what to fix, improve, or remove.

**What is sent**, always together with a random ID for this installation (it is not tied to you and is replaced by a
new one if you reinstall), the Ritmelli and Windows versions, and the Windows language:

- one entry for each day Ritmelli is used;
- the previous version, the first time a new version is opened;
- which voice effect was turned on, each time one is turned on;
- every half hour of use and when the app closes: how many seconds music played, how many seconds a voice effect was
  on, and how many seconds each effect stayed on;
- at the same time, the health of the sound sent to the game during that half hour (the `audio` event): how many times
  the sound dropped out because the microphone had no music to read (`secas`), how many of those happened during a
  transition between songs (`secas_passagem`) and how many during a tempo adjustment (`secas_esticamento`), the
  smallest buffer of sound ahead of the microphone (`folga_min_ms`) and the longest delay between two sends
  (`volta_max_ms`), how many transitions were prepared (`passagens`), how many tempo adjustments started
  (`esticamentos`) and for how long one was running (`esticamento_ms`), how many times and for how many seconds the
  microphone stopped receiving the music (`leitor_perdido`, `leitor_perdido_s`), for how many seconds the voice effect
  ran in the microphone filter (`fx_no_filtro_s`) and the voice came from the backup microphone opened by Ritmelli
  (`mic_reserva_s`), and the microphone's sample rate (`voz_taxa`, such as 48000);
- errors: the error type, the place in the code where it occurred (file, function, and line), and the error message,
  with anything in quotes, addresses, and folder paths removed.

**What is never sent:** name, account, email, song names, searches, links, audio, your voice, the names of your devices
(microphone and headphones), or your files. Your IP address is not stored.

**Where the data goes:** usage data to [PostHog](https://posthog.com/privacy) and error reports to
[Sentry](https://sentry.io/privacy/), both stored in the European Union. Usage data is kept for up to 1 year, and error
reports for up to 90 days. Only the Ritmelli team has access to them, and the data is never sold or used for
advertising.

**How to turn it on or off:** during installation, on the "Usage Data and Errors" page, and later, in Ritmelli, under
**Mic and headphones**. When sending is off, nothing is sent, and anything not yet sent is discarded. Anyone updating
from a version that did not send this data will see a notice in Ritmelli, and nothing is sent until they make a choice.
When what is sent grows, anyone who had sending on sees the notice again, with the current text, and the new data
(such as the sound health) is only sent after they turn sending on with that text; until then, only what the previous
text described keeps being sent.

**Legal basis:** our legitimate interest in improving Ritmelli and fixing its errors (Brazil's LGPD, art. 7, IX), with
the data kept to the minimum necessary, without identifying anyone, and with the option to turn sending off at any time.

**The code that sends the data** is open source: [`metricas.py`](metricas.py), with the full list of what can be sent,
and the test that checks that list, [`dev/testa_metricas.py`](dev/testa_metricas.py).

## Data controller

Behling Informática Ltda., the publisher of Ritmelli. For questions about your data, or to request the deletion of
an installation's data (please include its ID, found in `%LOCALAPPDATA%\Ritmelli\metricas.json`),
[open an issue](https://github.com/ritmelli/ritmelli/issues) without including any personal data; we will reply there.
