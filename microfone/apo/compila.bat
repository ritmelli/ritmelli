@echo off
rem Compila o micfx.dll (x64, CRT estatico: o audiodg.exe nao precisa do redistribuivel do Visual C++).
rem Precisa do Visual Studio 2022 (qualquer edicao, ou o Build Tools) com C++ e do Windows SDK (10.0.22621 ou mais
rem novo). O vswhere acha a instalacao: na esteira do GitHub e o Enterprise, num PC costuma ser o Build Tools.
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
if "%1"=="teste" goto teste
cl /nologo /O2 /EHsc /W4 /MT /std:c++17 /DUNICODE /D_UNICODE /LD micfx.cpp /Fosaida\ /Fesaida\micfx.dll /link /DEF:micfx.def audiobaseprocessingobject.lib audiomediatypecrt.lib legacy_stdio_definitions.lib ole32.lib advapi32.lib user32.lib
exit /b %errorlevel%
:teste
rem compila.bat teste: a banca do reamostra.h (teste\teste_reamostra.py mede)
cl /nologo /O2 /EHsc /W4 /MT /std:c++17 /LD teste\teste_reamostra.cpp /Fosaida\ /Fesaida\teste_reamostra.dll
exit /b %errorlevel%
