; *** Inno Setup version 6.5.0+ Brazilian Portuguese messages made by Cesar82 cesar.zanetti.82@gmail.com ***
;
; To download user-contributed translations of this file, go to:
;   https://jrsoftware.org/files/istrans/
;
; Note: When translating this text, do not add periods (.) to the end of
; messages that didn't have them already, because on those messages Inno
; Setup adds the periods automatically (appending a period would result in
; two periods being displayed).

[LangOptions]
; The following three entries are very important. Be sure to read and
; understand the '[LangOptions] section' topic in the help file.
LanguageName=Português Brasileiro
LanguageID=$0416
LanguageCodePage=1252
; If the language you are translating to requires special font faces or
; sizes, uncomment any of the following entries and change them accordingly.
;DialogFontName=
;DialogFontSize=9
;DialogFontBaseScaleWidth=7
;DialogFontBaseScaleHeight=15
;WelcomeFontName=Segoe UI
;WelcomeFontSize=14

[Messages]

; *** Application titles
SetupAppTitle=Instalador
SetupWindowTitle=%1 - Instalador
UninstallAppTitle=Desinstalar
UninstallAppFullTitle=Desinstalar %1

; *** Misc. common
InformationTitle=Informação
ConfirmTitle=Confirmar
ErrorTitle=Erro

; *** SetupLdr messages
SetupLdrStartupMessage=Você está prestes a instalar %1. Deseja continuar?
LdrCannotCreateTemp=Não foi possível criar um arquivo temporário. Instalação interrompida
LdrCannotExecTemp=Não foi possível executar o arquivo na pasta temporária. Instalação interrompida
HelpTextNote=

; *** Startup error messages
LastErrorMessage=%1.%n%nErro %2: %3
SetupFileMissing=O arquivo %1 não foi encontrado na pasta de instalação. Corrija o problema ou obtenha uma nova cópia do programa.
SetupFileCorrupt=Os arquivos de instalação estão corrompidos. Obtenha uma nova cópia do programa.
SetupFileCorruptOrWrongVer=Os arquivos de instalação estão corrompidos ou são incompatíveis com esta versão do instalador. Corrija o problema ou obtenha uma nova cópia do programa.
InvalidParameter=Foi informado um parâmetro inválido na linha de comando:%n%n%1
SetupAlreadyRunning=O instalador já está em execução.
WindowsVersionNotSupported=Este programa não é compatível com a versão do Windows instalada neste computador.
WindowsServicePackRequired=Este programa requer o %1 Service Pack %2 ou posterior.
NotOnThisPlatform=Este programa não pode ser executado no %1.
OnlyOnThisPlatform=Este programa deve ser executado no %1.
OnlyOnTheseArchitectures=Este programa só pode ser instalado em versões do Windows projetadas para as seguintes arquiteturas de processador:%n%n%1
WinVersionTooLowError=Este programa requer o %1 versão %2 ou posterior.
WinVersionTooHighError=Este programa não pode ser instalado no %1 versão %2 ou posterior.
AdminPrivilegesRequired=Para instalar este programa, é necessário estar conectado como administrador.
PowerUserPrivilegesRequired=Para instalar este programa, é necessário estar conectado como administrador ou como membro do grupo Usuários Avançados.
SetupAppRunningError=O instalador detectou que %1 está em execução.%n%nFeche todas as instâncias do programa e clique em OK para continuar ou em Cancelar para sair.
UninstallAppRunningError=O desinstalador detectou que %1 está em execução.%n%nFeche todas as instâncias do programa e clique em OK para continuar ou em Cancelar para sair.

; *** Startup questions
PrivilegesRequiredOverrideTitle=Selecionar o modo de instalação
PrivilegesRequiredOverrideInstruction=Selecione o modo de instalação
PrivilegesRequiredOverrideText1=É possível instalar %1 para todos os usuários (requer privilégios de administrador) ou somente para você.
PrivilegesRequiredOverrideText2=É possível instalar %1 somente para você ou para todos os usuários (requer privilégios de administrador).
PrivilegesRequiredOverrideAllUsers=Instalar para &todos os usuários
PrivilegesRequiredOverrideAllUsersRecommended=Instalar para &todos os usuários (recomendado)
PrivilegesRequiredOverrideCurrentUser=Instalar somente para &mim
PrivilegesRequiredOverrideCurrentUserRecommended=Instalar somente para &mim (recomendado)

