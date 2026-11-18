# Política de privacidade do Ritmelli

[English below](#ritmelli-privacy-policy)

O Ritmelli é executado no seu computador. Ele acessa a internet em três situações: quando você busca, ouve ou baixa
músicas do YouTube e do YouTube Music, a seu pedido; quando ele consulta no GitHub o manifesto público das versões e, se
houver uma nova versão, baixa a atualização, sem enviar nenhum dado seu; e, se você permitir, quando ele envia **dados
anônimos de uso e relatórios de erro**, conforme descrito abaixo.

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

Ritmelli runs on your computer. It connects to the internet in three situations: when you search for, listen to, or
download music from YouTube and YouTube Music, at your request; when it checks the public release manifest on GitHub
and, if there is a new version, downloads the update, without sending any of your data; and, if you allow it, when it
sends **anonymous usage data and error reports**, as described below.

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

**Legal basis:** our legitimate interest in improving Ritmelli and fixing its errors (Brazil's LGPD, art. 7, IX), with
the data kept to the minimum necessary, without identifying anyone, and with the option to turn sending off at any time.

**The code that sends the data** is open source: [`metricas.py`](metricas.py), with the full list of what can be sent,
and the test that checks that list, [`dev/testa_metricas.py`](dev/testa_metricas.py).

## Data controller

Behling Informática Ltda., the publisher of Ritmelli. For questions about your data, or to request the deletion of
an installation's data (please include its ID, found in `%LOCALAPPDATA%\Ritmelli\metricas.json`),
[open an issue](https://github.com/ritmelli/ritmelli/issues) without including any personal data; we will reply there.
