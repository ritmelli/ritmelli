# A versao do PyInstaller do build: o bootloader de bin\ e o desta fonte (o compila.ps1 compila, o monta.ps1 instala o
# PyInstaller dela com o bootloader de bin\). Para trocar de versao: a URL e o hash do sdist no PyPI, e rodar o
# compila.ps1 de novo, porque o bootloader de uma versao nao serve na outra.
@{
  Versao = '6.22.3'
  Url    = 'https://files.pythonhosted.org/packages/63/41/f90302845945abd4ed647933ff5ee7c6ac93983187be67f897b6cb613331/pyinstaller-6.22.3.tar.gz'
  Sha    = '05EB2F5615503E72939A7224D68B4AFF572C6B0438EE4A17D0A4B481F399362D'
}
