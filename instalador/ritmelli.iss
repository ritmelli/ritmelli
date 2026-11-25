; O instalador do Ritmelli (Inno Setup 6). Nao compile direto: o monta.ps1 congela o app, baixa o ffmpeg e o
; Deno e passa os caminhos e a versao (/DVersao, /DApp, /DFfmpeg, /DDeno, /DLicenca e /DTerceiros, a GPLv3 do
; Ritmelli e os avisos de terceiros que o terceiros.py monta, e /DVozes e /DLicencaVozes, as vozes do vozes_iss.py).
;
; Instala o ritmelli.exe em Program Files, com o ffmpeg, o ffprobe e o Deno na bin\ (o app acha la, ver o
; pastas.py), cria a regra do firewall para o celular alcancar o PC e pendura o filtro do Ritmelli em todo microfone
; do PC (microfone\microfone.py): e por ele que a musica toca no microfone que o jogo ja usa. Tambem cria a tarefa
; do Windows que pendura o filtro num microfone que aparecer depois, sem o app pedir administrador, e a que atualiza o
; Ritmelli sozinho (atualizador.py): ela roda este setup como SYSTEM, em silencio e sem /reabrir, com o Ritmelli fechado.
; Desinstalar tira o filtro, devolve o efeito original de cada microfone e apaga as duas tarefas. Os dados de quem usa
; (%LOCALAPPDATA%\Ritmelli) ficam.
;
; A pasta do app tem de ser protegida (o protegida.ps1, a mesma regra do pastas.pasta_protegida do app): as duas
; tarefas rodam como SYSTEM o ritmelli.exe dela, e a de atualizacao roda dali o setup baixado. Por isso nao ha pagina de
; escolher a pasta: o destino e a instalacao anterior, quando ela passa na regra, ou a Program Files\Ritmelli, ou a
; primeira Program Files\Ritmelli-N livre quando aquela nao passa. A instalacao anterior que fica para tras (fora de
; Program Files, ou numa pasta que nao passa) nao e apagada nem desinstalada: so o ritmelli.exe dela vira
; ritmelli.exe.antigo (renomeia.ps1), e nenhuma tarefa aponta mais para ela. Um /DIR= e conferido do mesmo jeito.
;
; A troca de nome (#58): ate a 0.4.1 o app se chamava Vitrola (vitrola.exe em Program Files\Vitrola, as tarefas
; "Vitrola Atualiza" e \Vitrola\Microfone, o HKLM\SOFTWARE\Vitrola). Por cima de uma instalacao dessas, o setup fecha o
; app de antes (pelo caminho do vitrola.exe, encerra.ps1), muda a pasta para Program Files\Ritmelli, copia o registro
; antes do filtro, troca as tarefas e, no fim, apaga o que sobrou do app de antes (migra.py, so numa pasta protegida). Os dados de quem usa mudam de
; pasta no proprio app, ao abrir (pastas.migra). O AppId e o mesmo: para o Windows e a mesma instalacao.
;
; Com /DParcial e /DApaga (o monta.ps1 -Anterior), sai a atualizacao parcial, o caminho B do atualizador: o mesmo setup,
; mas so com os arquivos que mudaram desde a versao anterior (a pasta /DParcial, que o atualizacao\parcial.py separa)
; e apagando so o que a versao nova nao tem mais (o /DApaga, o [InstallDelete] que ele gera). Ela so roda por cima de
; um Ritmelli instalado, e o app so a usa quando o resto do que esta instalado bate com o manifesto novo.
;
; As vozes do pedal de troca de voz (#129): o setup nao as leva dentro. A pagina de licenca e a das vozes (a GPLv3 do
; Ritmelli vai na de informacao, que nao pede aceite), e no clique de Instalar o [Code] baixa do ritmelli-voices, para a
; {tmp}, cada arquivo do vozes.json que ainda nao esta na {app}\vozes com o sha256 certo, antes de a instalacao mexer
; em qualquer coisa: um download que falha volta para a pagina de Pronto, e em silencio o setup sai com 1 e o app de
; antes fica inteiro (o [InstallDelete] ainda nao rodou). O /DVozes e o /DLicencaVozes sao o que o vozes_iss.py gera.
; Uma atualizacao com as mesmas releases nao baixa nada, e a pasta de uma release que saiu do vozes.json e apagada.

#ifndef Versao
  #error Rode pelo monta.ps1 (falta /DVersao)
#endif
#ifndef Vozes
  #error Rode pelo monta.ps1 (falta /DVozes)
#endif
; o VozesRepo, o VozesTags, o VozesLista e o VozesMB, e o [Files] que copia da {tmp} o que o [Code] baixou
#include Vozes

