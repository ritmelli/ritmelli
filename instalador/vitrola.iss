; O instalador da Vitrola (Inno Setup 6). Nao compile direto: o monta.ps1 congela o app, baixa o ffmpeg e o
; Deno e passa os caminhos e a versao (/DVersao, /DApp, /DFfmpeg, /DDeno, e /DLicenca e /DTerceiros, a GPLv3 da Vitrola
; e os avisos de terceiros que o terceiros.py monta).
;
; Instala o vitrola.exe em Program Files, com o ffmpeg, o ffprobe e o Deno na bin\ (o app acha la, ver o
; pastas.py), cria a regra do firewall para o celular alcancar o PC e pendura o filtro da Vitrola em todo microfone
; do PC (microfone\microfone.py): e por ele que a musica toca no microfone que o jogo ja usa. Tambem cria a tarefa
; do Windows que pendura o filtro num microfone que aparecer depois, sem o app pedir administrador, e a que atualiza a
; Vitrola sozinha (atualizador.py): ela roda este setup como SYSTEM, em silencio e sem /reabrir, com a Vitrola fechada.
; Desinstalar tira o filtro, devolve o efeito original de cada microfone e apaga as duas tarefas. Os dados de quem usa
; (%LOCALAPPDATA%\Vitrola) ficam.
;
; Com /DParcial e /DApaga (o monta.ps1 -Anterior), sai a atualizacao parcial, o caminho B do atualizador: o mesmo setup,
; mas so com os arquivos que mudaram desde a versao anterior (a pasta /DParcial, que o atualizacao\parcial.py separa)
; e apagando so o que a versao nova nao tem mais (o /DApaga, o [InstallDelete] que ele gera). Ela so roda por cima de
; uma Vitrola instalada, e o app so a usa quando o resto do que esta instalado bate com o manifesto novo.

#ifndef Versao
  #error Rode pelo monta.ps1 (falta /DVersao)
#endif