; *** Misc. errors
ErrorCreatingDir=O instalador não conseguiu criar a pasta "%1"
ErrorTooManyFilesInDir=Não foi possível criar um arquivo na pasta "%1" porque ela contém arquivos em excesso

; *** Setup common messages
ExitSetupTitle=Sair do instalador
ExitSetupMessage=A instalação não foi concluída. Se você sair agora, o programa não será instalado.%n%nVocê poderá executar o instalador novamente mais tarde para concluir a instalação.%n%nDeseja sair do instalador?
AboutSetupMenuItem=&Sobre o instalador...
AboutSetupTitle=Sobre o instalador
AboutSetupMessage=%1 versão %2%n%3%n%nSite do %1:%n%4
AboutSetupNote=
TranslatorNote=

; *** Buttons
ButtonBack=< &Voltar
ButtonNext=&Avançar >
ButtonInstall=&Instalar
ButtonOK=OK
ButtonCancel=Cancelar
ButtonYes=&Sim
ButtonYesToAll=Sim para &todos
ButtonNo=&Não
ButtonNoToAll=Nã&o para todos
ButtonFinish=&Concluir
ButtonBrowse=&Procurar...
ButtonWizardBrowse=P&rocurar...
ButtonNewFolder=&Criar nova pasta

; *** "Select Language" dialog messages
SelectLanguageTitle=Selecionar o idioma do instalador
SelectLanguageLabel=Selecione o idioma que será usado durante a instalação:

; *** Common wizard text
ClickNext=Clique em Avançar para continuar ou em Cancelar para sair do instalador.
BeveledLabel=
BrowseDialogTitle=Procurar pasta
BrowseDialogLabel=Selecione uma pasta na lista abaixo e clique em OK.
NewFolderName=Nova pasta

; *** "Welcome" wizard page
WelcomeLabel1=Bem-vindo ao assistente de instalação de [name]
WelcomeLabel2=Este assistente instalará [name/ver] no seu computador.%n%nÉ recomendável fechar todos os outros aplicativos antes de continuar.

; *** "Password" wizard page
WizardPassword=Senha
PasswordLabel1=Esta instalação está protegida por senha.
PasswordLabel3=Digite a senha e clique em Avançar para continuar. A senha diferencia maiúsculas de minúsculas.
PasswordEditLabel=&Senha:
IncorrectPassword=A senha digitada está incorreta. Tente novamente.

; *** "License Agreement" wizard page
WizardLicense=Contrato de licença
LicenseLabel=Leia as informações importantes a seguir antes de continuar.
LicenseLabel3=Leia o contrato de licença a seguir. Você precisa aceitar os termos deste contrato antes de prosseguir com a instalação.
LicenseAccepted=Eu a&ceito os termos do contrato
LicenseNotAccepted=Eu &não aceito os termos do contrato

; *** "Information" wizard pages
WizardInfoBefore=Informações
InfoBeforeLabel=Leia as informações importantes a seguir antes de continuar.
InfoBeforeClickLabel=Quando estiver pronto para continuar a instalação, clique em Avançar.
WizardInfoAfter=Informações
InfoAfterLabel=Leia as informações importantes a seguir antes de continuar.
InfoAfterClickLabel=Quando estiver pronto para continuar a instalação, clique em Avançar.

; *** "User Information" wizard page
WizardUserInfo=Informações do usuário
UserInfoDesc=Informe seus dados.
UserInfoName=&Nome do usuário:
UserInfoOrg=&Organização:
UserInfoSerial=Número de &série:
UserInfoNameRequired=É necessário informar um nome.

