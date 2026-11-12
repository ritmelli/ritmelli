; O instalador da Vitrola (Inno Setup 6). Nao compile direto: o monta.ps1 congela o app, baixa o ffmpeg e o
; Deno e passa os caminhos e a versao (/DVersao, /DApp, /DFfmpeg, /DDeno, e /DLicenca e /DTerceiros, a GPLv3 da Vitrola
; e os avisos de terceiros que o terceiros.py monta).
;
; Instala o vitrola.exe em Program Files, com o ffmpeg, o ffprobe e o Deno na bin\ (o app acha la, ver o
; pastas.py), cria a regra do firewall para o celular alcancar o PC e guia a instalacao do VB-Cable, que nunca
; vem junto: a etapa so mostra os passos e leva a pagina oficial da VB-Audio. Os dados de quem usa
; (%LOCALAPPDATA%\Vitrola) ficam ao desinstalar.
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
; administrador de qualquer jeito: o firewall e o driver do VB-Cable pedem
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
pt.FinishedLabel=A Vitrola foi instalada e fica no menu Iniciar.%n%nNo jogo, escolha "CABLE Output (VB-Audio Virtual Cable)" como microfone.
en.FinishedLabel=Vitrola is installed. You'll find it in the Start menu.%n%nIn the game, choose "CABLE Output (VB-Audio Virtual Cable)" as your microphone.