[Setup]
; o AppId nunca muda: e por ele que o Windows reconhece a versao nova por cima da velha
AppId={{320EB2BD-48BC-420D-8F52-C22F644E47D4}
AppName=Ritmelli
AppVersion={#Versao}
AppVerName=Ritmelli {#Versao}
AppPublisher=Behling Informática Ltda.
AppCopyright=Software livre sob a GPLv3 / Free software under the GPLv3
VersionInfoVersion={#Versao}
; a pasta da instalacao anterior quando ela e protegida, menos a padrao de antes da troca de nome (PastaPadrao, no
; [Code]); sem pagina para escolher outra
DefaultDirName={code:PastaPadrao}
UsePreviousAppDir=no
DisableDirPage=yes
DisableProgramGroupPage=yes
; administrador de qualquer jeito: o firewall e o filtro dos microfones pedem
PrivilegesRequired=admin
; so Windows x64 de verdade: o filtro dos microfones (micfx.dll) e o voz.dll sao so x64, e no Windows ARM o audiodg.exe
; e ARM64 e nao carrega DLL x64 (o x64compatible deixava instalar pela emulacao, e a musica nunca chegava ao microfone;
; #125). A mensagem de recusa diz por que, no [Messages]
ArchitecturesAllowed=x64os
ArchitecturesInstallIn64BitMode=x64os
MinVersion=10.0
#ifdef Parcial
OutputBaseFilename=Ritmelli-{#Versao}-parcial
#else
OutputBaseFilename=Ritmelli-{#Versao}-setup
#endif
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ShowLanguageDialog=auto
; o app ligado segura os arquivos: o instalador fecha ele (nao tem janela para pedir)
CloseApplications=force
CloseApplicationsFilter=*.exe,*.dll,*.pyd
RestartApplications=no
UninstallDisplayIcon={app}\ritmelli.exe
UninstallDisplayName=Ritmelli
SetupLogging=yes
; o icone do setup e o do exe, que o ritmelli.spec poe na _internal\icone\. O desenho mora no dev/icone.py do
; repo ritmelli, que tambem grava aqui as imagens do assistente (a 100% e a 200%; o Inno escolhe pela escala)
SetupIconFile={#App}\_internal\icone\ritmelli.ico
WizardSmallImageFile=assistente-pequena-55.png,assistente-pequena-110.png
WizardImageFile=assistente-grande-164.png,assistente-grande-328.png
; no fim, avisa o Windows que os icones mudaram: o Explorer guarda o icone pelo caminho do exe, que e o mesmo de
; uma versao para a outra, e sem o aviso o atalho seguia com o icone velho depois de atualizar
ChangesAssociations=yes
; o {localappdata} do desinstalador (o codigo aleatorio dos dados de uso) e o de quem instalou, que e quem usa
UsedUserAreasWarning=no

[Languages]
; a licenca numa pagina de informacao, e nao de "aceito": a GPLv3 nao precisa ser aceita para usar (secao 9). A das
; vozes, sim (a secao 2 dela): vai na pagina de licenca, com o texto em portugues, que e o que vale, e a traducao em
; ingles depois dele. A traducao pt-BR do Inno corrigida (a oficial usa "pra" e maiusculas no meio da frase): o pt-BR.isl, ao lado
Name: "en"; MessagesFile: "compiler:Default.isl"; InfoBeforeFile: "licenca-en.txt"; LicenseFile: "{#LicencaVozes}"
Name: "pt"; MessagesFile: "pt-BR.isl"; InfoBeforeFile: "licenca-pt.txt"; LicenseFile: "{#LicencaVozes}"

[Messages]
; a pagina de licenca (InfoBefore) diz que e a licenca e que nao precisa aceitar; a Pronto para instalar avisa
; do som que corta (a de boas-vindas o Inno nao mostra: DisableWelcomePage e yes por padrao)
pt.WizardInfoBefore=Licença
en.WizardInfoBefore=License
pt.InfoBeforeLabel=O Ritmelli é software livre. Não é necessário aceitar esta licença para instalar ou usar o Ritmelli.
en.InfoBeforeLabel=Ritmelli is free software. You do not need to accept this license to install or use Ritmelli.
pt.WizardLicense=Licença das vozes
en.WizardLicense=Voices License
pt.LicenseLabel3=O pedal de troca de voz usa as vozes Mina e Lira, que o instalador baixa do GitHub (cerca de {#VozesMB} MB). Elas têm uma licença própria, separada da do Ritmelli. Aceite-a para continuar.
en.LicenseLabel3=The voice changer pedal uses the Mina and Lira voices, which the installer downloads from GitHub (about {#VozesMB} MB). They have their own license, separate from Ritmelli's. The Portuguese text is the binding one, and the English translation follows it. Accept it to continue.
pt.ReadyLabel2a=Durante a instalação, o som do computador pode ser interrompido por alguns segundos. Se você estiver em uma partida ou em uma chamada de voz, conclua-a primeiro.%n%nClique em Instalar para continuar a instalação ou em Voltar para revisar ou alterar alguma configuração.
en.ReadyLabel2a=During installation, your computer's sound may cut out for a few seconds. If you are in a match or a voice call, finish it first.%n%nClick Install to continue with the installation, or click Back if you want to review or change any settings.
pt.ReadyLabel2b=Durante a instalação, o som do computador pode ser interrompido por alguns segundos. Se você estiver em uma partida ou em uma chamada de voz, conclua-a primeiro.%n%nClique em Instalar para continuar a instalação.
en.ReadyLabel2b=During installation, your computer's sound may cut out for a few seconds. If you are in a match or a voice call, finish it first.%n%nClick Install to continue with the installation.
; desinstalar nao apaga a prateleira nem as escolhas (%LOCALAPPDATA%\Ritmelli fica)
pt.ConfirmUninstall=Tem certeza de que deseja remover o %1 deste computador? Os discos da prateleira e as suas escolhas continuam guardados e voltam a aparecer se você o instalar novamente. Durante a remoção, o som do computador pode ser interrompido por alguns segundos.
en.ConfirmUninstall=Are you sure you want to remove %1 from this computer? Your records on the shelf and your settings will be kept and will reappear if you reinstall it. During removal, your computer's sound may cut out for a few seconds.
pt.FinishedLabel=O Ritmelli foi instalado e está disponível no menu Iniciar.%n%nNo jogo e nas chamadas de voz, continue usando o seu microfone habitual: o Ritmelli toca a música nele. No Discord, selecione Estúdio em Perfil de entrada, pois os outros perfis podem cortar a música.
en.FinishedLabel=Ritmelli has been installed and is available in the Start menu.%n%nIn games and voice calls, keep using your usual microphone: Ritmelli plays the music through it. In Discord, select Studio under Input Profile. The other profiles can cut out the music.

; o Windows que nao e x64 (ARM ou 32 bits): a recusa logo no comeco, com o motivo (#125)
pt.OnlyOnTheseArchitectures=O Ritmelli precisa do Windows de 64 bits em um PC com processador Intel ou AMD. Em um PC com processador ARM (como o Snapdragon), o filtro do microfone não funciona, e a música não chegaria ao seu microfone.
en.OnlyOnTheseArchitectures=Ritmelli needs 64-bit Windows on a PC with an Intel or AMD processor. On a PC with an ARM processor (such as Snapdragon), the microphone filter can't run, so the music would never reach your microphone.

[CustomMessages]
pt.Abrir=Abrir o Ritmelli
en.Abrir=Open Ritmelli
pt.Firewall=Liberando o Ritmelli no firewall para que o celular possa se conectar ao computador...
en.Firewall=Allowing Ritmelli through the firewall so your phone can connect to the computer...
pt.Microfone=Preparando os microfones (o som pode ser interrompido por alguns segundos)...
en.Microfone=Preparing your microphones (the sound may cut out for a few seconds)...
pt.VozesTitulo=Baixando as vozes
en.VozesTitulo=Downloading the Voices
pt.VozesDescricao=O instalador está baixando as vozes Mina e Lira do GitHub (cerca de {#VozesMB} MB).
en.VozesDescricao=Setup is downloading the Mina and Lira voices from GitHub (about {#VozesMB} MB).
pt.VozesErro=Não foi possível baixar as vozes do pedal de troca de voz (%1).%n%nConfira a conexão com a internet e clique em Instalar para tentar novamente.
en.VozesErro=Setup couldn't download the voices for the voice changer pedal (%1).%n%nCheck your internet connection and click Install to try again.
pt.PastaDesprotegida=O Ritmelli não pode ser instalado em %1, porque essa pasta não está protegida contra alterações de outros usuários e programas (%2).%n%nAs tarefas do Ritmelli rodam como sistema e só usam uma pasta que apenas os administradores podem alterar.
en.PastaDesprotegida=Ritmelli can't be installed in %1, because that folder isn't protected from changes by other users and programs (%2).%n%nRitmelli's tasks run as the system and only use a folder that only administrators can change.
pt.ParcialSemApp=Esta é uma atualização do Ritmelli e só pode ser aplicada a uma instalação existente. Para instalar o Ritmelli, use o arquivo Ritmelli-{#Versao}-setup.exe.
en.ParcialSemApp=This is a Ritmelli update and can only be applied to an existing installation. To install Ritmelli, use Ritmelli-{#Versao}-setup.exe.
; a pagina dos dados de uso e dos erros (metricas.py): a politica na instalacao e a opcao de desligar, como a SignPath
; pede (o PRIVACIDADE.md tem o texto inteiro)
pt.MetricasTitulo=Dados de uso e erros
en.MetricasTitulo=Usage Data and Errors
pt.MetricasDescricao=O que o Ritmelli pode enviar para melhorar o aplicativo, sem identificar você.
en.MetricasDescricao=What Ritmelli can send to help improve the app, without identifying you.
pt.MetricasSub=Leia o que é enviado. Se não quiser enviar, desmarque a caixa abaixo. É possível alterar essa escolha depois no Ritmelli, pelo botão Microfone e fone.
en.MetricasSub=Review the details below. If you do not want to send this data, clear the check box. You can change this choice later in Ritmelli with the Mic and headphones button.
pt.MetricasTexto=O Ritmelli pode enviar dados anônimos de uso e relatórios de erro para saber quantas pessoas o usam, se as novas versões chegam até elas, quais erros ocorrem e quais efeitos são usados.%n%nO que é enviado: um código aleatório desta instalação, as versões do Ritmelli e do Windows e o idioma do Windows; um registro por dia de uso; por quanto tempo a música toca e cada efeito de voz fica ativo; a saúde do som que vai para o jogo (quantas vezes ele falhou e quantas dessas foram numa passagem entre músicas ou num ajuste de andamento, a menor folga e a maior demora do envio, quantas passagens e quantos ajustes de andamento houve e quanto tempo os ajustes levaram, quantas vezes e por quanto tempo o microfone deixou de receber a música, por quanto tempo o efeito de voz rodou no filtro do microfone e a voz veio do microfone de reserva, e a taxa do microfone); e os erros, com a parte do aplicativo em que ocorreram.%n%nO que nunca é enviado: nome, conta, e-mail, músicas, buscas, links, áudio, voz ou o nome dos seus dispositivos. O endereço IP não é armazenado.%n%nPara onde vão os dados: os dados de uso, para o PostHog, e os relatórios de erro, para o Sentry. São dois serviços de outras empresas, com armazenamento na União Europeia. Os dados de uso são mantidos por até 1 ano, e os relatórios de erro, por até 90 dias.%n%nPolítica de privacidade completa: https://github.com/ritmelli/ritmelli/blob/main/PRIVACIDADE.md
en.MetricasTexto=Ritmelli can send anonymous usage data and error reports so we can learn how many people use it, whether new versions are reaching them, which errors occur, and which effects are used.%n%nWhat is sent: a random ID for this installation, the Ritmelli and Windows versions, and the Windows language; one entry per day of use; how long music plays and how long each voice effect stays on; the health of the sound sent to the game (how many times it dropped out and how many of those happened during a transition between songs or a tempo adjustment, the smallest buffer and the longest delay in sending, how many transitions and tempo adjustments there were and how long the adjustments took, how many times and for how long the microphone stopped receiving the music, how long the voice effect ran in the microphone filter and the voice came from the backup microphone, and the microphone's sample rate); and errors, with the part of the app where they occurred.%n%nWhat is never sent: name, account, email, music, searches, links, audio, voice, or the names of your devices. Your IP address is not stored.%n%nWhere the data goes: usage data to PostHog and error reports to Sentry, two third-party services that store it in the European Union. Usage data is kept for up to 1 year, and error reports for up to 90 days.%n%nFull privacy policy: https://github.com/ritmelli/ritmelli/blob/main/PRIVACIDADE.md#ritmelli-privacy-policy
pt.MetricasCaixa=Enviar dados anônimos de uso e relatórios de erro
en.MetricasCaixa=Send anonymous usage data and error reports

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[InstallDelete]
#ifdef Parcial
; a parcial so apaga o que a versao anterior tinha e a nova nao tem: o resto fica, e o que mudou e trocado
#include Apaga
#else
; a _internal\ e a bin\ de uma versao antiga saem inteiras: arquivo que a nova nao tem nao fica para tras (as DLLs do
; ffmpeg completo de antes eram 240 MB)
Type: filesandordirs; Name: "{app}\_internal"
Type: filesandordirs; Name: "{app}\bin"
; o app de antes da troca de nome numa pasta escolhida a mao (que fica a mesma), e os atalhos com o nome de antes
Type: files; Name: "{app}\vitrola.exe"
Type: files; Name: "{autoprograms}\Vitrola.lnk"
Type: files; Name: "{autodesktop}\Vitrola.lnk"
#endif

[Files]
; o que o [Code] roda pelo PowerShell do sistema, so na {tmp}: a regra da pasta protegida, o fim dos processos da
; instalacao que o setup substitui e a renomeacao do ritmelli.exe da que fica para tras. No comeco do [Files]: com a
; compressao solida, um arquivo do fim so sairia depois de descomprimir o app inteiro, e o [Code] extrai estes antes
Source: "protegida.ps1"; Flags: dontcopy
Source: "encerra.ps1"; Flags: dontcopy
Source: "renomeia.ps1"; Flags: dontcopy
#ifdef Parcial
; so o que mudou, cada arquivo no caminho dele na pasta do app (a bin\ tambem, se o ffmpeg ou o Deno mudaram)
Source: "{#Parcial}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
#else
; uma bin\ que tenha sobrado no dist (teste a mao) nao entra: a bin\ e so a de baixo
Source: "{#App}\*"; DestDir: "{app}"; Excludes: "\bin"; Flags: ignoreversion recursesubdirs createallsubdirs
; o ffmpeg so de audio, com a licenca e a FONTE.txt de como foi compilado (a LGPL pede que vao junto)
Source: "{#Ffmpeg}\*"; DestDir: "{app}\bin"; Flags: ignoreversion
Source: "{#Deno}\deno.exe"; DestDir: "{app}\bin"; Flags: ignoreversion
#endif

; quem recebe o programa recebe as licencas: a GPLv3 do Ritmelli e o texto de cada componente de terceiros
Source: "{#Licenca}"; DestDir: "{app}"; DestName: "LICENSE.txt"; Flags: ignoreversion
Source: "{#Terceiros}"; DestDir: "{app}"; DestName: "TERCEIROS.txt"; Flags: ignoreversion

[Registry]
; a escolha da pagina dos dados de uso e dos erros, que o metricas.py le (a feita no Ritmelli vale sobre ela). So grava
; quando a pessoa viu a pagina, ou com /metricas=0 ou 1: a atualizacao em silencio mantem a escolha de antes (a de
; antes da troca de nome vem pelo migra.py), e quem nunca escolheu ve o aviso no Ritmelli antes de qualquer envio
Root: HKLM; Subkey: "SOFTWARE\Ritmelli"; ValueType: dword; ValueName: "Metricas"; ValueData: "{code:MetricasValor}"; Flags: uninsdeletevalue uninsdeletekeyifempty; Check: GravaMetricas
; e a versao do texto da pagina (o MetricasTexto acima): o TEXTO do metricas.py, que o dev/testa_metricas.py confere. Quem
; ligou num texto de antes (sem ela) ve o aviso de novo no Ritmelli
Root: HKLM; Subkey: "SOFTWARE\Ritmelli"; ValueType: dword; ValueName: "MetricasVersao"; ValueData: "2"; Flags: uninsdeletevalue uninsdeletekeyifempty; Check: GravaMetricas

[Icons]
Name: "{autoprograms}\Ritmelli"; Filename: "{app}\ritmelli.exe"
Name: "{autodesktop}\Ritmelli"; Filename: "{app}\ritmelli.exe"; Tasks: desktopicon

[Run]
; a troca de nome, antes de tudo (migra.py): o registro de antes vem para o novo antes de o filtro olhar os
; microfones, e as tarefas de antes saem
Filename: "{app}\ritmelli.exe"; Parameters: "--migra maquina"; Flags: runhidden
; o servidor atende a rede de casa (o celular). Privadas e publicas: muito Wi-Fi de casa esta como publico no
; Windows (o do Chris estava), e so privadas deixava o celular de fora. Pela rede, so entra o celular pareado
; (pareamento.py, no repo ritmelli). A regra de antes da troca de nome sai junto
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""Vitrola"""; Flags: runhidden
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""Ritmelli"""; Flags: runhidden
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall add rule name=""Ritmelli"" dir=in action=allow program=""{app}\ritmelli.exe"" enable=yes profile=private,public"; StatusMsg: "{cm:Firewall}"; Flags: runhidden
; o filtro em todo microfone que ainda nao tem, a DLL desta versao no lugar da velha e a tarefa do Windows que faz o
; mesmo depois, chamada pelo app sem UAC (o audio do PC reinicia so se algo mudou: atualizar sem DLL nova nao mexe).
; So o setup completo cria as tarefas: a parcial so troca a DLL, e as tarefas que o app apagou por achar a pasta
; desprotegida continuam apagadas ate o setup completo
#ifdef Parcial
Filename: "{app}\ritmelli.exe"; Parameters: "--microfone instala-todos"; StatusMsg: "{cm:Microfone}"; Flags: runhidden
#else
Filename: "{app}\ritmelli.exe"; Parameters: "--microfone instala-todos --tarefa"; StatusMsg: "{cm:Microfone}"; Flags: runhidden
; a tarefa da atualizacao automatica (atualizador.py): no logon e de 4 em 4 horas, como SYSTEM, sem UAC
Filename: "{app}\ritmelli.exe"; Parameters: "--atualizador tarefa"; Flags: runhidden
#endif
; o que sobrou do app de antes da troca de nome, com o filtro novo ja no lugar (migra.py)
Filename: "{app}\ritmelli.exe"; Parameters: "--migra limpa"; Flags: runhidden
; como quem instalou, e nao como administrador: os dados vao para o %LOCALAPPDATA% dele
Filename: "{app}\ritmelli.exe"; Description: "{cm:Abrir}"; Flags: postinstall nowait skipifsilent runasoriginaluser
; a atualizacao pelo app (atualizacao.py, no repo ritmelli) roda este setup em silencio com /reabrir=1: no fim o
; Ritmelli abre de novo, como quem instalou, com a janela dele (janela.py): a janela da versao velha fechou junto com
; ela. Vindo de uma versao sem janela, a aba que estava aberta tambem reconecta sozinha
Filename: "{app}\ritmelli.exe"; Flags: nowait runasoriginaluser; Check: Reabrir

[UninstallRun]
; a tarefa da atualizacao sai primeiro, e a rodada dela que esperava o Ritmelli fechar para: depois do taskkill ela
; veria o Ritmelli fechado e rodaria o instalador no meio do desinstalador
Filename: "{app}\ritmelli.exe"; Parameters: "--atualizador remove"; Flags: runhidden; RunOnceId: "Atualizador"
Filename: "{sys}\taskkill.exe"; Parameters: "/F /IM ritmelli.exe"; Flags: runhidden; RunOnceId: "Fecha"
; tira o filtro de todo microfone que o tem, devolve o efeito original de cada um e apaga a tarefa (sem nenhum, nao mexe
; no audio)
Filename: "{app}\ritmelli.exe"; Parameters: "--microfone remove"; Flags: runhidden; RunOnceId: "Microfone"
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""Ritmelli"""; Flags: runhidden; RunOnceId: "Firewall"
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""Vitrola"""; Flags: runhidden; RunOnceId: "FirewallVitrola"

[UninstallDelete]
; o que a atualizacao automatica baixou (os setups, o estado e o log dela)
Type: filesandordirs; Name: "{app}\atualizacao"
; as vozes: o que esta instalacao baixou sai pelo registro do desinstalador, e o de uma versao anterior, por aqui
Type: filesandordirs; Name: "{app}\vozes"
; o codigo aleatorio da instalacao que vai nos dados de uso (metricas.py): reinstalar comeca outro. O da pasta de antes
; da troca de nome sai tambem, se o app nao chegou a abrir depois dela
Type: files; Name: "{localappdata}\Ritmelli\metricas.json"
Type: files; Name: "{localappdata}\Vitrola\metricas.json"

[Code]
const
  // a chave de desinstalacao do Inno para o AppId: e nela que mora a pasta da instalacao anterior
  ChaveDesinstalar = 'SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\{320EB2BD-48BC-420D-8F52-C22F644E47D4}_is1';

var
  // a pasta da instalacao anterior, lida no comeco: antes de um /DIR= (que pula o PastaPadrao) e antes de o setup
  // gravar a pasta nova no registro
  PastaAnterior: String;
  // a pasta que o PastaPadrao escolheu (ele confere a regra uma vez so)
  PastaEscolhida: String;

function InitializeSetup: Boolean;
var
  Anterior: String;
begin
  Result := True;
  if RegQueryStringValue(HKLM64, ChaveDesinstalar, 'Inno Setup: App Path', Anterior) and (Anterior <> '') then
    PastaAnterior := RemoveBackslashUnlessRoot(Anterior);
  Log('instalacao anterior: ' + PastaAnterior);
end;

// o texto entre aspas simples do PowerShell: cada aspa simples dobrada, inclusive as tipograficas, que o PowerShell
// tambem le como aspa simples (U+2018, U+2019, U+201A e U+201B)
function Aspas(S: String): String;
begin
  StringChangeEx(S, '''', '''''', True);
  StringChangeEx(S, #$2018, #$2018#$2018, True);
  StringChangeEx(S, #$2019, #$2019#$2019, True);
  StringChangeEx(S, #$201A, #$201A#$201A, True);
  StringChangeEx(S, #$201B, #$201B#$201B, True);
  Result := '''' + S + '''';
end;

// roda um .ps1 do setup (extraido para a {tmp}) pelo PowerShell do sistema, como texto: a politica de execucao de
// scripts do PC nao entra. Args ja vem com as aspas. O .ps1 responde no arquivo Saida; '' sem resposta
function RodaPs(Script, Args, Saida: String): String;
var
  Codigo: Integer;
  Texto: AnsiString;
begin
  Result := '';
  // nenhum caminho do Windows tem aspas duplas: com uma, o comando entre aspas duplas acabaria no meio
  if (Pos('"', Args) > 0) or (Pos('"', Saida) > 0) then begin
    Log(Script + ': argument with a double quote refused');
    Exit;
  end;
  ExtractTemporaryFile(Script);
  // a resposta de uma vez anterior nunca vale por esta: sem conseguir apaga-la, sem resposta
  if FileExists(Saida) and not DeleteFile(Saida) then begin
    Log(Script + ': could not remove the previous answer ' + Saida);
    Exit;
  end;
  if not Exec(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'),
              '-NoProfile -NonInteractive -Command "& ([scriptblock]::Create([IO.File]::ReadAllText(' +
              Aspas(ExpandConstant('{tmp}\') + Script) + '))) ' + Args + ' -Saida ' + Aspas(Saida) + '"',
              '', SW_HIDE, ewWaitUntilTerminated, Codigo) then
    Log(Script + ': o PowerShell nao rodou (' + SysErrorMessage(Codigo) + ')')
  else if Codigo <> 0 then
    Log(Script + ': o PowerShell saiu com ' + IntToStr(Codigo))
  else if LoadStringFromFile(Saida, Texto) then
    Result := Trim(String(Texto));
end;

// a regra da pasta protegida (protegida.ps1) com a raiz {autopf}: '' se a pasta passa; senao, o motivo
function Protegida(Pasta: String): String;
begin
  Result := RodaPs('protegida.ps1', '-Pasta ' + Aspas(Pasta) + ' -Raiz ' + Aspas(ExpandConstant('{autopf}')),
                   ExpandConstant('{tmp}\protegida.txt'));
  if Result = 'OK' then
    Result := ''
  else if Result = '' then
    Result := 'the check did not answer';
  if Result = '' then
    Log('pasta protegida: ' + Pasta)
  else
    Log('pasta nao protegida: ' + Pasta + ': ' + Result);
end;

// a pasta do app: a instalacao anterior, quando ela passa na regra da pasta protegida e nao e a padrao de antes da
// troca de nome (Program Files\Vitrola, que vai para a Program Files\Ritmelli); senao a Program Files\Ritmelli, se ela
// passar; e se nem ela passar (a propria instalacao anterior ali, com uma ACL que reprova), a primeira
// Program Files\Ritmelli-N livre. Se a raiz nao passa, fica a Program Files\Ritmelli, e a conferencia do destino recusa
// com o motivo. A parcial so serve por cima da instalacao anterior (a conferencia do destino recusa o resto)
function PastaPadrao(Param: String): String;
var
  Raiz, Candidata: String;
  N: Integer;
begin
  if PastaEscolhida <> '' then begin
    Result := PastaEscolhida;
    Exit;
  end;
  Raiz := ExpandConstant('{autopf}');
  Result := Raiz + '\Ritmelli';
#ifdef Parcial
  if PastaAnterior <> '' then
    Result := PastaAnterior;
#else
  if (PastaAnterior <> '') and (CompareText(PastaAnterior, Raiz + '\Vitrola') <> 0) and
     (Protegida(PastaAnterior) = '') then
    Result := PastaAnterior
  else if Protegida(Result) <> '' then
    for N := 2 to 99 do begin
      Candidata := Raiz + '\Ritmelli-' + IntToStr(N);
      if not DirExists(Candidata) and not FileExists(Candidata) then begin
        // livre: ou ela passa, ou quem reprova e a raiz (e fica a Ritmelli, que a conferencia do destino recusa)
        if Protegida(Candidata) = '' then
          Result := Candidata;
        Break;
      end;
    end;
#endif
  Log('pasta do app: ' + Result);
  PastaEscolhida := Result;
end;

// o destino final: a regra da pasta protegida e, na parcial, a instalacao anterior com o ritmelli.exe. '' se serve;
// senao, a mensagem para quem instala
function ConfereDestino: String;
var
  Destino, Motivo: String;
begin
  Result := '';
  Destino := RemoveBackslashUnlessRoot(WizardDirValue);
#ifdef Parcial
  if (PastaAnterior = '') or (CompareText(Destino, PastaAnterior) <> 0) then begin
    Log('destino recusado: ' + Destino + ' nao e a instalacao anterior (' + PastaAnterior + ')');
    Result := CustomMessage('ParcialSemApp');
    Exit;
  end;
#endif
  // a regra antes de olhar qualquer coisa dentro do destino
  Motivo := Protegida(Destino);
  if Motivo <> '' then begin
    Result := FmtMessage(CustomMessage('PastaDesprotegida'), [Destino, Motivo]);
    Exit;
  end;
#ifdef Parcial
  if not FileExists(AddBackslash(Destino) + 'ritmelli.exe') then begin
    Log('destino recusado: ' + Destino + ' nao tem o ritmelli.exe');
    Result := CustomMessage('ParcialSemApp');
  end;
#endif
end;

// setup.exe /VERYSILENT /reabrir=1, o da atualizacao pelo app: abre o Ritmelli de novo no fim
function Reabrir: Boolean;
begin
  Result := WizardSilent and (ExpandConstant('{param:reabrir|0}') = '1');
end;

// a pagina dos dados de uso e dos erros, depois da licenca: a politica e a caixa de enviar, que vem marcada (ou como
// a pessoa deixou da outra vez, tambem antes da troca de nome)
var
  MetricasPagina: TOutputMsgMemoWizardPage;
  MetricasCaixa: TNewCheckBox;
  VozesPagina: TDownloadWizardPage;
  VozesVistas: TStringList;

procedure InitializeWizard;
var
  Antes: Cardinal;
  Achou: Boolean;
begin
  VozesPagina := CreateDownloadPage(CustomMessage('VozesTitulo'), CustomMessage('VozesDescricao'), nil);
  VozesPagina.ShowBaseNameInsteadOfUrl := True;
  MetricasPagina := CreateOutputMsgMemoPage(wpInfoBefore, CustomMessage('MetricasTitulo'),
    CustomMessage('MetricasDescricao'), CustomMessage('MetricasSub'), CustomMessage('MetricasTexto'));
  MetricasPagina.RichEditViewer.Height := MetricasPagina.RichEditViewer.Height - ScaleY(30);
  MetricasCaixa := TNewCheckBox.Create(MetricasPagina);
  MetricasCaixa.Parent := MetricasPagina.Surface;
  MetricasCaixa.Left := MetricasPagina.RichEditViewer.Left;
  MetricasCaixa.Top := MetricasPagina.RichEditViewer.Top + MetricasPagina.RichEditViewer.Height + ScaleY(10);
  MetricasCaixa.Width := MetricasPagina.SurfaceWidth;
  MetricasCaixa.Height := ScaleY(20);
  MetricasCaixa.Caption := CustomMessage('MetricasCaixa');
  Achou := RegQueryDWordValue(HKLM, 'SOFTWARE\Ritmelli', 'Metricas', Antes);
  if not Achou then
    Achou := RegQueryDWordValue(HKLM, 'SOFTWARE\Vitrola', 'Metricas', Antes);
  MetricasCaixa.Checked := not (Achou and (Antes = 0));
end;

// o /metricas=0 ou 1 do setup em silencio, ou '' sem ele
function MetricasParam: String;
begin
  Result := ExpandConstant('{param:metricas|}');
  if (Result <> '0') and (Result <> '1') then
    Result := '';
end;

function GravaMetricas: Boolean;
begin
  Result := (MetricasParam <> '') or not WizardSilent;
end;

function MetricasValor(Param: String): String;
begin
  Result := MetricasParam;
  if Result = '' then
    if MetricasCaixa.Checked then Result := '1' else Result := '0';
end;

// as vozes (#129). FaltaVoz: o arquivo (tag\nome) ainda nao esta na {app}\vozes com o sha256 certo. E o Check de cada
// linha do vozes.iss, e o BaixaVozes pergunta o mesmo: a resposta de cada arquivo fica guardada (os ~325 MB se conferem
// em ~1 s, uma vez so)
function FaltaVoz(Arquivo, Sha: String): Boolean;
var
  Caminho: String;
begin
  if VozesVistas = nil then
    VozesVistas := TStringList.Create;
  if VozesVistas.IndexOf('1|' + Arquivo) >= 0 then begin
    Result := True;
    Exit;
  end;
  if VozesVistas.IndexOf('0|' + Arquivo) >= 0 then begin
    Result := False;
    Exit;
  end;
  Caminho := ExpandConstant('{app}\vozes\') + Arquivo;
  Result := True;
  if FileExists(Caminho) then
    try
      Result := CompareText(GetSHA256OfFile(Caminho), Sha) <> 0;
    except
      Result := True;
    end;
  if Result then begin
    Log('vozes: falta ' + Arquivo);
    VozesVistas.Add('1|' + Arquivo);
  end else
    VozesVistas.Add('0|' + Arquivo);
end;

// o campo N (do 0) de 'tag|nome|sha256'
function VozCampo(S: String; N: Integer): String;
var
  I, P: Integer;
begin
  for I := 1 to N do
    S := Copy(S, Pos('|', S) + 1, Length(S));
  P := Pos('|', S);
  if P > 0 then
    S := Copy(S, 1, P - 1);
  Result := S;
end;

// baixa para a {tmp} (vozes-<tag>-<nome>) cada arquivo da VozesLista que falta, conferindo o sha256: com a pagina de
// download, ou direto em silencio. '' se deu certo; senao, o motivo
function BaixaVozes: String;
var
  Lista: TStringList;
  S, Tag, Nome, Sha, Url: String;
  I, N: Integer;
begin
  Result := '';
  Lista := TStringList.Create;
  try
    try
      S := '{#VozesLista}';
      StringChangeEx(S, ';', #13#10, True);
      Lista.Text := S;
      if not WizardSilent then
        VozesPagina.Clear;
      N := 0;
      for I := 0 to Lista.Count - 1 do begin
        Tag := VozCampo(Lista[I], 0);
        Nome := VozCampo(Lista[I], 1);
        Sha := VozCampo(Lista[I], 2);
        if FaltaVoz(Tag + '\' + Nome, Sha) then begin
          Url := 'https://github.com/{#VozesRepo}/releases/download/' + Tag + '/' + Nome;
          if WizardSilent then
            DownloadTemporaryFile(Url, 'vozes-' + Tag + '-' + Nome, Sha, nil)
          else
            VozesPagina.Add(Url, 'vozes-' + Tag + '-' + Nome, Sha);
          N := N + 1;
        end;
      end;
      if (N > 0) and not WizardSilent then begin
        VozesPagina.Show;
        try
          VozesPagina.Download;
        finally
          VozesPagina.Hide;
        end;
      end;
    except
      Result := GetExceptionMessage;
    end;
  finally
    Lista.Free;
  end;
end;

// no clique de Instalar (e na mesma hora em silencio), antes de qualquer mudanca: o destino e as vozes que faltam. Um
// destino recusado nao baixa as vozes nem le a {app}\vozes: com a janela, o setup fica na pagina de Pronto; em
// silencio, segue para o PrepareToInstall, que recusa de novo e sai com o codigo 7. Se as vozes nao vierem, o setup
// fica na pagina de Pronto (em silencio, sai com 1)
function NextButtonClick(CurPageID: Integer): Boolean;
var
  Erro: String;
begin
  Result := True;
  if CurPageID = wpReady then begin
    Erro := ConfereDestino;
    if Erro <> '' then begin
      Log('destino recusado: ' + Erro);
      if not WizardSilent then begin
        MsgBox(Erro, mbCriticalError, MB_OK);
        Result := False;
      end;
      Exit;
    end;
    Erro := BaixaVozes;
    if Erro <> '' then begin
      Log('vozes: ' + Erro);
      if WizardSilent or not VozesPagina.AbortedByUser then
        SuppressibleMsgBox(FmtMessage(CustomMessage('VozesErro'), [Erro]), mbCriticalError, MB_OK, IDOK);
      Result := False;
    end;
  end;
end;

// depois de copiar: a pasta de uma release que saiu do vozes.json (a voz de antes de uma versao nova dela)
procedure LimpaVozes;
var
  F: TFindRec;
  Pasta: String;
begin
  Pasta := ExpandConstant('{app}\vozes\');
  if FindFirst(Pasta + '*', F) then
    try
      repeat
        if (F.Attributes and FILE_ATTRIBUTE_DIRECTORY <> 0) and (F.Name <> '.') and (F.Name <> '..') and
           (Pos('|' + Lowercase(F.Name) + '|', Lowercase('{#VozesTags}')) = 0) then begin
          Log('vozes: apaga ' + F.Name);
          DelTree(Pasta + F.Name, True, True, True);
        end;
      until not FindNext(F);
    finally
      FindClose(F);
    end;
end;

// a migracao para outra pasta (a anterior ficou fora de Program Files, reprovou na regra ou e a Program Files\Vitrola):
// a pasta anterior fica onde esta, sem nenhuma tarefa apontando para ela (apagar uma pasta escolhida a mao arriscaria
// arquivos de outros programas), e so o ritmelli.exe dela vira ritmelli.exe.antigo (renomeia.ps1, que confere o
// caminho e o arquivo antes): o atualizador da versao antiga, que espera este setup terminar, reabriria a versao
// velha. Em qualquer erro, so o motivo vai para o log
procedure AposentaAnterior;
var
  Destino, Exe, Resposta: String;
begin
  Destino := RemoveBackslashUnlessRoot(WizardDirValue);
  if (PastaAnterior = '') or (CompareText(PastaAnterior, Destino) = 0) then
    Exit;
  Log('migracao: a instalacao anterior em ' + PastaAnterior + ' fica onde esta, e o app vai para ' + Destino);
  // sem conferir antes se o exe existe: o renomeia.ps1 diz no log por que nao renomeou (nao existe, ponto de
  // reanalise, acesso negado)
  Exe := AddBackslash(PastaAnterior) + 'ritmelli.exe';
  Resposta := RodaPs('renomeia.ps1', '-Exe ' + Aspas(Exe) + ' -Destino ' + Aspas(Destino),
                     ExpandConstant('{tmp}\renomeia.txt'));
  if Resposta = '' then
    Resposta := 'the rename did not answer';
  Log('migracao: ' + Resposta);
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then begin
    LimpaVozes;
    AposentaAnterior;
  end;
end;

// da instalacao que o setup substitui (a anterior e a Program Files\Vitrola): o vitrola.exe; e, quando o destino e
// outra pasta, tambem o ritmelli.exe e os da bin\ (na mesma pasta, o Restart Manager ja fecha o que o setup troca).
// Caminhos separados por |
function AlvosDe(Pasta, Destino: String): String;
begin
  Pasta := RemoveBackslashUnlessRoot(Pasta);
  Result := Pasta + '\vitrola.exe|';
  if CompareText(Pasta, Destino) <> 0 then
    Result := Result + Pasta + '\ritmelli.exe|' + Pasta + '\bin\ffmpeg.exe|' + Pasta + '\bin\ffprobe.exe|' + Pasta +
              '\bin\deno.exe|';
end;

// antes de trocar os arquivos, e antes de encerrar ou rodar qualquer coisa: o destino (a regra da pasta protegida; na
// parcial, a instalacao anterior, sem a qual falta todo o resto). Recusado, em silencio o setup sai com o codigo 7.
// Depois, o que segura a instalacao que o setup substitui sai pelo caminho completo do executavel (encerra.ps1): nunca o
// que roda da atualizacao\ (o setup baixado pela tarefa), o proprio setup, quem o lancou ou outro programa
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  Destino, Alvos, Resposta: String;
begin
  Result := ConfereDestino;
  if Result <> '' then begin
    Log('destino recusado: ' + Result);
    Exit;
  end;
  Destino := RemoveBackslashUnlessRoot(WizardDirValue);
  Alvos := AlvosDe(ExpandConstant('{autopf}\Vitrola'), Destino);
  if (PastaAnterior <> '') and (CompareText(PastaAnterior, ExpandConstant('{autopf}\Vitrola')) <> 0) then
    Alvos := Alvos + AlvosDe(PastaAnterior, Destino);
  Resposta := RodaPs('encerra.ps1', '-Caminhos ' + Aspas(Alvos), ExpandConstant('{tmp}\encerra.txt'));
  Log('processos da instalacao anterior: ' + Resposta);
end;