; *** "Select Destination Location" wizard page
WizardSelectDir=Selecionar o local de destino
SelectDirDesc=Onde você deseja instalar [name]?
SelectDirLabel3=O instalador instalará [name] na pasta a seguir.
SelectDirBrowseLabel=Para continuar, clique em Avançar. Para selecionar outra pasta, clique em Procurar.
DiskSpaceGBLabel=São necessários pelo menos [gb] GB de espaço livre em disco.
DiskSpaceMBLabel=São necessários pelo menos [mb] MB de espaço livre em disco.
CannotInstallToNetworkDrive=O instalador não pode instalar em uma unidade de rede.
CannotInstallToUNCPath=O instalador não pode instalar em um caminho UNC.
InvalidPath=Digite um caminho completo com a letra da unidade, por exemplo:%n%nC:\APP%n%nou um caminho UNC no formato:%n%n\\servidor\compartilhamento
InvalidDrive=A unidade ou o compartilhamento UNC selecionado não existe ou não está acessível. Selecione outro local.
DiskSpaceWarningTitle=Espaço em disco insuficiente
DiskSpaceWarning=O instalador precisa de pelo menos %1 KB de espaço livre, mas a unidade selecionada tem apenas %2 KB disponíveis.%n%nDeseja continuar mesmo assim?
DirNameTooLong=O nome ou caminho da pasta é muito longo.
InvalidDirName=O nome da pasta não é válido.
BadDirName32=Os nomes de pasta não podem conter nenhum dos seguintes caracteres:%n%n%1
DirExistsTitle=A pasta já existe
DirExists=A pasta:%n%n%1%n%njá existe. Deseja instalar nessa pasta mesmo assim?
DirDoesntExistTitle=A pasta não existe
DirDoesntExist=A pasta:%n%n%1%n%nnão existe. Deseja criá-la?

; *** "Select Components" wizard page
WizardSelectComponents=Selecionar componentes
SelectComponentsDesc=Quais componentes devem ser instalados?
SelectComponentsLabel2=Selecione os componentes que deseja instalar e desmarque os que não deseja instalar. Clique em Avançar quando estiver pronto para continuar.
FullInstallation=Instalação completa
; if possible don't translate 'Compact' as 'Minimal' (I mean 'Minimal' in your language)
CompactInstallation=Instalação compacta
CustomInstallation=Instalação personalizada
NoUninstallWarningTitle=Componentes já instalados
NoUninstallWarning=O instalador detectou que os seguintes componentes já estão instalados no seu computador:%n%n%1%n%nDesmarcar esses componentes não fará com que sejam desinstalados.%n%nDeseja continuar mesmo assim?
ComponentSize1=%1 KB
ComponentSize2=%1 MB
ComponentsDiskSpaceGBLabel=A seleção atual requer pelo menos [gb] GB de espaço em disco.
ComponentsDiskSpaceMBLabel=A seleção atual requer pelo menos [mb] MB de espaço em disco.

; *** "Select Additional Tasks" wizard page
WizardSelectTasks=Selecionar tarefas adicionais
SelectTasksDesc=Quais tarefas adicionais devem ser executadas?
SelectTasksLabel2=Selecione as tarefas adicionais que o instalador deve executar durante a instalação de [name] e clique em Avançar.

; *** "Select Start Menu Folder" wizard page
WizardSelectProgramGroup=Selecionar a pasta do menu Iniciar
SelectStartMenuFolderDesc=Onde o instalador deve criar os atalhos do programa?
SelectStartMenuFolderLabel3=O instalador criará os atalhos do programa na seguinte pasta do menu Iniciar.
SelectStartMenuFolderBrowseLabel=Para continuar, clique em Avançar. Para selecionar outra pasta, clique em Procurar.
MustEnterGroupName=É necessário informar um nome de pasta.
GroupNameTooLong=O nome ou caminho da pasta é muito longo.
InvalidGroupName=O nome da pasta não é válido.
BadGroupName=O nome da pasta não pode conter nenhum dos seguintes caracteres:%n%n%1
NoProgramGroupCheck2=&Não criar uma pasta no menu Iniciar

; *** "Ready to Install" wizard page
WizardReady=Pronto para instalar
ReadyLabel1=O instalador está pronto para começar a instalação de [name] no seu computador.
ReadyLabel2a=Clique em Instalar para continuar a instalação ou em Voltar para revisar ou alterar alguma configuração.
ReadyLabel2b=Clique em Instalar para continuar a instalação.
ReadyMemoUserInfo=Informações do usuário:
ReadyMemoDir=Local de destino:
ReadyMemoType=Tipo de instalação:
ReadyMemoComponents=Componentes selecionados:
ReadyMemoGroup=Pasta do menu Iniciar:
ReadyMemoTasks=Tarefas adicionais:

; *** TDownloadWizardPage wizard page and DownloadTemporaryFile
DownloadingLabel2=Baixando arquivos...
ButtonStopDownload=&Parar download
StopDownload=Tem certeza de que deseja parar o download?
ErrorDownloadAborted=Download interrompido
ErrorDownloadFailed=Falha no download: %1 %2
ErrorDownloadSizeFailed=Falha ao obter o tamanho: %1 %2
ErrorProgress=Progresso inválido: %1 de %2
ErrorFileSize=Tamanho de arquivo inválido: esperado %1, encontrado %2