[CustomMessages]
pt.Abrir=Abrir a Vitrola
en.Abrir=Open Vitrola
pt.Firewall=Liberando a Vitrola no firewall, para o celular alcançar o PC...
en.Firewall=Allowing Vitrola through the firewall, so your phone can reach the PC...
pt.CaboTitulo=VB-Audio Virtual Cable
en.CaboTitulo=VB-Audio Virtual Cable
pt.CaboSub=O cabo que leva o som da Vitrola para o microfone do jogo.
en.CaboSub=The cable that carries Vitrola's sound into the game's microphone.
pt.CaboFalta=O VB-Cable ainda não está instalado. Ele é gratuito, da VB-Audio, e sem ele o jogo não ouve a Vitrola.
en.CaboFalta=VB-Cable isn't installed yet. It's free, made by VB-Audio, and without it the game can't hear Vitrola.
pt.CaboPassos=1. Clique em "Abrir a página do VB-Cable" e baixe o pacote para Windows (.zip).%n2. Extraia o .zip. Clique com o botão direito em VBCABLE_Setup_x64.exe e escolha "Executar como administrador".%n3. Clique em "Install Driver" e espere terminar.%n4. Volte aqui e clique em "Conferir de novo".
en.CaboPassos=1. Click "Open the VB-Cable page" and download the Windows package (.zip).%n2. Extract the .zip. Right-click VBCABLE_Setup_x64.exe and choose "Run as administrator".%n3. Click "Install Driver" and wait for it to finish.%n4. Come back here and click "Check again".
pt.CaboAbrir=Abrir a página do VB-Cable
en.CaboAbrir=Open the VB-Cable page
pt.CaboConferir=Conferir de novo
en.CaboConferir=Check again
pt.CaboAchou=VB-Cable encontrado. Pode seguir.
en.CaboAchou=VB-Cable found. You can continue.
pt.CaboNaoAchou=Ainda não encontrado. Se você acabou de instalar, pode ser preciso reiniciar o PC.
en.CaboNaoAchou=Not found yet. If you just installed it, you may need to restart your PC.
pt.ParcialSemApp=Esta é uma atualização da Vitrola, e só serve onde a Vitrola já está instalada. Para instalar, use o Vitrola-{#Versao}-setup.exe.
en.ParcialSemApp=This is a Vitrola update, and it only works where Vitrola is already installed. To install Vitrola, use Vitrola-{#Versao}-setup.exe.
pt.CaboSeguir=O VB-Cable ainda não foi encontrado. Dá para instalar depois, mas até lá o jogo não ouve a Vitrola.%n%nSeguir mesmo assim?
en.CaboSeguir=VB-Cable wasn't found yet. You can install it later, but until then the game can't hear Vitrola.%n%nContinue anyway?

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
; como quem instalou, e nao como administrador: os dados vao para o %LOCALAPPDATA% dele
Filename: "{app}\vitrola.exe"; Description: "{cm:Abrir}"; Flags: postinstall nowait skipifsilent runasoriginaluser
; a atualizacao pelo app (atualizacao.py, no repo vitrola) roda este setup em silencio com /reabrir=1: no fim a Vitrola
; abre de novo, como quem instalou, sem abrir outra aba (a pagina que estava aberta reconecta e recarrega sozinha)
Filename: "{app}\vitrola.exe"; Parameters: "--no-browser"; Flags: nowait runasoriginaluser; Check: Reabrir

[UninstallRun]
Filename: "{sys}\taskkill.exe"; Parameters: "/F /IM vitrola.exe"; Flags: runhidden; RunOnceId: "Fecha"
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""Vitrola"""; Flags: runhidden; RunOnceId: "Firewall"

[Code]
const
  CABO_CHAVE = 'SOFTWARE\Microsoft\Windows\CurrentVersion\MMDevices\Audio\Capture';
  CABO_NOME = '{a45c254e-df1c-4efd-8020-67d146a850e0},2';
  CABO_PAGINA = 'https://vb-audio.com/Cable/';

var
  PaginaCabo: TWizardPage;
  StatusCabo: TNewStaticText;

// o cabo existe quando o Windows tem um microfone "CABLE Output" ativo (DeviceState 1): o mesmo que o jogo usa
function CaboInstalado: Boolean;
var
  Ids: TArrayOfString;
  Nome: String;
  Estado: Cardinal;
  I: Integer;
begin
  Result := False;
  if not RegGetSubkeyNames(HKLM64, CABO_CHAVE, Ids) then
    Exit;
  for I := 0 to GetArrayLength(Ids) - 1 do
    if RegQueryStringValue(HKLM64, CABO_CHAVE + '\' + Ids[I] + '\Properties', CABO_NOME, Nome) then
      if Pos('CABLE Output', Nome) > 0 then
        if RegQueryDWordValue(HKLM64, CABO_CHAVE + '\' + Ids[I], 'DeviceState', Estado) then
          if Estado = 1 then
          begin
            Result := True;
            Exit;
          end;
end;

procedure AbrirPagina(Sender: TObject);
var
  Codigo: Integer;
begin
  // o navegador abre como quem instalou, nao como administrador
  ShellExecAsOriginalUser('open', CABO_PAGINA, '', '', SW_SHOWNORMAL, ewNoWait, Codigo);
end;

procedure Conferir(Sender: TObject);
begin
  if CaboInstalado then
    StatusCabo.Caption := CustomMessage('CaboAchou')
  else
    StatusCabo.Caption := CustomMessage('CaboNaoAchou');
end;

// a etapa do cabo vem depois de instalar os arquivos, e so aparece se ele faltar
procedure InitializeWizard;
var
  Texto: TNewStaticText;
  Abrir, DeNovo: TNewButton;
begin
  PaginaCabo := CreateCustomPage(wpInfoAfter, CustomMessage('CaboTitulo'), CustomMessage('CaboSub'));

  Texto := TNewStaticText.Create(PaginaCabo);
  Texto.Parent := PaginaCabo.Surface;
  Texto.Width := PaginaCabo.SurfaceWidth;
  Texto.WordWrap := True;
  Texto.Caption := CustomMessage('CaboFalta') + #13#10#13#10 + CustomMessage('CaboPassos');

  Abrir := TNewButton.Create(PaginaCabo);
  Abrir.Parent := PaginaCabo.Surface;
  Abrir.Top := Texto.Top + Texto.Height + ScaleY(16);
  Abrir.Width := ScaleX(220);
  Abrir.Height := WizardForm.NextButton.Height;
  Abrir.Caption := CustomMessage('CaboAbrir');
  Abrir.OnClick := @AbrirPagina;

  DeNovo := TNewButton.Create(PaginaCabo);
  DeNovo.Parent := PaginaCabo.Surface;
  DeNovo.Top := Abrir.Top;
  DeNovo.Left := Abrir.Left + Abrir.Width + ScaleX(8);
  DeNovo.Width := ScaleX(150);
  DeNovo.Height := Abrir.Height;
  DeNovo.Caption := CustomMessage('CaboConferir');
  DeNovo.OnClick := @Conferir;

  StatusCabo := TNewStaticText.Create(PaginaCabo);
  StatusCabo.Parent := PaginaCabo.Surface;
  StatusCabo.Top := Abrir.Top + Abrir.Height + ScaleY(12);
  StatusCabo.Width := PaginaCabo.SurfaceWidth;
  StatusCabo.WordWrap := True;
  StatusCabo.Font.Style := [fsBold];
  StatusCabo.Caption := '';
end;

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
// setup.exe /cabo=1 mostra a etapa mesmo com o cabo instalado (para testar a tela)
function ShouldSkipPage(PageID: Integer): Boolean;
begin
  Result := False;
  if PageID = PaginaCabo.ID then
    Result := CaboInstalado and (ExpandConstant('{param:cabo|0}') <> '1');
end;

// em silencio o Inno passa por esta etapa do mesmo jeito, e o MsgBox comum aparece mesmo com /SUPPRESSMSGBOXES: sem
// o cabo, a atualizacao pelo app ficava parada numa pergunta. Suprimida, a resposta e seguir
function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if CurPageID = PaginaCabo.ID then
    if not CaboInstalado then
      Result := SuppressibleMsgBox(CustomMessage('CaboSeguir'), mbConfirmation, MB_YESNO, IDYES) = IDYES;
end;
