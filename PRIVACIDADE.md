# Política de privacidade da Vitrola

[English below](#vitrola-privacy-policy)

A Vitrola roda no seu PC. Ela fala com a internet em três casos: quando você busca, ouve ou baixa música do YouTube e do
YouTube Music (você pede); quando confere no GitHub se existe versão nova (só baixa o manifesto público das versões);
e, se você deixar, quando envia **dados anônimos de uso e os erros** que acontecem, como explicado aqui.

## Dados de uso e erros

**Para quê:** saber quantas pessoas usam a Vitrola, se as versões novas estão chegando, que erros acontecem e o que é
usado de verdade (cada efeito de voz, a música), para decidir o que corrigir, melhorar ou tirar.

**O que vai**, sempre junto de um código aleatório desta instalação (não é ligado a você; reinstalar gera outro), da
versão da Vitrola, da versão do Windows e da língua do Windows:

- um aviso por dia em que a Vitrola é usada;
- a versão de antes, na primeira vez que uma versão nova abre;
- quando um efeito de voz é ligado, qual efeito;
- a cada meia hora de uso e ao fechar: quantos segundos a música tocou, quantos a voz ficou com efeito, e quantos cada
  efeito ficou ligado;
- os erros: o tipo do erro, o lugar do código onde aconteceu (arquivo, função e linha) e a mensagem dele sem o que está
  entre aspas, sem endereços e sem caminhos de pastas.

**O que nunca vai:** nome, conta, e-mail, o nome de músicas, buscas, links, áudio, a sua voz, o nome dos seus aparelhos
(microfone e fone) ou os seus arquivos. O endereço IP não é guardado.

**Para onde vai:** os dados de uso para o [PostHog](https://posthog.com/privacy) e os erros para o
[Sentry](https://sentry.io/privacy/), os dois com os dados guardados na União Europeia. Os dados de uso ficam guardados
por até 1 ano, e os erros, por até 90 dias. Ninguém além da equipe da Vitrola tem acesso, e os dados não são vendidos
nem usados para propaganda.

**Como ligar ou desligar:** na instalação, na página "Dados de uso e erros"; e depois, na Vitrola, em **Microfone e
fone**. Desligado, nada sai, e o que ainda não tinha saído é descartado. Quem atualizou de uma versão sem esses dados vê
um aviso na Vitrola, e nada sai antes de escolher.

**Base legal:** o legítimo interesse de melhorar a Vitrola e corrigir os erros dela (LGPD, art. 7º, IX), com os dados
reduzidos ao mínimo, sem identificar ninguém, e com a opção de desligar a qualquer momento.

**O código que envia** é aberto: [`metricas.py`](metricas.py), com a lista inteira do que pode ir, e o teste que confere
essa lista, [`dev/testa_metricas.py`](dev/testa_metricas.py).

## Quem cuida

Behling Informática Ltda, que publica a Vitrola. Para falar sobre os seus dados, ou pedir que os dados de uma instalação
sejam apagados (mande o código dela, no arquivo `%LOCALAPPDATA%\Vitrola\metricas.json`):
[abra uma issue](https://github.com/ritmelli/ritmelli/issues) sem dados pessoais nela, que a gente responde por lá.

---

# Vitrola privacy policy

Vitrola runs on your PC. It talks to the internet in three cases: when you search, listen to or download music from
YouTube and YouTube Music (you ask for it); when it checks GitHub for a new version (it only downloads the public
release manifest); and, if you allow it, when it sends **anonymous usage data and the errors** that happen, as
explained here.

## Usage data and errors

**What for:** to know how many people use Vitrola, whether new versions are arriving, which errors happen and what is
really used (each voice effect, the music), so we can decide what to fix, improve or remove.

**What is sent**, always with a random code for this installation (it is not tied to you; reinstalling creates a new
one), the Vitrola version, the Windows version and the Windows language:

- one notice per day Vitrola is used;
- the previous version, the first time a new version opens;
- when a voice effect is turned on, which effect;
- every half hour of use and on closing: how many seconds music played, how many the voice had an effect on, and how
  many each effect stayed on;
- errors: the error type, the place in the code where it happened (file, function and line) and its message without
  anything in quotes, without addresses and without folder paths.

**What is never sent:** name, account, email, song names, searches, links, audio, your voice, the names of your devices
(microphone and headphones) or your files. The IP address is not stored.

**Where it goes:** usage data to [PostHog](https://posthog.com/privacy) and errors to
[Sentry](https://sentry.io/privacy/), both with the data stored in the European Union. Usage data is kept for up to 1
year, and errors for up to 90 days. Nobody outside the Vitrola team has access, and the data is not sold or used for
advertising.

**How to turn it on or off:** during installation, on the "Usage data and errors" page; and later, in Vitrola, under
**Mic and headphones**. When it's off, nothing is sent, and whatever hadn't been sent yet is discarded. Anyone who
updated from a version without this data sees a notice in Vitrola, and nothing is sent before they choose.

**Legal basis:** the legitimate interest of improving Vitrola and fixing its errors (Brazil's LGPD, art. 7, IX), with
the data kept to a minimum, without identifying anyone, and with the option to turn it off at any time.

**The code that sends it** is open: [`metricas.py`](metricas.py), with the full list of what can be sent, and the test
that checks that list, [`dev/testa_metricas.py`](dev/testa_metricas.py).

## Who is responsible

Behling Informática Ltda, the publisher of Vitrola. To talk about your data, or to ask for an installation's data to be
deleted (send its code, found in `%LOCALAPPDATA%\Vitrola\metricas.json`):
[open an issue](https://github.com/ritmelli/ritmelli/issues) without personal data in it, and we'll answer there.