; *** TExtractionWizardPage wizard page and ExtractArchive
ExtractingLabel=Extraindo arquivos...
ButtonStopExtraction=&Parar extração
StopExtraction=Tem certeza de que deseja parar a extração?
ErrorExtractionAborted=Extração interrompida
ErrorExtractionFailed=Falha na extração: %1

; *** Archive extraction failure details
ArchiveIncorrectPassword=A senha está incorreta
ArchiveIsCorrupted=O arquivo compactado está corrompido
ArchiveUnsupportedFormat=O formato do arquivo compactado não é compatível

; *** "Preparing to Install" wizard page
WizardPreparing=Preparando a instalação
PreparingDesc=O instalador está se preparando para instalar [name] no seu computador.
PreviousInstallNotCompleted=A instalação ou remoção de um programa anterior não foi concluída. É necessário reiniciar o computador para concluir essa operação.%n%nDepois de reiniciar o computador, execute o instalador novamente para concluir a instalação de [name].
CannotContinue=O instalador não pode continuar. Clique em Cancelar para sair.
ApplicationsFound=Os aplicativos a seguir estão usando arquivos que precisam ser atualizados pelo instalador. É recomendável permitir que o instalador feche esses aplicativos automaticamente.
ApplicationsFound2=Os aplicativos a seguir estão usando arquivos que precisam ser atualizados pelo instalador. É recomendável permitir que o instalador feche esses aplicativos automaticamente. Após a conclusão da instalação, o instalador tentará reiniciar os aplicativos.
CloseApplications=&Fechar os aplicativos automaticamente
DontCloseApplications=&Não fechar os aplicativos
ErrorCloseApplications=O instalador não conseguiu fechar todos os aplicativos automaticamente. Antes de continuar, é recomendável fechar todos os aplicativos que usam arquivos a serem atualizados pelo instalador.
PrepareToInstallNeedsRestart=O instalador precisa reiniciar o computador. Depois de reiniciar, execute o instalador novamente para concluir a instalação de [name].%n%nDeseja reiniciar agora?

; *** "Installing" wizard page
WizardInstalling=Instalando
InstallingLabel=Aguarde enquanto o instalador instala [name] no seu computador.

; *** "Setup Completed" wizard page
FinishedHeadingLabel=Concluindo o assistente de instalação de [name]
FinishedLabelNoIcons=O instalador concluiu a instalação de [name] no seu computador.
FinishedLabel=O instalador concluiu a instalação de [name] no seu computador. Para abrir o aplicativo, use os atalhos instalados.
ClickFinish=Clique em Concluir para sair do instalador.
FinishedRestartLabel=Para concluir a instalação de [name], o instalador precisa reiniciar o computador. Deseja reiniciar agora?
FinishedRestartMessage=Para concluir a instalação de [name], o instalador precisa reiniciar o computador.%n%nDeseja reiniciar agora?
ShowReadmeCheck=Sim, exibir o arquivo README
YesRadio=&Sim, reiniciar o computador agora
NoRadio=&Não, reiniciar o computador mais tarde
; used for example as 'Run MyProg.exe'
RunEntryExec=Executar %1
; used for example as 'View Readme.txt'
RunEntryShellExec=Exibir %1

; *** "Setup Needs the Next Disk" stuff
ChangeDiskTitle=O instalador precisa do próximo disco
SelectDiskLabel2=Insira o disco %1 e clique em OK.%n%nSe os arquivos deste disco estiverem em uma pasta diferente da exibida abaixo, digite o caminho correto ou clique em Procurar.
PathLabel=&Caminho:
FileNotInDir2=O arquivo "%1" não foi encontrado em "%2". Insira o disco correto ou selecione outra pasta.
SelectDirectoryLabel=Especifique o local do próximo disco.

; *** Installation phase messages
SetupAborted=A instalação não foi concluída.%n%nCorrija o problema e execute o instalador novamente.
AbortRetryIgnoreSelectAction=Selecione uma ação
AbortRetryIgnoreRetry=&Tentar novamente
AbortRetryIgnoreIgnore=&Ignorar o erro e continuar
AbortRetryIgnoreCancel=Cancelar a instalação
RetryCancelSelectAction=Selecione uma ação
RetryCancelRetry=&Tentar novamente
RetryCancelCancel=Cancelar

