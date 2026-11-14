; O instalador da Vitrola (Inno Setup 6). Nao compile direto: o monta.ps1 congela o app, baixa o ffmpeg e o
; Deno e passa os caminhos e a versao (/DVersao, /DApp, /DFfmpeg, /DDeno, e /DLicenca e /DTerceiros, a GPLv3 da Vitrola
; e os avisos de terceiros que o terceiros.py monta).
;
; Instala o vitrola.exe em Program Files, com o ffmpeg, o ffprobe e o Deno na bin\ (o app acha la, ver o
; pastas.py), cria a regra do firewall para o celular alcancar o PC e pendura o filtro da Vitrola em todo microfone
; do PC (microfone\microfone.py): e por ele que a musica toca no microfone que o jogo ja usa. Tambem cria a tarefa
; do Windows que pendura o filtro num microfone que aparecer depois, sem o app pedir administrador. Desinstalar tira o
; filtro e devolve o efeito original de cada microfone. Os dados de quem usa (%LOCALAPPDATA%\Vitrola) ficam.
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
AppName=Vitrola
AppVersion={#Versao}
AppVerName=Vitrola {#Versao}
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
UninstallDisplayName=Vitrola
SetupLogging=yes
; o icone do setup e o do exe, que o vitrola.spec poe na _internal\icone\. O desenho mora no dev/icone.py do
; repo vitrola, que tambem grava aqui as imagens do assistente (a 100% e a 200%; o Inno escolhe pela escala)
SetupIconFile={#App}\_internal\icone\vitrola.ico
WizardSmallImageFile=assistente-pequena-55.png,assistente-pequena-110.png
WizardImageFile=assistente-grande-164.png,assistente-grande-328.png
; no fim, avisa o Windows que os icones mudaram: o Explorer guarda o icone pelo caminho do exe, que e o mesmo de
; uma versao para a outra, e sem o aviso o atalho seguia com o icone velho depois de atualizar
ChangesAssociations=yes

[Languages]
; a licenca numa pagina de informacao, e nao de "aceito": a GPLv3 nao precisa ser aceita para usar (secao 9)
Name: "pt"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"; InfoBeforeFile: "licenca-pt.txt"
Name: "en"; MessagesFile: "compiler:Default.isl"; InfoBeforeFile: "licenca-en.txt"

[Messages]
pt.FinishedLabel=A Vitrola foi instalada e fica no menu Iniciar.%n%nNo jogo, use o seu microfone de sempre: a Vitrola toca a música nele. No Discord, use o perfil Estúdio, senão ele corta a música.
en.FinishedLabel=Vitrola is installed. You'll find it in the Start menu.%n%nIn the game, keep your usual microphone: Vitrola plays the music into it. In Discord, use the Studio profile, or it cuts the music out.

[CustomMessages]
pt.Abrir=Abrir a Vitrola
en.Abrir=Open Vitrola
pt.Firewall=Liberando a Vitrola no firewall, para o celular alcançar o PC...
en.Firewall=Allowing Vitrola through the firewall, so your phone can reach the PC...
pt.Microfone=Preparando os microfones para a Vitrola (o som do PC some por alguns segundos)...
en.Microfone=Getting your microphones ready for Vitrola (your PC's sound drops for a few seconds)...
pt.ParcialSemApp=Esta é uma atualização da Vitrola, e só serve onde a Vitrola já está instalada. Para instalar, use o Vitrola-{#Versao}-setup.exe.
en.ParcialSemApp=This is a Vitrola update, and it only works where Vitrola is already installed. To install Vitrola, use Vitrola-{#Versao}-setup.exe.

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

[Icons]
Name: "{autoprograms}\Vitrola"; Filename: "{app}\vitrola.exe"
Name: "{autodesktop}\Vitrola"; Filename: "{app}\vitrola.exe"; Tasks: desktopicon

[Run]
; o servidor atende a rede de casa (o celular). Privadas e publicas: muito Wi-Fi de casa esta como publico no
; Windows (o do Chris estava), e so privadas deixava o celular de fora. Pela rede, so entra o celular pareado
; (pareamento.py, no repo vitrola)
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""Vitrola"""; Flags: runhidden
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall add rule name=""Vitrola"" dir=in action=allow program=""{app}\vitrola.exe"" enable=yes profile=private,public"; StatusMsg: "{cm:Firewall}"; Flags: runhidden
; o filtro em todo microfone que ainda nao tem, a DLL desta versao no lugar da velha e a tarefa do Windows que faz o
; mesmo depois, chamada pelo app sem UAC (o audio do PC reinicia so se algo mudou: atualizar sem DLL nova nao mexe)
Filename: "{app}\vitrola.exe"; Parameters: "--microfone instala-todos --tarefa"; StatusMsg: "{cm:Microfone}"; Flags: runhidden
; como quem instalou, e nao como administrador: os dados vao para o %LOCALAPPDATA% dele
Filename: "{app}\vitrola.exe"; Description: "{cm:Abrir}"; Flags: postinstall nowait skipifsilent runasoriginaluser
; a atualizacao pelo app (atualizacao.py, no repo vitrola) roda este setup em silencio com /reabrir=1: no fim a Vitrola
; abre de novo, como quem instalou, sem abrir outra aba (a pagina que estava aberta reconecta e recarrega sozinha)
Filename: "{app}\vitrola.exe"; Parameters: "--no-browser"; Flags: nowait runasoriginaluser; Check: Reabrir

[UninstallRun]
Filename: "{sys}\taskkill.exe"; Parameters: "/F /IM vitrola.exe"; Flags: runhidden; RunOnceId: "Fecha"
; tira o filtro de todo microfone que o tem, devolve o efeito original de cada um e apaga a tarefa (sem nenhum, nao mexe
; no audio)
Filename: "{app}\vitrola.exe"; Parameters: "--microfone remove"; Flags: runhidden; RunOnceId: "Microfone"
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""Vitrola"""; Flags: runhidden; RunOnceId: "Firewall"

[Code]
// setup.exe /VERYSILENT /reabrir=1, o da atualizacao pelo app: abre a Vitrola de novo no fim
function Reabrir: Boolean;
begin
  Result := WizardSilent and (ExpandConstant('{param:reabrir|0}') = '1');
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
