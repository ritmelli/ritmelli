@echo off
rem Compila o micfx.dll, o filtro (x64, CRT estatico: o audiodg.exe nao precisa do redistribuivel do Visual C++), e o
rem voz.dll, o motor de efeitos dele (voz.h) para a voz com efeito que sai pelo app (microfone\voz.py). Os dois vao no
rem instalador (ritmelli.spec).
rem Precisa do Visual Studio 2022 (qualquer edicao, ou o Build Tools) com C++, o ATL (o atls.lib do link) e o Windows
rem SDK 10.0.26100 ou mais novo (a IApoAcousticEchoCancellation2 do micfx.cpp nao existe no 22621). O vswhere acha a
rem instalacao: na esteira do GitHub e o Enterprise, num PC costuma ser o Build Tools.
setlocal
set "VSWHERE=%ProgramFiles(x86)%\Microsoft Visual Studio\Installer\vswhere.exe"
set "VS="
if not exist "%VSWHERE%" goto fixo
for /f "usebackq delims=" %%i in (`"%VSWHERE%" -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath`) do set "VS=%%i\VC\Auxiliary\Build\vcvars64.bat"
:fixo
if not defined VS set "VS=%ProgramFiles(x86)%\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat"
if exist "%VS%" goto achou
echo sem o Visual Studio 2022 com C++ (nem o Build Tools)
exit /b 1
:achou
call "%VS%" >nul
cd /d "%~dp0"
if not exist saida mkdir saida
set "VERSAO="
for /f "tokens=3" %%v in ('findstr /b /c:"VERSAO = " ..\..\versao.py') do set "VERSAO=%%~v"
echo %VERSAO%| findstr /r "^[0-9][0-9]*\.[0-9][0-9]*\.[0-9][0-9]*$" >nul
if errorlevel 1 (
  echo couldn't read the version X.Y.Z from versao.py ^(got "%VERSAO%"^)
  exit /b 1
)
for /f "tokens=1-3 delims=." %%a in ("%VERSAO%") do (
  > saida\version.h echo #define RITMELLI_VERSION %%a,%%b,%%c,0
  >> saida\version.h echo #define RITMELLI_VERSION_STR "%VERSAO%"
)
rc /nologo /i saida /d RITMELLI_MICFX /fo saida\micfx.res version.rc
if errorlevel 1 exit /b %errorlevel%
rc /nologo /i saida /d RITMELLI_VOZ /fo saida\voz.res version.rc
if errorlevel 1 exit /b %errorlevel%
if "%1"=="teste" goto teste
call :micfx
if errorlevel 1 exit /b %errorlevel%
cl /nologo /O2 /EHsc /W4 /MT /std:c++17 /LD voz.cpp saida\voz.res /Fosaida\ /Fesaida\voz.dll
exit /b %errorlevel%
:teste
cl /nologo /O2 /EHsc /W4 /MT /std:c++17 /LD teste\teste_reamostra.cpp /Fosaida\ /Fesaida\teste_reamostra.dll
if errorlevel 1 exit /b %errorlevel%
cl /nologo /O2 /EHsc /W4 /MT /std:c++17 /LD voz.cpp saida\voz.res /Fosaida\ /Fesaida\voz.dll
if errorlevel 1 exit /b %errorlevel%
call :micfx
if errorlevel 1 exit /b %errorlevel%
rem a banca do filtro inteiro (o micfx.cpp com o anel num nome so do teste; dev\testa_filtro.py)
cl /nologo /O2 /EHsc /W4 /MT /std:c++17 /DUNICODE /D_UNICODE /LD teste\banca_filtro.cpp /Fosaida\ /Fesaida\banca_filtro.dll /link audiobaseprocessingobject.lib audiomediatypecrt.lib legacy_stdio_definitions.lib ole32.lib advapi32.lib user32.lib
exit /b %errorlevel%
:micfx
cl /nologo /O2 /EHsc /W4 /MT /std:c++17 /DUNICODE /D_UNICODE /LD micfx.cpp saida\micfx.res /Fosaida\ /Fesaida\micfx.dll /link /DEF:micfx.def audiobaseprocessingobject.lib audiomediatypecrt.lib legacy_stdio_definitions.lib ole32.lib advapi32.lib user32.lib
exit /b %errorlevel%