; *** Installation status messages
StatusClosingApplications=Fechando aplicativos...
StatusCreateDirs=Criando pastas...
StatusExtractFiles=Extraindo arquivos...
StatusDownloadFiles=Baixando arquivos...
StatusCreateIcons=Criando atalhos...
StatusCreateIniEntries=Criando entradas INI...
StatusCreateRegistryEntries=Criando entradas no Registro...
StatusRegisterFiles=Registrando arquivos...
StatusSavingUninstall=Salvando informações de desinstalação...
StatusRunProgram=Concluindo a instalação...
StatusRestartingApplications=Reiniciando os aplicativos...
StatusRollback=Desfazendo as alterações...

; *** Misc. errors
ErrorInternal2=Erro interno: %1
ErrorFunctionFailedNoCode=%1 falhou
ErrorFunctionFailed=%1 falhou; código %2
ErrorFunctionFailedWithMessage=%1 falhou; código %2.%n%3
ErrorExecutingProgram=Não foi possível executar o arquivo:%n%1

; *** Registry errors
ErrorRegOpenKey=Erro ao abrir a chave do Registro:%n%1\%2
ErrorRegCreateKey=Erro ao criar a chave do Registro:%n%1\%2
ErrorRegWriteKey=Erro ao gravar na chave do Registro:%n%1\%2

; *** INI errors
ErrorIniEntry=Erro ao criar a entrada INI no arquivo "%1".

; *** File copying errors
FileAbortRetryIgnoreSkipNotRecommended=&Pular este arquivo (não recomendado)
FileAbortRetryIgnoreIgnoreNotRecommended=&Ignorar o erro e continuar (não recomendado)
SourceIsCorrupted=O arquivo de origem está corrompido
SourceDoesntExist=O arquivo de origem "%1" não existe
SourceVerificationFailed=A verificação do arquivo de origem falhou: %1
VerificationSignatureDoesntExist=O arquivo de assinatura "%1" não existe
VerificationSignatureInvalid=O arquivo de assinatura "%1" é inválido
VerificationKeyNotFound=O arquivo de assinatura "%1" utiliza uma chave desconhecida
VerificationFileNameIncorrect=O nome do arquivo está incorreto
VerificationFileTagIncorrect=A tag do arquivo está incorreta
VerificationFileSizeIncorrect=O tamanho do arquivo está incorreto
VerificationFileHashIncorrect=O hash do arquivo está incorreto
ExistingFileReadOnly2=Não foi possível substituir o arquivo existente porque ele está marcado como somente leitura.
ExistingFileReadOnlyRetry=&Remover o atributo somente leitura e tentar novamente
ExistingFileReadOnlyKeepExisting=&Manter o arquivo existente
ErrorReadingExistingDest=Ocorreu um erro ao tentar ler o arquivo existente:
FileExistsSelectAction=Selecione uma ação
FileExists2=O arquivo já existe.
FileExistsOverwriteExisting=&Sobrescrever o arquivo existente
FileExistsKeepExisting=&Manter o arquivo existente
FileExistsOverwriteOrKeepAll=&Fazer isso para os próximos conflitos
ExistingFileNewerSelectAction=Selecione uma ação
ExistingFileNewer2=O arquivo existente é mais recente que o arquivo que o instalador está tentando instalar.
ExistingFileNewerOverwriteExisting=&Sobrescrever o arquivo existente
ExistingFileNewerKeepExisting=&Manter o arquivo existente (recomendado)
ExistingFileNewerOverwriteOrKeepAll=&Fazer isso para os próximos conflitos
ErrorChangingAttr=Ocorreu um erro ao tentar alterar os atributos do arquivo existente:
ErrorCreatingTemp=Ocorreu um erro ao tentar criar um arquivo na pasta de destino:
ErrorReadingSource=Ocorreu um erro ao tentar ler o arquivo de origem:
ErrorCopying=Ocorreu um erro ao tentar copiar um arquivo:
ErrorDownloading=Ocorreu um erro ao tentar baixar um arquivo:
ErrorExtracting=Ocorreu um erro ao tentar extrair o arquivo compactado:
ErrorReplacingExistingFile=Ocorreu um erro ao tentar substituir o arquivo existente:
ErrorRestartReplace=Falha no RestartReplace:
ErrorRenamingTemp=Ocorreu um erro ao tentar renomear um arquivo na pasta de destino:
ErrorRegisterServer=Não foi possível registrar a DLL/OCX: %1
ErrorRegSvr32Failed=O RegSvr32 falhou com o código de saída %1
ErrorRegisterTypeLib=Não foi possível registrar a biblioteca de tipos: %1