[Setup]
; o AppId nunca muda: e por ele que o Windows reconhece a versao nova por cima da velha
AppId={{320EB2BD-48BC-420D-8F52-C22F644E47D4}
AppName=Ritmelli
AppVersion={#Versao}
AppVerName=Ritmelli {#Versao}
AppPublisher=Behling Informática Ltda
AppCopyright=Software livre sob a GPLv3
VersionInfoVersion={#Versao}
DefaultDirName={autopf}\Vitrola
DisableProgramGroupPage=yes
; administrador de qualquer jeito: o firewall e o filtro dos microfones pedem
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
#ifdef Parcial
OutputBaseFilename=Vitrola-{#Versao}-parcial
#else
OutputBaseFilename=Vitrola-{#Versao}-setup
#endif
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ShowLanguageDialog=auto
; o app ligado segura os arquivos: o instalador fecha ele (nao tem janela para pedir)
CloseApplications=force
CloseApplicationsFilter=*.exe,*.dll,*.pyd
RestartApplications=no
UninstallDisplayIcon={app}\vitrola.exe
UninstallDisplayName=Ritmelli
SetupLogging=yes
; o icone do setup e o do exe, que o vitrola.spec poe na _internal\icone\. O desenho mora no dev/icone.py do
; repo vitrola, que tambem grava aqui as imagens do assistente (a 100% e a 200%; o Inno escolhe pela escala)
SetupIconFile={#App}\_internal\icone\vitrola.ico
WizardSmallImageFile=assistente-pequena-55.png,assistente-pequena-110.png
WizardImageFile=assistente-grande-164.png,assistente-grande-328.png
; no fim, avisa o Windows que os icones mudaram: o Explorer guarda o icone pelo caminho do exe, que e o mesmo de
; uma versao para a outra, e sem o aviso o atalho seguia com o icone velho depois de atualizar
ChangesAssociations=yes
; o {localappdata} do desinstalador (o codigo aleatorio dos dados de uso) e o de quem instalou, que e quem usa
UsedUserAreasWarning=no

[Languages]
; a licenca numa pagina de informacao, e nao de "aceito": a GPLv3 nao precisa ser aceita para usar (secao 9)
; a traducao pt-BR do Inno corrigida (a oficial usa "pra" e maiusculas no meio da frase): o pt-BR.isl, ao lado
Name: "pt"; MessagesFile: "pt-BR.isl"; InfoBeforeFile: "licenca-pt.txt"
Name: "en"; MessagesFile: "compiler:Default.isl"; InfoBeforeFile: "licenca-en.txt"

[Messages]
pt.FinishedLabel=O Ritmelli foi instalado e está disponível no menu Iniciar.%n%nNo jogo e nas chamadas de voz, continue usando o seu microfone habitual: o Ritmelli toca a música nele. No Discord, selecione Estúdio em Perfil de entrada, pois os outros perfis podem cortar a música.
en.FinishedLabel=Ritmelli has been installed and is available in the Start menu.%n%nIn games and voice calls, keep using your usual microphone: Ritmelli plays the music through it. In Discord, select Studio under Input Profile, as the other profiles can cut out the music.

[CustomMessages]
pt.Abrir=Abrir o Ritmelli
en.Abrir=Open Ritmelli
pt.Firewall=Liberando o Ritmelli no firewall para que o celular possa se conectar ao computador...
en.Firewall=Allowing Ritmelli through the firewall so your phone can connect to the computer...
pt.Microfone=Preparando os microfones para o Ritmelli (o som do computador é interrompido por alguns segundos)...
en.Microfone=Preparing your microphones for Ritmelli (the computer's sound will cut out for a few seconds)...
pt.ParcialSemApp=Esta é uma atualização do Ritmelli e só pode ser aplicada a uma instalação existente. Para instalar o Ritmelli, use o arquivo Vitrola-{#Versao}-setup.exe.
en.ParcialSemApp=This is a Ritmelli update and can only be applied to an existing installation. To install Ritmelli, use Vitrola-{#Versao}-setup.exe.
; a pagina dos dados de uso e dos erros (metricas.py): a politica na instalacao e a opcao de desligar, como a SignPath
; pede (o PRIVACIDADE.md tem o texto inteiro)
pt.MetricasTitulo=Dados de uso e erros
en.MetricasTitulo=Usage data and errors
pt.MetricasDescricao=O que o Ritmelli envia para melhorar, sem identificar você.
en.MetricasDescricao=What Ritmelli sends to improve, without identifying you.
pt.MetricasSub=Leia o que é enviado e faça a sua escolha abaixo. É possível alterá-la depois no Ritmelli, em Microfone e fone.
en.MetricasSub=Read what is sent and make your choice below. You can change it later in Ritmelli, under Mic and headphones.
pt.MetricasTexto=Para saber quantas pessoas usam o Ritmelli, se as novas versões estão chegando, quais erros ocorrem e quais efeitos são usados, o Ritmelli pode enviar dados anônimos de uso e relatórios de erro.%n%nO que é enviado: um código aleatório desta instalação, as versões do Ritmelli e do Windows e o idioma; um registro por dia de uso; por quanto tempo a música toca e cada efeito de voz fica ativo; e os erros, com o ponto do código em que ocorreram.%n%nO que nunca é enviado: nome, conta, e-mail, músicas, buscas, links, áudio, voz ou o nome dos seus dispositivos. O endereço IP não é armazenado.%n%nPara onde vão os dados: PostHog (uso) e Sentry (erros), com armazenamento na União Europeia. Os dados de uso são mantidos por até 1 ano, e os relatórios de erro, por até 90 dias.%n%nPolítica de privacidade completa: https://github.com/ritmelli/ritmelli/blob/main/PRIVACIDADE.md
en.MetricasTexto=To learn how many people use Ritmelli, whether new versions are reaching them, which errors occur and which effects are used, Ritmelli can send anonymous usage data and error reports.%n%nWhat is sent: a random code for this installation, the Ritmelli and Windows versions and the language; one record per day of use; how long music plays and how long each voice effect stays on; and errors, with the place in the code where they occurred.%n%nWhat is never sent: name, account, email, music, searches, links, audio, voice or the names of your devices. The IP address is not stored.%n%nWhere the data goes: PostHog (usage) and Sentry (errors), stored in the European Union. Usage data is kept for up to 1 year, and error reports for up to 90 days.%n%nFull privacy policy: https://github.com/ritmelli/ritmelli/blob/main/PRIVACIDADE.md
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
#endif

[Files]
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

; quem recebe o programa recebe as licencas: a GPLv3 da Vitrola e o texto de cada componente de terceiros
Source: "{#Licenca}"; DestDir: "{app}"; DestName: "LICENSE.txt"; Flags: ignoreversion
Source: "{#Terceiros}"; DestDir: "{app}"; DestName: "TERCEIROS.txt"; Flags: ignoreversion

[Registry]
; a escolha da pagina dos dados de uso e dos erros, que o metricas.py le (a feita na Vitrola vale sobre ela). So grava
; quando a pessoa viu a pagina, ou com /metricas=0 ou 1: a atualizacao em silencio mantem a escolha de antes, e quem
; nunca escolheu ve o aviso na Vitrola antes de qualquer envio
Root: HKLM; Subkey: "SOFTWARE\Vitrola"; ValueType: dword; ValueName: "Metricas"; ValueData: "{code:MetricasValor}"; Flags: uninsdeletevalue uninsdeletekeyifempty; Check: GravaMetricas

[Icons]
Name: "{autoprograms}\Ritmelli"; Filename: "{app}\vitrola.exe"
Name: "{autodesktop}\Ritmelli"; Filename: "{app}\vitrola.exe"; Tasks: desktopicon

[Run]
; o servidor atende a rede de casa (o celular). Privadas e publicas: muito Wi-Fi de casa esta como publico no
; Windows (o do Chris estava), e so privadas deixava o celular de fora. Pela rede, so entra o celular pareado
; (pareamento.py, no repo vitrola)
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""Vitrola"""; Flags: runhidden
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""Ritmelli"""; Flags: runhidden
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall add rule name=""Ritmelli"" dir=in action=allow program=""{app}\vitrola.exe"" enable=yes profile=private,public"; StatusMsg: "{cm:Firewall}"; Flags: runhidden
; o filtro em todo microfone que ainda nao tem, a DLL desta versao no lugar da velha e a tarefa do Windows que faz o
; mesmo depois, chamada pelo app sem UAC (o audio do PC reinicia so se algo mudou: atualizar sem DLL nova nao mexe)
Filename: "{app}\vitrola.exe"; Parameters: "--microfone instala-todos --tarefa"; StatusMsg: "{cm:Microfone}"; Flags: runhidden
; a tarefa da atualizacao automatica (atualizador.py): no logon e de 4 em 4 horas, como SYSTEM, sem UAC
Filename: "{app}\vitrola.exe"; Parameters: "--atualizador tarefa"; Flags: runhidden
; como quem instalou, e nao como administrador: os dados vao para o %LOCALAPPDATA% dele
Filename: "{app}\vitrola.exe"; Description: "{cm:Abrir}"; Flags: postinstall nowait skipifsilent runasoriginaluser
; a atualizacao pelo app (atualizacao.py, no repo vitrola) roda este setup em silencio com /reabrir=1: no fim a Vitrola
; abre de novo, como quem instalou, com a janela dela (janela.py): a janela da versao velha fechou junto com ela. Vindo
; de uma versao sem janela, a aba que estava aberta tambem reconecta sozinha
Filename: "{app}\vitrola.exe"; Flags: nowait runasoriginaluser; Check: Reabrir

[UninstallRun]
; a tarefa da atualizacao sai primeiro, e a rodada dela que esperava a Vitrola fechar para: depois do taskkill ela veria
; a Vitrola fechada e rodaria o instalador no meio do desinstalador
Filename: "{app}\vitrola.exe"; Parameters: "--atualizador remove"; Flags: runhidden; RunOnceId: "Atualizador"
Filename: "{sys}\taskkill.exe"; Parameters: "/F /IM vitrola.exe"; Flags: runhidden; RunOnceId: "Fecha"
; tira o filtro de todo microfone que o tem, devolve o efeito original de cada um e apaga a tarefa (sem nenhum, nao mexe
; no audio)
Filename: "{app}\vitrola.exe"; Parameters: "--microfone remove"; Flags: runhidden; RunOnceId: "Microfone"
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""Vitrola"""; Flags: runhidden; RunOnceId: "Firewall"
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""Ritmelli"""; Flags: runhidden; RunOnceId: "FirewallRitmelli"

[UninstallDelete]
; o que a atualizacao automatica baixou (os setups, o estado e o log dela)
Type: filesandordirs; Name: "{app}\atualizacao"
; o codigo aleatorio da instalacao que vai nos dados de uso (metricas.py): reinstalar comeca outro
Type: files; Name: "{localappdata}\Vitrola\metricas.json"

[Code]
// setup.exe /VERYSILENT /reabrir=1, o da atualizacao pelo app: abre a Vitrola de novo no fim
function Reabrir: Boolean;
begin
  Result := WizardSilent and (ExpandConstant('{param:reabrir|0}') = '1');
end;

// a pagina dos dados de uso e dos erros, depois da licenca: a politica e a caixa de enviar, que vem marcada (ou como
// a pessoa deixou da outra vez)
var
  MetricasPagina: TOutputMsgMemoWizardPage;
  MetricasCaixa: TNewCheckBox;

procedure InitializeWizard;
var
  Antes: Cardinal;
begin
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
  MetricasCaixa.Checked := not (RegQueryDWordValue(HKLM, 'SOFTWARE\Vitrola', 'Metricas', Antes) and (Antes = 0));
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


#ifdef Parcial
// a parcial so troca o que mudou: sem a Vitrola instalada, falta todo o resto. Em silencio, o setup sai com o codigo 7
function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  Result := '';
  if not FileExists(ExpandConstant('{app}\vitrola.exe')) then
    Result := CustomMessage('ParcialSemApp');
end;

#endif
