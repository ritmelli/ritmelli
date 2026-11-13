@echo off
rem Compila o micfx.dll (x64, CRT estatico: o audiodg.exe nao precisa do redistribuivel do Visual C++).
rem Precisa do VS 2022 Build Tools com C++ e do Windows SDK (10.0.22621 ou mais novo).
setlocal
set "VS=%ProgramFiles(x86)%\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat"
if exist "%VS%" goto achou
echo sem o VS 2022 Build Tools com C++
exit /b 1
:achou
call "%VS%" >nul
cd /d "%~dp0"
if not exist saida mkdir saida
if "%1"=="teste" goto teste
cl/nologo /O2 /EHsc /W4 /MT /std:c++17 /DUNICODE /D_UNICODE /LD micfx.cpp /Fosaida\ /Fesaida\micfx.dll /link /DEF:micfx.def audiobaseprocessingobject.lib audiomediatypecrt.lib legacy_stdio_definitions.lib ole32.lib advapi32.lib user32.lib
exit /b %errorlevel%
:teste
rem compila.bat teste: a banca do reamostra.h (teste\teste_reamostra.py mede)
cl /nologo /O2 /EHsc /W4 /MT /std:c++17 /LD teste\teste_reamostra.cpp /Fosaida\ /Fesaida\teste_reamostra.dll
exit /b %errorlevel%