; *** Uninstall display name markings
; used for example as 'My Program (32-bit)'
UninstallDisplayNameMark=%1 (%2)
; used for example as 'My Program (32-bit, All users)'
UninstallDisplayNameMarks=%1 (%2, %3)
UninstallDisplayNameMark32Bit=32 bits
UninstallDisplayNameMark64Bit=64 bits
UninstallDisplayNameMarkAllUsers=Todos os usuários
UninstallDisplayNameMarkCurrentUser=Usuário atual

; *** Post-installation errors
ErrorOpeningReadme=Ocorreu um erro ao tentar abrir o arquivo README.
ErrorRestartingComputer=O instalador não conseguiu reiniciar o computador. Reinicie-o manualmente.

; *** Uninstaller messages
UninstallNotFound=O arquivo "%1" não existe. Não é possível desinstalar.
UninstallOpenError=O arquivo "%1" não pôde ser aberto. Não é possível desinstalar
UninstallUnsupportedVer=O arquivo de log de desinstalação "%1" está em um formato não reconhecido por esta versão do desinstalador. Não é possível desinstalar
UninstallUnknownEntry=Uma entrada desconhecida (%1) foi encontrada no log de desinstalação
ConfirmUninstall=Tem certeza de que deseja remover completamente %1 e todos os seus componentes?
UninstallOnlyOnWin64=Esta instalação só pode ser desinstalada no Windows de 64 bits.
OnlyAdminCanUninstall=Esta instalação só pode ser desinstalada por um usuário com privilégios de administrador.
UninstallStatusLabel=Aguarde enquanto o desinstalador remove %1 do seu computador.
UninstalledAll=A desinstalação de %1 foi concluída com sucesso.
UninstalledMost=A desinstalação de %1 foi concluída.%n%nAlguns elementos não puderam ser removidos e podem ser excluídos manualmente.
UninstalledAndNeedsRestart=Para concluir a desinstalação de %1, é necessário reiniciar o computador.%n%nDeseja reiniciar agora?
UninstallDataCorrupted=O arquivo "%1" está corrompido. Não é possível desinstalar

; *** Uninstallation phase messages
ConfirmDeleteSharedFileTitle=Remover arquivo compartilhado?
ConfirmDeleteSharedFile2=O sistema indica que o arquivo compartilhado a seguir não está mais sendo usado por nenhum programa. Deseja que o desinstalador remova esse arquivo compartilhado?%n%nSe algum programa ainda estiver usando esse arquivo e ele for removido, esse programa poderá deixar de funcionar corretamente. Em caso de dúvida, escolha Não. Manter o arquivo no sistema não causará nenhum problema.
SharedFileNameLabel=Nome do arquivo:
SharedFileLocationLabel=Local:
WizardUninstalling=Status da desinstalação
StatusUninstalling=Desinstalando %1...

; *** Shutdown block reasons
ShutdownBlockReasonInstallingApp=Instalando %1.
ShutdownBlockReasonUninstallingApp=Desinstalando %1.

; The custom messages below aren't used by Setup itself, but if you make
; use of them in your scripts, you'll want to translate them.

[CustomMessages]

NameAndVersion=%1 versão %2
AdditionalIcons=Atalhos adicionais:
CreateDesktopIcon=Criar um atalho &na área de trabalho
CreateQuickLaunchIcon=Criar um atalho na &barra de inicialização rápida
ProgramOnTheWeb=%1 na Web
UninstallProgram=Desinstalar %1
LaunchProgram=Iniciar %1
AssocFileExtension=Associar %1 à &extensão de arquivo %2
AssocingFileExtension=Associando %1 à extensão de arquivo %2...
AutoStartProgramGroupDescription=Inicialização:
AutoStartProgram=Iniciar %1 automaticamente
AddonHostProgramNotFound=Não foi possível localizar %1 na pasta selecionada.%n%nDeseja continuar mesmo assim?
